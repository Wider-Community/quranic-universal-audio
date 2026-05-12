# Phase 6 — Implementation notes

Companion to [`06-public-dashboard.md`](06-public-dashboard.md). The phase doc is the contract — what gets shipped. This doc is the plan — *how*, in what order, against what reuse map, with what tests. Edits here don't change scope; if they do, update the contract first.

Mockups feeding this plan live in [`inspector/frontend/design/`](../../../../inspector/frontend/design/) (worktree `worktree-phase6-dashboard-mockups`). The mockups are reference, not source — Svelte ports happen below.

## Goal

Land the Phase 6 contract through nine small, sequential slices. No big-bang merges. Each slice is independently reviewable and reverts cleanly. Frontend slices run against mocked data first; backend slices wire in real data per their own slice. Existing live UI (Segments tab, Timestamps tab) stays functional throughout — Phase 6 is additive until Slice H removes the Audio tab.

## Pre-flight

Before the first slice lands:

- Decide whether mockups merge to `dev` alongside the first real-code slice, or live on `worktree-phase6-dashboard-mockups` as design reference only. Recommendation: merge mockups + `tokens.css` source into `dev` under `inspector/frontend/design/` so the design folder is a permanent reference + token authority. Component-style ports (modal, picker, etc.) live alongside Svelte components in `lib/`, not in `design/`.
- Confirm the schema-descriptor approach for `ReciterPicker`: built at app startup as a pure function of `/api/static/catalog.json`. No hardcoded `riwayah` / `style` / `source` literals in the picker; the descriptor lists `axes: [{key, label, values, multi?}]`, `searchableFields`, `sortKeys`. Phase 6 phase doc requires this — reaffirm before writing the component.
- Lock the file layout under `inspector/frontend/src/lib/components/picker/` so all subsequent slices reference one location.

## Slice sequence

Nine slices, ordered for forward progress and easy reverts. Each ships behind no feature flag — Phase 6 surfaces are net-new; the existing tab bar gains a new entry without breaking old ones.

### Slice A — Tokens migration + design folder promotion

**Goal.** Port the OKLCH token vocabulary from `design/tokens.css` into the live frontend so subsequent slices can theme components consistently. No visual regression to existing tabs.

**Files.**
- New `inspector/frontend/src/styles/tokens.css` — same content as `design/tokens.css`, tuned to match `base.css`'s sRGB palette in OKLCH (see mockup commit `7f839cbe` token deltas).
- Modify `inspector/frontend/src/main.ts` to import `tokens.css` before `base.css`.
- Promote `design/` from the worktree to `dev` as-is (5 mockups + tokens.css + components.css) so the reference is committed alongside the source.

**Reuse.** `tokens.css` only introduces CSS variables. `base.css` keeps its hex values for now; per-component migrations consume the new tokens incrementally.

**Tests.** Visual smoke — open every tab, confirm no regression. Existing CSS is unchanged.

**Risk.** None structural. Token additions are additive.

---

### Slice B — Public state mapper + minimal public APIs (backend)

**Goal.** Stand up `services/public_state.py::to_public(state_row)` and the read-only endpoints that the dashboard needs. No frontend wiring yet.

**Files.**
- New `inspector/services/public_state.py` — pure mapper, assignee fields stripped, six public buckets per Phase 6 contract.
- New `inspector/routes/public.py` — Blueprint `/api/public`. Endpoints `GET /stats`, `GET /reciters` (paginated, `bucket=`, `search=`, `sort=`, `cursor=`).
- Modify `inspector/app.py` — register the blueprint.
- New `inspector/tests/services/test_public_state.py` — every internal state → expected public bucket, assignee redaction.
- New `inspector/tests/routes/test_route_public_stats.py` + `test_route_public_reciters.py`.

**Reuse.** Reads from `services/state.py::all_rows()` + `services/catalog.py::get_reciter()` — no new state machinery.

**Caching.** `Cache-Control: public, max-age=30` per Phase 6 contract.

**Out of slice.** `/api/public/reciter/<slug>` (Slice E) and `/api/public/activity` (Slice F).

---

### Slice C — ReciterPicker primitive (frontend)

**Goal.** The taxonomy-agnostic, reusable picker that powers segments-tab, dashboard rows, the bottom player chip, and (later) admin bulk actions.

