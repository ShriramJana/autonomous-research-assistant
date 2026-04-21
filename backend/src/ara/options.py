"""Per-run research options.

Depth is a UX-facing knob that maps to two backend dials —
`max_sub_queries` (planner) and `max_iterations` (researcher web_search
budget). `web_search_enabled` is an independent toggle.

Defaults: depth=standard, web_search_enabled=True. Both preserve the
original always-on behaviour so existing callers and tests are unaffected
unless they opt in.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

Depth = Literal["quick", "standard", "deep"]


@dataclass(frozen=True)
class ResearchOptions:
    max_sub_queries: int
    max_iterations: int
    web_search_enabled: bool = True


_DEPTH_PRESETS: dict[Depth, ResearchOptions] = {
    "quick": ResearchOptions(max_sub_queries=3, max_iterations=2),
    "standard": ResearchOptions(max_sub_queries=5, max_iterations=3),
    "deep": ResearchOptions(max_sub_queries=7, max_iterations=5),
}


def options_for_depth(depth: Depth, *, web_search_enabled: bool = True) -> ResearchOptions:
    return replace(_DEPTH_PRESETS[depth], web_search_enabled=web_search_enabled)
