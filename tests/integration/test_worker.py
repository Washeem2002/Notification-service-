import asyncio

from httpx import AsyncClient

from tests.conftest import Harness
from worker.runner import WorkerRunner


async def wait_for_status(client: AsyncClient, notification_id: str, expected: str) -> dict:
    for _ in range(300):
        body = (await client.get(f"/api/v1/notifications/{notification_id}")).json()
        if body["status"] == expected:
            return body
        await asyncio.sleep(0.05)
    raise AssertionError(f"notification never reached {expected}: {body}")


async def test_worker_runner_delivers_end_to_end(client: AsyncClient, harness: Harness) -> None:
    settings = harness.delivery.settings
    settings.worker_concurrency = 2
    settings.reaper_interval_seconds = 1
    runner = WorkerRunner(settings, harness.queue, harness.delivery, harness.reaper)
    task = asyncio.create_task(runner.run())
    ids = []
    for category in ("marketing", "otp", "transactional"):
        response = await client.post(
            "/api/v1/notifications",
            json={
                "user_id": "u1",
                "channel": "sms",
                "category": category,
                "recipient": "+14155550123",
                "body": "hi",
            },
        )
        ids.append(response.json()["id"])
    for notification_id in ids:
        body = await wait_for_status(client, notification_id, "sent")
        assert body["attempts"] == 1
    runner.stop()
    await asyncio.wait_for(task, timeout=5)


async def test_worker_runner_retries_through_delayed_queue(
    client: AsyncClient, harness: Harness
) -> None:
    from app.providers.base import TransientProviderError

    original = harness.providers["sms"].send
    calls = {"n": 0}

    async def flaky(message):
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientProviderError("blip")
        return await original(message)

    harness.providers["sms"].send = flaky
    settings = harness.delivery.settings
    settings.worker_concurrency = 1
    runner = WorkerRunner(settings, harness.queue, harness.delivery, harness.reaper)
    task = asyncio.create_task(runner.run())
    response = await client.post(
        "/api/v1/notifications",
        json={"user_id": "u1", "channel": "sms", "recipient": "+14155550123", "body": "hi"},
    )
    body = await wait_for_status(client, response.json()["id"], "sent")
    assert body["attempts"] == 3
    runner.stop()
    await asyncio.wait_for(task, timeout=5)
