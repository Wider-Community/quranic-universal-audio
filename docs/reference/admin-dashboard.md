# Admin dashboard

Owner/maintainer control surface launched from the Dashboard activity rail. A wide modal with a top tab strip; **Users**, **Requests**, **Reviews**, and **Permissions** ship. The **Permissions** tab is **owner-only** — it's filtered out of the tab strip for non-owners (`tabs = ALL_TABS.filter(t => !t.ownerOnly || $isOwner)` in `AdminDashboardModal.svelte`), and an active-tab guard snaps back to Users on a live owner→maintainer demotion.

## Permissions compartment (owner-only)

`PermissionsCompartment.svelte` renders the capability matrix (`GET /api/admin/permissions`) grouped by category; each capability row is an On/Off `Toggle` (`lib/components/Toggle.svelte`) per tier (anonymous / contributor / maintainer), with a static always-on **Owner** indicator. Anonymous cells render a locked **N/A** marker when the capability isn't `anon_eligible`; the `manage_permissions` row is fully locked (owner-only fixed). Toggling is optimistic + revert-on-error (mirrors `UsersCompartment.changeRole`); a modified cell shows a reset (↺) affordance → `POST …/<cap>/<tier>` with `{reset:true}`. API client `lib/api/admin-permissions.ts`; the resolved capability model + endpoints live in [auth-permissions.md](auth-permissions.md) § Capabilities.

Gated on `$isAdmin` (maintainer **or** owner). Read-only data for maintainers; the role picker (Users), request resolution (Requests), and reviewer overrides (Reviews → General-drawer popover) are owner-only or use existing owner-gated routes.

The entry button (`AdminDashboardButton`) shows a single quiet **dot** (no number) when the caller has **any** unviewed admin work — either unviewed open requests **or** unviewed marked-ready reviews — OR'd from `adminDashboard.unviewedRequests` and `adminDashboard.unviewedReviews`. Two independent 30s `visiblePoll`s drive those counters (`/api/admin/requests/unviewed-count` + `/api/admin/reviews/unviewed-count`); the tooltip lists both counts. Inside the modal the **Requests** and **Reviews** tabs each carry an independent numeric pill (`am-tab-count`) so a maintainer can see at a glance which surface needs attention.

## Frontend

`tabs/dashboard/components/admin/`

