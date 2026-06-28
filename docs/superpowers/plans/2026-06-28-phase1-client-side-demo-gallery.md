# Phase 1 — Free Client-Side Demo Gallery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A visitor with no API key sees a gallery of finished sample reports, clicks one, and watches the entire research process (plan → parallel researchers → streaming synthesis → cost meter) replay entirely in the browser from static JSON — zero backend calls, zero cost.

**Architecture:** A backend recorder script runs a real report once and serializes the ordered SSE event stream (with timing) to static JSON shipped in `frontend/public/demos/`. The frontend gains a `useReplayFromJson` hook that drives the *existing* `useResearchStream` reducer over that static array on a timer, and `ResearchLive` becomes presentational (accepts external state) so the demo reuses the real UI. The public gallery reads a static manifest and links to `/demo/[slug]` instead of the backend.

**Tech Stack:** Python 3.11 / Pydantic v2 (recorder), Next.js 16 App Router / React 19 / TypeScript strict (frontend), vitest (one pure-helper unit test).

---

## File Structure

**Backend**
- Create `backend/src/ara/demos.py` — pure builders (`build_demo_payload`, `build_manifest`) that turn captured events into the on-disk JSON shape. Testable without an API key.
- Create `backend/scripts/record_run.py` — CLI that runs `run_report` with a full-capture store and writes `frontend/public/demos/<slug>.json` + refreshes `manifest.json`. Needs a real key; verified manually.
- Create `backend/tests/test_demos.py` — unit tests for the pure builders.

**Frontend**
- Modify `frontend/hooks/use-research-stream.ts` — export `reducer`, `initialState`, and the existing types for reuse.
- Create `frontend/lib/replay.ts` — pure `computeDelays(...)` helper (timing schedule). Unit-tested.
- Create `frontend/hooks/use-replay-from-json.ts` — replays a `DemoEvent[]` through the shared reducer on a timer; returns `ResearchStreamState` + `restart`.
- Create `frontend/lib/demos.ts` — `DemoManifestEntry` / `DemoFile` types + `loadDemoEvents(slug)` fetch helper; static import of the manifest.
- Modify `frontend/components/research-live.tsx` — accept optional `state` prop; when provided, render it without opening an EventSource.
- Create `frontend/components/demo-replay.tsx` — client component: loads a demo file, runs `useReplayFromJson`, renders `ResearchLive` with the replayed state + a Replay button.
- Create `frontend/app/demo/[slug]/page.tsx` — route that renders `<DemoReplay slug=… />`.
- Modify `frontend/components/gallery-snapshot.tsx` — read the static manifest, link to `/demo/[slug]`.
- Modify `frontend/app/gallery/page.tsx` — read the static manifest, link to `/demo/[slug]`.
- Create `frontend/public/demos/manifest.json` + `frontend/public/demos/sample-quantum.json` — committed fixture so the gallery renders in CI / without recording.
- Create `frontend/lib/replay.test.ts` — vitest unit test for `computeDelays`.
- Modify `frontend/package.json` — add `vitest` devDep + `"test": "vitest run"` script.
- Create `frontend/vitest.config.ts` — node-env vitest config.

---

## Task 1: Pure demo-payload builders (backend)

