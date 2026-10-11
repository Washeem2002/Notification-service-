from datetime import UTC, datetime, timedelta

from httpx import AsyncClient

EMAIL = {
    "user_id": "u1",
    "channel": "email",
    "category": "transactional",
    "recipient": "user@example.com",
    "subject": "Hello",
    "body": "World",
}


async def test_requires_api_key(client: AsyncClient) -> None:
    response = await client.post("/api/v1/notifications", json=EMAIL, headers={"X-API-Key": "bad"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_health_and_ready(client: AsyncClient) -> None:
    assert (await client.get("/health")).json() == {"status": "ok"}
    ready = await client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"database": "ok", "redis": "ok"}


async def test_metrics_endpoint(client: AsyncClient) -> None:
    response = await client.get("/metrics")
    assert response.status_code == 200
    assert "http_requests_total" in response.text


async def test_create_notification_is_queued(client: AsyncClient) -> None:
    response = await client.post("/api/v1/notifications", json=EMAIL)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["priority"] == 1
    fetched = await client.get(f"/api/v1/notifications/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["history"] == []


async def test_priority_by_category(client: AsyncClient) -> None:
    otp = await client.post("/api/v1/notifications", json={**EMAIL, "category": "otp"})
    marketing = await client.post("/api/v1/notifications", json={**EMAIL, "category": "marketing"})
    assert otp.json()["priority"] == 0
    assert marketing.json()["priority"] == 2


async def test_idempotency_key_returns_same_notification(client: AsyncClient) -> None:
    headers = {"Idempotency-Key": "abc-123"}
    first = await client.post("/api/v1/notifications", json=EMAIL, headers=headers)
    second = await client.post("/api/v1/notifications", json=EMAIL, headers=headers)
    assert first.status_code == 202
    assert second.status_code == 200
    assert second.headers["Idempotent-Replayed"] == "true"
    assert first.json()["id"] == second.json()["id"]
    listing = await client.get("/api/v1/notifications")
    assert len(listing.json()["items"]) == 1


async def test_validation_error_shape(client: AsyncClient) -> None:
    response = await client.post("/api/v1/notifications", json={**EMAIL, "recipient": "nope"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


async def test_template_flow(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/templates",
        json={
            "name": "welcome",
            "channel": "email",
            "subject": "Welcome {{ name }}",
            "body": "Hi {{ name }}, your code is {{ code }}",
        },
    )
    assert created.status_code == 201
    duplicate = await client.post(
        "/api/v1/templates",
        json={"name": "welcome", "channel": "email", "body": "x"},
    )
    assert duplicate.status_code == 409

    sent = await client.post(
        "/api/v1/notifications",
        json={
            "user_id": "u1",
            "channel": "email",
            "recipient": "user@example.com",
            "template_name": "welcome",
            "variables": {"name": "Sam", "code": "42"},
        },
    )
    assert sent.status_code == 202
    assert sent.json()["subject"] == "Welcome Sam"
    assert sent.json()["body"] == "Hi Sam, your code is 42"

    missing_var = await client.post(
        "/api/v1/notifications",
        json={
            "user_id": "u1",
            "channel": "email",
            "recipient": "user@example.com",
            "template_name": "welcome",
            "variables": {"name": "Sam"},
        },
    )
    assert missing_var.status_code == 400

    wrong_channel = await client.post(
        "/api/v1/notifications",
        json={
            "user_id": "u1",
            "channel": "sms",
            "recipient": "+14155550123",
            "template_name": "welcome",
        },
    )
    assert wrong_channel.status_code == 400

    unknown = await client.post(
        "/api/v1/notifications", json={**EMAIL, "template_name": "ghost", "body": None}
    )
    assert unknown.status_code == 404


async def test_template_update_and_delete(client: AsyncClient) -> None:
    await client.post("/api/v1/templates", json={"name": "t1", "channel": "sms", "body": "v1"})
    updated = await client.put("/api/v1/templates/t1", json={"body": "v2"})
    assert updated.json()["body"] == "v2"
    assert (await client.get("/api/v1/templates")).json()[0]["name"] == "t1"
    assert (await client.delete("/api/v1/templates/t1")).status_code == 204
    assert (await client.get("/api/v1/templates/t1")).status_code == 404
    bad = await client.post(
        "/api/v1/templates", json={"name": "bad", "channel": "sms", "body": "{{ oops"}
    )
    assert bad.status_code == 400


async def test_preferences_opt_out_skips_marketing_but_not_otp(client: AsyncClient) -> None:
    updated = await client.put(
        "/api/v1/users/u1/preferences",
        json={
            "preferences": [
                {"channel": "email", "category": "marketing", "enabled": False},
                {"channel": "email", "category": "otp", "enabled": False},
            ]
        },
    )
    assert updated.status_code == 200
    assert len(updated.json()["preferences"]) == 2

    marketing = await client.post("/api/v1/notifications", json={**EMAIL, "category": "marketing"})
    assert marketing.json()["status"] == "skipped"
    otp = await client.post("/api/v1/notifications", json={**EMAIL, "category": "otp"})
    assert otp.json()["status"] == "queued"
    fetched = await client.get("/api/v1/users/u1/preferences")
    assert fetched.json()["user_id"] == "u1"


async def test_scheduled_notification_goes_to_delayed_queue(client: AsyncClient) -> None:
    due = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    response = await client.post("/api/v1/notifications", json={**EMAIL, "scheduled_at": due})
    assert response.status_code == 202
    ready, delayed = await client.app.state.queue.depths()
    assert (ready, delayed) == (0, 1)


async def test_cancel_notification(client: AsyncClient) -> None:
    created = await client.post("/api/v1/notifications", json=EMAIL)
    notification_id = created.json()["id"]
    cancelled = await client.post(f"/api/v1/notifications/{notification_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    again = await client.post(f"/api/v1/notifications/{notification_id}/cancel")
    assert again.status_code == 409
    assert await client.app.state.queue.depths() == (0, 0)


async def test_list_filters_and_cursor_pagination(client: AsyncClient) -> None:
    for index in range(5):
        await client.post("/api/v1/notifications", json={**EMAIL, "user_id": f"user{index % 2}"})
    first = await client.get("/api/v1/notifications", params={"limit": 2})
    page = first.json()
    assert len(page["items"]) == 2
    assert page["next_cursor"]
    second = await client.get(
        "/api/v1/notifications", params={"limit": 2, "cursor": page["next_cursor"]}
    )
    seen = {item["id"] for item in page["items"]} | {item["id"] for item in second.json()["items"]}
    assert len(seen) == 4
    filtered = await client.get("/api/v1/notifications", params={"user_id": "user0"})
    assert len(filtered.json()["items"]) == 3
    bad = await client.get("/api/v1/notifications", params={"cursor": "garbage"})
    assert bad.status_code == 400


async def test_batch_create(client: AsyncClient) -> None:
    response = await client.post("/api/v1/notifications/batch", json={"items": [EMAIL, EMAIL]})
    assert response.status_code == 202
    assert len(response.json()["items"]) == 2
    assert (await client.app.state.queue.depths())[0] == 2


async def test_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/v1/notifications/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_producer_rate_limit(client: AsyncClient) -> None:
    client.app.state.settings.create_rate_limit = 2
    statuses = [
        (await client.post("/api/v1/notifications", json=EMAIL)).status_code for _ in range(4)
    ]
    assert statuses[:2] == [202, 202]
    assert statuses[-1] == 429
    blocked = await client.post("/api/v1/notifications", json=EMAIL)
    assert blocked.headers["Retry-After"]
