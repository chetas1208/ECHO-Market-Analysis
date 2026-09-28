# D1 UI compliance audit (UI.md) — 2026-09-20

Setup: db `audit_ui` (alembic head + seed, 1 event `evt_mock_hormuz_naval_001`), API 127.0.0.1:8111 (CORS 3111), `next dev` :3111 with NEXT_PUBLIC_API_URL=http://localhost:8111. Playwright headless chromium, viewports 1440x900 and 375x800. Servers killed by PID (2242698, 2242773), db dropped.
Scripts/screens (scratchpad): ui_audit.py (baseline), ui_audit2.py (post-repair), ui_states.py, d1_open_{1440,375}.png, d1_before_*.png.

## Results (post-repair unless marked)

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Max 5 primary tabs | PASS | drawer nav = Dashboard, Events, Graph, Forecasts, Strategy; no others |
| 2 | No horizontal tabs / duplicate primary nav / permanent sidebar | PASS | 0 `a` in `.topbar`; with drawer closed 0 primary links visible; `aside` visibility:hidden + inert when closed |
| 3 | Hamburger opens OVERLAY vertical drawer | PASS | aside `position:fixed`, x=0, w=304px @1440 (21%), 337.5px = 90vw @375, z 40 |
| 4 | Content does NOT shift | PASS | content x [28,28,28] before/after @1440, [16,16,16] @375; `.main` left=0 |
| 5 | Backdrop dims AND blurs | PASS | `.scrim` bg rgba(2,8,18,0.55), computed `backdrop-filter: blur(8px)`; drawer itself `backdrop-filter: none`; opacity transition .2s ease-out; drawer transform .2s ease-out |
| 6 | Close: hamburger position, close button, backdrop, Esc, item select | PASS (all 5) | 1440 + 375; item select routes to /forecasts and closes |
| 7 | Focus: trap while open, return to hamburger on close | PASS (repaired) | 14 Tab + 14 Shift+Tab stay in drawer; focus = "Open navigation" after every close method |
| 8 | Body scroll locked / background inert when open | PASS (repaired) | body overflow hidden (restored after), `.main` inert |
| 9 | Top bar stays visible | PASS (repaired) | sticky, top=0 after scrollY=300 |
| 10 | No horizontal page scroll | PASS (repaired) | sw==iw all routes both viewports (was 380>375 on `/` @375) |
| 11 | No unnecessary vertical scroll | PARTIAL | see below |
| 12 | Event from backend, not hardcoded | PASS | no "Hormuz"/evt id string in app source (outside tests); DB title changed to BACKEND-PROBE-TITLE-XYZ appears on `/`, `/events`, `/events/:id`; requests to :8111 `/api/v1/events`, `/events/:id`, `/ready` |
| 13 | Loading state | PASS | delayed API: `role=status aria-busy` + 2 skeleton cards on /events |
| 14 | Empty state | PASS | `[]` response: "No events returned…" (/events), "No active events / No forecast opportunities" (/) |
| 15 | Error state | PASS | 503 envelope and network abort on `/`, `/events`, `/events/:id`: message + code/http/request_id + Retry; 404 detail shows not_found |
| 16 | Console errors | PASS | none on any route/viewport; only expected "Failed to load resource" when API deliberately failed |

## Violations found and repaired (frontend/, minimal)
1. Closed drawer links reachable by Tab / rendered offscreen only; now `inert` + `visibility:hidden` while closed (`components/Sidebar.tsx`, `app/globals.css`).
2. No focus trap, no focus-return, page scrollable and background focusable while open: added in `components/AppShell.tsx` (Tab wrap, initial focus on active item, Esc, body scroll lock with scrollbar-compensation, `inert` on page wrapper, focus back to hamburger).
3. Two hamburgers (one hidden inside aside, topbar button swapped icon under scrim, unclickable): now single opener in top bar (always "Open navigation"); drawer has its own "Close navigation" button positioned exactly over the hamburger (28px/16px gutter) so clicking the hamburger spot closes.
4. Mobile drawer was 320px = 85.3vw (spec 88–92vw §54 / 85–90vw §3.2): now 90vw at <=700px.
5. Top bar scrolled away: made sticky, full-bleed, opaque, below scrim (z 20 < 30).
6. Unnecessary 64px/34px scroll on Events, Graph, Forecasts, Strategy (page `min-height: calc(100vh - 64px)` + main padding): removed in 5 `*.module.css`; now 0px overflow on Graph/Forecasts/Strategy/Events@1440.
7. Horizontal overflow on `/` @375 (event-confidence 91% pushed grid): `minmax(0,1fr)` on `.dashboard-events a`.
8. Stale rail/push CSS (`--rail-w` margin, desktop push at >=900px) removed; `<main>` no longer wraps the header (header + `<main id=main>` inside `.main` wrapper).
9. New tests `components/__tests__/AppShell.test.tsx` (5 tests: five destinations only, inert states, Esc + focus return, all close paths, Tab trap).
Verification: `pnpm typecheck && pnpm lint && pnpm test` -> clean, 10 files / 75 tests pass. Full Playwright re-run: all PASS above, 0 console errors.

## Open / not repaired (out of nav-shell scope)
- Vertical scroll is content-driven, not a layout bug: Dashboard 1242px @1440x900 (+342) and 2294px @375; Events @375 +89; Event Detail +61 @1440, +344 @375 (raw JSON blocks). Dashboard does not fit "one screen" per UI.md 9; needs dense-layout redesign (row 2 leaves an empty column hole; Accuracy spans 2 cols).
- Top-bar status shows `LIVE` (green) whenever /ready is ok although the only data is `MOCK / FIXTURE` seed; violates UI.md 45/63 (LIVE only if live sources healthy; DEMO DATA labelling). Suggest DEMO/PAPER state.
- Drawer footer "Data sources" / "Model status" are inert text, no Settings/Docs/Sign out; avatar has no profile menu (UI.md 3.3, 74).
- Error states do not say whether existing data remains valid (UI.md 43). Dashboard "Events returned" metric etc. show "—" honestly (no fabricated values: good).
- Routing: `/dashboard` route from UI.md 55 is `/` here; `/settings`, `/events/shocks/:id`, `/strategy/*` sub-routes absent.
- Dev-server note: Next dev issues one extra self-reload on first load after edits (HMR), can make a scripted `wait_for_selector` flaky; not an app bug.

Status: nav/drawer rules COMPLIANT after repair; layout-scroll on Dashboard/Detail and LIVE-label semantics open.