**Files.**
- New `inspector/frontend/src/lib/components/picker/ReciterPicker.svelte` — the modal + inline-filter shell. Props: `{reciters, schema, mode: 'modal' | 'inline', initialFilter?, multiSelect?, onSelect}`.
- New `inspector/frontend/src/lib/components/picker/PickerHeader.svelte` — title + close + search field with kbd hint.
- New `inspector/frontend/src/lib/components/picker/PickerStateTabs.svelte` — horizontal state pill row.
- New `inspector/frontend/src/lib/components/picker/PickerFilterRail.svelte` — 220px secondary filter rail.
- New `inspector/frontend/src/lib/components/picker/PickerRow.svelte` — single reciter row with inline-expand affordance.
- New `inspector/frontend/src/lib/components/picker/DeliveryPicker.svelte` — inline delivery sub-picker inside a reciter row.
- New `inspector/frontend/src/lib/components/picker/PickerFooter.svelte` — keyboard hints + cancel.
- New `inspector/frontend/src/lib/catalog/schema.ts` — pure function `buildSchemaDescriptor(catalog)`; emits `{axes, searchableFields, sortKeys}`.
- New `inspector/frontend/src/lib/api/public-reciters.ts` — fetch + cache `/api/public/reciters`.

**Reuse.**
- **Faceted filter logic** — port the faceted-count semantics from `tabs/segments/components/history/HistoryFilters.svelte` (lines 39–141). Extract into `lib/components/picker/facets.ts` as a pure function so both `HistoryFilters` and the picker share the same code path later (Slice I cleanup).
- **Search normalization** — reuse the Arabic-aware substring matcher in `lib/components/SearchableSelect.svelte` (lines 35–52). Extract into `lib/utils/fuzzy-match.ts` so both `SearchableSelect` and the picker share one implementation.
- **Keyboard nav** — same pattern as `SearchableSelect.svelte` (lines 82–103): ↑↓ cycle, ↵ select, Esc close, `/` focus. Extract into `lib/utils/keyboard-nav.ts`.

**Wiring.** No mount yet. Stands alone with a Storybook-style harness in `lib/components/picker/__demo__/PickerDemo.svelte` (gated behind dev-only route or a manual mount).

**Tests.**
- Unit: `facets.ts` semantics (faceted count recompute, empty-state handling) — port the 7-case `HistoryFilters` test suite shape.
- Unit: `fuzzy-match.ts` against the Arabic-diacritic normalization corpus that `SearchableSelect` already exercises.
- Component: keyboard nav, multi-delivery inline-expand, single-delivery commit-on-click, search filter effects.

**Out of slice.** Mounting the picker anywhere; that's Slices D, G, H.

---

### Slice D — Dashboard tab + last-tab persistence

**Goal.** New `/dashboard` route shipped as the 4th tab and default landing surface for first-time visitors.

**Files.**
- New `inspector/frontend/src/tabs/dashboard/DashboardTab.svelte` — the orchestrator.
- New `inspector/frontend/src/tabs/dashboard/components/Standfirst.svelte` — magazine-style intro with clickable count shortcuts.
- New `inspector/frontend/src/tabs/dashboard/components/FilterRail.svelte` — left rail, reuses `PickerFilterRail` primitive from Slice C.
- New `inspector/frontend/src/tabs/dashboard/components/CatalogTable.svelte` — reciter-primary table with inline-expandable deliveries; reuses `PickerRow` for row chrome.
- New `inspector/frontend/src/tabs/dashboard/components/AvailableToClaimStrip.svelte` — claim cards strip above the table.
- New `inspector/frontend/src/tabs/dashboard/stores/dashboard-state.ts` — active filter sets, sort, pagination cursor.
- New `inspector/frontend/src/lib/stores/last-tab.ts` — `inspector.last_tab` localStorage helper (read on boot, write on every tab change).
- Modify `inspector/frontend/src/App.svelte` — add Dashboard as the 4th tab; default to it when `localStorage.inspector.last_tab` is absent.

**Reuse.**
- Public state pills, state colors, chips, table primitives from Slice A's `tokens.css` + a new `lib/components/state-pill/StatePill.svelte`.
- The activity rail is in this surface but its content lives in Slice F. Render an empty placeholder ("No recent activity") until Slice F lands.

