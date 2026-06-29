from __future__ import annotations

import pytest

from ara.llm.client import AnthropicClient
from ara.llm.factory import build_client
from ara.llm.openai_client import OpenAICompatClient
from ara.options import options_for_depth
from ara.runtime.overrides import RuntimeOverrides


def _overrides(**kw: object) -> RuntimeOverrides:
    base: dict[str, object] = {
        "api_key": "k",
        "planner_model": "m",
        "researcher_model": "m",
        "synthesizer_model": "m",
        "options": options_for_depth("quick"),
    }
    base.update(kw)
    return RuntimeOverrides(**base)  # type: ignore[arg-type]


def test_build_client_anthropic_default() -> None:
    client = build_client(_overrides())
    assert isinstance(client, AnthropicClient)


def test_build_client_openai() -> None:
    client = build_client(
        _overrides(provider="openai", base_url="https://api.openai.com/v1")
    )
    assert isinstance(client, OpenAICompatClient)


def test_build_client_openai_requires_base_url() -> None:
    with pytest.raises(ValueError, match="base_url"):
        build_client(_overrides(provider="openai", base_url=None))
