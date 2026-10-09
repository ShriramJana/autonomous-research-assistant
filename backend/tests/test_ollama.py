from __future__ import annotations

import httpx
import respx

from ara.ollama import list_models

BASE = "http://ollama.test:11434"


@respx.mock
async def test_lists_installed_models() -> None:
    respx.get(f"{BASE}/api/tags").mock(
        return_value=httpx.Response(
            200,
            json={
                "models": [
                    {"name": "qwen2.5:7b", "size": 4700000000},
                    {"name": "llama3.2:3b", "size": 2000000000},
                ]
            },
        )
    )
    status = await list_models(BASE)
    assert status.available is True
    assert [(m.name, m.size_bytes) for m in status.models] == [
        ("qwen2.5:7b", 4700000000),
        ("llama3.2:3b", 2000000000),
    ]


@respx.mock
async def test_connection_error_is_unavailable() -> None:
    respx.get(f"{BASE}/api/tags").mock(side_effect=httpx.ConnectError("refused"))
    status = await list_models(BASE)
    assert status.available is False and status.models == []


@respx.mock
async def test_ollama_malformed_response_is_unavailable() -> None:
    route = respx.get(f"{BASE}/api/tags")
    route.mock(return_value=httpx.Response(200, content=b"not json"))
    assert (await list_models(BASE)).available is False
    route.mock(return_value=httpx.Response(500, json={}))
    assert (await list_models(BASE)).available is False
    route.mock(return_value=httpx.Response(200, json={"models": "x"}))
    assert (await list_models(BASE)).available is False
    route.mock(return_value=httpx.Response(200, json=["not", "a", "dict"]))
    assert (await list_models(BASE)).available is False


@respx.mock
async def test_odd_rows_are_skipped_or_defaulted_never_raise() -> None:
    respx.get(f"{BASE}/api/tags").mock(
        return_value=httpx.Response(
            200,
            json={
                "models": [
                    {"name": None, "size": 1},
                    {"name": "a:1", "size": "big"},
                    {"name": "b:2"},
                    "junk",
                    {"name": "c:3", "size": 5},
                ]
            },
        )
    )
    status = await list_models(BASE)
    assert status.available is True
    assert [(m.name, m.size_bytes) for m in status.models] == [
        ("a:1", 0),
        ("b:2", 0),
        ("c:3", 5),
    ]
