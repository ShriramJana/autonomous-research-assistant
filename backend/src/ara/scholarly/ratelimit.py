"""Process-wide politeness limiter: at most one request per `interval` seconds.

Parallel researchers share one limiter per catalog and queue on it instead
of tripping 429s. Clock and sleep are injectable so tests never wait.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

Clock = Callable[[], float]
Sleep = Callable[[float], Awaitable[None]]


class RateLimiter:
    def __init__(
        self,
        interval: float,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._interval = interval
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            wait = self._next_allowed - self._clock()
            if wait > 0:
                await self._sleep(wait)
            self._next_allowed = self._clock() + self._interval
