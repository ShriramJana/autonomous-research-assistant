"""OpenAI-compatible native client (configurable base_url).

Translates the normalized message/tool shapes used by the agents into the
OpenAI Chat Completions wire format and back into a `CompletionResult`.
No server-side web search; the researcher drives a client-side Tavily loop
for this provider.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

from openai import AsyncOpenAI

from ara.llm.client import (
    CompletionResult,
    MessageDict,
    OnApiCall,
    ToolSpec,
    ToolUse,
)

_FINISH_REASON_MAP = {"tool_calls": "tool_use", "stop": "end_turn"}


class OpenAICompatClient:
    provider: str = "openai"
    supports_server_side_search: bool = False

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        openai_client: AsyncOpenAI | None = None,
        on_api_call: OnApiCall | None = None,
    ) -> None:
        if openai_client is None:
            if not api_key:
                raise ValueError(
                    "OpenAICompatClient requires either `openai_client` or a non-empty `api_key`"
                )
            openai_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._client = openai_client
        self._on_api_call = on_api_call

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
            "messages": _to_openai_messages(messages, system),
            "max_tokens": max_tokens,
        }
        if tools is not None:
            kwargs["tools"] = [_to_openai_tool(t) for t in tools]
        if tool_choice is not None:
            kwargs["tool_choice"] = _to_openai_tool_choice(tool_choice)

        comp: Any = await self._client.chat.completions.create(**kwargs)
        message = comp.choices[0].message
        text = message.content or ""
        tool_uses: list[ToolUse] = []
        for tc in message.tool_calls or []:
            try:
                parsed = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                parsed = {}
            tool_uses.append(ToolUse(id=tc.id, name=tc.function.name, input=parsed))

        in_tokens = comp.usage.prompt_tokens if comp.usage else 0
        out_tokens = comp.usage.completion_tokens if comp.usage else 0
        await self._record(model, in_tokens, out_tokens)

        finish = comp.choices[0].finish_reason or "stop"
        return CompletionResult(
            text=text,
            tool_uses=tool_uses,
            server_tool_uses=[],
            stop_reason=_FINISH_REASON_MAP.get(finish, finish),
            input_tokens=in_tokens,
            output_tokens=out_tokens,
        )

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
            "messages": _to_openai_messages(messages, system),
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        in_tokens = 0
        out_tokens = 0
        text_len = 0
        stream: Any = await self._client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if chunk.usage is not None:
                in_tokens = chunk.usage.prompt_tokens
                out_tokens = chunk.usage.completion_tokens
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None)
            if piece:
                text_len += len(piece)
                yield piece
        if out_tokens == 0 and text_len:
            # Some base_urls omit usage on streaming — rough fallback so cost still records.
            out_tokens = max(1, text_len // 4)
        await self._record(model, in_tokens, out_tokens)

    async def _record(self, model: str, input_tokens: int, output_tokens: int) -> None:
        if self._on_api_call is not None:
            await self._on_api_call(model, input_tokens, output_tokens)


def _to_openai_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object"}),
        },
    }


def _to_openai_tool_choice(tool_choice: dict[str, Any]) -> Any:
    if tool_choice.get("type") == "tool" and "name" in tool_choice:
        return {"type": "function", "function": {"name": tool_choice["name"]}}
    return tool_choice


def _to_openai_messages(
    messages: list[MessageDict], system: str | None
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if system is not None:
        out.append({"role": "system", "content": system})
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            out.append(
                {
                    "role": "assistant",
                    "content": m.get("content") or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["name"],
                                "arguments": json.dumps(tc["input"]),
                            },
                        }
                        for tc in m["tool_calls"]
                    ],
                }
            )
        elif role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m["tool_call_id"],
                    "content": m["content"],
                }
            )
        else:
            out.append({"role": role, "content": m.get("content", "")})
    return out
