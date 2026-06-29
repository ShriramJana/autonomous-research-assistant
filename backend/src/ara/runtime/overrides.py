"""Per-run, per-request inputs that override `Settings` defaults.

Settings is infrastructure (server config, the *default* free-tier key,
the *default* models). RuntimeOverrides is what the request handler
actually wants this specific run to use — which is either:

- BYOK: user-supplied key + their chosen models + their chosen depth
- Free tier: server's key + Haiku-everywhere + quick depth, no browsing
"""

from __future__ import annotations

from dataclasses import dataclass

from ara.options import ResearchOptions


@dataclass(frozen=True)
class RuntimeOverrides:
    api_key: str
    planner_model: str
    researcher_model: str
    synthesizer_model: str
    options: ResearchOptions
    provider: str = "anthropic"
    base_url: str | None = None
