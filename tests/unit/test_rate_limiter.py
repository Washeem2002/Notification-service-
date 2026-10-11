import fakeredis

from app.infra.rate_limiter import TokenBucketLimiter


async def test_allows_up_to_capacity_then_blocks(redis: fakeredis.FakeAsyncRedis) -> None:
    limiter = TokenBucketLimiter(redis)
    results = [await limiter.acquire("k", capacity=3, per_seconds=60) for _ in range(5)]
    assert [r.allowed for r in results] == [True, True, True, False, False]
    assert results[-1].retry_after_seconds > 0


async def test_keys_are_isolated(redis: fakeredis.FakeAsyncRedis) -> None:
    limiter = TokenBucketLimiter(redis)
    for _ in range(2):
        await limiter.acquire("a", capacity=2, per_seconds=60)
    assert (await limiter.acquire("a", capacity=2, per_seconds=60)).allowed is False
    assert (await limiter.acquire("b", capacity=2, per_seconds=60)).allowed is True


async def test_refills_over_time(redis: fakeredis.FakeAsyncRedis) -> None:
    limiter = TokenBucketLimiter(redis)
    await limiter.acquire("r", capacity=1, per_seconds=0.2)
    assert (await limiter.acquire("r", capacity=1, per_seconds=0.2)).allowed is False
    import asyncio

    await asyncio.sleep(0.3)
    assert (await limiter.acquire("r", capacity=1, per_seconds=0.2)).allowed is True


async def test_fails_open_when_redis_unavailable() -> None:
    class Broken:
        def register_script(self, _: str):
            async def run(**_: object):
                raise ConnectionError("down")

            return run

    limiter = TokenBucketLimiter(Broken(), fail_open=True)
    assert (await limiter.acquire("k", capacity=1)).allowed is True
    closed = TokenBucketLimiter(Broken(), fail_open=False)
    assert (await closed.acquire("k", capacity=1)).allowed is False