**Wiring.** `/api/public/stats` + `/api/public/reciters` from Slice B. Cache headers respected via `fetch` with `cache: 'default'`.

**Tests.**
- Vitest unit: count-shortcut clicks scope the catalog correctly.
- Vitest unit: faceted filter recompute matches the mockup's JS (port the mockup test surface).
- Playwright smoke on dev Space: anonymous visitor lands on Dashboard, sees catalog, no claim CTAs.

**Out of slice.** Activity rail content (Slice F), bottom player (Slice G), reciter detail navigation (Slice E).

---

### Slice E — Reciter detail page (`/reciter/<slug>`)

**Goal.** Public detail page reachable from any catalog row.

**Files.**
- New `inspector/frontend/src/tabs/dashboard/ReciterDetail.svelte` — full-page surface.
- New `inspector/frontend/src/tabs/dashboard/components/DeliveriesTable.svelte` — Smithsonian-density mono table; slug never exposed.
- New `inspector/frontend/src/tabs/dashboard/components/Timeline.svelte` — vertical state timeline; state-keyed dot colors.
- New `inspector/frontend/src/tabs/dashboard/components/FactsList.svelte` — key/val list; rows with null values omitted entirely (no "Unknown" / "—" placeholders).
- New `inspector/services/public_state.py::detail(slug)` extension — assembles the full detail payload from state + catalog + audit log (timeline subset).
- New `inspector/routes/public.py::reciter_detail` — `GET /api/public/reciter/<slug>`.
- Modify `CatalogTable.svelte` from Slice D — row click navigates to `/reciter/<slug>` rather than (re)opening the picker.

**Reuse.** Reuses state pill, coverage chip, primitives from Slices A + D.

**Subscribe CTA.** Renders disabled with hint "coming soon". No wiring; Phase 7/8 will decide.

**Tests.**
- Backend: detail payload shape, timeline event filtering (6-event allowlist), slug 404 handling.
- Frontend: null fact rows are absent from the DOM; multi-mushaf reciter shows `Riwayah(s)` plural label with `·`-separated values.

---

### Slice F — Public activity feed

**Goal.** Activity rail on the dashboard wires to the audit log via a redacted feed.

**Files.**
- New `inspector/services/public_activity.py` — reads `<bucket>/audit/<YYYY>-<MM>.jsonl`, filters to the 6 allowlisted event types per Phase 6 contract, transforms to feed cards. Cursor pagination.
- New `inspector/routes/public.py::activity` — `GET /api/public/activity?limit=50&cursor=...`.
- New `inspector/tests/services/test_public_activity.py` — redaction check (inject `claim.force_released` event, assert it does not surface).
- Modify `DashboardTab.svelte` — mount `ActivityRail.svelte` with real data.
- New `inspector/frontend/src/tabs/dashboard/components/ActivityRail.svelte` — vertical event stream, 30s poll with Page Visibility pause.

**Reuse.** Activity item visual primitives from `design/components.css` ported.

**Cache.** `no-store` per Phase 6 contract.

**Risk.** Naive per-request scan of `audit/<YYYY>-<MM>.jsonl` may become slow at 10× scale. Phase 6 contract notes a deferred mitigation (capped-tail derived file). Skip for now; revisit if measured.

---

### Slice G — Bottom player + audio-tab decommission

**Goal.** Persistent bottom player on the Dashboard tab, replacing the Audio tab.

**Files.**
- New `inspector/frontend/src/lib/components/player/BottomPlayer.svelte` — the shell.
- New `inspector/frontend/src/lib/components/player/PlayerMetaChip.svelte` — left side; opens the same `ReciterPicker` from Slice C (modal mode).
- New `inspector/frontend/src/lib/components/player/PlayerControls.svelte` — prev / -15s / play / +15s / next.
- New `inspector/frontend/src/lib/components/player/PlayerProgress.svelte` — scrub bar + times.
- New `inspector/frontend/src/lib/components/player/SurahPopover.svelte` — wraps the existing `SearchableSelect.svelte` for surah selection; format matches `surahOptionText(num)` (num · EN · AR). No new fuzzy logic; reuse `SearchableSelect` directly.
- New `inspector/frontend/src/lib/components/player/SpeedPopover.svelte` — small menu (0.5× / 0.75× / 1.0× / 1.25× / 1.5× / 2.0×).
- New `inspector/frontend/src/lib/stores/player-context.ts` — `{currentReciter, currentDelivery, currentSurah, isPlaying, position, speed}`.
- Modify `DashboardTab.svelte` — mount `BottomPlayer` at app shell, scoped to Dashboard route.
- Modify `App.svelte` — remove Audio tab from the tab bar.
- Modify `inspector/frontend/src/tabs/audio/` — archive the directory. Code is dead but kept for one release as fallback.

