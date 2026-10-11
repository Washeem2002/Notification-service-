from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.metrics import DELAYED_DEPTH, QUEUE_DEPTH, REAPED
from app.infra.queue import NotificationQueue
from app.models.base import Status
from app.repositories.notification_repo import NotificationRepository

log = get_logger("reaper")


class ReaperService:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        queue: NotificationQueue,
        settings: Settings,
    ) -> None:
        self.sessions = sessions
        self.queue = queue
        self.settings = settings

    async def run_once(self) -> dict[str, int]:
        now = datetime.now(UTC)
        recovered = {"lease": 0, "stale": 0, "promoted": 0}
        recovered["promoted"] = await self.queue.promote_due()

        async with self.sessions() as session:
            repo = NotificationRepository(session)
            for notification in await repo.expired_leases(now):
                if notification.attempts >= notification.max_attempts:
                    notification.status = Status.dead
                    notification.last_error = "lease expired after final attempt"
                    notification.locked_until = None
                else:
                    notification.status = Status.retrying
                    notification.locked_until = None
                    notification.next_attempt_at = now
                    await session.flush()
                    await self.queue.push(notification.id, notification.priority)
                recovered["lease"] += 1
                REAPED.labels("lease").inc()
            await session.commit()

            cutoff = now - timedelta(seconds=self.settings.stale_queued_seconds)
            for notification in await repo.stale_queued(cutoff):
                notification.updated_at = now
                await self.queue.push(notification.id, notification.priority)
                recovered["stale"] += 1
                REAPED.labels("stale").inc()
            await session.commit()

        ready, delayed = await self.queue.depths()
        QUEUE_DEPTH.set(ready)
        DELAYED_DEPTH.set(delayed)
        if recovered["lease"] or recovered["stale"]:
            log.info("reaper_recovered", **recovered)
        return recovered
