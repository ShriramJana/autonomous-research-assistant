from __future__ import annotations

import pytest

from ara.config import Settings
from ara.credentials import CredentialError, CredentialRecord
from ara.crypto import CredentialDecryptError, encrypt_secret
from ara.runtime.resolver import resolve_overrides

KEY = "nPQdjPgh3-EHVpruwF9thxZ6C-RntJeekJ05w6lAB4c="  # a valid 32-byte urlsafe-b64 Fernet key


def _settings() -> Settings:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    s.ara_encryption_key = KEY
    s.claude_planner_model = "p"
    s.claude_researcher_model = "r"
    s.claude_synthesizer_model = "syn"
    return s


def _rec(**kw: object) -> CredentialRecord:
    base: dict[str, object] = {
        "active_provider": "free",
        "anthropic_key_ciphertext": None,
        "openai_key_ciphertext": None,
        "openai_base_url": None,
        "openai_model": None,
    }
    base.update(kw)
    return CredentialRecord(**base)  # type: ignore[arg-type]


def test_none_record_is_free_tier() -> None:
    assert resolve_overrides(None, settings=_settings(), depth="standard",
                             browse_web=True, tavily_capped=False) is None


def test_active_free_is_free_tier() -> None:
    assert resolve_overrides(_rec(active_provider="free"), settings=_settings(),
                             depth="standard", browse_web=True, tavily_capped=False) is None


def test_anthropic_uses_per_role_models_and_decrypted_key() -> None:
    s = _settings()
    ciphertext = encrypt_secret("sk-ant", key=KEY)
    rec = _rec(active_provider="anthropic", anthropic_key_ciphertext=ciphertext)
    ov = resolve_overrides(rec, settings=s, depth="deep", browse_web=True, tavily_capped=False)
    assert ov is not None
    assert ov.provider == "anthropic"
    assert ov.api_key == "sk-ant"
    assert (ov.planner_model, ov.researcher_model, ov.synthesizer_model) == ("p", "r", "syn")
    assert ov.options.web_search_enabled is True


def test_openai_uses_single_model_and_base_url() -> None:
    s = _settings()
    rec = _rec(
        active_provider="openai",
        openai_key_ciphertext=encrypt_secret("sk-oai", key=KEY),
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o",
    )
    ov = resolve_overrides(rec, settings=s, depth="standard", browse_web=True, tavily_capped=False)
    assert ov is not None
    assert ov.provider == "openai"
    assert ov.base_url == "https://api.openai.com/v1"
    assert ov.api_key == "sk-oai"
    assert ov.planner_model == ov.researcher_model == ov.synthesizer_model == "gpt-4o"


def test_openai_tavily_capped_forces_search_off() -> None:
    s = _settings()
    rec = _rec(
        active_provider="openai",
        openai_key_ciphertext=encrypt_secret("sk-oai", key=KEY),
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o",
    )
    ov = resolve_overrides(rec, settings=s, depth="standard", browse_web=True, tavily_capped=True)
    assert ov is not None
    assert ov.options.web_search_enabled is False


def test_active_but_unconfigured_raises() -> None:
    with pytest.raises(CredentialError):
        resolve_overrides(_rec(active_provider="openai"), settings=_settings(),
                          depth="standard", browse_web=True, tavily_capped=False)


def test_decrypt_failure_propagates() -> None:
    rec = _rec(active_provider="anthropic", anthropic_key_ciphertext="not-a-valid-token")
    with pytest.raises(CredentialDecryptError):
        resolve_overrides(rec, settings=_settings(), depth="standard",
                          browse_web=True, tavily_capped=False)