**Reuse.**
- `lib/components/SearchableSelect.svelte` for the surah popover. No new search code.
- `lib/utils/surah-info.ts` for surah option formatting.
- Existing audio playback infrastructure under `lib/playback/` (audio-port, format detection, etc.) — `BottomPlayer` drives it the same way the current Audio tab does. The migration is *who* drives the playback element, not *how*.

**Player mount semantics.** Mounts when `player-context.ts` has a non-null `currentReciter`; persists across navigation within Dashboard tab; hidden when user navigates to Segments or Timestamps tab. Listen CTA on any catalog row or detail page seeds the context.

**Tests.**
- Component: SurahPopover correctly delegates filtering to `SearchableSelect`.
- Component: SpeedPopover commits selection + closes.
- Integration: clicking PlayerMetaChip opens ReciterPicker; selecting a reciter updates player-context.
- Playwright smoke: listen flow end-to-end on dev Space.

**Risk.** Audio tab decommission is destructive. Mitigation: ship player on Dashboard for ≥2 days before merging the App.svelte tab-bar removal. Two separate commits inside this slice.

---

### Slice H — Segments-tab context strip + dropdown removal

**Goal.** Replace the segments-tab reciter dropdown with the reciter context chip + browse-by-state strip; clicking either opens the same `ReciterPicker`.

**Files.**
- New `inspector/frontend/src/tabs/segments/components/header/ReciterContextChip.svelte` — clickable chip at the top of the Segments tab; opens picker in modal mode.
- New `inspector/frontend/src/tabs/segments/components/header/BrowseByStateStrip.svelte` — horizontal pill row (Your active claim · Available · Under review · Published); each opens the picker pre-filtered.
- Modify `inspector/frontend/src/tabs/segments/SegmentsTab.svelte` — replace the existing reciter dropdown with the chip + strip. Existing chapter dropdown (the surah dropdown) stays — that one is the reusable `SearchableSelect` and we keep it.

**Reuse.**
- `ReciterPicker` (modal mode) from Slice C.
- `SearchableSelect.svelte` for chapter selection stays as-is.

**Tests.**
- Component: ReciterContextChip opens picker on click; selecting a different reciter updates segments-tab context + URL.
- Snapshot: removed dropdown is gone from the DOM tree.

---

### Slice I — Last polish + acceptance sweep

**Goal.** Close out the Phase 6 contract.

**Files.**
- Modify `inspector/frontend/src/App.svelte` — add the `Open admin →` link in the masthead area for signed-in maintainer+.
- Modify `inspector/frontend/src/lib/components/picker/facets.ts` — refactor `HistoryFilters.svelte` to consume the shared `facets.ts` extracted in Slice C (closes the "two copies of faceted logic" debt).
- Modify `inspector/frontend/src/lib/components/SearchableSelect.svelte` — refactor to consume the shared `fuzzy-match.ts` extracted in Slice C.
- New `inspector/frontend/src/tests/playwright/phase6-acceptance.spec.ts` — every acceptance criterion from `06-public-dashboard.md` mapped to one test.

**Tests.** Run the full acceptance suite against the dev Space. Sign off on the phase contract.

---

## Reuse map

| Existing | Where it's reused |
|---|---|
| `lib/components/SearchableSelect.svelte` | Slice G `SurahPopover` (wraps it); Slice I refactors it to consume shared `fuzzy-match.ts`. |
| `lib/utils/surah-info.ts` + `surahOptionText()` | Slice G surah popover format. |
| `tabs/segments/components/history/HistoryFilters.svelte` faceted logic | Slice C extracts into `lib/components/picker/facets.ts`; Slice I refactors `HistoryFilters` to consume the extracted copy. |
| `services/state.py::all_rows()` | Slice B `public_state.to_public_list()`. |
| `services/catalog.py::get_reciter()` | Slice B + E. |
| `services/audit.py` | Slice F `public_activity.py`. |
| `tokens.css` (from design folder) | Slice A promotes to `src/styles/`. |
| Audio playback infrastructure under `lib/playback/` | Slice G `BottomPlayer` drives the same primitives the Audio tab currently drives. |
| `_meta.audio_source` peek and Audio tab routes | Slice G archives; Slice I `removes after stability window`. |

