import uuid

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_notification_service, require_api_key
from app.core.errors import AppError
from app.schemas.notification import NotificationOut, NotificationPage
from app.services.notification_service import NotificationService

router = APIRouter(prefix="/api/v1/dlq", tags=["dlq"], dependencies=[Depends(require_api_key)])


@router.get("", response_model=NotificationPage)
async def list_dead(
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    service: NotificationService = Depends(get_notification_service),
) -> NotificationPage:
    try:
        rows, next_cursor = await service.list_dead(limit, cursor)
    except ValueError as exc:
        raise AppError("invalid cursor") from exc
    return NotificationPage(
        items=[NotificationOut.model_validate(row) for row in rows], next_cursor=next_cursor
    )


@router.post("/{notification_id}/retry", response_model=NotificationOut)
async def retry_dead(
    notification_id: uuid.UUID,
    service: NotificationService = Depends(get_notification_service),
) -> NotificationOut:
    return NotificationOut.model_validate(await service.retry_dead(notification_id))