**Files:**
- Create: `backend/src/ara/demos.py`
- Test: `backend/tests/test_demos.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_demos.py
"""Tests for the pure demo-payload builders (no API key needed)."""

from __future__ import annotations

from ara.demos import build_demo_payload, build_manifest
from ara.models.events import PlanReady, SynthesisToken
from ara.models.research import Priority, ResearchPlan, SubQuery


def _sample_events() -> list[tuple[float, object]]:
    plan = ResearchPlan(
        original_question="What is quantum supremacy?",
        sub_queries=[
            SubQuery(
                question="Define quantum supremacy",
                rationale="Establish the core definition.",
                priority=Priority.HIGH,
            ),
            SubQuery(
                question="Notable demonstrations",
                rationale="Ground it in real experiments.",
                priority=Priority.MEDIUM,
            ),
            SubQuery(
                question="Criticisms of the claims",
                rationale="Balance the picture with skepticism.",
                priority=Priority.LOW,
            ),
        ],
        web_search_enabled=True,
    )
    return [
        (0.0, PlanReady(plan=plan)),
        (0.5, SynthesisToken(token="Quantum ")),
        (0.75, SynthesisToken(token="supremacy")),
    ]


def test_build_demo_payload_shape() -> None:
    payload = build_demo_payload(
        slug="sample-quantum",
        title="Quantum supremacy",
        question="What is quantum supremacy?",
        model="claude-sonnet-4-5",
        created_at="2026-06-28T00:00:00Z",
        events=_sample_events(),
    )
    assert payload["slug"] == "sample-quantum"
    assert payload["question"] == "What is quantum supremacy?"
    assert len(payload["events"]) == 3
    first = payload["events"][0]
    assert first["t_ms"] == 0
    assert first["event"]["type"] == "plan_ready"
    # Timing offsets are integer milliseconds derived from the float seconds.
    assert payload["events"][1]["t_ms"] == 500
    assert payload["events"][2]["t_ms"] == 750


def test_build_manifest_entry_summarizes() -> None:
    payload = build_demo_payload(
        slug="sample-quantum",
        title="Quantum supremacy",
        question="What is quantum supremacy?",
        model="claude-sonnet-4-5",
        created_at="2026-06-28T00:00:00Z",
        events=_sample_events(),
    )
    manifest = build_manifest([payload])
    assert manifest == [
        {
            "slug": "sample-quantum",
            "title": "Quantum supremacy",
            "question": "What is quantum supremacy?",
            "model": "claude-sonnet-4-5",
            "created_at": "2026-06-28T00:00:00Z",
            "n_events": 3,
        }
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_demos.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ara.demos'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/src/ara/demos.py
"""Pure builders that turn captured events into the static demo JSON shape.

Kept free of I/O and the Anthropic SDK so they can be unit-tested without a
key. The recorder script (scripts/record_run.py) supplies the captured
events; these functions only reshape them.
"""

from __future__ import annotations

from typing import Any

from ara.models.events import ResearchEvent


def build_demo_payload(
    *,
    slug: str,
    title: str,
    question: str,
    model: str,
    created_at: str,
    events: list[tuple[float, ResearchEvent]],
) -> dict[str, Any]:
    """Reshape (offset_seconds, event) pairs into the on-disk demo file.

    `t_ms` is the integer-millisecond offset from the start of the run, used
    by the frontend to pace replay. `event` is the exact SSE wire object
    (model_dump(mode="json")), so it round-trips through the frontend's
    JSON.parse without translation.
    """
    return {
        "slug": slug,
        "title": title,
        "question": question,
        "model": model,
        "created_at": created_at,
        "events": [
            {"t_ms": int(round(offset * 1000)), "event": event.model_dump(mode="json")}
            for offset, event in events
        ],
    }


def build_manifest(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Summarize demo payloads into the manifest the gallery lists."""
    return [
        {
            "slug": p["slug"],
            "title": p["title"],
            "question": p["question"],
            "model": p["model"],
            "created_at": p["created_at"],
            "n_events": len(p["events"]),
        }
        for p in payloads
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_demos.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Lint + typecheck**

Run: `cd backend && uv run ruff check src/ara/demos.py tests/test_demos.py && uv run mypy --strict src/ara/demos.py`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add backend/src/ara/demos.py backend/tests/test_demos.py
git commit -m "feat(demos): pure builders for static demo payload + manifest"
```

---

## Task 2: Recorder CLI (backend)

**Files:**
- Create: `backend/scripts/record_run.py`

This task wraps `run_report` with a store that captures *every* event (the production `InMemoryReportStore` caps at 50 via a ring buffer, which would drop most synthesis tokens). Verified manually with a real key — no unit test, because it performs live API calls.

- [ ] **Step 1: Write the recorder script**

