# Settings (view-only) — ARA config visibility

## Goal

Give a signed-out user visible confirmation of what ARA is running, so
the ambient question "which model is doing the synthesis?" has a
self-serve answer. View-only for v1; editing is explicitly deferred.

## What this feature is *not*

- Not auth-gated (auth is parked per the earlier brainstorming pivot).
- Not editable — no model picker, no env override UI.
- Not a dashboard for runtime health (cost, uptime, etc.).
- Not a system-settings page (no theme toggle, no preferences).

## Backend

New route: `GET /api/config` on the existing `/api` prefix. Returns a
sanitized `ConfigResponse`:

```jsonc
{
  "models": {
    "planner":     "claude-sonnet-4-5",
    "researcher":  "claude-sonnet-4-5",
    "synthesizer": "claude-opus-4-5"
  },
  "depth_presets": {
    "quick":    { "max_sub_queries": 3, "max_iterations": 2 },
    "standard": { "max_sub_queries": 5, "max_iterations": 3 },
    "deep":     { "max_sub_queries": 7, "max_iterations": 5 }
  }
}
```

Explicitly **omitted** from the response:

- `anthropic_api_key` — sensitive
- `ara_host`, `ara_port`, `ara_cors_origins` — infra, not useful to a
  reader
- `ara_researcher_max_iterations`, `ara_researcher_input_token_budget` —
  engineering internals; the Depth presets are the user-facing story

Test: one `test_api.py` case that hits `GET /api/config` and asserts the
model fields match `Settings` defaults + the depth-preset block matches
`_DEPTH_PRESETS`.

## Frontend

New route: `app/settings/page.tsx` as a client component. Fetches
`/api/config` on mount; shows skeleton while loading and a mono error
line if the backend is unreachable.

Layout: TopNav stays, reused `max-w-4xl` rail, Cognitive Terminal
panels. Two sections:

1. **Active models** — three rows on a `bg-card` panel:
   `PLANNER / RESEARCHER / SYNTHESIZER → model-id` (mono, selectable).
2. **Depth presets** — small mono table echoing the backend response:
   preset → sub-queries → iterations. Matches what the user sees on the
   form's depth dropdown; this is the canonical source.

`lib/config.ts` with `fetchConfig(): Promise<Config>` — typed mirror of
the backend response shape.

Error state: if `/api/config` fails, the page shows a single mono line
"Config unavailable — backend may be offline" instead of throwing.

Loading state: three skeleton rows matching the models panel.

TopNav changes:

- Settings link: `/#settings` → `/settings`
- Active-state: `pathname === "/settings"` now highlights Settings

## Out of scope

- Editing any config value
- Per-user or per-org overrides (auth is parked)
- Showing runtime values (cost, recent errors, etc.)
- Hot-reloading config changes

## Done means

- `GET /api/config` returns the sanitized payload and is covered by a
  pytest case.
- `/settings` renders both panels against a running backend.
- `make lint` (ruff + mypy --strict on src + eslint) clean.
- Clicking Settings in the TopNav from any route lands on `/settings`
  and the link highlights correctly.
