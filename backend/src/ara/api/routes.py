"""HTTP routes.

Auth: all endpoints require a signed-in Supabase user EXCEPT:
- GET  /api/health             (public — liveness)
- GET  /api/config             (public)
- GET  /api/gallery            (public — lists is_sample=true reports)
- GET  /api/reports/{id}       (public when is_sample OR ?t=share_token)
- GET  /api/research/{id}/stream  (same rule as GET /reports/{id})
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Literal
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ara.auth import User, get_current_user, get_optional_user, require_admin
from ara.config import Settings, get_settings
from ara.credentials import (
    CredentialError,
    check_tavily_cap,
    clear_anthropic,
    clear_openai,
    get_credentials,
    set_active,
    upsert_anthropic,
    upsert_openai,
)
from ara.crypto import CredentialDecryptError, encrypt_secret
from ara.options import Depth, depth_presets, options_for_depth
from ara.quota import QuotaDenial, check_free_tier
from ara.runtime.orchestrator import run_report
from ara.runtime.overrides import RuntimeOverrides
from ara.runtime.resolver import resolve_overrides
from ara.storage.base import ReportStore

router = APIRouter(prefix="/api")

FREE_TIER_MODEL = "claude-haiku-4-5"
REPLAY_INTER_EVENT_DELAY_MS = 80


# ---------- Request / response models ----------


class CreateResearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    depth: Depth = "standard"
    browse_web: bool = True


class AnthropicKeyRequest(BaseModel):
    key: str = Field(min_length=1)


class OpenAIConfigRequest(BaseModel):
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    key: str = Field(min_length=1)


class ActiveProviderRequest(BaseModel):
    provider: Literal["free", "anthropic", "openai"]


class OpenAIConfigStatus(BaseModel):
    configured: bool
    base_url: str | None
    model: str | None


class CredentialsResponse(BaseModel):
    active_provider: Literal["free", "anthropic", "openai"]
    anthropic_configured: bool
    openai: OpenAIConfigStatus


class CreateResearchResponse(BaseModel):
    report_id: UUID


class ModelsConfig(BaseModel):
    planner: str
    researcher: str
    synthesizer: str


class DepthPresetConfig(BaseModel):
    max_sub_queries: int
    max_iterations: int


class ConfigResponse(BaseModel):
    models: ModelsConfig
    depth_presets: dict[str, DepthPresetConfig]


class MeResponse(BaseModel):
    id: UUID
    email: str


class ReportSummary(BaseModel):
    id: UUID
    question: str
    status: Literal["running", "completed", "error"]
    depth: Depth
    used_byok: bool
    is_sample: bool
    cost_usd: float | None
    created_at: str
    completed_at: str | None


class ReportDetail(ReportSummary):
    report_payload: dict[str, Any] | None
    error_message: str | None
    share_token: UUID | None


class ShareResponse(BaseModel):
    share_url_path: str
    share_token: UUID


class QuotaResponse(BaseModel):
    used: int
    limit: int
    global_spend_usd: float
    global_cap_usd: float
    circuit_breaker_tripped: bool
    tavily_used: int
    tavily_cap: int
    tavily_cap_reached: bool
    free_tier_available: bool


# ---------- Helpers ----------


def _pool_or_503(request: Request) -> asyncpg.Pool:
    pool = request.app.state.db_pool
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail="Database not configured (set SUPABASE_DB_URL)",
        )
    return pool


def _encryption_key_or_503(settings: Settings) -> str:
    if not settings.ara_encryption_key:
        raise HTTPException(
            status_code=503,
            detail="Credential storage not configured (set ARA_ENCRYPTION_KEY)",
        )
    return settings.ara_encryption_key


async def _fetch_report_row(pool: asyncpg.Pool, report_id: UUID) -> asyncpg.Record | None:
    async with pool.acquire() as conn:
        return await conn.fetchrow("select * from reports where id = $1", report_id)


async def _require_report_access(
    pool: asyncpg.Pool,
    report_id: UUID,
    user: User | None,
    share_token: UUID | None,
) -> asyncpg.Record:
    """Three-path access check. Returns the row or raises 403/404."""
    row = await _fetch_report_row(pool, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if user is not None and row["owner_id"] == user.id:
        return row
    if row["is_sample"]:
        return row
    if (
        share_token is not None
        and row["share_token"] is not None
        and row["share_token"] == share_token
    ):
        return row
    raise HTTPException(status_code=403, detail="Not authorized to view this report")


def _row_to_summary(row: asyncpg.Record) -> ReportSummary:
    return ReportSummary(
        id=row["id"],
        question=row["question"],
        status=row["status"],
        depth=row["depth"],
        used_byok=row["used_byok"],
        is_sample=row["is_sample"],
        cost_usd=float(row["cost_usd"]) if row["cost_usd"] is not None else None,
        created_at=row["created_at"].isoformat(),
        completed_at=row["completed_at"].isoformat() if row["completed_at"] else None,
    )


def _row_to_detail(row: asyncpg.Record) -> ReportDetail:
    return ReportDetail(
        **_row_to_summary(row).model_dump(),
        report_payload=row["report_payload"],
        error_message=row["error_message"],
        share_token=row["share_token"],
    )


# ---------- Public endpoints ----------


@router.get("/config", response_model=ConfigResponse)
async def get_config() -> ConfigResponse:
    settings = get_settings()
    return ConfigResponse(
        models=ModelsConfig(
            planner=settings.claude_planner_model,
            researcher=settings.claude_researcher_model,
            synthesizer=settings.claude_synthesizer_model,
        ),
        depth_presets={d: DepthPresetConfig(**p) for d, p in depth_presets().items()},
    )


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe for the host (Render). Public, no DB, no auth."""
    return {"status": "ok"}


