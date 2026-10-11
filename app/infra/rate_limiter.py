import time
from dataclasses import dataclass
from pathlib import Path

from redis.asyncio import Redis

from app.core.logging import get_logger

SCRIPT = (Path(__file__).parent / "lua" / "token_bucket.lua").read_text()
log = get_logger("rate_limiter")


@dataclass(frozen=True)
class LimitResult:
    allowed: bool
    remaining: int
    retry_after_seconds: float


class TokenBucketLimiter:
    def __init__(self, redis: Redis, prefix: str = "rl", fail_open: bool = True) -> None:
        self.redis = redis
        self.prefix = prefix
        self.fail_open = fail_open
        self.script = redis.register_script(SCRIPT)

    async def acquire(
        self, key: str, capacity: int, per_seconds: float = 60.0, cost: int = 1
    ) -> LimitResult:
        refill = capacity / per_seconds
        now_ms = int(time.time() * 1000)
        try:
            allowed, remaining, retry_ms = await self.script(
                keys=[f"{self.prefix}:{key}"], args=[capacity, refill, now_ms, cost]
            )
        except Exception as exc:
            log.warning("rate_limiter_unavailable", error=str(exc))
            return LimitResult(self.fail_open, capacity, 0.0)
        return LimitResult(bool(allowed), int(remaining), int(retry_ms) / 1000)