```python
# backend/scripts/record_run.py
"""Record a real ARA run to a static demo JSON for the client-side gallery.

    uv run python scripts/record_run.py "your question" --slug my-demo --title "My demo"

Runs the full pipeline with the server ANTHROPIC_API_KEY (costs a few cents),
captures every SSE event with timing, and writes
frontend/public/demos/<slug>.json, then rebuilds frontend/public/demos/manifest.json
from every *.json in that directory. Replay is then 100% client-side and free.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from ara.config import get_settings
from ara.demos import build_demo_payload, build_manifest
from ara.models.events import ResearchEvent
from ara.models.research import ReportEnvelope
from ara.options import Depth, options_for_depth
from ara.runtime.orchestrator import run_report
from ara.runtime.overrides import RuntimeOverrides

_DEMOS_DIR = Path(__file__).resolve().parents[2] / "frontend" / "public" / "demos"


class _RecordingStore:
    """Full-capture ReportStore for recording — no ring-buffer cap."""

    def __init__(self) -> None:
        self.events: list[tuple[float, ResearchEvent]] = []
        self.question: str = ""
        self._t0: float | None = None

    async def create(
        self,
        report_id: UUID,
        question: str,
        *,
        owner_id: UUID,
        depth: Depth,
        browse_web: bool,
        used_byok: bool,
    ) -> None:
        self._t0 = time.monotonic()
        self.question = question

    async def get_question(self, report_id: UUID) -> str | None:
        return self.question

    async def put_event(self, report_id: UUID, event: ResearchEvent) -> None:
        offset = 0.0 if self._t0 is None else time.monotonic() - self._t0
        self.events.append((offset, event))

    async def close(
        self,
        report_id: UUID,
        *,
        status: Literal["completed", "error"],
        cost_usd: float | None = None,
        report_payload: ReportEnvelope | None = None,
        error_message: str | None = None,
    ) -> None:
        if status == "error":
            print(f"run closed with error: {error_message}", file=sys.stderr)

    async def subscribe(self, report_id: UUID) -> AsyncIterator[ResearchEvent]:
        # Required by the ReportStore Protocol; unused during recording.
        return
        yield  # pragma: no cover — makes this an async generator


async def _main(question: str, slug: str, title: str, depth: Depth) -> int:
    settings = get_settings()
    if not settings.anthropic_api_key:
        print("ANTHROPIC_API_KEY is not set; populate .env first.", file=sys.stderr)
        return 2

    store = _RecordingStore()
    overrides = RuntimeOverrides(
        api_key=settings.anthropic_api_key,
        planner_model=settings.claude_planner_model,
        researcher_model=settings.claude_researcher_model,
        synthesizer_model=settings.claude_synthesizer_model,
        options=options_for_depth(depth),
    )

    await run_report(
        report_id=uuid4(),
        question=question,
        store=store,  # type: ignore[arg-type]  # structural ReportStore
        settings=settings,
        overrides=overrides,
        owner_id=uuid4(),
    )

    payload = build_demo_payload(
        slug=slug,
        title=title,
        question=question,
        model=settings.claude_synthesizer_model,
        created_at=datetime.now(timezone.utc).isoformat(),
        events=store.events,
    )

    _DEMOS_DIR.mkdir(parents=True, exist_ok=True)
    (_DEMOS_DIR / f"{slug}.json").write_text(json.dumps(payload, indent=2))

    payloads = [
        json.loads(p.read_text())
        for p in sorted(_DEMOS_DIR.glob("*.json"))
        if p.name != "manifest.json"
    ]
    (_DEMOS_DIR / "manifest.json").write_text(
        json.dumps(build_manifest(payloads), indent=2)
    )

    print(f"wrote {slug}.json ({len(store.events)} events) + manifest.json")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record an ARA run to demo JSON.")
    parser.add_argument("question")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument(
        "--depth", choices=["quick", "standard", "deep"], default="standard"
    )
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(_main(args.question, args.slug, args.title, args.depth))
    )
```

- [ ] **Step 2: Lint + typecheck the script**

Run: `cd backend && uv run ruff check scripts/record_run.py && uv run mypy --strict scripts/record_run.py`
Expected: no errors

- [ ] **Step 3: Commit (script only — recording happens later, after the frontend can render it)**

```bash
git add backend/scripts/record_run.py
git commit -m "feat(demos): record_run.py — capture a real run to static demo JSON"
```

---

## Task 3: Export the shared reducer (frontend)

**Files:**
- Modify: `frontend/hooks/use-research-stream.ts`

The replay hook must reuse the *exact* live reducer so demo and live behave identically. Currently `reducer` and `initialState` are module-private.

- [ ] **Step 1: Export `initialState` and `reducer`**

In `frontend/hooks/use-research-stream.ts`, change the two declarations to named exports (add `export`):

```typescript
export const initialState: ResearchStreamState = {
  status: "idle",
  plan: null,
  agents: [],
  streamedMarkdown: "",
  report: null,
  errorMessage: null,
  cumulativeCostUsd: 0,
  costByModel: {},
};

export type Action = { kind: "event"; event: ResearchEvent } | { kind: "reset" };

export function reducer(state: ResearchStreamState, action: Action): ResearchStreamState {
```

(Only `export` is added to `initialState`, the `Action` type, and `reducer`. The body is unchanged.)

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add frontend/hooks/use-research-stream.ts
git commit -m "refactor(stream): export reducer + initialState for replay reuse"
```

---

## Task 4: Replay timing helper + vitest (frontend)

**Files:**
- Create: `frontend/lib/replay.ts`
- Create: `frontend/lib/replay.test.ts`
- Create: `frontend/vitest.config.ts`
- Modify: `frontend/package.json`

- [ ] **Step 1: Add vitest config**

```typescript
// frontend/vitest.config.ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["lib/**/*.test.ts"],
  },
});
```

- [ ] **Step 2: Add the test script + devDep to package.json**

In `frontend/package.json`, add `"test": "vitest run"` to `scripts` and `"vitest": "^3.0.0"` to `devDependencies`:

```json
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "lint": "eslint",
    "test": "vitest run"
  },
