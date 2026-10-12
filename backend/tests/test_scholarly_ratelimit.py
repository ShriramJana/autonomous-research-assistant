from __future__ import annotations

import asyncio

from ara.scholarly.ratelimit import RateLimiter


class FakeTime:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 6))
        self.now += seconds


async def test_first_acquire_is_immediate() -> None:
    t = FakeTime()
    rl = RateLimiter(3.0, clock=t.clock, sleep=t.sleep)
    await rl.acquire()
    assert t.sleeps == []


async def test_parallel_acquires_are_spaced_by_interval() -> None:
    t = FakeTime()
    rl = RateLimiter(3.0, clock=t.clock, sleep=t.sleep)
    await asyncio.gather(*(rl.acquire() for _ in range(3)))
    assert t.sleeps == [3.0, 3.0]


async def test_no_wait_after_interval_elapsed() -> None:
    t = FakeTime()
    rl = RateLimiter(1.0, clock=t.clock, sleep=t.sleep)
    await rl.acquire()
    t.now += 5.0
    await rl.acquire()
    assert t.sleeps == []


async def test_zero_interval_never_sleeps() -> None:
    t = FakeTime()
    rl = RateLimiter(0.0, clock=t.clock, sleep=t.sleep)
    await asyncio.gather(*(rl.acquire() for _ in range(5)))
    assert t.sleeps == []
