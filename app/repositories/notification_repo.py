import base64
import uuid
from datetime import datetime

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Status, utcnow
from app.models.notification import Notification, NotificationAttempt


def encode_cursor(created_at: datetime, notification_id: uuid.UUID) -> str:
    raw = f"{created_at.isoformat()}|{notification_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    stamp, _, raw_id = raw.partition("|")
    return datetime.fromisoformat(stamp), uuid.UUID(raw_id)


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add(self, notification: Notification) -> Notification:
        self.session.add(notification)
        await self.session.flush()
        return notification

    async def get(self, notification_id: uuid.UUID) -> Notification | None:
        return await self.session.get(Notification, notification_id)

    async def get_by_idempotency_key(self, key: str) -> Notification | None:
        result = await self.session.execute(
            select(Notification).where(Notification.idempotency_key == key)
        )
        return result.scalar_one_or_none()

    async def list_page(
        self,
        limit: int,
        user_id: str | None = None,
        status: str | None = None,
        channel: str | None = None,
        cursor: str | None = None,
    ) -> list[Notification]:
        query = select(Notification)
        if user_id:
            query = query.where(Notification.user_id == user_id)
        if status:
            query = query.where(Notification.status == status)
        if channel:
            query = query.where(Notification.channel == channel)
        if cursor:
            created_at, last_id = decode_cursor(cursor)
            query = query.where(
                or_(
                    Notification.created_at < created_at,
                    and_(Notification.created_at == created_at, Notification.id < last_id),
                )
            )
        query = query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars())

    async def history(self, notification_id: uuid.UUID) -> list[NotificationAttempt]:
        result = await self.session.execute(
            select(NotificationAttempt)
            .where(NotificationAttempt.notification_id == notification_id)
            .order_by(NotificationAttempt.id)
        )
        return list(result.scalars())

    async def record_attempt(
        self, notification_id: uuid.UUID, attempt: int, outcome: str, error: str | None
    ) -> None:
        self.session.add(
            NotificationAttempt(
                notification_id=notification_id, attempt=attempt, outcome=outcome, error=error
            )
        )
        await self.session.flush()

    async def claim(self, notification_id: uuid.UUID, lease_until: datetime) -> bool:
        result = await self.session.execute(
            update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.status.in_([Status.queued, Status.retrying]),
            )
            .values(
                status=Status.processing,
                locked_until=lease_until,
                attempts=Notification.attempts + 1,
                updated_at=utcnow(),
            )
        )
        return result.rowcount == 1

    async def cancel(self, notification_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.status.in_([Status.queued, Status.retrying]),
            )
            .values(status=Status.cancelled, updated_at=utcnow())
        )
        return result.rowcount == 1

    async def expired_leases(self, now: datetime, limit: int = 200) -> list[Notification]:
        result = await self.session.execute(
            select(Notification)
            .where(Notification.status == Status.processing, Notification.locked_until < now)
            .limit(limit)
        )
        return list(result.scalars())

    async def stale_queued(self, before: datetime, limit: int = 200) -> list[Notification]:
        result = await self.session.execute(
            select(Notification)
            .where(
                Notification.status.in_([Status.queued, Status.retrying]),
                Notification.updated_at < before,
                or_(Notification.next_attempt_at.is_(None), Notification.next_attempt_at < before),
            )
            .limit(limit)
        )
        return list(result.scalars())
