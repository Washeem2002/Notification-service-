from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import get_logger
from app.core.metrics import DELAYED_DEPTH, QUEUE_DEPTH, REAPED
from app.infra.queue import NotificationQueue
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
            to_push = []
            for notification in await repo.expired_leases(now):
                final = notification.attempts >= notification.max_attempts
                if not await repo.reclaim_expired(notification.id, now, dead=final):
                    continue
                if not final:
                    to_push.append((notification.id, notification.priority))
                recovered["lease"] += 1
                REAPED.labels("lease").inc()
            await session.commit()
            for notification_id, priority in to_push:
                await self.queue.push(notification_id, priority)

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
