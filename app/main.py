import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.api.routers import dlq, health, notifications, preferences, templates
from app.core.config import Settings, get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.metrics import HTTP_LATENCY, HTTP_REQUESTS
from app.infra.db import build_engine, build_sessionmaker
from app.infra.queue import NotificationQueue
from app.infra.rate_limiter import TokenBucketLimiter
from app.infra.redis import build_redis


def create_app(
    settings: Settings | None = None,
    engine: AsyncEngine | None = None,
    redis: Redis | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db_engine = engine or build_engine(settings.database_url)
        redis_client = redis or build_redis(settings.redis_url)
        sessions: async_sessionmaker[AsyncSession] = build_sessionmaker(db_engine)
        app.state.settings = settings
        app.state.engine = db_engine
        app.state.sessions = sessions
        app.state.redis = redis_client
        app.state.queue = NotificationQueue(redis_client)
        app.state.limiter = TokenBucketLimiter(redis_client)
        yield
        if redis is None:
            await redis_client.aclose()
        if engine is None:
            await db_engine.dispose()

    app = FastAPI(title="Notification Service", version="1.0.0", lifespan=lifespan)
    register_error_handlers(app)

    @app.middleware("http")
    async def observe(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        response = await call_next(request)
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
        HTTP_LATENCY.labels(request.method, path).observe(time.perf_counter() - started)
        response.headers["X-Request-ID"] = request_id
        return response

    app.include_router(health.router)
    app.include_router(notifications.router)
    app.include_router(templates.router)
    app.include_router(preferences.router)
    app.include_router(dlq.router)
    return app


app = create_app()
