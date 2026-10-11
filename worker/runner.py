import asyncio

from app.core.config import Settings
from app.core.logging import get_logger
from app.infra.queue import NotificationQueue
from app.services.delivery_service import DeliveryService
from app.services.reaper_service import ReaperService

log = get_logger("worker")


class WorkerRunner:
    def __init__(
        self,
        settings: Settings,
        queue: NotificationQueue,
        delivery: DeliveryService,
        reaper: ReaperService,
    ) -> None:
        self.settings = settings
        self.queue = queue
        self.delivery = delivery
        self.reaper = reaper
        self.stop_event = asyncio.Event()

    async def consume(self, index: int) -> None:
        while not self.stop_event.is_set():
            try:
                notification_id = await self.queue.pop(timeout=1)
                if notification_id is None:
                    continue
                outcome = await self.delivery.process(notification_id)
                log.info("processed", worker=index, id=str(notification_id), outcome=outcome)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("consumer_error", worker=index, error=str(exc))
                await asyncio.sleep(1)

    async def promote_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                await self.queue.promote_due()
            except Exception as exc:
                log.error("promote_error", error=str(exc))
            await self.wait(1.0)

    async def reap_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                await self.reaper.run_once()
            except Exception as exc:
                log.error("reaper_error", error=str(exc))
            await self.wait(self.settings.reaper_interval_seconds)

    async def wait(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=seconds)
        except TimeoutError:
            return

    async def run(self) -> None:
        tasks = [
            asyncio.create_task(self.consume(index))
            for index in range(self.settings.worker_concurrency)
        ]
        tasks.append(asyncio.create_task(self.promote_loop()))
        tasks.append(asyncio.create_task(self.reap_loop()))
        log.info("worker_started", concurrency=self.settings.worker_concurrency)
        await self.stop_event.wait()
        await asyncio.gather(*tasks, return_exceptions=True)
        log.info("worker_stopped")

    def stop(self) -> None:
        self.stop_event.set()
