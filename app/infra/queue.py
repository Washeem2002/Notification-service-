import time
import uuid

from redis.asyncio import Redis

READY_KEY = "queue:ready"
DELAYED_KEY = "queue:delayed"
PRIORITY_WEIGHT = 10_000_000_000_000


def ready_score(priority: int, now: float | None = None) -> float:
    moment = time.time() if now is None else now
    return priority * PRIORITY_WEIGHT + int(moment * 1000)


class NotificationQueue:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def push(self, notification_id: uuid.UUID, priority: int) -> None:
        await self.redis.zadd(READY_KEY, {str(notification_id): ready_score(priority)})

    async def push_delayed(
        self, notification_id: uuid.UUID, priority: int, due_at: float
    ) -> None:
        await self.redis.zadd(DELAYED_KEY, {f"{priority}:{notification_id}": due_at})

    async def pop(self, timeout: float = 1.0) -> uuid.UUID | None:
        item = await self.redis.bzpopmin(READY_KEY, timeout=timeout)
        if not item:
            return None
        return uuid.UUID(item[1])

    async def promote_due(self, now: float | None = None, limit: int = 500) -> int:
        moment = time.time() if now is None else now
        due = await self.redis.zrangebyscore(DELAYED_KEY, "-inf", moment, start=0, num=limit)
        promoted = 0
        for member in due:
            if await self.redis.zrem(DELAYED_KEY, member):
                priority, _, raw_id = member.partition(":")
                await self.redis.zadd(READY_KEY, {raw_id: ready_score(int(priority), moment)})
                promoted += 1
        return promoted

    async def remove(self, notification_id: uuid.UUID) -> None:
        raw = str(notification_id)
        await self.redis.zrem(READY_KEY, raw)
        for priority in (0, 1, 2):
            await self.redis.zrem(DELAYED_KEY, f"{priority}:{raw}")

    async def depths(self) -> tuple[int, int]:
        return await self.redis.zcard(READY_KEY), await self.redis.zcard(DELAYED_KEY)