| File | Role |
|---|---|
| `AdminDashboardButton.svelte` | Entry button above the activity rail; rendered only when `$isAdmin`. Opens the modal via the store. Runs the two unviewed-count pollers (requests + reviews) — quiet dot when either is > 0. |
| `AdminDashboardModal.svelte` | `Modal size="wide"` + tab strip (`adminDashboard.activeTab`). Renders `UsersCompartment` / `RequestsCompartment` / `reviews/ReviewsCompartment`; Requests and Reviews tabs each carry an independent `am-tab-count` pill. |
| `RequestsCompartment.svelte` | Status facets (open / accepted / sent back / discarded + counts) over a review queue. Clicking a pending row expands an inline review (proposed-changes diff over `ProposedEdits` fields, requester note, conflict notice). Expanding a pending request marks it viewed (clears the unviewed dot/pill, decrements the badge). **Owner-only** inline reason + Send back / Discard; maintainers are read-only. Archived rows show a read-only resolution footer. Lazy-fetched on first activation + light `visiblePoll` while open. |
| `reviews/ReviewsCompartment.svelte` | Per-recitation oversight surface — four collapsible state buckets (Marked ready / Under review / Published / Available for review) split FE-side from one `/api/admin/reviews/list` fetch. Section order is fixed; Available collapsed by default (localStorage-persisted). Filter bar (Arabic + Latin search · riwayah/style/channel facets · `stalled`/`name` sort). Syncs `adminDashboard.setUnviewedReviews(resp.unviewed_marked_ready)` on every fetch so the entry-button dot / tab pill reconcile against the freshly-fetched list. |
| `reviews/ReviewsRow.svelte` | One row per recitation (`<tr>` so all sections share a `<colgroup>` for column alignment). Reciter cell shows Latin primary + Arabic muted trailing; renders a 7px `.unread` dot before the name when the row is server-marked unread **and** not yet session-viewed (the dot disappears synchronously on click). `Segments` button deep-links via `selectedReciter` + `setActiveTab('segments')` + `adminDashboard.close()`. On **under-review** rows a `Generate TS` button opens the Timestamps drawer (`reviewsStore.open(slug, 'timestamps')`). Row body click opens the General drawer; all drawer opens go through `reviewsStore.open()` which fires the best-effort viewed-mark POST and the row optimistically decrements `adminDashboard.unviewedReviews`. |
| `reviews/ReviewsGeneralDrawer.svelte` | Current-claim chip is the popover trigger for owners (subtle hover ring + caret); maintainers see static text. **Mark-ready submission** card (between Current reviewer and Reviewer history, visible only when `current_claim.mark_ready_submission` is set) renders the reviewer's checklist as a 6-row ✓ list plus the two optional comment boxes as quoted blocks — labels come from the same `tabs/segments/copy/mark-ready` module the reviewer saw, single source of truth. **Bypass submissions** (`submission.bypass_used === true`, written when an owner skipped the form via `claim.mark_ready_skip_gates`) replace the checklist with an italic "Submitted via owner bypass — the form checklist and the zero-count validation gates were skipped." line and display an "owner bypass" pill in the section header; the warning-tinted border on the card flags it visually. The two comment blocks still render when populated, regardless of mode. Also holds the reviewer-history table (closed claims), expanded vertical timeline, and a **Flagged issues** count (shown only when `flagged_issues_count > 0`) summarising segments flagged for a second look in the Segments editor. (Timestamps-job control + history moved to the dedicated `ReviewsTimestampsDrawer` — see below.) |
| `reviews/ReviewerActionsPopover.svelte` | **Owner-only** mode-driven popover anchored to the current-claim chip — three views: `menu` (Change reviewer / Remove reviewer), `change` (debounced 300 ms HF login lookup → resolved user card + reason → Reassign; disables when picked login equals current reviewer), `remove` (reason → Force-release). RolePicker-style click-outside + Escape dismissal; success fires `onaction` so the drawer + parent list refetch. |
| `reviews/ReviewsTimestampsDrawer.svelte` | Timestamps-generation control panel (under-review rows). **Settings form** — beam, probe beams, persist-audio + gen-peaks toggles, collapsible Advanced (workers/flavor/timeout) → `generateTimestamps(slug, settings)` (409 single-flight inline). **Live log pane** — `visiblePoll` on `GET /jobs/<id>` while running. **Job history** — `GET /reciters/<slug>/ts-jobs`; clicking a past run loads `GET /jobs/<id>/record` and renders its persisted logs read-only. Replaces the deleted Ops drawer. Deep dive: [timestamps-job.md](timestamps-job.md). |
| `reviews/ExpandedTimeline.svelte` | Vertical chronological timeline with tone variants (transition / admin / job dot styles). Newest-first sort. |
| `UsersCompartment.svelte` | Fetches the list once + visitor stats; people/traffic ribbon, search + role-filter toolbar, master table, detail drawer. Owns inline role-change orchestration (optimistic + revert + error banner). |
| `UsersTable.svelte` | Sortable master table. Role cell is a `RolePicker` (`editable={canEditRoles}`); the cell stops click-propagation only when editable so non-owners still open the drawer. |
| `UserDetailDrawer.svelte` | Lazy per-user detail (stats, role/claims/requests/activity timelines, HF profile link). Header pill is a `RolePicker`; reflects the live row role via `roleOverride`. |

State:
- `tabs/dashboard/stores/admin-dashboard.svelte.ts` (`adminDashboard`: `open`, `activeTab`, `unviewedRequests`, `unviewedReviews`, `openModal/close/setTab/setUnviewed*`).
- `lib/stores/reviews.svelte.ts` (`reviewsStore`: `selectedSlug`, `openDrawer`, `filters`, `sortBy`, `viewedThisSession`; `open(slug, kind)` is what fires `markReviewViewed` once per slug). The store stays `lib/`-pure — cross-store counter decrement is owned by the row.

