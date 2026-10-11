import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.notification import Notification
from app.providers.base import PermanentProviderError, TransientProviderError
from tests.conftest import Harness

EMAIL = {
    "user_id": "u1",
    "channel": "email",
    "recipient": "user@example.com",
    "subject": "Hello",
    "body": "World",
}


async def create(client: AsyncClient, **overrides: object) -> str:
    response = await client.post("/api/v1/notifications", json={**EMAIL, **overrides})
    assert response.status_code == 202, response.text
    return response.json()["id"]


async def fetch(client: AsyncClient, notification_id: str) -> dict:
    return (await client.get(f"/api/v1/notifications/{notification_id}")).json()


async def drain_one(client: AsyncClient, harness: Harness) -> str:
    notification_id = await harness.queue.pop(0.1)
    assert notification_id is not None
    return await harness.delivery.process(notification_id)


async def test_successful_delivery(client: AsyncClient, harness: Harness) -> None:
    notification_id = await create(client)
    assert await drain_one(client, harness) == "sent"
    body = await fetch(client, notification_id)
    assert body["status"] == "sent"
    assert body["attempts"] == 1
    assert body["provider_message_id"].startswith("email-")
    assert body["history"][0]["outcome"] == "sent"


async def test_transient_failure_retries_then_succeeds(
    client: AsyncClient, harness: Harness
) -> None:
    notification_id = await create(client)
    provider = harness.providers["email"]
    original = provider.send
    calls = {"n": 0}

    async def flaky(message):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransientProviderError("timeout")
        return await original(message)

    provider.send = flaky
    assert await drain_one(client, harness) == "retrying"
    body = await fetch(client, notification_id)
    assert body["status"] == "retrying"
    assert body["last_error"] == "timeout"
    assert await harness.queue.depths() == (0, 1)

    await asyncio.sleep(0.1)
    assert await harness.queue.promote_due() == 1
    assert await drain_one(client, harness) == "sent"
    final = await fetch(client, notification_id)
    assert final["status"] == "sent"
    assert final["attempts"] == 2
    assert [h["outcome"] for h in final["history"]] == ["retry", "sent"]


async def test_exhausted_retries_go_to_dead_letter_and_can_be_retried(
    client: AsyncClient, harness: Harness
) -> None:
    notification_id = await create(client)

    async def always_fail(message):
        raise TransientProviderError("down")

    harness.providers["email"].send = always_fail
    outcomes = []
    for _ in range(3):
        outcomes.append(await drain_one(client, harness))
        await asyncio.sleep(0.1)
        await harness.queue.promote_due()
    assert outcomes == ["retrying", "retrying", "dead"]

    dead = await client.get("/api/v1/dlq")
    assert [item["id"] for item in dead.json()["items"]] == [notification_id]

    async def ok(message):
        return "email-ok"

    harness.providers["email"].send = ok
    retried = await client.post(f"/api/v1/dlq/{notification_id}/retry")
    assert retried.json()["status"] == "queued"
    assert retried.json()["attempts"] == 0
    assert await drain_one(client, harness) == "sent"
    assert (await client.post(f"/api/v1/dlq/{notification_id}/retry")).status_code == 409


async def test_permanent_failure_is_dead_immediately(client: AsyncClient, harness: Harness) -> None:
    notification_id = await create(client, channel="push", recipient="invalid-token")
    assert await drain_one(client, harness) == "dead"
    body = await fetch(client, notification_id)
    assert body["status"] == "dead"
    assert body["attempts"] == 1

    async def refuse(message):
        raise PermanentProviderError("bad address")

    harness.providers["email"].send = refuse
    other = await create(client)
    assert await drain_one(client, harness) == "dead"
    assert (await fetch(client, other))["last_error"] == "bad address"


