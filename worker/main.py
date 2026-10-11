import asyncio
import signal

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infra.db import build_engine, build_sessionmaker
from app.infra.queue import NotificationQueue
from app.infra.rate_limiter import TokenBucketLimiter
from app.infra.redis import build_redis
from app.providers.registry import build_providers
from app.services.delivery_service import DeliveryService
from app.services.reaper_service import ReaperService
from worker.runner import WorkerRunner


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    engine = build_engine(settings.database_url)
    sessions = build_sessionmaker(engine)
    redis = build_redis(settings.redis_url)
    queue = NotificationQueue(redis)
    limiter = TokenBucketLimiter(redis)
    delivery = DeliveryService(sessions, queue, limiter, build_providers(settings), settings)
    reaper = ReaperService(sessions, queue, settings)
    runner = WorkerRunner(settings, queue, delivery, reaper)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, runner.stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_: runner.stop())

    try:
        await runner.run()
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