Cross-tab building blocks in `lib/components/`: `RolePill` (presentational badge), `RolePicker` (owner-editable wrapper — bare pill when `editable=false`, dropdown of role pills + click-outside/Escape when `true`), `Avatar`, `Timeline`. API clients `lib/api/admin-users.ts`, `lib/api/admin-requests.ts`, `lib/api/admin-reviews.ts`; formatters `lib/utils/admin-format.ts`.

## Backend

Blueprint `admin_users_bp` at `/api/admin` (`routes/admin/users.py`), all `@require_role(Role.MAINTAINER, Role.OWNER)`:

| Route | Purpose |
|---|---|
| `GET /users` | Master list. Cached on `db_seq` (`services/admin/users.py::list_users`, cache in `services/storage/cache.py`). |
| `GET /users/<hf_user_id>` | Per-user detail (lazy, uncached) — `repo_admin_users` aggregations. |
| `GET /visitor-stats` | Today's traffic rollup. Gated on env `INSPECTOR_VISITOR_ANALYTICS`; the compartment swallows failure. |
| `POST /users/<hf_user_id>/role` | **Owner-only** role change (`@require_role(Role.OWNER)` + `@require_same_origin`). |

Aggregation/reads: `services/db/repo_admin_users.py`, `repo_visitors.py`; visitor counting in `services/admin/visitors.py`. Schemas: `qua_shared/schemas/admin_users.py` (codegen'd to FE types).

### Requests compartment

Routes live in `requests_bp` (`routes/claims/requests.py`); reads in `services/admin/requests.py`; schema `qua_shared/schemas/admin_requests.py` (codegen'd).

| Route | Purpose |
|---|---|
| `GET /admin/requests?status=open\|accepted\|returned\|discarded` | Review-queue payload for one facet — catalog-joined (name/riwayah/style), proposed-changes diff over `ProposedEdits` fields, conflict flag, per-caller `viewed`, facet counts, and the caller's `unviewed_count`. Includes **slugless intake rows** (new-combo / new-reciter) alongside slug-based edit requests; intake rows carry `source` + `probe`. Maintainer+; **tier-redacted** (owners get `@login`+hf_id, maintainers role only). Base list cached on `db_seq` in `cache.py` (`get/set_admin_requests_cache`); per-caller overlay applied live. |
| `GET /admin/requests/unviewed-count` | The caller's unviewed-open count (button dot + tab pill). Never cached. |
| `POST /admin/requests/<id>/view` | Mark a request viewed for the calling admin (fired on inline expand). Per-admin, idempotent (`request_views` table); first view per (request, admin) is a durable write. |

Resolution of **slug-based edit requests** stays on the existing per-slug routes, now **owner-only**: `POST /admin/request/<slug>/reject-{soft,hard}` (`@require_role(Role.OWNER)`; the `reciter.request_rejected_{soft,hard}` transition handlers use `_require_owner`). Acceptance is implicit (the alignment pipeline → `reciter.alignment_completed` applies the proposed edits + resolves the request to `accepted`).

#### Intake requests (new combination / new reciter)

The Submit-recitation wizard's two **slugless** types — `existing_reciter_new_combo` and `new_reciter` — carry an audio **source** (direct links / playlist; a dropped CSV/JSON file is normalised into `links[]` client-side). They land in the unified `requests` table with `slug = NULL`, everything parked in `payload` (`reciter_id`, `proposed_edits` (ProposedEdits-shaped), `source`, three required `attestations` (distribution/links-verified/storage rights — recorded for audit), cached `probe`). Service: `services/admin/intake.py`; validation `intake_validation.py`; probe `intake_probe.py`; schemas `qua_shared/schemas/intake_requests.py` (codegen'd).

| Route | Purpose |
|---|---|
| `POST /requests/intake` | Submit (any signed-in user; `@require_same_origin`). Structural validation only — URL format (errors list malformed **chapter indices**), required combination + all three attestations, with 1–114 coverage / duplicates / playlist host as **warnings**. 400 carries `{errors, warnings}`. The wizard mirrors this client-side: live invalid/missing-chapter feedback in step 2, a step-4 confirm of the attestations. |
| `POST /admin/requests/<id>/accept` | **Owner-only.** Approval only — **does not write the catalog.** Records the owner-confirmed canonical `reciter_id` (new_reciter only) onto the payload and flips the request to `accepted` (slug stays NULL). Source/channel/bitrate/slug are probed from the audio and can't be validly classified by a human at accept time, so the **offline ingest** reads accepted slugless requests, fetches + probes the audio, and creates the reciter + delivery (correct source/channel/slug) + state row, honoring `auto_claim` — all offline. |
| `POST /admin/requests/<id>/probe` | **Owner-only.** Reachability probe of the source (ThreadPool HEAD/ranged-GET; playlist = single check). Caches `payload.probe`. Never on the submit path. |
| `POST /admin/requests/<id>/{return,discard}` | **Owner-only.** Id-based resolution for slugless rows — pure request-status mutation, **no** state-machine transition (no delivery/state row exists). ≥10-char reason. |

The Accept-confirm dialog (`AcceptIntakeDialog.svelte`) is deliberately thin: for a **new reciter** it confirms only the canonical `reciter_id` (the lone human decision); for a **new combination** it's a plain confirm. No source/channel/slug pickers — those are ingest's job. `request.intake_*` are audit-only events (slugless, not in `_HANDLERS`) — silently dropped from both activity rails, no classification entry needed.

Request review is **no longer a notification**: `reciter.request_rejected_{soft,hard}` are `HIDDEN_EVENTS` and `reciter.requested` is public-prose-only (not `ADMIN_ONLY_EVENTS`) in `activity_classification.py`.

### Reviews compartment

Routes live in `admin_reviews_bp` (`routes/admin/reviews.py`); reads + per-admin view marks in `services/admin/reviews.py`; schema `qua_shared/schemas/admin_reviews.py` (codegen'd). All endpoints `@require_role(Role.MAINTAINER, Role.OWNER)`.

| Route | Purpose |
|---|---|
| `GET /admin/reviews/list` | One whole-table JOIN over `delivery_states` + `deliveries` + `reciters` + open `claims`, filtered to the four review states (`awaiting_review`, `under_review`, `awaiting_timestamps`, `released`). Per-caller: each row carries `unread` (true only for `under_review` rows whose open claim's `marked_ready_at` is later than this admin's `review_views.viewed_at`), and the response carries the aggregate `unviewed_marked_ready` count. Not cached — sub-second JOIN, refreshed on every admin action. |
| `GET /admin/reviews/<slug>` | General-drawer payload — base + current claim + claim history + transition timeline + `timestamps_job_ids` + `flagged_issues_count` (segments carrying a `flag`, from one cached `load_detailed`). Bounded queries + one detailed read; cheap enough to fetch eagerly on every drawer open. 404 on unknown slug. |
| `GET /admin/reviews/unviewed-count` | Per-caller marked-ready unread count for the entry-button dot poller. `Cache-Control: no-store`. |
| `POST /admin/reviews/<slug>/view` | Upsert the caller's `viewed_at` for `slug` (fired on the first drawer open per slug in a session). `@require_same_origin`. Returns 404 on unknown slug. |

**Timestamps-generation** endpoints (`@require_capability("reviews.generate_timestamps")`, maintainer+) — drive the `ReviewsTimestampsDrawer`. Full subsystem: [timestamps-job.md](timestamps-job.md).
- `POST /api/admin/generate-timestamps/<slug>` — launch the in-container MFA job. Body → `_parse_ts_settings` → `TsJobSettings` (`beam` + `probe_beams` → `beams`, persist-audio/gen-peaks toggles, Advanced workers/flavor/timeout). 202 `{job_id, url}`; 409 if a job is already running for the slug; 400 invalid; 404 unknown. `@require_same_origin`. Does **not** transition the reciter.
- `GET /api/admin/jobs/<job_id>` — live status + bounded log tail (HF authoritative).
- `GET /api/admin/jobs/<job_id>/record` — persisted record (settings + status + full logs) from `jobs/ts/<job_id>.json`; 404 if none.
- `GET /api/admin/reciters/<slug>/ts-jobs` — persisted records for the slug (newest first), for the drawer's history list.

General-drawer popover mutations reuse existing per-slug routes:
- `POST /api/admin/claim/force-release/<slug>` — **owner-only** (`_require_owner` at both route + state-machine handler level). Used by the popover's Remove path.
- `POST /api/admin/claim/reassign/<slug>` — **owner-only**. Used by the popover's Change path; resolves `to_login` server-side via `hf_users.lookup` before persisting `claim.reassigned`.
- `POST /api/admin/users/lookup` — maintainer+. Lookup-only (no mutation); the popover hits it on debounced input to render the resolved-user card.
- `POST /api/admin/send-back/<slug>` — maintainer+ (quality gate, not a claim mutation). Rejects marked-ready work for more review.
- Publish / unpublish / unlock-for-revision are listed but **disabled** (see `docs/planning/reviews-tab-deferred.md`).

The owner-only tightening on force-release + reassign was a deliberate split: **owners manage who reviews; maintainers gate what ships**. Maintainers retain Send-back-to-UR (reject marked-ready work for more review) but cannot eject or transfer claims.

#### Per-admin view marks (`review_views`)

Mirror of `request_views` (migration 0004) but keyed by **slug**, not request id, with **upsert** semantics (latest view wins). Migration 0005 (`inspector/services/db/migrations/0005_review_views.sql`); repo `inspector/services/db/repo_review_views.py`.

```
review_views(slug, hf_user_id, viewed_at)  PK (slug, hf_user_id)
ix_review_views_user ON (hf_user_id)
```

The unread predicate is `viewed_at IS NULL OR viewed_at < claims.marked_ready_at` — **cycle-safe** by construction: maintainer sends back → claim closes → reviewer re-claims and re-marks ready → new `marked_ready_at > viewed_at` → the dot re-arms. No GC needed; stale rows (slug no longer in `delivery_states`, or claim now closed) are harmless because the predicate joins on the **live** open claim.

The Reviews compartment + the entry-button poller agree on this aggregate via `unviewed_marked_ready` on the list response (compartment refetch path) and the `/unviewed-count` endpoint (button-poll path) — both compute the same SQL predicate, so any optimistic FE decrement reconciles on the next read.

### Role change (`services/admin/users.py::set_role`)

Roles are tri-state with contributor **implicit** (no `role_assignments` row). `set_role` reads the current role and dispatches to the existing `services/auth/access.py` mutations so authz + audit + `durable_transaction` stay centralized:

| From → To | Action |
|---|---|
| contributor → maintainer/owner | `access.grant` |
| maintainer ↔ owner | `access.update` (in-place tier change) |
| maintainer/owner → contributor | `access.revoke(cascade_release=False)` — **preserves the user's open claim** (a contributor is a valid claim holder; demote ≠ offboard) |

Guard: refuse to remove the **last active owner** (`repo_access.active_owner_count`) → `LastOwnerError` → HTTP 409. Other mappings: `NotAuthorized`→403, `MemberNotFound`→404, bad input / `AccessError`→400.

> The legacy `/api/admin/access/{grant,revoke,update}` endpoints (`routes/admin/access.py`) remain — maintainer-capable, and `revoke` there keeps `cascade_release=True` (offboarding: auto-releases open claims). The picker is the owner-only path; offboarding is the access endpoints.

### Sync

No special wiring. `durable_transaction` bumps `db_seq` → the admin-users list cache self-invalidates on next read; `current_user()` resolves role fresh per request (no TTL), so the affected user becomes their new role on their next request. A self-demoting owner's own FE refreshes via `loadCurrentUser()` immediately (and on any reload at minimum).

See [auth-permissions.md](auth-permissions.md) for roles/predicates/edit-lock and [frontend.md](frontend.md) for the dashboard tab.
