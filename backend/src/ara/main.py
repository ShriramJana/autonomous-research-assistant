"""FastAPI app factory.

Lifespan creates a single in-memory `ReportStore` shared across requests
plus a set that holds references to in-flight orchestrator tasks (so the
GC doesn't collect them before they finish emitting events).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ara.api.routes import router
from ara.config import get_settings
from ara.storage.memory import InMemoryReportStore


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        # Shutdown: let in-flight tasks finish naturally. In v2 we'd
        # cancel + await them with a timeout.

    app = FastAPI(title="Autonomous Research Assistant", version="0.1.0", lifespan=lifespan)
    # State is populated eagerly (not in lifespan) so TestClient usage
    # without a context-manager `with` block still sees it.
    app.state.store = InMemoryReportStore(buffer_size=settings.ara_event_buffer_size)
    tasks: set[asyncio.Task[None]] = set()
    app.state.tasks = tasks

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
