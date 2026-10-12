"""SQLite `ReportsRepo` for local mode (aiosqlite, WAL, one guarded connection)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import aiosqlite

from ara.db.repo import CredentialRow, Depth, Provider, ReportRow

_PROVIDER_COLUMNS: dict[Provider, list[str]] = {
    "anthropic": ["anthropic_key_ciphertext"],
    "openai": ["openai_key_ciphertext", "openai_base_url", "openai_model"],
    "tavily": ["tavily_key_ciphertext"],
}


# Columns added after the first local release; applied in place on open.
_COLUMN_UPGRADES: tuple[tuple[str, str, str], ...] = (
    ("reports", "scholarly", "alter table reports add column scholarly integer not null default 0"),
)


async def _apply_column_upgrades(conn: aiosqlite.Connection) -> None:
    for table, column, ddl in _COLUMN_UPGRADES:
        cur = await conn.execute(f"pragma table_info({table})")
        existing = {row[1] for row in await cur.fetchall()}
        if column not in existing:
            await conn.execute(ddl)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row(r: aiosqlite.Row) -> ReportRow:
    created = _dt(r["created_at"])
    assert created is not None
    return ReportRow(
        id=UUID(r["id"]),
        owner_id=UUID(r["owner_id"]),
        question=r["question"],
        status=r["status"],
        depth=r["depth"],
        browse_web=bool(r["browse_web"]),
        scholarly=bool(r["scholarly"]),
        used_byok=bool(r["used_byok"]),
        is_sample=bool(r["is_sample"]),
        share_token=UUID(r["share_token"]) if r["share_token"] else None,
        cost_usd=float(r["cost_usd"]) if r["cost_usd"] is not None else None,
        report_payload=json.loads(r["report_payload"]) if r["report_payload"] else None,
        error_message=r["error_message"],
        tavily_searches=int(r["tavily_searches"]),
        created_at=created,
        completed_at=_dt(r["completed_at"]),
    )


class SqliteReportsRepo:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()

    @classmethod
    async def open(cls, path: str) -> SqliteReportsRepo:
        # The database holds credential ciphertexts: keep the data dir owner-only.
        Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("pragma journal_mode=wal")
        await conn.execute("pragma foreign_keys=on")
        schema = resources.files("ara.db").joinpath("sqlite_schema.sql").read_text()
        await conn.executescript(schema)
        await _apply_column_upgrades(conn)
        await conn.commit()
        return cls(conn)

    @property
    def connection(self) -> aiosqlite.Connection:
        """Shared handle for `SqliteReportStore` (same lock via `lock`)."""
        return self._conn

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    async def close(self) -> None:
        await self._conn.close()

    async def _run(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        async with self._lock:
            cur = await self._conn.execute(sql, params)
            await self._conn.commit()
            return cur.rowcount

    async def _one(self, sql: str, params: tuple[Any, ...] = ()) -> aiosqlite.Row | None:
        async with self._lock:
            cur = await self._conn.execute(sql, params)
            return await cur.fetchone()

    async def _all(self, sql: str, params: tuple[Any, ...] = ()) -> list[aiosqlite.Row]:
        async with self._lock:
            cur = await self._conn.execute(sql, params)
            return list(await cur.fetchall())

    # ---- reports ----
    async def create_report(
        self, report_id: UUID, *, owner_id: UUID, question: str, depth: Depth,
        browse_web: bool, used_byok: bool, scholarly: bool = False,
    ) -> None:
        await self._run(
            "insert or ignore into reports (id, owner_id, question, status, depth, browse_web, "
            "scholarly, used_byok, created_at) values (?, ?, ?, 'running', ?, ?, ?, ?, ?)",
            (
                str(report_id), str(owner_id), question, depth,
                int(browse_web), int(scholarly), int(used_byok), _now(),
            ),
        )

    async def append_event(self, report_id: UUID, event_json: str) -> int:
        async with self._lock:
            cur = await self._conn.execute(
                "insert into report_events (report_id, event, created_at) values (?, ?, ?)",
                (str(report_id), event_json, _now()),
            )
            await self._conn.commit()
            assert cur.lastrowid is not None
            return int(cur.lastrowid)

    async def close_report(
        self, report_id: UUID, *, status: Literal["completed", "error"], cost_usd: float | None,
        report_payload_json: str | None, error_message: str | None, tavily_searches: int,
    ) -> None:
        await self._run(
            "update reports set status = ?, cost_usd = ?, report_payload = ?, error_message = ?, "
            "tavily_searches = ?, completed_at = ? where id = ?",
            (
                status, cost_usd, report_payload_json, error_message,
                tavily_searches, _now(), str(report_id),
            ),
        )

    async def fail_running_reports(self, error_message: str) -> int:
        """Startup sweep (SQLite only): close rows left `running` by a previous process.

        In local mode there is exactly one process, so any `running` row at startup
        was orphaned by a stop/crash and would otherwise stay `running` forever.
        """
        return await self._run(
            "update reports set status = 'error', error_message = ?, completed_at = ? "
            "where status = 'running'",
            (error_message, _now()),
        )

    async def get_report(self, report_id: UUID) -> ReportRow | None:
        r = await self._one("select * from reports where id = ?", (str(report_id),))
        return _row(r) if r is not None else None

    async def list_reports(self, owner_id: UUID) -> list[ReportRow]:
        rows = await self._all(
            "select * from reports where owner_id = ? order by created_at desc, rowid desc",
            (str(owner_id),),
        )
        return [_row(r) for r in rows]

    async def list_samples(self) -> list[ReportRow]:
        rows = await self._all("select * from reports where is_sample = 1 order by created_at desc")
        return [_row(r) for r in rows]

    async def delete_report(self, report_id: UUID, owner_id: UUID) -> bool:
        n = await self._run(
            "delete from reports where id = ? and owner_id = ?", (str(report_id), str(owner_id))
        )
        return n > 0

    async def ensure_share_token(
        self, report_id: UUID, owner_id: UUID, token: UUID
    ) -> UUID | None:
        await self._run(
            "update reports set share_token = coalesce(share_token, ?) "
            "where id = ? and owner_id = ?",
            (str(token), str(report_id), str(owner_id)),
        )
        r = await self._one(
            "select share_token from reports where id = ? and owner_id = ?",
            (str(report_id), str(owner_id)),
        )
        return UUID(r["share_token"]) if r is not None and r["share_token"] else None

    async def revoke_share_token(self, report_id: UUID, owner_id: UUID) -> bool:
        n = await self._run(
            "update reports set share_token = null where id = ? and owner_id = ?",
            (str(report_id), str(owner_id)),
        )
        return n > 0

    async def set_sample(self, report_id: UUID, flag: bool) -> bool:
        n = await self._run(
            "update reports set is_sample = ? where id = ?", (int(flag), str(report_id))
        )
        return n > 0

    async def replay_events(self, report_id: UUID) -> list[str]:
        rows = await self._all(
            "select event from report_events where report_id = ? order by id asc", (str(report_id),)
        )
        return [r["event"] for r in rows]

    async def events_since(
        self, report_id: UUID, after_id: int, limit: int | None = None
    ) -> list[tuple[int, str]]:
        sql = "select id, event from report_events where report_id = ? and id > ? order by id asc"
        params: tuple[Any, ...] = (str(report_id), after_id)
        if limit is not None:
            sql += " limit ?"
            params = (*params, limit)
        rows = await self._all(sql, params)
        return [(int(r["id"]), r["event"]) for r in rows]

    # ---- credentials ----
    async def get_credentials(self, user_id: UUID) -> CredentialRow | None:
        r = await self._one("select * from user_credentials where user_id = ?", (str(user_id),))
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
        marks = ", ".join("?" for _ in values)
        sets = ", ".join(f"{c} = excluded.{c}" for c in values)
        await self._run(
            f"insert into user_credentials (user_id, {cols}, updated_at) values (?, {marks}, ?) "
            f"on conflict (user_id) do update set {sets}, updated_at = excluded.updated_at",
            (str(user_id), *values.values(), _now()),
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
        await self._run(
            f"update user_credentials set {sets}, "
            "active_provider = case when active_provider = ? then 'free' else active_provider end, "
            "updated_at = ? where user_id = ?",
            (provider, _now(), str(user_id)),
        )

    async def set_active(self, user_id: UUID, provider: str) -> None:
        await self._upsert(user_id, {"active_provider": provider})

    # ---- quotas ----
    async def count_free_runs(self, owner_id: UUID, *, since: datetime) -> int:
        r = await self._one(
            "select count(*) as n from reports "
            "where owner_id = ? and used_byok = 0 and created_at >= ?",
            (str(owner_id), since.astimezone(UTC).isoformat()),
        )
        return int(r["n"]) if r else 0

    async def sum_free_spend(self, *, since: datetime) -> float:
        r = await self._one(
            "select coalesce(sum(cost_usd), 0) as s from reports "
            "where used_byok = 0 and created_at >= ?",
            (since.astimezone(UTC).isoformat(),),
        )
        return float(r["s"]) if r else 0.0

    async def sum_tavily(self, *, since: datetime) -> int:
        r = await self._one(
            "select coalesce(sum(tavily_searches), 0) as n from reports where created_at >= ?",
            (since.astimezone(UTC).isoformat(),),
        )
        return int(r["n"]) if r else 0
