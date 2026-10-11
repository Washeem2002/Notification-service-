import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status

from app.api.deps import get_notification_service, get_settings_dep, limit_producer, require_api_key
from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.notification import (
    BatchCreate,
    BatchResult,
    NotificationCreate,
    NotificationDetail,
    NotificationOut,
    NotificationPage,
)
from app.services.notification_service import NotificationService

router = APIRouter(
    prefix="/api/v1/notifications",
    tags=["notifications"],
    dependencies=[Depends(require_api_key)],
)


@router.post(
    "",
    response_model=NotificationOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit_producer)],
)
async def create_notification(
    body: NotificationCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None, max_length=200),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationOut:
    notification, created = await service.create(body, idempotency_key)
    if not created:
        response.status_code = status.HTTP_200_OK
        response.headers["Idempotent-Replayed"] = "true"
    return NotificationOut.model_validate(notification)


@router.post(
    "/batch",
    response_model=BatchResult,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit_producer)],
)
async def create_batch(
    body: BatchCreate,
    service: NotificationService = Depends(get_notification_service),
    settings: Settings = Depends(get_settings_dep),
) -> BatchResult:
    if len(body.items) > settings.batch_max_size:
        raise AppError(f"batch size cannot exceed {settings.batch_max_size}")
    created = await service.create_batch(body.items)
    return BatchResult(items=[NotificationOut.model_validate(item) for item in created])


@router.get("", response_model=NotificationPage)
async def list_notifications(
    user_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    channel: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationPage:
    try:
        rows, next_cursor = await service.list_page(limit, user_id, status_filter, channel, cursor)
    except ValueError as exc:
        raise AppError("invalid cursor") from exc
    return NotificationPage(
        items=[NotificationOut.model_validate(row) for row in rows], next_cursor=next_cursor
    )


@router.get("/{notification_id}", response_model=NotificationDetail)
async def get_notification(
    notification_id: uuid.UUID,
    service: NotificationService = Depends(get_notification_service),
) -> NotificationDetail:
    notification, history = await service.detail(notification_id)
    detail = NotificationDetail.model_validate(notification)
    detail.history = [item for item in history]
    return detail


@router.post("/{notification_id}/cancel", response_model=NotificationOut)
async def cancel_notification(
    notification_id: uuid.UUID,
    service: NotificationService = Depends(get_notification_service),
) -> NotificationOut:
    return NotificationOut.model_validate(await service.cancel(notification_id))
