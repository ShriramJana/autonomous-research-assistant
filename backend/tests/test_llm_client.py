"""Unit tests for the `AnthropicClient` facade.

Exercises all three completion methods via injected fake Anthropic clients
and verifies the observability hook fires on every call.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from ara.llm.client import (
    WEB_SEARCH_TOOL_TYPE,
    AnthropicClient,
    CompletionResult,
    MessageStop,
    TextDelta,
    ToolUseBlock,
)
from tests.conftest import FakeStream, make_fake_anthropic, make_usage


def test_web_search_tool_spec_default() -> None:
    spec = AnthropicClient.web_search_tool_spec()
    assert spec == {"type": WEB_SEARCH_TOOL_TYPE, "name": "web_search", "max_uses": 5}


def test_web_search_tool_spec_custom_max() -> None:
    assert AnthropicClient.web_search_tool_spec(max_uses=3)["max_uses"] == 3


def test_client_rejects_construction_without_key_or_client() -> None:
    with pytest.raises(ValueError):
        AnthropicClient(api_key="")


def test_client_accepts_injected_anthropic() -> None:
    fake = MagicMock()
    client = AnthropicClient(anthropic_client=fake)
    assert client._client is fake


async def test_complete_with_tools_delegates_to_messages_create() -> None:
    response = MagicMock()
    response.usage = make_usage()
    response.content = []
    response.stop_reason = "end_turn"
    fake = make_fake_anthropic(create_return=response)

    client = AnthropicClient(anthropic_client=fake)
    await client.complete_with_tools(
        model="test-model",
        messages=[{"role": "user", "content": "hi"}],
        tools=[AnthropicClient.web_search_tool_spec()],
        system="you are a test",
        max_tokens=100,
    )

    fake.messages.create.assert_awaited_once()
    kwargs = fake.messages.create.await_args.kwargs
    assert kwargs["model"] == "test-model"
    assert kwargs["system"] == "you are a test"
    assert kwargs["max_tokens"] == 100
    assert kwargs["tools"][0]["type"] == WEB_SEARCH_TOOL_TYPE


async def test_complete_without_tools_omits_tools_kwarg() -> None:
    response = MagicMock()
    response.usage = make_usage()
    response.content = []
    response.stop_reason = "end_turn"
    fake = make_fake_anthropic(create_return=response)

    client = AnthropicClient(anthropic_client=fake)
    await client.complete_with_tools(
        model="m",
        messages=[{"role": "user", "content": "hi"}],
    )
    kwargs = fake.messages.create.await_args.kwargs
    assert "tools" not in kwargs
    assert "system" not in kwargs


async def test_on_api_call_hook_fires() -> None:
    response = MagicMock()
    response.usage = make_usage(input_tokens=42, output_tokens=7)
    response.content = []
    response.stop_reason = "end_turn"
    fake = make_fake_anthropic(create_return=response)

    calls: list[tuple[str, int, int]] = []

    async def on_api_call(model: str, inp: int, out: int) -> None:
        calls.append((model, inp, out))

    client = AnthropicClient(anthropic_client=fake, on_api_call=on_api_call)
    await client.complete_with_tools(model="m", messages=[{"role": "user", "content": "hi"}])
    assert calls == [("m", 42, 7)]


async def test_stream_completion_yields_text_tokens() -> None:
    stream = FakeStream(tokens=["hello", " ", "world"])
    fake = make_fake_anthropic(stream_return=stream)

    client = AnthropicClient(anthropic_client=fake)
    collected: list[str] = []
    async for tok in client.stream_completion(
        model="m",
        messages=[{"role": "user", "content": "hi"}],
    ):
        collected.append(tok)

    assert collected == ["hello", " ", "world"]


async def test_stream_completion_records_usage_after_stream() -> None:
    stream = FakeStream(tokens=["a"], input_tokens=99, output_tokens=3)
    fake = make_fake_anthropic(stream_return=stream)

    calls: list[tuple[str, int, int]] = []

    async def on_api_call(m: str, i: int, o: int) -> None:
        calls.append((m, i, o))

    client = AnthropicClient(anthropic_client=fake, on_api_call=on_api_call)
    async for _ in client.stream_completion(model="m", messages=[]):
        pass
    assert calls == [("m", 99, 3)]


def _text_delta_event(text: str) -> MagicMock:
    ev = MagicMock()
    ev.type = "content_block_delta"
    ev.delta = MagicMock()
    ev.delta.type = "text_delta"
    ev.delta.text = text
    return ev


def _tool_use_block(tool_id: str, name: str, payload: dict[str, Any]) -> MagicMock:
    b = MagicMock()
    b.type = "tool_use"
    b.id = tool_id
    b.name = name
    b.input = payload
    return b


async def test_stream_completion_with_tools_emits_text_then_tool_then_stop() -> None:
    stream = FakeStream(
        events=[_text_delta_event("hi")],
        final_content=[_tool_use_block("t1", "web_search", {"query": "rag"})],
        input_tokens=15,
        output_tokens=6,
    )
    fake = make_fake_anthropic(stream_return=stream)
    client = AnthropicClient(anthropic_client=fake)

    collected: list[object] = []
    async for ev in client.stream_completion_with_tools(
        model="m",
        messages=[{"role": "user", "content": "hi"}],
        tools=[AnthropicClient.web_search_tool_spec()],
    ):
        collected.append(ev)

    assert isinstance(collected[0], TextDelta)
    assert collected[0].text == "hi"
    assert isinstance(collected[1], ToolUseBlock)
    assert collected[1].name == "web_search"
    assert collected[1].input == {"query": "rag"}
    assert isinstance(collected[-1], MessageStop)
    assert collected[-1].stop_reason == "end_turn"
    assert collected[-1].input_tokens == 15


def _text_block(text: str) -> MagicMock:
    b = MagicMock()
    b.type = "text"
    b.text = text
    return b


def _server_tool_use_block(name: str, payload: dict[str, Any]) -> MagicMock:
    b = MagicMock()
    b.type = "server_tool_use"
    b.id = "srv-1"
    b.name = name
    b.input = payload
    return b


async def test_complete_with_tools_returns_completion_result() -> None:
    response = MagicMock()
    response.usage = make_usage(input_tokens=11, output_tokens=4)
    response.stop_reason = "tool_use"
    response.content = [
        _text_block("thinking"),
        _server_tool_use_block("web_search", {"query": "rag"}),
        _tool_use_block("t1", "submit_finding", {"summary": "s"}),
    ]
    fake = make_fake_anthropic(create_return=response)

    client = AnthropicClient(anthropic_client=fake)
    result = await client.complete_with_tools(
        model="m", messages=[{"role": "user", "content": "hi"}]
    )

    assert isinstance(result, CompletionResult)
    assert result.text == "thinking"
    assert result.stop_reason == "tool_use"
    assert result.input_tokens == 11
    assert [tu.name for tu in result.tool_uses] == ["submit_finding"]
    assert result.tool_uses[0].input == {"summary": "s"}
    assert [tu.input["query"] for tu in result.server_tool_uses] == ["rag"]


def test_anthropic_client_capability_flags() -> None:
    fake = MagicMock()
    client = AnthropicClient(anthropic_client=fake)
    assert client.provider == "anthropic"
    assert client.supports_server_side_search is True
