"""Ask a local Ollama daemon which models are installed (for the Settings picker)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class OllamaModel:
    name: str
    size_bytes: int


@dataclass(frozen=True)
class OllamaStatus:
    available: bool
    models: list[OllamaModel]


def _parse_row(row: Any) -> OllamaModel | None:
    """Tolerant row parser: skip rows without a string name, default odd sizes to 0."""
    if not isinstance(row, dict):
        return None
    name = row.get("name")
    if not isinstance(name, str) or not name:
        return None
    size = row.get("size", 0)
    # bool is an int subclass; reject it explicitly.
    size_bytes = size if isinstance(size, int) and not isinstance(size, bool) else 0
    return OllamaModel(name=name, size_bytes=size_bytes)


async def list_models(base_url: str, *, timeout: float = 2.0) -> OllamaStatus:
    """Never raises: any transport, status, or shape problem -> unavailable."""
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data: Any = resp.json()
    except (httpx.HTTPError, httpx.InvalidURL, ValueError):
        return OllamaStatus(available=False, models=[])
    rows = data.get("models") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return OllamaStatus(available=False, models=[])
    models = [m for m in (_parse_row(r) for r in rows) if m is not None]
    return OllamaStatus(available=True, models=models)
