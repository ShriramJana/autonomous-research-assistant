"""Graceful shutdown helpers.

A research run is a background task started by ``POST /api/research``, which
returns immediately. Uvicorn's graceful shutdown only waits for open HTTP
connections, so without this the process would exit and kill every in-flight
run no matter how long Kubernetes' termination grace period is.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable


async def drain_tasks(
    tasks: Iterable[asyncio.Task[None]], timeout: float
) -> tuple[int, int]:
    """Wait up to ``timeout`` seconds for ``tasks``; cancel the rest.

    Returns ``(finished, abandoned)``. Takes a snapshot, so a live set that
    discards tasks from a done-callback is safe to pass.
    """
    pending = [t for t in list(tasks) if not t.done()]
    if not pending:
        return 0, 0
    done, still_running = await asyncio.wait(pending, timeout=max(timeout, 0))
    for task in still_running:
        task.cancel()
    if still_running:
        await asyncio.gather(*still_running, return_exceptions=True)
    return len(done), len(still_running)
