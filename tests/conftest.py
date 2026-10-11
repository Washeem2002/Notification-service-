from collections.abc import AsyncIterator
from dataclasses import dataclass

import fakeredis
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.infra.queue import NotificationQueue
from app.infra.rate_limiter import TokenBucketLimiter
from app.main import create_app
from app.models import Base
from app.providers.base import Provider
from app.providers.registry import build_providers
from app.services.delivery_service import DeliveryService
from app.services.reaper_service import ReaperService


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite://",
        redis_url="redis://fake",
        api_keys=["test-key"],
        backoff_base_seconds=0.01,
        backoff_max_seconds=0.05,
        max_attempts=3,
        lease_seconds=1,
        stale_queued_seconds=0,
        channel_rate_email=1000,
        channel_rate_sms=1000,
        channel_rate_push=1000,
        create_rate_limit=1000,
    )


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def redis() -> AsyncIterator[fakeredis.FakeAsyncRedis]:
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    yield client
    await client.flushall()
    await client.aclose()


@pytest.fixture
def sessions(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def client(
    settings: Settings, engine: AsyncEngine, redis: fakeredis.FakeAsyncRedis
) -> AsyncIterator[AsyncClient]:
    app = create_app(settings=settings, engine=engine, redis=redis)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://test", headers={"X-API-Key": "test-key"}
        ) as http:
            http.app = app
            yield http


@dataclass
class Harness:
    queue: NotificationQueue
    delivery: DeliveryService
    reaper: ReaperService
    providers: dict[str, Provider]


@pytest.fixture
def harness(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    redis: fakeredis.FakeAsyncRedis,
) -> Harness:
    queue = NotificationQueue(redis)
    providers = build_providers(settings)
    delivery = DeliveryService(sessions, queue, TokenBucketLimiter(redis), providers, settings)
    reaper = ReaperService(sessions, queue, settings)
    return Harness(queue, delivery, reaper, providers)