async def test_unexpected_exception_is_treated_as_transient(
    client: AsyncClient, harness: Harness
) -> None:
    notification_id = await create(client)

    async def boom(message):
        raise RuntimeError("bug")

    harness.providers["email"].send = boom
    assert await drain_one(client, harness) == "retrying"
    assert "unexpected error" in (await fetch(client, notification_id))["last_error"]


async def test_cancelled_notification_is_not_delivered(
    client: AsyncClient, harness: Harness
) -> None:
    notification_id = await create(client)
    await harness.queue.push(uuid.UUID(notification_id), 1)
    await client.post(f"/api/v1/notifications/{notification_id}/cancel")
    await harness.queue.push(uuid.UUID(notification_id), 1)
    assert await drain_one(client, harness) == "skipped"
    assert (await fetch(client, notification_id))["status"] == "cancelled"


async def test_duplicate_queue_entries_deliver_once(client: AsyncClient, harness: Harness) -> None:
    notification_id = await create(client)
    await harness.queue.push(uuid.UUID(notification_id), 1)
    assert await drain_one(client, harness) == "sent"
    assert await harness.delivery.process(uuid.UUID(notification_id)) == "skipped"
    assert (await fetch(client, notification_id))["attempts"] == 1


async def test_channel_rate_limit_defers_without_consuming_attempt(
    client: AsyncClient, harness: Harness
) -> None:
    harness.delivery.settings.channel_rate_email = 1
    first = await create(client)
    second = await create(client)
    assert await drain_one(client, harness) == "sent"
    assert await drain_one(client, harness) == "throttled"
    body = await fetch(client, second)
    assert body["status"] == "retrying"
    assert body["attempts"] == 0
    assert await harness.queue.depths() == (0, 1)
    assert (await fetch(client, first))["status"] == "sent"


async def test_priority_is_respected_by_workers(client: AsyncClient, harness: Harness) -> None:
    marketing = await create(client, category="marketing")
    otp = await create(client, category="otp")
    assert str(await harness.queue.pop(0.1)) == otp
    assert str(await harness.queue.pop(0.1)) == marketing


async def test_reaper_recovers_expired_lease(
    client: AsyncClient,
    harness: Harness,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    notification_id = await create(client)
    await harness.queue.pop(0.1)
    async with sessions() as session:
        await session.execute(
            update(Notification)
            .where(Notification.id == uuid.UUID(notification_id))
            .values(
                status="processing",
                attempts=1,
                locked_until=datetime.now(UTC) - timedelta(seconds=5),
            )
        )
        await session.commit()
    result = await harness.reaper.run_once()
    assert result["lease"] == 1
    assert (await fetch(client, notification_id))["status"] == "retrying"
    assert await drain_one(client, harness) == "sent"


async def test_reaper_kills_expired_lease_after_final_attempt(
    client: AsyncClient,
    harness: Harness,
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    notification_id = await create(client)
    async with sessions() as session:
        await session.execute(
            update(Notification)
            .where(Notification.id == uuid.UUID(notification_id))
            .values(
                status="processing",
                attempts=3,
                locked_until=datetime.now(UTC) - timedelta(seconds=5),
            )
        )
        await session.commit()
    await harness.reaper.run_once()
    assert (await fetch(client, notification_id))["status"] == "dead"


async def test_reaper_requeues_notification_lost_from_queue(
    client: AsyncClient, harness: Harness
) -> None:
    notification_id = await create(client)
    await harness.queue.pop(0.1)
    assert await harness.queue.depths() == (0, 0)
    await asyncio.sleep(0.05)
    result = await harness.reaper.run_once()
    assert result["stale"] == 1
    assert await drain_one(client, harness) == "sent"
    assert (await fetch(client, notification_id))["status"] == "sent"


async def test_scheduled_notification_not_touched_by_reaper_until_due(
    client: AsyncClient, harness: Harness
) -> None:
    due = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    await create(client, scheduled_at=due)
    result = await harness.reaper.run_once()
    assert result["stale"] == 0
    assert await harness.queue.depths() == (0, 1)
