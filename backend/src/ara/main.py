"""FastAPI app factory."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ara.api.routes import router
from ara.config import get_settings
from ara.db.postgres import PostgresReportsRepo
from ara.db.sqlite import SqliteReportsRepo
from ara.localkey import load_or_create_key
from ara.shutdown import drain_tasks
from ara.storage.memory import InMemoryReportStore
from ara.storage.notify import EventDoorbell
from ara.storage.sqlite import SqliteReportStore
from ara.storage.supabase import SupabaseReportStore

logger = logging.getLogger(__name__)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_INTERRUPTED_MESSAGE = "Interrupted: the server stopped while this report was running"


async def _loopback_only(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Local mode has no auth: refuse any peer that is not this machine, even if
    something (a dev server, a proxy) exposes the port. Only the direct peer
    address counts; x-forwarded-for is deliberately ignored."""
    if request.client is not None and request.client.host not in _LOOPBACK_HOSTS:
        return JSONResponse(
            {"detail": "Local mode accepts loopback connections only"}, status_code=403
        )
    return await call_next(request)


async def _open_local_repo(data_dir: str) -> SqliteReportsRepo:
    repo = await SqliteReportsRepo.open(os.path.join(data_dir, "ara.db"))
    # One process owns this database, so any row still `running` was orphaned by a
    # previous stop/crash; close it so it never shows as running forever.
    swept = await repo.fail_running_reports(_INTERRUPTED_MESSAGE)
    if swept:
        logger.info("local mode: marked %d interrupted report(s) as error", swept)
    return repo


def create_app() -> FastAPI:
    get_settings.cache_clear()
    settings = get_settings()
    # Resolve the local key here (not in the lifespan) so it lives on this app's
    # own freshly cached Settings and handlers see it without mutating shared state.
    if settings.is_local and not settings.ara_encryption_key:
        settings.ara_encryption_key = load_or_create_key(settings.ara_data_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Uvicorn configures only its own loggers; surface ara.* INFO lines
        # (doorbell status, shutdown drain) in container logs.
        logging.basicConfig(
            level=logging.INFO, format="%(levelname)s:     %(name)s - %(message)s"
        )
        logging.getLogger("httpx").setLevel(logging.WARNING)
        doorbell: EventDoorbell | None = None
        if settings.is_local:
            data_dir = settings.ara_data_dir
            repo = await _open_local_repo(data_dir)
            app.state.db_pool = None
            app.state.repo = repo
            app.state.store = SqliteReportStore(repo, buffer_size=settings.ara_event_buffer_size)
            logger.info("local mode: data in %s", data_dir)
        elif settings.supabase_db_url:
            db_url = settings.supabase_db_url
            app.state.db_pool = await asyncpg.create_pool(db_url, min_size=1, max_size=10)
            app.state.repo = PostgresReportsRepo(app.state.db_pool)
            doorbell = EventDoorbell(lambda: asyncpg.connect(db_url))
            await doorbell.start()
            app.state.store = SupabaseReportStore(pool=app.state.db_pool, doorbell=doorbell)
        else:
            app.state.db_pool = None
            app.state.repo = None
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
            if settings.is_local and app.state.repo is not None:
                await app.state.repo.close()

    app = FastAPI(title="Autonomous Research Assistant", version="0.2.0", lifespan=lifespan)
    # Eager state init so TestClient without `with` still works.
    app.state.db_pool = None
    app.state.repo = None
    app.state.store = InMemoryReportStore(buffer_size=settings.ara_event_buffer_size)
    tasks: set[asyncio.Task[None]] = set()
    app.state.tasks = tasks

    if settings.is_local:
        app.middleware("http")(_loopback_only)

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