@router.get("/gallery", response_model=list[ReportSummary])
async def get_gallery(request: Request) -> list[ReportSummary]:
    pool = _pool_or_503(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "select * from reports where is_sample = true order by created_at desc"
        )
    return [_row_to_summary(r) for r in rows]


# ---------- Authed: identity, quota ----------


@router.get("/me", response_model=MeResponse)
async def get_me(user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(id=user.id, email=user.email)


@router.get("/quota", response_model=QuotaResponse)
async def get_quota(
    request: Request,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> QuotaResponse:
    pool = _pool_or_503(request)
    status_ = await check_free_tier(user.id, pool, settings)
    tavily = await check_tavily_cap(pool, settings)
    return QuotaResponse(
        used=status_.used,
        limit=status_.limit,
        global_spend_usd=status_.global_spend_usd,
        global_cap_usd=status_.global_cap_usd,
        circuit_breaker_tripped=(
            isinstance(status_, QuotaDenial)
            and status_.reason == "free_tier_global_cap_reached"
        ),
        tavily_used=tavily.used,
        tavily_cap=tavily.cap,
        tavily_cap_reached=tavily.reached,
        free_tier_available=bool(settings.anthropic_api_key),
    )


# ---------- Credential endpoints ----------


@router.get("/credentials", response_model=CredentialsResponse)
async def get_credentials_route(
    request: Request,
    user: User = Depends(get_current_user),
) -> CredentialsResponse:
    pool = _pool_or_503(request)
    rec = await get_credentials(user.id, pool)
    if rec is None:
        return CredentialsResponse(
            active_provider="free",
            anthropic_configured=False,
            openai=OpenAIConfigStatus(configured=False, base_url=None, model=None),
        )
    return CredentialsResponse(
        active_provider=rec.active_provider,  # type: ignore[arg-type]
        anthropic_configured=rec.anthropic_key_ciphertext is not None,
        openai=OpenAIConfigStatus(
            configured=rec.openai_key_ciphertext is not None,
            base_url=rec.openai_base_url,
            model=rec.openai_model,
        ),
    )


@router.put("/credentials/anthropic", status_code=204)
async def put_anthropic_key(
    req: AnthropicKeyRequest,
    request: Request,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> None:
    pool = _pool_or_503(request)
    key = _encryption_key_or_503(settings)
    await upsert_anthropic(user.id, pool, ciphertext=encrypt_secret(req.key, key=key))


@router.delete("/credentials/anthropic", status_code=204)
async def delete_anthropic_key(
    request: Request, user: User = Depends(get_current_user)
) -> None:
    pool = _pool_or_503(request)
    await clear_anthropic(user.id, pool)


@router.put("/credentials/openai", status_code=204)
async def put_openai_config(
    req: OpenAIConfigRequest,
    request: Request,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> None:
    pool = _pool_or_503(request)
    key = _encryption_key_or_503(settings)
    await upsert_openai(
        user.id,
        pool,
        ciphertext=encrypt_secret(req.key, key=key),
        base_url=req.base_url,
        model=req.model,
    )


@router.delete("/credentials/openai", status_code=204)
async def delete_openai_config(
    request: Request, user: User = Depends(get_current_user)
) -> None:
    pool = _pool_or_503(request)
    await clear_openai(user.id, pool)


@router.put("/credentials/active", status_code=204)
async def put_active_provider(
    req: ActiveProviderRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> None:
    pool = _pool_or_503(request)
    try:
        await set_active(user.id, pool, provider=req.provider)
    except CredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------- Reports CRUD ----------


@router.get("/reports", response_model=list[ReportSummary])
async def list_reports(
    request: Request, user: User = Depends(get_current_user)
) -> list[ReportSummary]:
    pool = _pool_or_503(request)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "select * from reports where owner_id = $1 order by created_at desc",
            user.id,
        )
    return [_row_to_summary(r) for r in rows]


@router.get("/reports/{report_id}", response_model=ReportDetail)
async def get_report(
    report_id: UUID,
    request: Request,
    t: UUID | None = Query(default=None),
    user: User | None = Depends(get_optional_user),
) -> ReportDetail:
    pool = _pool_or_503(request)
    row = await _require_report_access(pool, report_id, user, t)
    return _row_to_detail(row)


@router.delete("/reports/{report_id}", status_code=204)
async def delete_report(
    report_id: UUID, request: Request, user: User = Depends(get_current_user)
) -> None:
    pool = _pool_or_503(request)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "delete from reports where id = $1 and owner_id = $2",
            report_id, user.id,
        )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Report not found")


@router.post("/reports/{report_id}/share", response_model=ShareResponse)
async def share_report(
    report_id: UUID, request: Request, user: User = Depends(get_current_user)
) -> ShareResponse:
    pool = _pool_or_503(request)
    token = uuid4()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            update reports
            set share_token = coalesce(share_token, $1)
            where id = $2 and owner_id = $3
            returning share_token
            """,
            token, report_id, user.id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return ShareResponse(
        share_url_path=f"/r/{report_id}?t={row['share_token']}",
        share_token=row["share_token"],
    )


@router.delete("/reports/{report_id}/share", status_code=204)
async def revoke_share(
    report_id: UUID, request: Request, user: User = Depends(get_current_user)
) -> None:
    pool = _pool_or_503(request)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "update reports set share_token = null where id = $1 and owner_id = $2",
            report_id, user.id,
        )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Report not found")


@router.post("/reports/{report_id}/promote", status_code=204)
async def promote_report(
    report_id: UUID, request: Request, _: User = Depends(require_admin)
) -> None:
    pool = _pool_or_503(request)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "update reports set is_sample = true where id = $1", report_id
        )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Report not found")


@router.delete("/reports/{report_id}/promote", status_code=204)
async def unpromote_report(
    report_id: UUID, request: Request, _: User = Depends(require_admin)
) -> None:
    pool = _pool_or_503(request)
    async with pool.acquire() as conn:
        result = await conn.execute(
            "update reports set is_sample = false where id = $1", report_id
        )
    if result.endswith("0"):
        raise HTTPException(status_code=404, detail="Report not found")


# ---------- POST /research ----------


@router.post("/research", response_model=CreateResearchResponse)
async def create_research(
    req: CreateResearchRequest,
    request: Request,
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> CreateResearchResponse:
    pool = _pool_or_503(request)
    store: ReportStore = request.app.state.store
    tasks: set[asyncio.Task[None]] = request.app.state.tasks

    record = await get_credentials(user.id, pool)

    tavily_capped = False
    if record is not None and record.active_provider == "openai" and req.browse_web:
        tavily_capped = (await check_tavily_cap(pool, settings)).reached

    try:
        overrides = resolve_overrides(
            record,
            settings=settings,
            depth=req.depth,
            browse_web=req.browse_web,
            tavily_capped=tavily_capped,
        )
    except CredentialDecryptError:
        raise HTTPException(
            status_code=400,
            detail="Saved credential could not be read — please re-save it in Settings",
        ) from None
    except CredentialError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if overrides is None:
        # Free-tier path (unchanged behavior).
        if not settings.anthropic_api_key:
            raise HTTPException(
                status_code=503,
                detail="Free tier disabled (server has no ANTHROPIC_API_KEY)",
            )
        quota = await check_free_tier(user.id, pool, settings)
        if isinstance(quota, QuotaDenial):
            return JSONResponse(  # type: ignore[return-value]
                status_code=402,
                content={
                    "error": quota.reason,
                    "message": (
                        "Free-tier monthly limit reached"
                        if quota.reason == "free_tier_exhausted"
                        else "Free tier capped site-wide for this month"
                    ),
                    "used": quota.used,
                    "limit": quota.limit,
                    "global_spend_usd": quota.global_spend_usd,
                    "global_cap_usd": quota.global_cap_usd,
                },
            )
        overrides = RuntimeOverrides(
            api_key=settings.anthropic_api_key,
            planner_model=FREE_TIER_MODEL,
            researcher_model=FREE_TIER_MODEL,
            synthesizer_model=FREE_TIER_MODEL,
            options=options_for_depth("quick", web_search_enabled=False),
        )

    report_id = uuid4()
    task = asyncio.create_task(
        run_report(
            report_id=report_id,
            question=req.question,
            store=store,
            settings=settings,
            overrides=overrides,
            owner_id=user.id,
        )
    )
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return CreateResearchResponse(report_id=report_id)


# ---------- SSE stream ----------


@router.get("/research/{report_id}/stream")
async def stream_research(
    report_id: UUID,
    request: Request,
    t: UUID | None = Query(default=None),
    user: User | None = Depends(get_optional_user),
) -> EventSourceResponse:
    pool = _pool_or_503(request)
    await _require_report_access(pool, report_id, user, t)
    store: ReportStore = request.app.state.store

    async def event_source() -> AsyncIterator[dict[str, Any]]:
        async for event in store.subscribe(report_id):
            yield {"data": event.model_dump_json()}

    return EventSourceResponse(event_source())


@router.get("/reports/{report_id}/replay")
async def replay_report(
    report_id: UUID,
    request: Request,
    t: UUID | None = Query(default=None),
    user: User | None = Depends(get_optional_user),
) -> EventSourceResponse:
    pool = _pool_or_503(request)
    await _require_report_access(pool, report_id, user, t)

    async def event_source() -> AsyncIterator[dict[str, Any]]:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                select event from report_events
                where report_id = $1
                order by id asc
                """,
                report_id,
            )
        for row in rows:
            yield {"data": row["event"]}
            await asyncio.sleep(REPLAY_INTER_EVENT_DELAY_MS / 1000)

    return EventSourceResponse(event_source())
