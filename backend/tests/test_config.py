"""Settings — Supabase + free-tier fields parse and validate."""

from __future__ import annotations

import pytest

from ara.config import Settings


def test_supabase_fields_default_empty() -> None:
    """In tests with no env, Supabase fields default to empty strings — not None."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.supabase_url == ""
    assert s.supabase_db_url == ""


def test_free_tier_defaults() -> None:
    """Free-tier knobs have sane defaults so a fresh deployment works."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.free_tier_per_user_monthly == 3
    assert s.free_tier_global_cap_usd == 20.0


def test_admin_user_id_optional() -> None:
    """ADMIN_USER_ID is optional — when unset, no user has admin powers."""
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.admin_user_id is None


def test_settings_has_tavily_key_default_empty() -> None:
    from ara.config import Settings

    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.tavily_api_key == ""


def test_settings_2b_defaults() -> None:
    from ara.config import Settings

    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.ara_encryption_key == ""
    assert s.tavily_global_monthly_cap == 1000


def test_mode_defaults_hosted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARA_MODE", raising=False)
    s = Settings()
    assert s.ara_mode == "hosted"
    assert s.is_local is False


def test_local_mode_forces_loopback_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARA_MODE", "local")
    monkeypatch.setenv("ARA_HOST", "0.0.0.0")
    s = Settings()
    assert s.is_local is True
    assert s.ara_host == "127.0.0.1"


def test_data_dir_expands_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARA_DATA_DIR", "~/somewhere")
    assert "~" not in Settings().ara_data_dir


def test_ollama_base_url_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    assert Settings().ollama_base_url == "http://localhost:11434"


@pytest.mark.parametrize("marker", ["K_SERVICE", "KUBERNETES_SERVICE_HOST"])
def test_local_mode_refused_on_hosted_runtime(
    monkeypatch: pytest.MonkeyPatch, marker: str
) -> None:
    from pydantic import ValidationError

    monkeypatch.setenv("ARA_MODE", "local")
    monkeypatch.setenv(marker, "x")
    with pytest.raises(ValidationError, match="not allowed on a hosted runtime"):
        Settings()


def test_hosted_mode_fine_on_hosted_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ARA_MODE", raising=False)
    monkeypatch.setenv("K_SERVICE", "ara-backend")
    assert Settings().is_local is False
