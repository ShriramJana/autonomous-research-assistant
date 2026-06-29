"""Thin async wrapper around the Anthropic SDK.

This is the single swap-point in the backend for:

- model selection (driven by `Settings`)
- prompt caching (v2 — add `cache_control` here)
- retry / rate-limit handling (v2)
- token-level observability (`on_api_call` hook fires after every response)

Streaming tool-use exists as `stream_completion_with_tools` for a v2
synthesizer that can cite-check mid-stream. The v1 synthesizer uses the
plain `stream_completion` path.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, cast

from anthropic import AsyncAnthropic
from anthropic.types import Message

from ara.config import Settings

ToolSpec = dict[str, Any]
MessageDict = dict[str, Any]

WEB_SEARCH_TOOL_TYPE = "web_search_20250305"
WEB_SEARCH_TOOL_NAME = "web_search"


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class MessageStop:
    stop_reason: str
    input_tokens: int
    output_tokens: int


StreamEvent = TextDelta | ToolUseBlock | MessageStop

OnApiCall = Callable[[str, int, int], Awaitable[None]]


@dataclass(frozen=True)
class ToolUse:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class CompletionResult:
    text: str
    tool_uses: list[ToolUse]
    server_tool_uses: list[ToolUse]
    stop_reason: str
    input_tokens: int
    output_tokens: int


class LLMClient(Protocol):
    """Structural interface both native clients satisfy."""

    provider: str
    supports_server_side_search: bool

    async def complete_with_tools(
        self,
        *,
        model: str,
        messages: list[MessageDict],
        tools: list[ToolSpec] | None = None,
        tool_choice: dict[str, Any] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> CompletionResult: ...

    def stream_completion(
        self,
        *,
        model: str,
        messages: list[MessageDict],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]: ...


def _extract_text_delta(event: object) -> str | None:
    """Duck-typed narrowing of Anthropic's streaming event union.

    Returns the text payload if `event` is a `content_block_delta` of
    `text_delta` type; `None` otherwise. Avoids a brittle isinstance chain
    across the SDK's 12-way event union.
    """
    if getattr(event, "type", None) != "content_block_delta":
        return None
    delta = getattr(event, "delta", None)
    if getattr(delta, "type", None) != "text_delta":
        return None
    text = getattr(delta, "text", None)
    return text if isinstance(text, str) else None


class AnthropicClient:
    """Async, typed facade over `anthropic.AsyncAnthropic` (Protocol impl)."""

    provider: str = "anthropic"
    supports_server_side_search: bool = True

    def __init__(
        self,
        *,
        api_key: str | None = None,
        anthropic_client: AsyncAnthropic | None = None,
        on_api_call: OnApiCall | None = None,
    ) -> None:
        if anthropic_client is None:
            if not api_key:
                raise ValueError(
                    "AnthropicClient requires either `anthropic_client` or a non-empty `api_key`"
                )
            anthropic_client = AsyncAnthropic(api_key=api_key)
        self._client = anthropic_client
        self._on_api_call = on_api_call

    @classmethod
    def from_settings(cls, settings: Settings) -> AnthropicClient:
        return cls(api_key=settings.anthropic_api_key)

    @staticmethod
    def web_search_tool_spec(max_uses: int = 5) -> ToolSpec:
        """Anthropic server-side web search tool (`web_search_20250305`)."""
        return {
            "type": WEB_SEARCH_TOOL_TYPE,
            "name": WEB_SEARCH_TOOL_NAME,
            "max_uses": max_uses,
        }

    async def complete_with_tools(
        self,
        *,
        model: str,
        messages: list[MessageDict],
        tools: list[ToolSpec] | None = None,
        tool_choice: dict[str, Any] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> CompletionResult:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools is not None:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        if system is not None:
            kwargs["system"] = system

        response: Message = await self._client.messages.create(**kwargs)
        await self._record(model, response.usage.input_tokens, response.usage.output_tokens)
        return _to_completion_result(response)

    async def stream_completion(
        self,
        *,
        model: str,
        messages: list[MessageDict],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[str]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if system is not None:
            kwargs["system"] = system

        final: Message
        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text
            final = await stream.get_final_message()
        await self._record(model, final.usage.input_tokens, final.usage.output_tokens)

    async def stream_completion_with_tools(
        self,
        *,
        model: str,
        messages: list[MessageDict],
        tools: list[ToolSpec],
        system: str | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        """Streaming completion that can include tool-use blocks.

        Yields text deltas during streaming, then any completed tool_use
        blocks (assembled from the SDK's input_json_delta aggregation) and
        a terminating `MessageStop`. v1 call sites don't exercise this path;
        v2 synthesizer that cite-checks mid-stream will.
        """
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": tools,
            "max_tokens": max_tokens,
        }
        if system is not None:
            kwargs["system"] = system

        final: Message
        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                text = _extract_text_delta(event)
                if text is not None:
                    yield TextDelta(text=text)
            final = await stream.get_final_message()

        for block in final.content:
            if block.type == "tool_use":
                yield ToolUseBlock(
                    id=block.id,
                    name=block.name,
                    input=cast(dict[str, Any], block.input),
                )
        yield MessageStop(
            stop_reason=final.stop_reason or "end_turn",
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
        )
        await self._record(model, final.usage.input_tokens, final.usage.output_tokens)

    async def _record(self, model: str, input_tokens: int, output_tokens: int) -> None:
        if self._on_api_call is not None:
            await self._on_api_call(model, input_tokens, output_tokens)


def _to_completion_result(response: Message) -> CompletionResult:
    text_parts: list[str] = []
    tool_uses: list[ToolUse] = []
    server_tool_uses: list[ToolUse] = []
    for block in response.content:
        btype = getattr(block, "type", None)
        if btype == "text":
            text_parts.append(getattr(block, "text", ""))
        elif btype == "tool_use":
            tool_uses.append(
                ToolUse(
                    id=getattr(block, "id", ""),
                    name=getattr(block, "name", ""),
                    input=cast(dict[str, Any], getattr(block, "input", {}) or {}),
                )
            )
        elif btype == "server_tool_use":
            server_tool_uses.append(
                ToolUse(
                    id=getattr(block, "id", ""),
                    name=getattr(block, "name", ""),
                    input=cast(dict[str, Any], getattr(block, "input", {}) or {}),
                )
            )
    return CompletionResult(
        text="".join(text_parts),
        tool_uses=tool_uses,
        server_tool_uses=server_tool_uses,
        stop_reason=response.stop_reason or "end_turn",
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
