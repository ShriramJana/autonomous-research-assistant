"""Postgres `ReportsRepo` (hosted mode). SQL moved verbatim from routes/credentials/quota."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

import asyncpg

from ara.db.repo import CredentialRow, Depth, Provider, ReportRow

_PROVIDER_COLUMNS: dict[Provider, list[str]] = {
    "anthropic": ["anthropic_key_ciphertext"],
    "openai": ["openai_key_ciphertext", "openai_base_url", "openai_model"],
    "tavily": ["tavily_key_ciphertext"],
}


def _payload(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, str):
        loaded: Any = json.loads(value)
        return loaded if isinstance(loaded, dict) else None
    return value if isinstance(value, dict) else None


def _row(r: asyncpg.Record) -> ReportRow:
    return ReportRow(
        id=r["id"],
        owner_id=r["owner_id"],
        question=r["question"],
        status=r["status"],
        depth=r["depth"],
        browse_web=r["browse_web"],
        used_byok=r["used_byok"],
        is_sample=r["is_sample"],
        share_token=r["share_token"],
        cost_usd=float(r["cost_usd"]) if r["cost_usd"] is not None else None,
        report_payload=_payload(r["report_payload"]),
        error_message=r["error_message"],
        tavily_searches=int(r["tavily_searches"]),
        created_at=r["created_at"],
        completed_at=r["completed_at"],
    )


def _changed(result: str) -> bool:
    return not result.endswith(" 0")


class PostgresReportsRepo:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    async def close(self) -> None:  # pool lifetime is owned by main.py
        return None

    # ---- reports ----
    async def create_report(
        self, report_id: UUID, *, owner_id: UUID, question: str, depth: Depth,
        browse_web: bool, used_byok: bool,
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "insert into reports "
                "(id, owner_id, question, status, depth, browse_web, used_byok) "
                "values ($1, $2, $3, 'running', $4, $5, $6) on conflict (id) do nothing",
                report_id, owner_id, question, depth, browse_web, used_byok,
            )

    async def append_event(self, report_id: UUID, event_json: str) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "insert into report_events (report_id, event) values ($1, $2::jsonb) returning id",
                report_id, event_json,
            )
        return int(row["id"])

    async def close_report(
        self, report_id: UUID, *, status: Literal["completed", "error"], cost_usd: float | None,
        report_payload_json: str | None, error_message: str | None, tavily_searches: int,
    ) -> None:
        async with self.pool.acquire() as conn:
            await conn.execute(
                "update reports set status = $2, cost_usd = $3, report_payload = $4::jsonb, "
                "error_message = $5, tavily_searches = $6, completed_at = now() where id = $1",
                report_id, status, cost_usd, report_payload_json, error_message, tavily_searches,
            )

    async def get_report(self, report_id: UUID) -> ReportRow | None:
        async with self.pool.acquire() as conn:
            r = await conn.fetchrow("select * from reports where id = $1", report_id)
        return _row(r) if r is not None else None

    async def list_reports(self, owner_id: UUID) -> list[ReportRow]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "select * from reports where owner_id = $1 order by created_at desc", owner_id
            )
        return [_row(r) for r in rows]

    async def list_samples(self) -> list[ReportRow]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "select * from reports where is_sample = true order by created_at desc"
            )
        return [_row(r) for r in rows]

    async def delete_report(self, report_id: UUID, owner_id: UUID) -> bool:
        async with self.pool.acquire() as conn:
            res = await conn.execute(
                "delete from reports where id = $1 and owner_id = $2", report_id, owner_id
            )
        return _changed(res)

    async def ensure_share_token(
        self, report_id: UUID, owner_id: UUID, token: UUID
    ) -> UUID | None:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                "update reports set share_token = coalesce(share_token, $1) "
                "where id = $2 and owner_id = $3 returning share_token",
                token, report_id, owner_id,
            )
        return row["share_token"] if row is not None else None

    async def revoke_share_token(self, report_id: UUID, owner_id: UUID) -> bool:
        async with self.pool.acquire() as conn:
            res = await conn.execute(
                "update reports set share_token = null where id = $1 and owner_id = $2",
                report_id, owner_id,
            )
        return _changed(res)

    async def set_sample(self, report_id: UUID, flag: bool) -> bool:
        async with self.pool.acquire() as conn:
            res = await conn.execute(
                "update reports set is_sample = $2 where id = $1", report_id, flag
            )
        return _changed(res)

    async def replay_events(self, report_id: UUID) -> list[str]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "select event from report_events where report_id = $1 order by id asc", report_id
            )
        return [r["event"] for r in rows]

    async def events_since(
        self, report_id: UUID, after_id: int, limit: int | None = None
    ) -> list[tuple[int, str]]:
        sql = (
            "select id, event from report_events "
            "where report_id = $1 and id > $2 order by id asc"
        )
        args: list[Any] = [report_id, after_id]
        if limit is not None:
            sql += " limit $3"
            args.append(limit)
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(sql, *args)
        return [(int(r["id"]), r["event"]) for r in rows]

    # ---- credentials ----
    async def get_credentials(self, user_id: UUID) -> CredentialRow | None:
        async with self.pool.acquire() as conn:
            r = await conn.fetchrow("select * from user_credentials where user_id = $1", user_id)
        if r is None:
            return None
        return CredentialRow(
            active_provider=r["active_provider"],
            anthropic_key_ciphertext=r["anthropic_key_ciphertext"],
            openai_key_ciphertext=r["openai_key_ciphertext"],
            openai_base_url=r["openai_base_url"],
            openai_model=r["openai_model"],
            tavily_key_ciphertext=r["tavily_key_ciphertext"],
        )

    async def _upsert(self, user_id: UUID, values: dict[str, str]) -> None:
        cols = ", ".join(values)
        marks = ", ".join(f"${i + 2}" for i in range(len(values)))
        sets = ", ".join(f"{c} = excluded.{c}" for c in values)
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"insert into user_credentials (user_id, {cols}, updated_at) "
                f"values ($1, {marks}, now()) on conflict (user_id) do update "
                f"set {sets}, updated_at = now()",
                user_id, *values.values(),
            )

    async def upsert_anthropic(self, user_id: UUID, *, ciphertext: str) -> None:
        await self._upsert(user_id, {"anthropic_key_ciphertext": ciphertext})

    async def upsert_openai(
        self, user_id: UUID, *, ciphertext: str, base_url: str, model: str
    ) -> None:
        await self._upsert(
            user_id,
            {
                "openai_key_ciphertext": ciphertext,
                "openai_base_url": base_url,
                "openai_model": model,
            },
        )

    async def upsert_tavily(self, user_id: UUID, *, ciphertext: str) -> None:
        await self._upsert(user_id, {"tavily_key_ciphertext": ciphertext})

    async def clear_provider(self, user_id: UUID, provider: Provider) -> None:
        sets = ", ".join(f"{c} = null" for c in _PROVIDER_COLUMNS[provider])
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"update user_credentials set {sets}, "
                "active_provider = case when active_provider = $2 then 'free' "
                "else active_provider end, "
                "updated_at = now() where user_id = $1",
                user_id, provider,
            )

    async def set_active(self, user_id: UUID, provider: str) -> None:
        await self._upsert(user_id, {"active_provider": provider})

    # ---- quotas ----
    async def count_free_runs(self, owner_id: UUID, *, since: datetime) -> int:
        async with self.pool.acquire() as conn:
            r = await conn.fetchrow(
                "select count(*)::int as n from reports where owner_id = $1 and used_byok = false "
                "and created_at >= $2",
                owner_id, since,
            )
        return int(r["n"]) if r else 0

    async def sum_free_spend(self, *, since: datetime) -> float:
        async with self.pool.acquire() as conn:
            r = await conn.fetchrow(
                "select coalesce(sum(cost_usd), 0)::float as s from reports "
                "where used_byok = false and created_at >= $1",
                since,
            )
        return float(r["s"]) if r else 0.0

    async def sum_tavily(self, *, since: datetime) -> int:
        async with self.pool.acquire() as conn:
            r = await conn.fetchrow(
                "select coalesce(sum(tavily_searches), 0)::int as n from reports "
                "where created_at >= $1",
                since,
            )
        return int(r["n"]) if r else 0
