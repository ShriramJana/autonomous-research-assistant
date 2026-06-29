from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from ara.llm.client import CompletionResult
from ara.llm.openai_client import OpenAICompatClient


def _make_completion(
    *,
    content: str | None = "hi",
    tool_calls: list[Any] | None = None,
    finish_reason: str = "stop",
    prompt_tokens: int = 12,
    completion_tokens: int = 3,
) -> MagicMock:
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = finish_reason
    comp = MagicMock()
    comp.choices = [choice]
    comp.usage = MagicMock()
    comp.usage.prompt_tokens = prompt_tokens
    comp.usage.completion_tokens = completion_tokens
    return comp


def _tool_call(call_id: str, name: str, args: dict[str, Any]) -> MagicMock:
    tc = MagicMock()
    tc.id = call_id
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(args)
    return tc


def _fake_openai(*, create_return: Any = None) -> MagicMock:
    fake = MagicMock()
    fake.chat = MagicMock()
    fake.chat.completions = MagicMock()
    fake.chat.completions.create = AsyncMock(return_value=create_return)
    return fake


def test_capability_flags() -> None:
    client = OpenAICompatClient(openai_client=MagicMock())
    assert client.provider == "openai"
    assert client.supports_server_side_search is False


async def test_complete_with_tools_parses_tool_calls() -> None:
    comp = _make_completion(
        content=None,
        tool_calls=[_tool_call("c1", "submit_finding", {"summary": "s"})],
        finish_reason="tool_calls",
    )
    fake = _fake_openai(create_return=comp)
    client = OpenAICompatClient(openai_client=fake)

    result = await client.complete_with_tools(
        model="gpt-4o",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"name": "submit_finding", "description": "d", "input_schema": {"type": "object"}}],
        system="sys",
    )

    assert isinstance(result, CompletionResult)
    assert result.stop_reason == "tool_use"
    assert result.server_tool_uses == []
    assert result.tool_uses[0].name == "submit_finding"
    assert result.tool_uses[0].input == {"summary": "s"}
    assert result.input_tokens == 12

    kwargs = fake.chat.completions.create.await_args.kwargs
    assert kwargs["messages"][0] == {"role": "system", "content": "sys"}
    assert kwargs["tools"][0]["type"] == "function"
    assert kwargs["tools"][0]["function"]["name"] == "submit_finding"


async def test_complete_translates_tool_choice() -> None:
    comp = _make_completion(content="", tool_calls=[_tool_call("c1", "p", {})])
    fake = _fake_openai(create_return=comp)
    client = OpenAICompatClient(openai_client=fake)
    await client.complete_with_tools(
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"name": "p", "description": "d", "input_schema": {"type": "object"}}],
        tool_choice={"type": "tool", "name": "p"},
    )
    kwargs = fake.chat.completions.create.await_args.kwargs
    assert kwargs["tool_choice"] == {"type": "function", "function": {"name": "p"}}


async def test_complete_translates_assistant_and_tool_turns() -> None:
    comp = _make_completion()
    fake = _fake_openai(create_return=comp)
    client = OpenAICompatClient(openai_client=fake)
    await client.complete_with_tools(
        model="m",
        messages=[
            {"role": "user", "content": "q"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "name": "web_search", "input": {"query": "x"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "results"},
        ],
    )
    sent = fake.chat.completions.create.await_args.kwargs["messages"]
    assistant = next(m for m in sent if m["role"] == "assistant")
    assert assistant["tool_calls"][0]["id"] == "c1"
    assert assistant["tool_calls"][0]["function"]["name"] == "web_search"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"query": "x"}
    tool_msg = next(m for m in sent if m["role"] == "tool")
    assert tool_msg == {"role": "tool", "tool_call_id": "c1", "content": "results"}


async def test_complete_fires_on_api_call() -> None:
    comp = _make_completion(prompt_tokens=20, completion_tokens=8)
    fake = _fake_openai(create_return=comp)
    calls: list[tuple[str, int, int]] = []

    async def hook(m: str, i: int, o: int) -> None:
        calls.append((m, i, o))

    client = OpenAICompatClient(openai_client=fake, on_api_call=hook)
    await client.complete_with_tools(model="gpt-4o", messages=[{"role": "user", "content": "hi"}])
    assert calls == [("gpt-4o", 20, 8)]


class _FakeChunkStream:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._gen()

    async def _gen(self) -> AsyncIterator[Any]:
        for c in self._chunks:
            yield c


def _delta_chunk(text: str | None) -> MagicMock:
    chunk = MagicMock()
    choice = MagicMock()
    choice.delta = MagicMock()
    choice.delta.content = text
    chunk.choices = [choice]
    chunk.usage = None
    return chunk


def _usage_chunk(prompt: int, completion: int) -> MagicMock:
    chunk = MagicMock()
    chunk.choices = []
    chunk.usage = MagicMock()
    chunk.usage.prompt_tokens = prompt
    chunk.usage.completion_tokens = completion
    return chunk


async def test_stream_completion_yields_text_and_records_usage() -> None:
    stream = _FakeChunkStream([_delta_chunk("hel"), _delta_chunk("lo"), _usage_chunk(5, 2)])
    fake = _fake_openai()
    fake.chat.completions.create = AsyncMock(return_value=stream)
    calls: list[tuple[str, int, int]] = []

    async def hook(m: str, i: int, o: int) -> None:
        calls.append((m, i, o))

    client = OpenAICompatClient(openai_client=fake, on_api_call=hook)
    out: list[str] = []
    async for tok in client.stream_completion(
        model="m", messages=[{"role": "user", "content": "q"}]
    ):
        out.append(tok)

    assert out == ["hel", "lo"]
    assert calls == [("m", 5, 2)]
    kwargs = fake.chat.completions.create.await_args.kwargs
    assert kwargs["stream"] is True
    assert kwargs["stream_options"] == {"include_usage": True}
