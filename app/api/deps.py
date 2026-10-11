import secrets
from collections.abc import AsyncIterator

from fastapi import Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import RateLimitedError, UnauthorizedError
from app.infra.queue import NotificationQueue
from app.infra.rate_limiter import TokenBucketLimiter
from app.services.notification_service import NotificationService
from app.services.preference_service import PreferenceService
from app.services.template_service import TemplateService


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessions() as session:
        yield session


async def require_api_key(
    settings: Settings = Depends(get_settings_dep),
    x_api_key: str | None = Header(default=None),
) -> str:
    if x_api_key:
        for key in settings.api_keys:
            if secrets.compare_digest(key, x_api_key):
                return key
    raise UnauthorizedError("missing or invalid api key")


async def limit_producer(
    request: Request,
    response: Response,
    api_key: str = Depends(require_api_key),
    settings: Settings = Depends(get_settings_dep),
) -> None:
    limiter: TokenBucketLimiter = request.app.state.limiter
    result = await limiter.acquire(f"producer:{api_key}", settings.create_rate_limit, 60.0)
    response.headers["X-RateLimit-Limit"] = str(settings.create_rate_limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    if not result.allowed:
        retry = max(1, int(result.retry_after_seconds + 0.999))
        raise RateLimitedError("rate limit exceeded", headers={"Retry-After": str(retry)})


def get_queue(request: Request) -> NotificationQueue:
    return request.app.state.queue


def get_notification_service(
    session: AsyncSession = Depends(get_session),
    queue: NotificationQueue = Depends(get_queue),
    settings: Settings = Depends(get_settings_dep),
) -> NotificationService:
    return NotificationService(session, queue, settings)


def get_template_service(session: AsyncSession = Depends(get_session)) -> TemplateService:
    return TemplateService(session)


def get_preference_service(session: AsyncSession = Depends(get_session)) -> PreferenceService:
    return PreferenceService(session)
