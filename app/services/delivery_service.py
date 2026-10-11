import random
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.metrics import DEAD_LETTERED, DELIVERY_ATTEMPTS, DELIVERY_LATENCY
from app.infra.queue import NotificationQueue
from app.infra.rate_limiter import TokenBucketLimiter
from app.models.base import Status
from app.models.notification import Notification
from app.providers.base import (
    Message,
    PermanentProviderError,
    Provider,
    TransientProviderError,
)
from app.repositories.notification_repo import NotificationRepository

log = get_logger("delivery")


def backoff_delay(attempt: int, base: float, cap: float) -> float:
    ceiling = min(cap, base * (2 ** max(0, attempt - 1)))
    return random.uniform(ceiling / 2, ceiling)


class DeliveryService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        queue: NotificationQueue,
        limiter: TokenBucketLimiter,
        providers: dict[str, Provider],
        settings: Settings,
    ) -> None:
        self.sessions = sessions
        self.queue = queue
        self.limiter = limiter
        self.providers = providers
        self.settings = settings

    async def process(self, notification_id: uuid.UUID) -> str:
        lease = datetime.now(UTC) + timedelta(seconds=self.settings.lease_seconds)
        async with self.sessions() as session:
            repo = NotificationRepository(session)
            if not await repo.claim(notification_id, lease):
                await session.rollback()
                return "skipped"
            await session.commit()
            notification = await repo.get(notification_id)
            if notification is None:
                return "missing"
            await session.refresh(notification)

            gate = await self.limiter.acquire(
                f"channel:{notification.channel}",
                self.settings.channel_rate(notification.channel),
                60.0,
            )
            if not gate.allowed:
                return await self.defer(session, repo, notification, gate.retry_after_seconds)

            provider = self.providers[notification.channel]
            message = Message(
                notification_id=notification.id,
                recipient=notification.recipient,
                subject=notification.subject,
                body=notification.body,
            )
            started = time.perf_counter()
            try:
                provider_id = await provider.send(message)
            except PermanentProviderError as exc:
                return await self.fail(session, repo, notification, str(exc), permanent=True)
            except TransientProviderError as exc:
                return await self.fail(session, repo, notification, str(exc), permanent=False)
            except Exception as exc:
                return await self.fail(
                    session, repo, notification, f"unexpected error: {exc}", permanent=False
                )
            finally:
                DELIVERY_LATENCY.labels(notification.channel).observe(time.perf_counter() - started)

            notification.status = Status.sent
            notification.provider_message_id = provider_id
            notification.sent_at = datetime.now(UTC)
            notification.locked_until = None
            notification.last_error = None
            await repo.record_attempt(notification.id, notification.attempts, "sent", None)
            await session.commit()
            DELIVERY_ATTEMPTS.labels(notification.channel, "sent").inc()
            return "sent"

    async def defer(
        self,
        session: AsyncSession,
        repo: NotificationRepository,
        notification: Notification,
        delay: float,
    ) -> str:
        delay = max(delay, 1.0)
        due = datetime.now(UTC) + timedelta(seconds=delay)
        notification.status = Status.retrying
        notification.attempts = max(0, notification.attempts - 1)
        notification.next_attempt_at = due
        notification.locked_until = None
        await session.commit()
        await self.queue.push_delayed(notification.id, notification.priority, due.timestamp())
        DELIVERY_ATTEMPTS.labels(notification.channel, "throttled").inc()
        return "throttled"

    async def fail(
        self,
        session: AsyncSession,
        repo: NotificationRepository,
        notification: Notification,
        error: str,
        permanent: bool,
    ) -> str:
        notification.last_error = error[:1000]
        notification.locked_until = None
        exhausted = notification.attempts >= notification.max_attempts
        if permanent or exhausted:
            notification.status = Status.dead
            notification.next_attempt_at = None
            await repo.record_attempt(notification.id, notification.attempts, "dead", error[:1000])
            await session.commit()
            DEAD_LETTERED.labels(notification.channel).inc()
            DELIVERY_ATTEMPTS.labels(notification.channel, "dead").inc()
            log.warning("notification_dead", id=str(notification.id), error=error)
            return "dead"

        delay = backoff_delay(
            notification.attempts,
            self.settings.backoff_base_seconds,
            self.settings.backoff_max_seconds,
        )
        due = datetime.now(UTC) + timedelta(seconds=delay)
        notification.status = Status.retrying
        notification.next_attempt_at = due
        await repo.record_attempt(notification.id, notification.attempts, "retry", error[:1000])
        await session.commit()
        await self.queue.push_delayed(notification.id, notification.priority, due.timestamp())
        DELIVERY_ATTEMPTS.labels(notification.channel, "retry").inc()
        return "retrying"
