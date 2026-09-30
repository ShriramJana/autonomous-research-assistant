"""FastAPI app factory."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ara.api.routes import router
from ara.config import get_settings
from ara.shutdown import drain_tasks
from ara.storage.memory import InMemoryReportStore
from ara.storage.notify import EventDoorbell
from ara.storage.supabase import SupabaseReportStore

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Uvicorn configures only its own loggers; surface ara.* INFO lines
        # (doorbell status, shutdown drain) in container logs.
        logging.basicConfig(
            level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s"
        )
        doorbell: EventDoorbell | None = None
        if settings.supabase_db_url:
            db_url = settings.supabase_db_url
            app.state.db_pool = await asyncpg.create_pool(db_url, min_size=1, max_size=10)
            doorbell = EventDoorbell(lambda: asyncpg.connect(db_url))
            await doorbell.start()
            app.state.store = SupabaseReportStore(pool=app.state.db_pool, doorbell=doorbell)
        else:
            app.state.db_pool = None
            app.state.store = InMemoryReportStore(buffer_size=settings.ara_event_buffer_size)
        try:
            yield
        finally:
            finished, abandoned = await drain_tasks(
                app.state.tasks, settings.ara_shutdown_drain_seconds
            )
            if finished or abandoned:
                logger.info(
                    "shutdown drain: %d run(s) finished, %d abandoned",
                    finished,
                    abandoned,
                )
            if doorbell is not None:
                await doorbell.stop()
            if app.state.db_pool is not None:
                await app.state.db_pool.close()

    app = FastAPI(title="Autonomous Research Assistant", version="0.2.0", lifespan=lifespan)
    # Eager state init so TestClient without `with` still works.
    app.state.db_pool = None
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
