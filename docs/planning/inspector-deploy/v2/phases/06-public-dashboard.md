# Phase 6 — Public dashboard + reusable reciter picker

> Public landing surface. A new `/dashboard` tab (default on first visit, last-visited persisted) serves anonymous + signed-in users a unified view: hero stats, available-to-claim strip, recent activity, all-reciters table. A taxonomy-agnostic `ReciterPicker` ships and replaces the segments-tab dropdown.

**Status:** done (2026-05-13)
**Depends on:** Phase 5 (Publish pipeline) complete; reciter taxonomy / catalog schema refactor landed out-of-band
**Blocks:** Phase 7

## Goal

After this phase, Inspector opens to the dashboard tab by default, with `inspector.last_tab` in `localStorage` persisting subsequent navigation. The dashboard renders the six-bucket public taxonomy via a display-layer mapping over internal state — assignee identity never leaves the backend on any `/api/public/*` endpoint. A reusable `ReciterPicker` component, consuming a runtime schema descriptor, powers both the dashboard's filter UI and the segments-tab reciter selector. Public per-reciter detail pages (`/reciter/<slug>`) expose audio sample + state timeline + Listen/Review CTAs.

## Deliverables

### Public state display layer

- [ ] `inspector/services/public_state.py::to_public(state_row)` — pure mapping internal row → `{bucket, label, can_claim}` per the six-bucket taxonomy
- [ ] Six public buckets: `available_for_request`, `requested`, `available_for_review`, `under_review`, `publishing`, `published`
- [ ] `under_review (marked_ready=1)` collapses with `awaiting_timestamps` into `publishing` (invisible internal transition)
- [ ] Assignee fields (`assignee_hf_id`, `assignee_login`) stripped from every `/api/public/*` response

### Public API surface

- [ ] `GET /api/public/stats` — counts per public bucket
- [ ] `GET /api/public/reciters?bucket=...&search=...&sort=...&cursor=...` — paginated, assignee-stripped reciter list; sort options: `recent` (default), `available_first`, `recently_published`, `alphabetical`
- [ ] `GET /api/public/reciter/<slug>` — detail payload: catalog metadata, public state, audio sample URL, state timeline (derived from audit log filtered to public events for this slug)
- [ ] `GET /api/public/activity?limit=50&cursor=...` — paginated public activity feed; backed by `services/public_activity.py` which reads `<bucket>/audit/<YYYY>-<MM>.jsonl`, filters to user-facing events, transforms to feed cards
- [ ] All public endpoints filter `visibility == 'public'` (skip `discarded` / `archived`)

### Public activity feed (6 event types only)

- [ ] `catalog.reciter_added` (no audio yet) → "Available for request: *X*"
- [ ] State enters `awaiting_alignment` → "*X* has been requested"
- [ ] State enters `awaiting_review` (alignment complete) → "*X* is now available for review"
- [ ] `reciter.claimed` → "*X* is now under review" (no assignee)
- [ ] `reciter.marked_ready` → "*X* is being published"
- [ ] `reciter.timestamps_completed` → "*X* is now published"
- [ ] All other audit events (`reciter.released`, `reciter.unmarked_ready`, `reciter.published` intermediate, `claim.force_released`, `claim.reassigned`, `admin.force_set_state`, `reciter.merge_rejected`, `reciter.discarded`, etc.) redacted from public feed

### Dashboard frontend

- [ ] New top-level `/dashboard` route + nav tab; default tab when no `inspector.last_tab` in `localStorage`
- [ ] `inspector.last_tab` written on every top-level tab change; read on app boot
- [ ] Hero stats strip: `N published · N publishing · N under review · N available to claim · N requested · N available for request` — each clickable, filters the table below
- [ ] "Available to claim" strip — top N (~5) `available_for_review` rows; claim CTA for signed-in contributors; sign-in prompt for anonymous
- [ ] Recent activity feed — last 50 events, cursor-paginated, polls every 30 s while tab visible
- [ ] All-reciters table — taxonomy-agnostic filters via `ReciterPicker`; columns: name, public state pill, riwayah/source (sourced from schema descriptor), updated-ago, edit-count, claim CTA (when applicable)
- [ ] "Your active claim" pin at top (signed-in user with active claim)
- [ ] "Open admin →" link (signed-in maintainer+)

### Public reciter detail page

