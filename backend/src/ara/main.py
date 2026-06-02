"""FastAPI app factory."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ara.api.routes import router
from ara.config import get_settings
from ara.storage.memory import InMemoryReportStore
from ara.storage.supabase import SupabaseReportStore


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.supabase_db_url:
            app.state.db_pool = await asyncpg.create_pool(
                settings.supabase_db_url, min_size=1, max_size=10
            )
            app.state.store = SupabaseReportStore(pool=app.state.db_pool)
        else:
            app.state.db_pool = None
            app.state.store = InMemoryReportStore(buffer_size=settings.ara_event_buffer_size)
        try:
            yield
        finally:
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
