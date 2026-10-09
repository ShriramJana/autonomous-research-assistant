"""ReportsRepo contract — runs against every implementation.

SQLite runs always (temp file). Postgres is added in Task 3 under requires_db.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from ara.db.repo import ReportsRepo, month_start
from ara.db.sqlite import SqliteReportsRepo

OWNER = UUID("00000000-0000-4000-8000-000000000001")


@pytest.fixture(params=["sqlite"])
async def repo(request: pytest.FixtureRequest, tmp_path: Path) -> AsyncIterator[ReportsRepo]:
    # Async fixtures cannot be pulled via getfixturevalue from another async fixture,
    # so each backend is constructed inline here (Task 3 adds the "postgres" branch).
    impl: ReportsRepo
    if request.param == "sqlite":
        impl = await SqliteReportsRepo.open(str(tmp_path / "ara.db"))
    else:  # pragma: no cover
        raise AssertionError(request.param)
    try:
        yield impl
    finally:
        await impl.close()


async def _seed(repo: ReportsRepo, *, owner: UUID = OWNER, byok: bool = False) -> UUID:
    rid = uuid4()
    await repo.create_report(
        rid, owner_id=owner, question="q?", depth="quick", browse_web=False, used_byok=byok
    )
    return rid


async def test_create_then_get_roundtrips_fields(repo: ReportsRepo) -> None:
    rid = await _seed(repo)
    row = await repo.get_report(rid)
    assert row is not None
    assert (row.id, row.owner_id, row.question, row.status, row.depth) == (
        rid, OWNER, "q?", "running", "quick"
    )
    assert row.browse_web is False and row.used_byok is False and row.is_sample is False
    assert row.share_token is None and row.completed_at is None
    assert row.created_at.tzinfo is not None


async def test_get_unknown_is_none(repo: ReportsRepo) -> None:
    assert await repo.get_report(uuid4()) is None


async def test_events_append_replay_and_since(repo: ReportsRepo) -> None:
    rid = await _seed(repo)
    first = await repo.append_event(rid, json.dumps({"type": "a"}))
    second = await repo.append_event(rid, json.dumps({"type": "b"}))
    assert second > first
    assert [json.loads(e)["type"] for e in await repo.replay_events(rid)] == ["a", "b"]
    since = await repo.events_since(rid, first)
    assert [(i, json.loads(e)["type"]) for i, e in since] == [(second, "b")]
    assert await repo.events_since(rid, 0, limit=1) == [(first, json.dumps({"type": "a"}))]


async def test_close_sets_terminal_fields(repo: ReportsRepo) -> None:
    rid = await _seed(repo)
    await repo.close_report(
        rid, status="completed", cost_usd=0.25,
        report_payload_json=json.dumps({"k": 1}), error_message=None, tavily_searches=2,
    )
    row = await repo.get_report(rid)
    assert row is not None
    assert row.status == "completed" and row.cost_usd == pytest.approx(0.25)
    assert row.report_payload == {"k": 1} and row.tavily_searches == 2
    assert row.completed_at is not None


async def test_list_reports_is_owner_scoped_newest_first(repo: ReportsRepo) -> None:
    a = await _seed(repo)
    b = await _seed(repo)
    await _seed(repo, owner=uuid4())
    ids = [r.id for r in await repo.list_reports(OWNER)]
    assert ids[:2] == [b, a] or ids[:2] == [a, b]  # same-timestamp ties allowed
    assert set(ids) == {a, b}


async def test_samples_promote_list_unpromote(repo: ReportsRepo) -> None:
    rid = await _seed(repo)
    assert await repo.set_sample(rid, True) is True
    assert rid in [r.id for r in await repo.list_samples()]  # shared DBs may hold other samples
    assert await repo.set_sample(rid, False) is True
    assert rid not in [r.id for r in await repo.list_samples()]
    assert await repo.set_sample(uuid4(), True) is False


async def test_share_token_is_coalesced_and_revocable(repo: ReportsRepo) -> None:
    rid = await _seed(repo)
    t1, t2 = uuid4(), uuid4()
    assert await repo.ensure_share_token(rid, OWNER, t1) == t1
    assert await repo.ensure_share_token(rid, OWNER, t2) == t1  # existing token wins
    assert await repo.ensure_share_token(rid, uuid4(), t2) is None  # not owner
    assert await repo.revoke_share_token(rid, OWNER) is True
    row = await repo.get_report(rid)
    assert row is not None and row.share_token is None
    assert await repo.revoke_share_token(uuid4(), OWNER) is False


async def test_delete_is_owner_scoped_and_cascades_events(repo: ReportsRepo) -> None:
    rid = await _seed(repo)
    await repo.append_event(rid, "{}")
    assert await repo.delete_report(rid, uuid4()) is False
    assert await repo.delete_report(rid, OWNER) is True
    assert await repo.get_report(rid) is None
    assert await repo.replay_events(rid) == []


async def test_credentials_upsert_clear_active(repo: ReportsRepo) -> None:
    uid = uuid4()
    assert await repo.get_credentials(uid) is None
    await repo.upsert_anthropic(uid, ciphertext="c1")
    await repo.upsert_openai(uid, ciphertext="c2", base_url="http://x/v1", model="m")
    await repo.upsert_tavily(uid, ciphertext="c3")
    await repo.set_active(uid, "openai")
    row = await repo.get_credentials(uid)
    assert row is not None
    assert (row.anthropic_key_ciphertext, row.openai_key_ciphertext, row.tavily_key_ciphertext) == (
        "c1", "c2", "c3"
    )
    assert (row.openai_base_url, row.openai_model, row.active_provider) == (
        "http://x/v1", "m", "openai"
    )
    await repo.clear_provider(uid, "openai")  # active provider falls back to free
    row = await repo.get_credentials(uid)
    assert row is not None
    assert row.openai_key_ciphertext is None and row.openai_base_url is None
    assert row.active_provider == "free"
    await repo.clear_provider(uid, "tavily")
    row = await repo.get_credentials(uid)
    assert row is not None and row.tavily_key_ciphertext is None


async def test_quota_sums_only_free_runs(repo: ReportsRepo) -> None:
    free = await _seed(repo)
    byok = await _seed(repo, byok=True)
    await repo.close_report(free, status="completed", cost_usd=1.5, report_payload_json=None,
                            error_message=None, tavily_searches=3)
    await repo.close_report(byok, status="completed", cost_usd=9.0, report_payload_json=None,
                            error_message=None, tavily_searches=4)
    since = datetime.now(UTC) - timedelta(minutes=5)
    assert await repo.count_free_runs(OWNER, since=since) == 1  # owner-scoped: exact
    # Global sums: a shared Postgres DB may hold other users' rows, so assert lower bounds.
    assert await repo.sum_free_spend(since=since) >= 1.5 - 1e-9
    assert await repo.sum_tavily(since=since) >= 7  # tavily counts byok runs too


async def test_month_filters_exclude_older_rows(repo: ReportsRepo) -> None:
    rid = await _seed(repo)
    await repo.close_report(rid, status="completed", cost_usd=1.0, report_payload_json=None,
                            error_message=None, tavily_searches=1)
    future = datetime.now(UTC) + timedelta(days=1)
    assert await repo.count_free_runs(OWNER, since=future) == 0
    assert await repo.sum_free_spend(since=future) == 0.0
    assert await repo.sum_tavily(since=future) == 0


def test_month_start_is_first_of_month_utc() -> None:
    ms = month_start(datetime(2026, 10, 8, 13, 5, tzinfo=UTC))
    assert ms == datetime(2026, 10, 1, tzinfo=UTC)
