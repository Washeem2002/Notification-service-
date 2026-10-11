import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import InvalidStateError, NotFoundError
from app.core.logging import get_logger
from app.core.metrics import NOTIFICATIONS_CREATED, NOTIFICATIONS_SKIPPED
from app.infra.queue import NotificationQueue
from app.models.base import PRIORITY, Category, Status
from app.models.notification import Notification
from app.repositories.notification_repo import NotificationRepository, encode_cursor
from app.schemas.notification import NotificationCreate
from app.services.preference_service import PreferenceService
from app.services.template_service import TemplateService

log = get_logger("notification_service")


class NotificationService:
    def __init__(self, session: AsyncSession, queue: NotificationQueue, settings: Settings) -> None:
        self.session = session
        self.queue = queue
        self.settings = settings
        self.repo = NotificationRepository(session)
        self.templates = TemplateService(session)
        self.preferences = PreferenceService(session)

    async def create(
        self, data: NotificationCreate, idempotency_key: str | None = None
    ) -> tuple[Notification, bool]:
        if idempotency_key:
            existing = await self.repo.get_by_idempotency_key(idempotency_key)
            if existing:
                return existing, False

        subject, body = data.subject, data.body or ""
        if data.template_name:
            subject, body = await self.templates.render(
                data.template_name, data.channel.value, data.variables
            )

        allowed = await self.preferences.is_allowed(
            data.user_id, data.channel.value, data.category.value
        )
        scheduled = self.normalize(data.scheduled_at)
        notification = Notification(
            id=uuid.uuid4(),
            idempotency_key=idempotency_key,
            user_id=data.user_id,
            channel=data.channel.value,
            category=data.category.value,
            priority=PRIORITY[Category(data.category)],
            recipient=data.recipient,
            template_name=data.template_name,
            subject=subject,
            body=body,
            payload=data.variables or None,
            status=Status.queued if allowed else Status.skipped,
            attempts=0,
            max_attempts=self.settings.max_attempts,
            scheduled_at=scheduled,
            next_attempt_at=scheduled,
            last_error=None if allowed else "recipient opted out",
        )
        try:
            await self.repo.add(notification)
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            if idempotency_key:
                existing = await self.repo.get_by_idempotency_key(idempotency_key)
                if existing:
                    return existing, False
            raise

        if not allowed:
            NOTIFICATIONS_SKIPPED.labels(data.channel.value, data.category.value).inc()
            return notification, True

        NOTIFICATIONS_CREATED.labels(data.channel.value, data.category.value).inc()
        await self.enqueue(notification)
        return notification, True

    async def create_batch(self, items: list[NotificationCreate]) -> list[Notification]:
        created: list[Notification] = []
        for item in items:
            notification, _ = await self.create(item)
            created.append(notification)
        return created

    async def enqueue(self, notification: Notification) -> None:
        try:
            due = notification.scheduled_at
            if due and due > datetime.now(UTC):
                await self.queue.push_delayed(
                    notification.id, notification.priority, due.timestamp()
                )
            else:
                await self.queue.push(notification.id, notification.priority)
        except Exception as exc:
            log.warning("enqueue_failed", id=str(notification.id), error=str(exc))

    @staticmethod
    def normalize(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    async def get(self, notification_id: uuid.UUID) -> Notification:
        notification = await self.repo.get(notification_id)
        if not notification:
            raise NotFoundError(f"notification {notification_id} not found")
        return notification

    async def detail(self, notification_id: uuid.UUID) -> tuple[Notification, list]:
        notification = await self.get(notification_id)
        return notification, await self.repo.history(notification_id)

    async def list_page(
        self,
        limit: int,
        user_id: str | None,
        status: str | None,
        channel: str | None,
        cursor: str | None,
    ) -> tuple[list[Notification], str | None]:
        rows = await self.repo.list_page(limit + 1, user_id, status, channel, cursor)
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more else None
        return rows, next_cursor

    async def cancel(self, notification_id: uuid.UUID) -> Notification:
        notification = await self.get(notification_id)
        if not await self.repo.cancel(notification_id):
            raise InvalidStateError(f"cannot cancel notification in status {notification.status}")
        await self.session.commit()
        await self.session.refresh(notification)
        try:
            await self.queue.remove(notification_id)
        except Exception as exc:
            log.warning("queue_remove_failed", id=str(notification_id), error=str(exc))
        return notification

    async def list_dead(self, limit: int, cursor: str | None) -> tuple[list[Notification], str | None]:
        return await self.list_page(limit, None, Status.dead.value, None, cursor)

    async def retry_dead(self, notification_id: uuid.UUID) -> Notification:
        notification = await self.get(notification_id)
        if notification.status != Status.dead:
            raise InvalidStateError("only dead notifications can be retried")
        notification.status = Status.queued
        notification.attempts = 0
        notification.last_error = None
        notification.next_attempt_at = None
        notification.locked_until = None
        await self.session.commit()
        await self.enqueue(notification)
        return notification