## Token migration strategy

Phase 6 introduces OKLCH tokens. Existing live CSS (`base.css`, `components.css`, `segments.css`, etc.) keeps sRGB hex values. New code under `tabs/dashboard/`, `lib/components/picker/`, `lib/components/player/` consumes tokens directly. Tokens are sRGB-accurate translations of the existing palette — see `design/tokens.css` for the mapping.

A later non-Phase-6 cleanup pass migrates `base.css` to tokens. Out of scope here.

## Testing strategy

Per-slice unit and component tests above. The acceptance sweep in Slice I covers the contract end-to-end. Three test surfaces:

1. **Vitest** — pure logic (facets, fuzzy match, public state mapping, last-tab persistence).
2. **Vitest + @testing-library/svelte** — components (picker keyboard nav, popover open/close, row click → select, modal dismiss).
3. **Playwright on the dev Space** — integration smoke for each public-facing flow (anonymous browse, contributor claim from Dashboard row, listen via bottom player, reciter detail navigation, segments-tab reciter switch).

No Phase 6 endpoint ships without a route test. No Phase 6 component ships without a component test.

## Risks

- **`/api/public/activity` cost.** Naive per-request audit scan; deferred mitigation per Phase 6 contract. Watch p99 once Slice F is live.
- **Audio tab decommission.** Slice G two-commit split mitigates. If reverted, the tab returns from archive.
- **Token migration not happening together with this phase.** Existing CSS coexists with tokens. Inconsistent border / spacing tokens across surfaces possible; visual review at Slice I should catch.
- **ReciterPicker overuse.** Picker is reused by segments-tab, dashboard, player, and (later) admin bulk. Risk: it grows props to satisfy every call site. Mitigation: schema descriptor + small props surface in Slice C is load-bearing; reject prop additions in Slices D/G/H without explicit picker-config review.
- **Public activity injection regression.** The 6-event allowlist must be tight. Test injects a `claim.force_released` event and asserts it does not surface; keep this in the per-PR check, not only the Phase 6 acceptance sweep.

## Open questions

- **Bottom-player auto-mount.** Mockup default: player mounts when player-context has a non-null `currentReciter`; hidden until first Listen click. Confirm before Slice G.
- **Browse-by-state strip behavior on segments tab.** Mockup default: click opens picker pre-filtered. Alternative: click cycles the current reciter through the bucket without opening the picker. Confirm before Slice H.
- **`/admin` link visibility in Phase 6.** Phase 7 wires the route. Slice I renders the link only for maintainer+ — does it 404 cleanly today (before Phase 7), or 404 silently with a redirect? Recommendation: 404 cleanly; user knows the route is coming.
- **CDN front (D12).** Phase 6 ships without; measurement during Slice D + E will tell us if needed before Phase 7.

## Out of scope (carried)

Anchored against the phase contract:

- Admin dashboard panels (Phase 7).
- Bucket data hygiene workflow (Phase 7).
- Reciter Requests Space decommission (Phase 7).
- "Your contributions" personal page (D10, deferred).
- Notifications fan-out (D3, deferred).
- Slug rename support (D9, deferred).
- SSE for cross-tab sync (D8, deferred).
- Inspector-native reciter-request submission (D14, deferred — Subscribe CTA ships as disabled slot).

## Sequencing summary

```
A   tokens migration                       (independent)
B   public state + APIs                    (depends on A's tokens for view-side; backend-only itself)
C   ReciterPicker primitive                (depends on A; needs B for live data wiring but works against mocks)
D   Dashboard tab                          (depends on B + C)
E   Reciter detail                         (depends on B + D)
F   Public activity feed                   (depends on D)
G   Bottom player + audio decommission     (depends on C, D)
H   Segments-tab context strip             (depends on C)
I   Polish + acceptance sweep              (depends on A–H)
```

Frontend slices A, C, D can prototype against mocks before B ships. Backend slices B, F can land in parallel with C, D. Slice I closes the contract.
