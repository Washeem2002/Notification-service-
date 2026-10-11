import random
import uuid

from locust import HttpUser, between, task

HEADERS = {"X-API-Key": "dev-key"}


class Producer(HttpUser):
    wait_time = between(0.01, 0.1)

    def on_start(self) -> None:
        self.client.post(
            "/api/v1/templates",
            json={
                "name": "load_welcome",
                "channel": "email",
                "subject": "Welcome {{ name }}",
                "body": "Hello {{ name }}",
            },
            headers=HEADERS,
        )

    @task(6)
    def transactional_email(self) -> None:
        self.client.post(
            "/api/v1/notifications",
            json={
                "user_id": f"user{random.randint(1, 5000)}",
                "channel": "email",
                "category": "transactional",
                "recipient": "load@example.com",
                "template_name": "load_welcome",
                "variables": {"name": "Load"},
            },
            headers={**HEADERS, "Idempotency-Key": str(uuid.uuid4())},
            name="create email",
        )

    @task(3)
    def otp_sms(self) -> None:
        self.client.post(
            "/api/v1/notifications",
            json={
                "user_id": f"user{random.randint(1, 5000)}",
                "channel": "sms",
                "category": "otp",
                "recipient": "+14155550123",
                "body": "Your code is 123456",
            },
            headers=HEADERS,
            name="create otp",
        )

    @task(1)
    def marketing_push(self) -> None:
        self.client.post(
            "/api/v1/notifications",
            json={
                "user_id": f"user{random.randint(1, 5000)}",
                "channel": "push",
                "category": "marketing",
                "recipient": "device-token",
                "body": "Big sale",
            },
            headers=HEADERS,
            name="create marketing",
        )
