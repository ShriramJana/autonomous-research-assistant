"""Rough cost estimation for model calls.

Single source of truth for $/MTok rates used both by the scripts CLI and
the orchestrator's live CostUpdate events. Rates are vendor list prices
(standard tier, uncached, text) checked against each vendor's own pricing
page on the date in the comment; update when they change. Unknown model
ids fall back to zero cost and the UI shows "n/a" instead of dollars.
"""

from __future__ import annotations

PRICING: dict[str, tuple[float, float]] = {
    # (input_usd_per_mtok, output_usd_per_mtok)
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-5": (15.0, 75.0),
    "claude-opus-4-6": (15.0, 75.0),
    "claude-opus-4-7": (15.0, 75.0),
    "claude-haiku-4-5": (0.80, 4.0),
    # OpenAI (and OpenRouter slugs) — list prices, update when they change.
    "gpt-4o": (2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "openai/gpt-4o": (2.50, 10.0),
    "openai/gpt-4o-mini": (0.15, 0.60),
    # Provider-preset headline models (verified 2026-10-11 on vendor docs).
    # Google Gemini — 3.8 Flash is a promotional rate through 2026-12-31
    # (doubles to 1.50 / 7.50 from 2027-01-01).
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    # Groq-hosted open-weight models (same rate on Together / OpenRouter).
    "openai/gpt-oss-120b": (0.15, 0.60),
    "openai/gpt-oss-20b": (0.075, 0.30),
    # Mistral (the `-latest` aliases; Large omitted while its alias is in flux).
    "mistral-medium-latest": (1.50, 7.50),
    "mistral-small-latest": (0.15, 0.60),
    # xAI (standard tier, prompts under 200k tokens).
    "grok-4.3": (1.25, 2.50),
    "grok-4.7": (2.00, 6.00),
    # DeepSeek (peak-hour rate; off-peak is half).
    "deepseek-flash": (0.30, 1.20),
    "deepseek-v4-pro": (1.32, 3.96),
    # Together AI serverless.
    "zai-org/GLM-5.3-Flash": (0.15, 0.50),
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": (1.04, 1.04),
}


def model_is_priced(model: str) -> bool:
    """True when `model` has a known $/MTok rate (so USD is meaningful)."""
    return model in PRICING


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = PRICING.get(model, (0.0, 0.0))
    return (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