- [ ] `/reciter/<slug>` SPA route
- [ ] Renders: name + grouping metadata (from schema descriptor), public state pill, audio sample player (reuses existing audio component), state timeline from audit log
- [ ] CTAs: **Listen** (anchor to audio player) for `published`; **Review** (deep link into segments tab for that slug) for `available_for_review` (signed-in) or `under_review` (signed-in, when they're the assignee)
- [ ] Reciter card click on dashboard → detail page (NOT direct to segments tab)

### Reusable `ReciterPicker` component

- [ ] `inspector/frontend/src/lib/components/ReciterPicker.svelte` — props: `{reciters, schema, mode: 'single'|'multi', initialFilter, onSelect}`
- [ ] Taxonomy-agnostic: consumes a schema descriptor `{axes: [{key, label, values, multi?: bool}], searchableFields: [...], sortKeys: [...]}` — no hardcoded axis names (no `riwayah` / `source` / `qira'ah` literals in the component)
- [ ] Two modes: inline-filter (dashboard) + modal-trigger (segments-tab dropdown replacement)
- [ ] Schema descriptor built at app startup by `inspector/frontend/src/lib/catalog/schema.ts` as a pure function of `/api/static/catalog.json`; re-derives on catalog change
- [ ] Segments-tab reciter selector swap: existing reciter dropdown removed; opens `ReciterPicker` in modal single-select mode
- [ ] No remaining bare `<select>`-on-reciters anywhere in `inspector/frontend/src/`

### Caching

- [ ] `Cache-Control: public, max-age=30` on `/api/public/stats` + `/api/public/reciters` (matches the 30 s poll cadence)
- [ ] `Cache-Control: public, max-age=60` on `/api/public/reciter/<slug>` (detail pages drift slowly)
- [ ] `Cache-Control: no-store` on `/api/public/activity` (cursor-paginated; freshness matters)

## Out of scope

- Admin dashboard panels, admin actions UI, system health, contributor activity (Phase 7)
- Bucket data hygiene workflow (Phase 7)
- Reciter Requests Space decommission + `forward-to-inspector.yml` removal (Phase 7)
- "Your contributions" personal page (D10 — deferred)
- Inspector-native reciter request submission (D14 — deferred; Reciter Requests Space remains the intake until Phase 7)
- Notifications fan-out (D3)
- Slug rename support (D9)
- Server-Sent Events for live activity feed (D8 — deferred; 30 s poll is enough)

## Acceptance criteria

- [ ] Anonymous visitor lands on `/dashboard` by default; sees stats strip, available-to-claim strip, activity feed, all-reciters table — no claim buttons, no assignee names, no `Open admin →` link
- [ ] After clicking the Segments tab and refreshing, the same user lands on Segments (last-visited persisted)
- [ ] Signed-in contributor sees claim buttons on `available_for_review` rows; if they hold a claim, "Your active claim" pinned at top
- [ ] Signed-in maintainer additionally sees `Open admin →` link in the dashboard header
- [ ] Public state pill matches the six-bucket taxonomy on every public surface; no internal state names (`catalogued`, `awaiting_review`, `completed`) leak to any `/api/public/*` response
- [ ] `(under_review, marked_ready=1)` and `awaiting_timestamps` both render as **Publishing** publicly; the internal transition is invisible
- [ ] `grep -r "assignee" inspector/services/ | grep -i public` finds redaction logic; no `assignee_*` keys present in `curl /api/public/reciters | jq` output
- [ ] Activity feed surfaces only the six allowed event types; injecting a `claim.force_released` audit entry does not appear in the feed
- [ ] Public detail page state timeline shows ≤ 6 transitions sourced from audit log
- [ ] `ReciterPicker` renders against the live catalog schema descriptor; segments-tab reciter selector uses it in modal single-select mode
- [ ] No remaining bare `<select>`-on-reciters in the frontend (`grep -rn '<select' inspector/frontend/src/ | grep -i reciter` returns nothing)
- [ ] p99 cold `/dashboard` load ≤ 800 ms; warm ≤ 50 ms
- [ ] p99 `/api/public/activity?limit=50` ≤ 250 ms

## Verification

```bash
SPACE=https://hetchyy-quranic-inspector-dev.hf.space

# Default-tab + last-visited (manual; in browser)
# 1. Fresh profile → lands on /dashboard
# 2. Click Segments → reload → lands on Segments
# 3. Clear localStorage → reload → lands on /dashboard

# Public stats
curl -fsS $SPACE/api/public/stats | jq
# Expect keys: available_for_request, requested, available_for_review, under_review, publishing, published

# Assignee-leak check
curl -fsS $SPACE/api/public/reciters | jq '[.[] | keys] | add | unique' \
  | grep -E '"assignee|"login' && echo "FAIL: assignee leak" || echo "OK"

# Activity feed event-type allowlist
curl -fsS "$SPACE/api/public/activity?limit=200" \
  | jq '[.events[].type] | unique' \
  | jq 'all(. as $t | ["reciter.added","reciter.requested","reciter.available_for_review","reciter.under_review","reciter.publishing","reciter.published"] | contains([$t]))'
# Expect: true

# Public state pill — no internal name leaks
curl -fsS $SPACE/api/public/reciters | jq '[.[].state] | unique' \
  | jq 'all(. as $s | ["available_for_request","requested","available_for_review","under_review","publishing","published"] | contains([$s]))'
# Expect: true

# Public detail page
curl -fsS $SPACE/api/public/reciter/saad_al_ghamdi | jq '{state, label, timeline_len: (.timeline | length)}'

# ReciterPicker swap discipline
grep -rn 'ReciterPicker' inspector/frontend/src/ | head
grep -rn '<select' inspector/frontend/src/ | grep -i reciter
# Expect: empty (no bare select-on-reciters)

# Cache headers
curl -fsSI $SPACE/api/public/stats         | grep -i cache-control  # public, max-age=30
curl -fsSI $SPACE/api/public/activity      | grep -i cache-control  # no-store
curl -fsSI $SPACE/api/public/reciter/saad_al_ghamdi | grep -i cache-control  # public, max-age=60
```

## Risks

- **Audit log scan cost for activity feed** — naive per-request scan of `<bucket>/audit/<YYYY>-<MM>.jsonl` is fine at current volume but degrades at 10× scale. Mitigation: derive `<bucket>/audit/public_recent.json` (capped tail) on every audit write; defer until measured.
- **Schema-descriptor drift** — `ReciterPicker` reads a runtime schema descriptor; when the catalog refactor lands, the descriptor must update without UI churn. Mitigation: build it as a pure function of catalog JSON. Refinement of this doc happens after the refactor lands, not before.
- **Activity feed redaction completeness** — easy to ship an internal event that surfaces publicly. Verification step injects a `claim.force_released` and asserts it does not appear. Add this to the per-PR test suite.
- **Default-tab regression for power users** — returning users with no localStorage entry land on dashboard, which may surprise contributors who expect Segments. The `inspector.last_tab` write-on-every-nav covers it. Document in runbook.
- **Detail page audio bandwidth** — `/reciter/<slug>` Listen CTA reuses the segments-tab audio component; cold audio fetch per detail-page open is the same as today. Acceptable.

## Reference

- [`phase-6-implementation-notes.md`](phase-6-implementation-notes.md) — slice-by-slice implementation plan, reuse map, token migration strategy, testing strategy
- Mockups (high-fi, design exploration) — [`inspector/frontend/design/`](../../../../inspector/frontend/design/) (5 HTML files + shared tokens + components)
- [`inspector-state-management.md`](../inspector-state-management.md) §4 — internal state machine + events feeding the public mapping
- [`inspector-admin-perms.md`](../inspector-admin-perms.md) §6 — admin dashboard panel shapes (Phase 7 extends Phase 6 widgets)
- [`inspector-deployment-plan.md`](../inspector-deployment-plan.md) §4 — auth surface (signed-in claim CTA behavior)
- [`inspector-data-storage.md`](../inspector-data-storage.md) §8 — audit log layout (source for activity feed + detail-page timeline)

## Outcomes

Shipped 2026-05-13 in twelve sequential slices on `dev` (commits `2d94bb40` → `66380f6b`). Tab order is now **Dashboard · Timestamps · Segments**; Audio tab decommissioned.

**Public APIs:** `/api/public/{stats, reciters, reciter/<id>, activity}`. All assignee fields stripped at the service layer (`services/public_state.py`, `services/public_activity.py`); slug appears only as an internal ID, never rendered. Reciter-list `limit` cap is 500 (raised from 200) so the dashboard fetches the full catalog in one round trip.

**Six-bucket taxonomy** computed at the reciter level: `available_for_request · requested · available_for_review · under_review · publishing · published`. `primary_bucket` = most-progressed across the reciter's deliveries. Mutually exclusive in `/stats`. Internal states `UNDER_REVIEW + marked_ready` and `AWAITING_TIMESTAMPS` both collapse to `publishing`.

**Activity feed allowlist (`services/public_activity.py`):** `catalog.added`, `reciter.alignment_completed`, `reciter.claimed`, `reciter.marked_ready`, `reciter.timestamps_completed`, plus state transitions into `awaiting_alignment` (surface as "requested"). Every other audit event — `claim.force_released`, `claim.reassigned`, `admin.force_set_state`, `reciter.discarded`, role changes, unmarked-ready, intermediate publishes — is redacted before reaching the route layer.

**Shared utilities** (`inspector/frontend/src/lib/utils/`): `fuzzy-match.ts` (Arabic-normalizing matcher, single canonical impl — `SearchableSelect` consumes it), `facets.ts` (sibling-axis count semantics), `visible-poll.ts` (Page Visibility-aware polling with resolve-time discard), `relative-time.ts`. Backend twin: `services/search_normalize.py` for symmetric server-side search.

**Reusable primitives** (`inspector/frontend/src/lib/components/`): `StatePill`, `CoveragePill`, `FilterPill`, `ReciterRow`, `DeliveriesTable`, `Modal` (focus-trap + body-scroll-lock).

**ReciterPicker** (`inspector/frontend/src/lib/components/picker/`): modal + inline modes; schema-descriptor-driven from `buildSchemaDescriptor(reciters)` so no taxonomy literals exist in picker code; powers Dashboard secondary rail, segments-tab chip, and BottomPlayer chip. `onSelect` contract emits `{kind: 'reciter', reciter, delivery: Delivery | null}` — `null` only for 0-delivery (`requested` / `available_for_request`) rows.

**Dashboard tab** (`inspector/frontend/src/tabs/dashboard/`): default first-time landing surface. Six centered bucket-count cards (Standfirst), faceted filter rail, `AvailableToClaimStrip` (top-5), `CatalogTable` with inline delivery expansion, `ActivityRail` polling at 30 s while visible. List ↔ detail toggle uses the App-shell `hidden` pattern at the view level — back-navigation preserves filter state because both views stay mounted.

**Detail page** (`/api/public/reciter/<reciter_id>` + `ReciterDetail.svelte`): full deliveries table, six-bucket `Timeline` highlighting current state, side-rail `FactsList` that **omits null fields entirely** (no "Unknown" / "—" placeholders). 404 + retry states wired.

**BottomPlayer** (`inspector/frontend/src/lib/components/player/`): Dashboard-scoped, sticky at the tab bottom, hidden by the App-shell `hidden` cascade when Dashboard is inactive. Owns a new `dashPort = new AudioPort()` (per-tab pattern, no global). Tab leave pauses; tab return preserves position but does NOT auto-resume — user must press play. Source swap mid-playback (reciter / delivery / surah change) resets position to 0 and auto-resumes if `isPlaying` was true. Persists `{deliverySlug, surahNum, speed}` to `insp_dash_reciter`. Surah popover wraps `SearchableSelect` via `surahOptionText()` (same row format as elsewhere); SpeedPopover reuses `SPEEDS`.

**Segments-tab chip swap** (`tabs/segments/components/header/`): `ReciterContextChip` + `BrowseByStateStrip` replace the bare-select reciter dropdown. Both open `ReciterPicker` (chip → `under_review` pre-filter, strip → clicked bucket). Existing chapter + verse `SearchableSelect`s unchanged.

**App-shell hygiene:** `localStorage` keys starting with `insp_aud_` are swept once on boot so the dead Audio tab leaves no zombies. Returning visitors with `insp_active_tab='audio'` fall through to Dashboard via the existing `validTabs` guard.

**Slug exposure** (Slice 0): three pre-Phase-6 leaks fixed — `ReviewerBanner` (`row.slug` → `row.name ?? row.slug`), claims-client 409 toast (`existing_claim_name` + `target_name` enrichment), reciter-task row payload (`name` field added via `catalog_service.display_name(slug)`).

**HistoryFilters refactor onto `facets.ts`** was deferred — the existing logic threads through `deriveOpIssueDelta` + chain/item polymorphism that doesn't benefit from the generic helper, so a refactor would have added adapters rather than removed duplication. Recorded in [`inspector-deferred.md`](../inspector-deferred.md) if a third consumer ever appears.

**Tests:** ~70 new tests cover services + routes (`test_public_state.py`, `test_public_activity.py`, `test_search_normalize.py`, `test_route_public.py`), utilities (`fuzzy-match`, `facets`, `visible-poll`, `relative-time`, `schema-descriptor`), and the `Modal` focus-trap surface.
