"""Map a stored credential to the RuntimeOverrides the engine consumes.

Pure and synchronous. Returns None to signal the free-tier path (the caller
runs the existing quota + Haiku block). Decryption errors propagate so the
API layer can return a clear 4xx.
"""

from __future__ import annotations

from ara.config import Settings
from ara.credentials import CredentialError, CredentialRecord
from ara.crypto import decrypt_secret
from ara.options import Depth, options_for_depth
from ara.runtime.overrides import RuntimeOverrides


def resolve_overrides(
    record: CredentialRecord | None,
    *,
    settings: Settings,
    depth: Depth,
    browse_web: bool,
    tavily_capped: bool,
) -> RuntimeOverrides | None:
    if record is None or record.active_provider == "free":
        return None

    if record.active_provider == "anthropic":
        if record.anthropic_key_ciphertext is None:
            raise CredentialError("anthropic is active but not configured")
        api_key = decrypt_secret(record.anthropic_key_ciphertext, key=settings.ara_encryption_key)
        return RuntimeOverrides(
            api_key=api_key,
            planner_model=settings.claude_planner_model,
            researcher_model=settings.claude_researcher_model,
            synthesizer_model=settings.claude_synthesizer_model,
            options=options_for_depth(depth, web_search_enabled=browse_web),
        )

    if record.active_provider == "openai":
        if (
            record.openai_key_ciphertext is None
            or not record.openai_base_url
            or not record.openai_model
        ):
            raise CredentialError("openai is active but not fully configured")
        api_key = decrypt_secret(record.openai_key_ciphertext, key=settings.ara_encryption_key)
        web = browse_web and not tavily_capped
        return RuntimeOverrides(
            api_key=api_key,
            planner_model=record.openai_model,
            researcher_model=record.openai_model,
            synthesizer_model=record.openai_model,
            options=options_for_depth(depth, web_search_enabled=web),
            provider="openai",
            base_url=record.openai_base_url,
        )

    raise CredentialError(f"unknown active_provider {record.active_provider!r}")
