"""Pick the right native LLM client for a per-request provider config."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ara.llm.client import AnthropicClient, LLMClient, OnApiCall
from ara.llm.openai_client import OpenAICompatClient

if TYPE_CHECKING:
    from ara.runtime.overrides import RuntimeOverrides


def build_client(
    overrides: RuntimeOverrides, *, on_api_call: OnApiCall | None = None
) -> LLMClient:
    if overrides.provider == "openai":
        if not overrides.base_url:
            raise ValueError("openai provider requires a base_url")
        return OpenAICompatClient(
            api_key=overrides.api_key,
            base_url=overrides.base_url,
            on_api_call=on_api_call,
        )
    return AnthropicClient(api_key=overrides.api_key, on_api_call=on_api_call)
