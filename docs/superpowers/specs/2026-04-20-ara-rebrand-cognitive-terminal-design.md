# ARA Rebrand & Cognitive Terminal Restyle

## Goal

Recreate the imported Stitch design ("Cognitive Terminal") in the existing Next.js
frontend, and rebrand the displayed product name from "Autonomous Research Assistant"
to "ARA". Backend, package names, and directory names are unchanged.

## Source of truth

Three screens + one design system doc, imported under
`stitch_ara_research_terminal/`:

- `ara_landing_entry/` — landing + question entry + recent reports
- `ara_live_research_stream/` — three-rail live terminal (plan tree | report | sources/cost)
- `ara_completed_report/` — same shell, static report with quantitative blocks
- `synthesis_mono/DESIGN.md` — "Cognitive Terminal" system

The HTML files are reference implementations (raw Tailwind, Material Symbols), not
code to copy verbatim. The design system doc is authoritative for tokens, type
hierarchy, and the "no lines / tonal stacking / ambient depth" rules.

## Locked decisions

| Topic | Decision | Rationale |
| --- | --- | --- |
| Body / heading font | Geist Sans (already wired) | DESIGN.md names Geist explicitly; Inter in HTML was a Stitch default |
| Mono font | Geist Mono (already wired) | Same — JetBrains Mono in HTML is interchangeable, Geist already loaded |
| Icon library | `lucide-react` (already a shadcn dep) | Material Symbols in HTML is ~300KB font; lucide is tree-shaken SVG |
| Color tokens | Map Stitch Material 3 palette into existing shadcn semantic vars | Less churn than introducing a parallel token system |
| Default theme | Force dark | Stitch palette is dark-only; light mode is out of scope for v1 |
| Side nav on live/completed views | Build now | Part of the terminal aesthetic, visible in Stitch screens |
| Repo / package / dir names | Unchanged | Backend package is already `ara`; only display copy changes |

## Architecture (what changes, what doesn't)

**Unchanged**: routes (`/`, `/r/[reportId]`), component file names, hooks
(`use-research-stream`, `use-history`), lib (`api`, `events`, `types`), SSE event
contract, backend.

**Changed**:

- `app/globals.css` — replace neutral oklch theme with Cognitive Terminal palette;
  remove tri-color blob backdrop, add subtle blue ambient glow.
- `app/layout.tsx` — set `dark` class on `<html>`; update `<title>`/metadata; mount
  new `TopNav`.
- `app/page.tsx` — restructure landing per Stitch (asymmetric whitespace, eyebrow
  + display heading + elevated textarea card + recent reports list).
- All `components/*.tsx` — restyle classes only. No prop or behavior changes
  unless required by the new layout (e.g. side nav state).
- New: `components/top-nav.tsx`, `components/side-nav.tsx`.

## Cognitive Terminal palette → shadcn variable mapping

| Stitch token | Hex | shadcn var |
| --- | --- | --- |
| `surface` | `#131313` | `--background` |
| `surface-container-lowest` | `#0e0e0e` | (added: `--surface-lowest`) |
| `surface-container-low` | `#1c1b1b` | `--card`, `--popover` |
| `surface-container` | `#201f1f` | `--muted` |
| `surface-container-high` | `#2a2a2a` | `--secondary` |
| `surface-container-highest` | `#353534` | `--accent` |
| `primary` | `#b5c4ff` | `--primary` |
| `primary-container` | `#638aff` | (added: `--primary-container` for gradient CTA) |
| `on-surface` | `#e5e2e1` | `--foreground` |
| `on-surface-variant` | `#c3c5d7` | `--muted-foreground` |
| `outline-variant` | `#434654` | `--border` (at 20% opacity per "Ghost Border" rule) |
| `error` | `#ffb4ab` | `--destructive` |

Radius: `--radius` set to `0.375rem` (Stitch `rounded-md`).

## Staging plan (commit per stage, eyeball after stage 4)

1. **Theme & tokens** — `globals.css` rewrite + `layout.tsx` dark default
2. **Brand rename** — display copy in `layout.tsx`, `page.tsx`, `README.md`
3. **TopNav + SideNav** — new components, mounted in `layout.tsx`; SideNav rendered
   conditionally on report routes
4. **Landing restyle** — `page.tsx`, `research-form.tsx`, `history-list.tsx`
5. *(Checkpoint — Shriram reviews in browser before stages 6–7)*
6. **Live view restyle** — `app/r/[reportId]/page.tsx`, `plan-tree.tsx`,
   `report-stream.tsx`, `sources-list.tsx`, `cost-meter.tsx`, `agent-status.tsx`,
   `status-pill.tsx`, `citation.tsx`, `research-live.tsx`
7. **Completed view restyle** — quantitative blocks, COPY/SHARE/PDF actions
8. Verify in browser via `make dev-frontend`

## Out of scope

- Light theme
- Mobile bottom nav (Stitch shows one, but ARA is desktop-first portfolio piece)
- Material Symbols icon font
- Inter font swap
- Backend changes
- Routing / data layer changes
- Auth, history scoping per account (separate spec)
- Vercel deployment (separate spec, blocked on this rebrand)

## Done means

- `make lint` passes (eslint clean on frontend)
- `make dev-frontend` renders landing page that visually matches
  `stitch_ara_research_terminal/ara_landing_entry/screen.png`
- Live and completed views render in Cognitive Terminal palette with the
  three-rail layout
- All "Autonomous Research Assistant" display strings replaced by "ARA"
- No regression in the SSE streaming behavior (existing
  `use-research-stream` + components still wired the same way)