```

Then run: `cd frontend && npm install`
Expected: vitest installed, lockfile updated.

- [ ] **Step 3: Write the failing test**

```typescript
// frontend/lib/replay.test.ts
import { describe, expect, it } from "vitest";
import { computeDelays } from "@/lib/replay";

describe("computeDelays", () => {
  it("returns the gap between consecutive timestamps", () => {
    const events = [{ t_ms: 0 }, { t_ms: 200 }, { t_ms: 500 }];
    expect(computeDelays(events, { maxGapMs: 1000 })).toEqual([0, 200, 300]);
  });

  it("clamps long idle gaps to maxGapMs so replay never stalls", () => {
    const events = [{ t_ms: 0 }, { t_ms: 30_000 }];
    expect(computeDelays(events, { maxGapMs: 800 })).toEqual([0, 800]);
  });

  it("never emits a negative delay if timestamps go backwards", () => {
    const events = [{ t_ms: 100 }, { t_ms: 50 }];
    expect(computeDelays(events, { maxGapMs: 1000 })).toEqual([0, 0]);
  });

  it("returns [] for no events", () => {
    expect(computeDelays([], { maxGapMs: 1000 })).toEqual([]);
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — cannot resolve `@/lib/replay`

- [ ] **Step 5: Implement `computeDelays`**

```typescript
// frontend/lib/replay.ts
// Pure timing helper for client-side demo replay. Given recorded event
// offsets (t_ms from run start), produce the per-event delay (ms) to wait
// before dispatching each one, so the visual cadence matches the real run —
// while clamping long idle gaps so a recorded pause never stalls the demo.

export interface TimedEvent {
  t_ms: number;
}

export interface DelayOptions {
  maxGapMs: number;
}

export function computeDelays(
  events: readonly TimedEvent[],
  { maxGapMs }: DelayOptions,
): number[] {
  return events.map((ev, i) => {
    if (i === 0) return 0;
    const gap = ev.t_ms - events[i - 1].t_ms;
    if (gap < 0) return 0;
    return Math.min(gap, maxGapMs);
  });
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (4 tests)

- [ ] **Step 7: Commit**

```bash
git add frontend/lib/replay.ts frontend/lib/replay.test.ts frontend/vitest.config.ts frontend/package.json frontend/package-lock.json
git commit -m "feat(replay): computeDelays timing helper + vitest setup"
```

---

## Task 5: Replay hook + demo loaders (frontend)

**Files:**
- Create: `frontend/lib/demos.ts`
- Create: `frontend/hooks/use-replay-from-json.ts`

- [ ] **Step 1: Create the demo types + loader**

```typescript
// frontend/lib/demos.ts
import type { ResearchEvent } from "@/lib/events";
import manifest from "@/public/demos/manifest.json";

export interface DemoManifestEntry {
  slug: string;
  title: string;
  question: string;
  model: string;
  created_at: string;
  n_events: number;
}

export interface DemoEvent {
  t_ms: number;
  event: ResearchEvent;
}

export interface DemoFile {
  slug: string;
  title: string;
  question: string;
  model: string;
  created_at: string;
  events: DemoEvent[];
}

// Static import — bundled at build time, so the gallery renders with no
// network call and no backend.
export const demoManifest = manifest as DemoManifestEntry[];

// The event payloads can be large; fetch them on demand from /public.
export async function loadDemoEvents(slug: string): Promise<DemoFile> {
  const res = await fetch(`/demos/${slug}.json`, { cache: "force-cache" });
  if (!res.ok) throw new Error(`demo ${slug} not found`);
  return (await res.json()) as DemoFile;
}
```

Note: `@/public/...` resolves via the `@/*` tsconfig path alias (which maps to the frontend root). Confirm in Step 3.

- [ ] **Step 2: Create the replay hook**

```typescript
// frontend/hooks/use-replay-from-json.ts
"use client";

import { useEffect, useReducer, useState } from "react";

import { initialState, reducer } from "@/hooks/use-research-stream";
import type { ResearchStreamState } from "@/hooks/use-research-stream";
import { computeDelays } from "@/lib/replay";
import type { DemoEvent } from "@/lib/demos";

const MAX_GAP_MS = 800;

export interface ReplayResult {
  state: ResearchStreamState;
  /** Restart the replay from the beginning. */
  restart: () => void;
}

// Drives the SHARED live reducer over a static recorded array on a timer, so
// the demo is visually identical to a live run but makes zero network calls.
export function useReplayFromJson(events: DemoEvent[] | null): ReplayResult {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!events || events.length === 0) return;
    dispatch({ kind: "reset" });

    const delays = computeDelays(events, { maxGapMs: MAX_GAP_MS });
    const timers: ReturnType<typeof setTimeout>[] = [];
    let elapsed = 0;
    for (let i = 0; i < events.length; i++) {
      elapsed += delays[i];
      const event = events[i].event;
      timers.push(setTimeout(() => dispatch({ kind: "event", event }), elapsed));
    }

    return () => {
      for (const t of timers) clearTimeout(t);
    };
  }, [events, nonce]);

  return { state, restart: () => setNonce((n) => n + 1) };
}
```

- [ ] **Step 3: Typecheck (also validates the `@/public` alias)**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors. If `@/public/demos/manifest.json` fails to resolve, add `"resolveJsonModule": true` to `frontend/tsconfig.json` `compilerOptions` (Next enables it by default; only add if tsc complains), and ensure the fixture from Task 8 exists. If the import still fails at typecheck because the file is created in Task 8, proceed — Task 8 creates it before any build/run step that exercises this module.

- [ ] **Step 4: Commit**

```bash
git add frontend/lib/demos.ts frontend/hooks/use-replay-from-json.ts
git commit -m "feat(replay): useReplayFromJson hook + demo file loaders"
```

---

## Task 6: Make ResearchLive presentational (frontend)

**Files:**
- Modify: `frontend/components/research-live.tsx`

Add an optional `state` prop. When supplied, the component renders that state and never opens an EventSource (the existing hook with a `null` reportId and no `streamUrl` already no-ops, so calling it unconditionally is safe — React hook rules require the call to be unconditional).

- [ ] **Step 1: Import the state type**

Change the import on line 12 to also import the state type:

```typescript
import { useResearchStream } from "@/hooks/use-research-stream";
import type { ResearchStreamState } from "@/hooks/use-research-stream";
```

- [ ] **Step 2: Add the prop and prefer it over the live hook**

Replace the props interface and the first line of the component body (lines 27-39) with:

```typescript
export interface ResearchLiveProps {
  reportId?: string;
  shareToken?: string;
  streamUrl?: string;
  /** When provided (demo replay), render this state instead of streaming. */
  state?: ResearchStreamState;
}

