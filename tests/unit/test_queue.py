import time
import uuid

import fakeredis

from app.infra.queue import NotificationQueue


async def test_priority_order(redis: fakeredis.FakeAsyncRedis) -> None:
    queue = NotificationQueue(redis)
    low, normal, high = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await queue.push(low, 2)
    await queue.push(normal, 1)
    await queue.push(high, 0)
    assert [await queue.pop(0.1) for _ in range(3)] == [high, normal, low]


async def test_fifo_within_same_priority(redis: fakeredis.FakeAsyncRedis) -> None:
    queue = NotificationQueue(redis)
    first, second = uuid.uuid4(), uuid.uuid4()
    await queue.push(first, 1)
    await queue.push(second, 1)
    assert await queue.pop(0.1) == first
    assert await queue.pop(0.1) == second


async def test_empty_pop_returns_none(redis: fakeredis.FakeAsyncRedis) -> None:
    assert await NotificationQueue(redis).pop(0.1) is None


async def test_delayed_items_promote_when_due(redis: fakeredis.FakeAsyncRedis) -> None:
    queue = NotificationQueue(redis)
    item = uuid.uuid4()
    await queue.push_delayed(item, 0, time.time() + 100)
    assert await queue.promote_due() == 0
    assert await queue.pop(0.1) is None
    assert await queue.promote_due(now=time.time() + 200) == 1
    assert await queue.pop(0.1) == item


async def test_remove_clears_both_queues(redis: fakeredis.FakeAsyncRedis) -> None:
    queue = NotificationQueue(redis)
    ready, delayed = uuid.uuid4(), uuid.uuid4()
    await queue.push(ready, 1)
    await queue.push_delayed(delayed, 1, time.time() + 50)
    await queue.remove(ready)
    await queue.remove(delayed)
    assert await queue.depths() == (0, 0)