export function ResearchLive({
  reportId,
  shareToken,
  streamUrl,
  state: stateProp,
}: ResearchLiveProps) {
  // Hook call is unconditional (React rule). With a null reportId and no
  // streamUrl it no-ops and returns idle, so passing `stateProp` makes this
  // component purely presentational with zero network activity.
  const liveState = useResearchStream(reportId ?? null, shareToken, streamUrl);
  const state = stateProp ?? liveState;
  const [mobileTab, setMobileTab] = useState<Tab>("report");
  const [flash, setFlash] = useState<Flash>(null);
```

(The rest of the component is unchanged — it already reads everything from `state`.)

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/components/research-live.tsx
git commit -m "refactor(research-live): accept external state for demo replay"
```

---

## Task 7: Demo route + replay component (frontend)

**Files:**
- Create: `frontend/components/demo-replay.tsx`
- Create: `frontend/app/demo/[slug]/page.tsx`

- [ ] **Step 1: Create the demo replay client component**

```tsx
// frontend/components/demo-replay.tsx
"use client";

import { useEffect, useState } from "react";
import { RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { ResearchLive } from "@/components/research-live";
import { useReplayFromJson } from "@/hooks/use-replay-from-json";
import { loadDemoEvents } from "@/lib/demos";
import type { DemoEvent } from "@/lib/demos";

export function DemoReplay({ slug }: { slug: string }) {
  const [events, setEvents] = useState<DemoEvent[] | null>(null);
  const [notFound, setNotFound] = useState(false);
  const { state, restart } = useReplayFromJson(events);

  useEffect(() => {
    let active = true;
    loadDemoEvents(slug)
      .then((file) => {
        if (active) setEvents(file.events);
      })
      .catch(() => {
        if (active) setNotFound(true);
      });
    return () => {
      active = false;
    };
  }, [slug]);

  if (notFound) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-24 text-center">
        <p className="text-muted-foreground font-mono text-sm">
          Demo &ldquo;{slug}&rdquo; not found.
        </p>
      </main>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <div className="flex items-center justify-between border-b border-white/[0.06] px-6 py-2 print:hidden">
        <span className="text-muted-foreground font-mono text-[10px] uppercase tracking-widest">
          Demo replay · no API key · runs in your browser
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={restart}
          className="text-muted-foreground hover:text-foreground font-mono text-xs uppercase tracking-wider"
        >
          <RotateCcw className="mr-1.5 h-3.5 w-3.5" strokeWidth={1.75} />
          Replay
        </Button>
      </div>
      <ResearchLive state={state} />
    </div>
  );
}
```

- [ ] **Step 2: Create the route**

```tsx
// frontend/app/demo/[slug]/page.tsx
import { DemoReplay } from "@/components/demo-replay";

export default async function DemoPage({
  params,
}: {
  params: Promise<{ slug: string }>;
}) {
  const { slug } = await params;
  return <DemoReplay slug={slug} />;
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add frontend/components/demo-replay.tsx frontend/app/demo/
git commit -m "feat(demo): /demo/[slug] route replays a recorded run client-side"
```

---

## Task 8: Commit a fixture demo (frontend)

**Files:**
- Create: `frontend/public/demos/manifest.json`
- Create: `frontend/public/demos/sample-quantum.json`

A small hand-authored fixture so the gallery renders and the route works without running the recorder (CI-safe, key-free). The recorder (Task 2) overwrites these with richer real runs later.

- [ ] **Step 1: Create the demo event file**

The model shapes below are the real ones (verified against `backend/src/ara/models/research.py`): `SubQuery` requires `question`+`rationale`+`priority` (1/2/3); `ResearchPlan` requires 3–7 sub-queries; `Source.url` must be a valid URL; `FinalReport` requires `report_id`, `executive_summary`, and ≥1 `sections` (there is **no** `markdown` field).

```json
{
  "slug": "sample-quantum",
  "title": "What is quantum supremacy?",
  "question": "What is quantum supremacy?",
  "model": "claude-opus-4-5",
  "created_at": "2026-06-28T00:00:00Z",
  "events": [
    {
      "t_ms": 0,
      "event": {
        "type": "plan_ready",
        "plan": {
          "original_question": "What is quantum supremacy?",
          "web_search_enabled": true,
          "sub_queries": [
            { "id": "11111111-1111-1111-1111-111111111111", "question": "Define quantum supremacy", "rationale": "Establish the core definition.", "priority": 3 },
            { "id": "22222222-2222-2222-2222-222222222222", "question": "Notable demonstrations of quantum supremacy", "rationale": "Ground it in real experiments.", "priority": 2 },
            { "id": "33333333-3333-3333-3333-333333333333", "question": "Criticisms of quantum supremacy claims", "rationale": "Balance the picture with skepticism.", "priority": 1 }
          ]
        }
      }
    },
    { "t_ms": 300, "event": { "type": "researcher_started", "sub_query_id": "11111111-1111-1111-1111-111111111111", "question": "Define quantum supremacy" } },
    { "t_ms": 350, "event": { "type": "researcher_started", "sub_query_id": "22222222-2222-2222-2222-222222222222", "question": "Notable demonstrations of quantum supremacy" } },
    { "t_ms": 400, "event": { "type": "researcher_started", "sub_query_id": "33333333-3333-3333-3333-333333333333", "question": "Criticisms of quantum supremacy claims" } },
    { "t_ms": 700, "event": { "type": "researcher_progress", "sub_query_id": "11111111-1111-1111-1111-111111111111", "tool_call": "web_search: quantum supremacy definition" } },
    {
      "t_ms": 1400,
      "event": {
        "type": "researcher_complete",
        "sub_query_id": "11111111-1111-1111-1111-111111111111",
        "finding": {
          "sub_query_id": "11111111-1111-1111-1111-111111111111",
          "summary": "Quantum supremacy is the point at which a quantum computer solves a problem no classical computer can in feasible time.",
          "key_facts": [],
          "sources": [
            { "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "url": "https://example.com/quantum-supremacy", "title": "Quantum supremacy explained" }
          ]
        }
      }
    },
    {
      "t_ms": 1600,
      "event": {
        "type": "researcher_complete",
        "sub_query_id": "22222222-2222-2222-2222-222222222222",
        "finding": {
          "sub_query_id": "22222222-2222-2222-2222-222222222222",
          "summary": "Google's 2019 Sycamore experiment is the best-known claimed demonstration.",
          "key_facts": [],
          "sources": [
            { "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "url": "https://example.com/sycamore", "title": "Sycamore processor" }
          ]
        }
      }
    },
    {
      "t_ms": 1750,
      "event": {
        "type": "researcher_complete",
        "sub_query_id": "33333333-3333-3333-3333-333333333333",
        "finding": {
          "sub_query_id": "33333333-3333-3333-3333-333333333333",
          "summary": "IBM argued the classical runtime estimate was inflated, so the 'supremacy' label is contested.",
          "key_facts": [],
          "sources": [
            { "id": "cccccccc-cccc-cccc-cccc-cccccccccccc", "url": "https://example.com/ibm-response", "title": "IBM's response" }
          ]
        }
      }
    },
    { "t_ms": 1900, "event": { "type": "synthesis_token", "token": "Quantum supremacy marks the moment " } },
    { "t_ms": 2000, "event": { "type": "synthesis_token", "token": "a quantum computer outperforms any classical one [1]. " } },
    { "t_ms": 2100, "event": { "type": "synthesis_token", "token": "The landmark demonstration was Google's Sycamore in 2019 [2]." } },
    {
      "t_ms": 2300,
      "event": {
        "type": "report_complete",
        "report": {
          "report_id": "99999999-9999-9999-9999-999999999999",
          "original_question": "What is quantum supremacy?",
          "web_search_enabled": true,
          "executive_summary": "Quantum supremacy is the milestone at which a programmable quantum device solves a problem no classical computer can solve in feasible time [1]. The most prominent demonstration was Google's 2019 Sycamore experiment [2], though the claim has drawn methodological criticism [3].",
          "sections": [
            { "heading": "Definition", "content": "Quantum supremacy denotes the point where a quantum computer outperforms the best classical computer on a specific task [1].", "citation_ids": ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"] },
            { "heading": "Landmark demonstration", "content": "In 2019 Google reported that its 53-qubit Sycamore processor performed a sampling task in 200 seconds that it estimated would take a classical supercomputer millennia [2].", "citation_ids": ["bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"] },
            { "heading": "Criticism", "content": "IBM argued the classical runtime estimate was inflated and the task could be simulated far faster, so the 'supremacy' label remains contested [3].", "citation_ids": ["cccccccc-cccc-cccc-cccc-cccccccccccc"] }
          ],
          "citations": [
            { "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "url": "https://example.com/quantum-supremacy", "title": "Quantum supremacy explained" },
            { "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "url": "https://example.com/sycamore", "title": "Sycamore processor" },
            { "id": "cccccccc-cccc-cccc-cccc-cccccccccccc", "url": "https://example.com/ibm-response", "title": "IBM's response" }
          ]
        }
      }
    },
    { "t_ms": 2300, "event": { "type": "cost_update", "model": "claude-opus-4-5", "input_tokens": 4200, "output_tokens": 600, "cumulative_usd": 0.0492 } }
  ]
}
```

- [ ] **Step 2: Verify the fixture matches the real schema**

The event shapes above must satisfy the backend Pydantic models so a recorded run is a drop-in replacement. Validate the fixture against the real adapter:

Run:
```bash
cd backend && uv run python -c "
import json, pathlib
from ara.models.events import ResearchEventAdapter
f = json.loads(pathlib.Path('../frontend/public/demos/sample-quantum.json').read_text())
for item in f['events']:
    ResearchEventAdapter.validate_python(item['event'])
print('ok', len(f['events']), 'events')
"
```
Expected: `ok 13 events`. If any event fails validation, fix the fixture to match the model (the error names the missing/invalid field) and re-run.

- [ ] **Step 3: Create the manifest**

```json
[
  {
    "slug": "sample-quantum",
    "title": "What is quantum supremacy?",
    "question": "What is quantum supremacy?",
    "model": "claude-opus-4-5",
    "created_at": "2026-06-28T00:00:00Z",
    "n_events": 13
  }
]
```

- [ ] **Step 4: Run the frontend unit tests + typecheck**

Run: `cd frontend && npm test && npx tsc --noEmit`
Expected: vitest passes; tsc clean (the `@/public/demos/manifest.json` import now resolves).

- [ ] **Step 5: Commit**

```bash
git add frontend/public/demos/manifest.json frontend/public/demos/sample-quantum.json
git commit -m "test(demo): committed fixture demo so gallery renders key-free"
```

---

## Task 9: Repoint the public gallery to the static manifest (frontend)

**Files:**
- Modify: `frontend/components/gallery-snapshot.tsx`
- Modify: `frontend/app/gallery/page.tsx`

- [ ] **Step 1: Rewrite the gallery snapshot to use the static manifest**

Replace the entire contents of `frontend/components/gallery-snapshot.tsx`:

```tsx
import Link from "next/link";

import { demoManifest } from "@/lib/demos";

export function GallerySnapshot() {
  const items = demoManifest.slice(0, 3);
  if (items.length === 0) return null;
  return (
    <div>
      <h2 className="text-muted-foreground mb-4 font-mono text-xs uppercase tracking-widest">
        Sample reports
      </h2>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        {items.map((r) => (
          <Link
            key={r.slug}
            href={`/demo/${r.slug}`}
            className="bg-card hover:bg-card/80 block rounded-lg p-4 transition-colors"
          >
            <p className="font-medium leading-snug">{r.question}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
```

Note: this component was previously a client component (`"use client"` + `useEffect`). It is now a server component that reads the bundled manifest — no `"use client"` directive. If `frontend/app/page.tsx` imports it inside a client component, that's fine (server components can be rendered by client trees only when passed as children; if `page.tsx` is a server component, the direct import works). Verify in Step 3; if `page.tsx` is `"use client"`, keep `GallerySnapshot` as a server component by leaving the import in `page.tsx` and confirming tsc passes — if Next errors at build about a server component imported into a client component, add `"use client"` back to the top of `gallery-snapshot.tsx` (the `demoManifest` static import works in client components too).

- [ ] **Step 2: Rewrite the gallery page to use the static manifest**

Replace the entire contents of `frontend/app/gallery/page.tsx`:

```tsx
import Link from "next/link";

import { demoManifest } from "@/lib/demos";

export default function GalleryPage() {
  const items = demoManifest;
  return (
    <main className="mx-auto max-w-5xl px-6 py-12">
      <h1 className="font-mono text-2xl tracking-tight">Sample gallery</h1>
      <p className="text-muted-foreground mt-2 text-sm">
        Curated runs showing what ARA does end-to-end. Each one replays in your
        browser — no API key, no cost.
      </p>
      <div className="mt-8 grid grid-cols-1 gap-4 md:grid-cols-3">
        {items.length === 0 && (
          <p className="text-muted-foreground col-span-3 font-mono text-xs">
            Gallery is empty.
          </p>
        )}
        {items.map((r) => (
          <Link
            key={r.slug}
            href={`/demo/${r.slug}`}
            className="bg-card hover:bg-card/80 block rounded-lg p-5 transition-colors"
          >
            <p className="font-medium leading-snug">{r.question}</p>
            <p className="text-muted-foreground/60 mt-3 font-mono text-[10px] uppercase tracking-wider">
              Watch replay
            </p>
          </Link>
        ))}
      </div>
    </main>
  );
}
```

(The `export const dynamic = "force-dynamic"` and the backend `fetch` are removed — the manifest is static, so the page can be statically rendered.)

- [ ] **Step 3: Typecheck + production build**

Run: `cd frontend && npx tsc --noEmit && npm run build`
Expected: tsc clean; `next build` succeeds and lists `/demo/[slug]` and `/gallery` routes.

- [ ] **Step 4: Commit**

```bash
git add frontend/components/gallery-snapshot.tsx frontend/app/gallery/page.tsx
git commit -m "feat(gallery): public gallery reads static manifest, links to client demos"
```

---

## Task 10: End-to-end manual verification (backend-down)

**Files:** none (verification only)

- [ ] **Step 1: Start ONLY the frontend (backend intentionally not running)**

Run: `cd frontend && npm run dev`
Then open `http://localhost:3000/gallery`.

- [ ] **Step 2: Confirm the demo plays with no backend**

- The gallery lists "What is quantum supremacy?".
- Click it → `/demo/sample-quantum` shows the plan tree populate, two researchers run then complete, synthesis text stream in, the report render, and the cost meter show a non-zero value.
- Open the browser Network tab and confirm the ONLY request is `GET /demos/sample-quantum.json` — no `/api/*` calls.
- Click **Replay** → the whole sequence runs again from the start.

- [ ] **Step 3: (Optional, needs a key) Record a real demo**

Run: `cd backend && uv run python scripts/record_run.py "How does CRISPR gene editing work?" --slug crispr --title "How does CRISPR work?"`
Then reload `/gallery` — the new card appears and plays. Commit the generated files:

```bash
git add frontend/public/demos/crispr.json frontend/public/demos/manifest.json
git commit -m "content(demo): record CRISPR sample run"
```

- [ ] **Step 4: Final full-suite check**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run mypy --strict src` then `cd ../frontend && npm test && npm run build`
Expected: all green.

---

## Self-Review Notes

- **Spec coverage (Phase 1):** static client-side gallery (Tasks 6-9), recorder → static JSON (Tasks 1-2), `use-replay-from-json` reusing render components (Tasks 3-7), committed fixture for CI/key-free render (Task 8), backend untouched for live users (only additive `demos.py` + script). ✓
- **Out of scope here:** multi-provider BYOK (Phase 2) and deploy (Phase 3) get their own plans.
- **Type consistency:** `computeDelays`, `DemoEvent`, `DemoFile`, `ResearchStreamState`, `reducer`, `initialState` names match across tasks. The fixture event shapes are validated against `ResearchEventAdapter` in Task 8 Step 2.
- **Known assumption to verify during execution:** the exact required fields on `SubQueryFinding`, `Source`, `ResearchPlan`, `SubQuery`, and `FinalReport` — Task 8 Step 2 catches any mismatch against the real Pydantic models and tells you what to fix.
```
