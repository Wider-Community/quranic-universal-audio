# Inspector Admin & Permissions (v2)

Companion to [`inspector-deployment-plan.md`](inspector-deployment-plan.md). Implementation-grade reference for user roles, the permission matrix, override actions, the admin dashboard, and the audit trail. Pairs with [`inspector-state-management.md`](inspector-state-management.md) (events vocabulary), [`inspector-data-storage.md`](inspector-data-storage.md) (bucket layout), and [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) (publish/HF Jobs orchestration).

The parent doc's three roles (anonymous, contributor, claim-holder) are the happy path. This doc adds the elevated **maintainer** and **owner** tiers, the override surfaces they unlock, the dashboard that gives them visibility, and the audit trail that keeps them honest.

## 1. Model in one paragraph

Authorization is layered on top of authentication. Authentication answers "who is this user" (HF OAuth → `hf_user_id` canonical, `login` display-only). Authorization answers "what can they do" — derived from a single source: `data/inspector_roles.json` on GitHub (consolidated owners + maintainers — see §3). Anonymous users see public completed reciters. Logged-in contributors can claim one reciter at a time. Maintainers get a named, audited set of override actions — each one a discrete admin endpoint, **no `state.manual_override` wildcard**. Owners (small subset) can additionally rotate the Space's HF token, edit the roles file itself, and approve irrecoverable destructive actions. Every elevated action is named, audited to `<bucket>/state/audit/<YYYY>-<MM>.jsonl`, and confined to the smallest blast radius that solves a real recurring problem.

## 2. Roles

### `anonymous`

Not authenticated. Read-only access to public data — completed reciters, plus in-flight reciters if the parent doc's "anonymous viewing of in-review data" defaults to yes.

### `contributor`

Authenticated HF user. Can:

- Read everything an anonymous user can read.
- Claim one `awaiting_review` reciter at a time.
- Edit segments for the reciter they hold a claim on.
- Release / mark-ready / unmark-ready their own claim.
- View their own contribution history (claims made, publishes, etc.) — sourced from `<bucket>/state/audit.jsonl`.

A contributor becomes a **claim-holder** while a claim is active. The claim-holder distinction is implicit (derived from `state.assignee == user.login`) and not a separate role.

### `maintainer`

Authenticated HF user with `role: maintainer` in `data/inspector_roles.json`. Adds: force-release, reassign, discrete admin overrides (force-set-state on narrow targets, force-clear-assignee, force-unmark-ready), catalog edit (direct to bucket, no PR), publish, send-back from ready, discard/undiscard, archive/unarchive, internal data views.

Cannot: rotate the Space's HF token, edit the roles file, approve owner-only destructive actions.

### `owner`

Authenticated HF user with `role: owner` in `data/inspector_roles.json`. Superset of maintainer. Adds: edit `data/inspector_roles.json` (CODEOWNERS-gated PR), rotate the Space's HF token, accept irrecoverable destructive actions (e.g. mass discard).

Owners count: recommend 2–3 minimum for bus-factor, ≤5 maximum to keep responsibility concentrated.

## 3. Role identity — single consolidated file

**Sole source of role truth: `data/inspector_roles.json` on GitHub** (was two separate files in earlier drafts).

Schema:

```jsonc
{
  "schema_version": 1,
  "members": [
    {
      "hf_user_id": "12345",                // canonical (immutable)
      "login": "ahmed",                     // display cache (refreshed periodically)
      "role": "owner",                      // 'owner' | 'maintainer'
      "added_at": "2026-04-01T...",
      "added_by_hf_id": "67890",
      "removed_at": null,                   // soft-delete; preserves audit
      "removed_by_hf_id": null
    }
  ]
}
```

PR-reviewed (CODEOWNERS gates to existing owners). Adding/removing/promoting is a deliberate audited action.

### Why one file, why `hf_user_id` canonical, why soft-delete

- **One file** instead of two (`inspector_owners.json` + `inspector_maintainers.json`): collapses the failure mode where one file exists and the other doesn't, makes "promote to owner" a single-row edit instead of cross-file move.
- **`hf_user_id` canonical:** if a maintainer renames themselves on HF, login-keyed lookup silently revokes their role. The lookup is `member.hf_user_id == user.hf_user_id`, never `login`.
- **Soft-delete via `removed_at`:** historical role membership stays queryable. "Who was an owner when X bad action happened?" is a JSON scan, not a `git blame`.

### Backend resolution

```python
def resolve_role(user: AuthenticatedUser) -> Role:
    member = next(
        (m for m in MEMBERS_CACHE
         if m.hf_user_id == user.hf_user_id and m.removed_at is None),
        None,
    )
    return member.role if member else Role.CONTRIBUTOR
```

Cache: 60 s. Source: GitHub raw URL (no auth, public repo). Refreshed via simple HTTP fetch. Owner-only `POST /api/admin/refresh-roles` forces immediate refresh for emergency revocation.

If the live file is unreachable on Inspector startup, fall back to a stale snapshot baked into the Space image (`data/inspector_roles.json` is in the COPY list of the Dockerfile). Live wins on next refresh.

### Why GitHub for the roles file (not the bucket)

Roles govern *who can edit*, not *what's edited*. CODEOWNERS-gated PR review is the right gate for security-critical role changes (existing owners must approve). The bucket is the right place for *content* (catalog, state); GitHub is the right place for *permissions*.

## 4. Permission matrix

| Action | anon | contrib | maint | owner |
|---|:---:|:---:|:---:|:---:|
| View completed reciter | ✓ | ✓ | ✓ | ✓ |
| View in-flight reciter | ✓¹ | ✓ | ✓ | ✓ |
| View `discarded` / internal-only reciter | — | — | ✓ | ✓ |
| View own claim history | — | ✓ | ✓ | ✓ |
| View any user's claim history | — | — | ✓ | ✓ |
| Claim a reciter | — | ✓ | ✓ | ✓ |
| Release own claim | — | ✓ | ✓ | ✓ |
| Edit segments (own claim) | — | ✓ | ✓ | ✓ |
| Mark own claim ready for merge | — | ✓ | ✓ | ✓ |
| Unmark own claim (pull back to under_review) | — | ✓ | ✓ | ✓ |
| **Publish a `ready_for_merge` reciter** | — | — | ✓ | ✓ |
| **Send back from ready_for_merge** | — | — | ✓ | ✓ |
| **Force-release someone else's claim** | — | — | ✓ | ✓ |
| **Reassign claim to specific user** | — | — | ✓ | ✓ |
| **Edit segments without holding claim** (force-claim) | — | — | ✓ ² | ✓ ² |
| **Discrete state overrides** (`admin.force_set_state` on narrow targets, `force_clear_assignee`, `force_unmark_ready`) | — | — | ✓ | ✓ |
| **Catalog entry edit** (direct to bucket, no PR) | — | — | ✓ | ✓ |
| **Discard / undiscard** (visibility flag, not a state) | — | — | ✓ | ✓ |
| **Archive / unarchive** (visibility flag, completed reciters only) | — | — | ✓ | ✓ |
| **Trigger pipeline rerun** ³ | — | — | ✓ | ✓ |
| Re-run a failed publish HF Job | — | — | ✓ | ✓ |
| View admin dashboard | — | — | ✓ | ✓ |
| View audit log | — | — | ✓ | ✓ |
| Edit `data/inspector_roles.json` | — | — | — | ✓ |
| Rotate the Space's `INSPECTOR_HF_TOKEN` | — | — | — | ✓ |
| Mass discard / bulk destructive | — | — | — | ✓ ⁴ |

**No `state.manual_override` wildcard.** Earlier drafts had a single "any → any" admin endpoint as an escape hatch. v2 replaces it with discrete named operations (see §5.4–§5.10 + state-mgmt §4 events list). If a recovery scenario isn't covered by the listed admin events, the response is to add a new named one — not extend a wildcard. Discipline: write the use case, name the event, add to the matrix, ship.

¹ Default per parent doc Open Questions; can flip to maintainer-only later.
² Maintainer edit-without-claim auto-acquires a temporary force-claim with a 30-min lease. Released on session end or after 30 min of inactivity. Original assignee retains their claim; maintainer's writes coexist (see §5.3).
³ Web surface fires the trigger; the pipeline itself runs unchanged on Katana / HF Space / HF Job.
⁴ Destructive bulk actions also require a typed confirmation phrase and a 24-hour soft-lock window before they fire (see §6.5).

## 5. Override actions — full spec

Each override has: trigger, preconditions, request shape, side effects, audit-log entry, reversibility, UI affordance. **All overrides go through Inspector backend's `services/state.py::transition()` for state mutations** — same path as user actions, just gated by maintainer+ role. This keeps the state machine the single point of validation.

### 5.1 Force-release

**Use case:** reviewer disappeared mid-session; reciter has been `under_review` with no edits for >7 days; need to free it up for someone else.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/claim/force-release` |
| Body | `{ "slug": "...", "reason": "..." }` |
| Preconditions | reciter is `under_review` or `ready_for_merge`; caller is maintainer+ |
| State transition | (current) → `awaiting_review`, clears assignee |
| Event in audit | `claim.force_released { slug, by_login, original_assignee, reason }` |
| Reversibility | Soft — the original assignee can re-claim; their bucket entry's last-flushed state is preserved |
| UI | Button on reciter card in dashboard ("Force-release") + on the reciter's segments tab when viewed by a maintainer |
| Confirmation | Modal: "Force-release `<slug>` from `<assignee>`? Reason (required):" |

The bucket entry's current contents are preserved — the reviewer's last-flushed state stays in `<bucket>/wip/<slug>/...` for the next reviewer to pick up. Anything still buffered locally on the original reviewer's container (within the 30 s mount flush window) is lost.

### 5.2 Reassign

**Use case:** maintainer wants to hand a stuck reciter to a specific contributor.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/claim/reassign/<slug>` |
| Body | `{ "to_login": "...", "reason": "..." }` (no `to_hf_user_id` — backend resolves) |
| Preconditions | reciter is `awaiting_review`, `under_review`, or `ready_for_merge`; `to_login` resolves via `GET https://huggingface.co/api/users/<to_login>/overview` (returns 200 with stable `_id`; 404 → `BadRequest`) |
| State transition | → `under_review`, sets `assignee = canonical_login`, `assignee_hf_id = _id` (the API's casing wins over user input) |
| Event in audit | `claim.reassigned { slug, by_login, from_login, to_login, to_hf_user_id, reason }` |
| Reversibility | Soft — reassign back |
| UI | "Reassign…" button + free-text login input (no public typeahead API exists). On blur, the UI calls `/api/admin/users/lookup?login=<x>` (a thin proxy to the HF endpoint) and shows `fullname + avatarUrl` from the response so the maintainer can confirm before submit. |

No invitation needed in v2 — HF users don't need any specific repo permission to use the Inspector; the reassign just sets the assignee fields.

**Why store both `to_login` and `to_hf_user_id`:** the HF `_id` (= OIDC `sub`) is **stable across username renames**; the `login` is mutable display only. All claim-ownership checks compare `assignee_hf_id`, never `assignee`. If a reviewer renames their HF account mid-claim, their existing claim survives.

### 5.3 Edit-without-claim (force-claim)

**Use case:** maintainer needs to make a quick correction on a reciter under someone else's claim without disrupting them long-term.

| Field | Value |
|---|---|
| HTTP | none — implicit; first save under maintainer auth on a reciter they don't own auto-acquires |
| State transition | none (assignee field unchanged); a separate `force_assignee` field is added with a 30-min lease |
| Event in audit | `claim.force_acquired { slug, by_login, original_assignee }` |
| Reversibility | Auto-released after 30 min inactivity or maintainer explicit release |
| UI | Banner: "You are editing a reciter held by `<assignee>`. Your edits will save as you and auto-release in 30 min." |

The original assignee retains their claim. Both writers' saves go to the bucket; the in-process mutex per-`(slug)` serializes them — neither overwrites the other's in-flight state. Visible to original assignee as: "A maintainer is making corrections — your saves may briefly pause."

This is a v2 simplification vs v1: there's no separate "PR branch" to commit on; both writers write to the same bucket entry; the mutex is the coordination point.

### 5.4 Discrete state overrides (replaces v1 `state.manual_override` wildcard)

**Use case:** state machine rejected a transition that should have happened, or a manual operational fix is needed. Each scenario has a discrete named endpoint — no wildcard.

#### 5.4a Force-set state (narrow allowed targets)

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/state/force-set/<slug>` |
| Body | `{ "to_state": "...", "reason": "..." }` |
| Preconditions | caller is maintainer+; `(from, to)` is in the allowed-pairs list (see below) |
| State transition | from → to (no automatic side effects) |
| Event in audit | `admin.force_set_state { slug, by_hf_id, from_state, to_state, reason }` |
| Reversibility | Manual — set back via the reverse-pair if allowed |
| UI | Dropdown in admin dashboard restricted to the allowed targets for the row's current state |

**Allowed `(from, to)` pairs** (intentionally narrow — extend by adding to this list, not by widening the endpoint):
- `awaiting_alignment ↔ awaiting_review` (alignment recovery without re-running pipeline)
- `awaiting_timestamps ↔ completed` (TS-job recovery)
- `under_review → awaiting_review` (alternative path to `claim.force_released` that doesn't bump force-release-count)

Any other pair returns 400 with the message "use a discrete operation: see admin §5.X." If a real use case appears for a missing pair, add it to the list and to the state-mgmt matrix; do NOT widen this endpoint to "any → any."

#### 5.4b Force-clear assignee

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/claim/clear/<slug>` |
| Body | `{ "reason": "..." }` |
| Preconditions | caller is maintainer+; row has `assignee_hf_id IS NOT NULL` |
| Effect | Clear `assignee_*`, `marked_ready = 0`. State unchanged. |
| Event in audit | `admin.force_clear_assignee { slug, by_hf_id, original_assignee_hf_id, reason }` |
| UI | Button in admin dashboard's "Active sessions" panel |

This is distinct from `claim.force_released` (which transitions `under_review → awaiting_review`). `force_clear_assignee` only clears the columns; useful for state-machine cleanup after an `admin.force_set_state` that left orphaned assignee data.

#### 5.4c Force-unmark-ready (admin path)

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/state/force-unmark-ready/<slug>` |
| Body | `{ "reason": "..." }` |
| Preconditions | caller is maintainer+; row has `marked_ready = 1` |
| Effect | `marked_ready = 0`. State + assignee unchanged. |
| Event in audit | `admin.force_unmark_ready { slug, by_hf_id, original_assignee_hf_id, reason }` |

Distinct from `reciter.unmarked_ready` (reviewer-driven; requires actor to be the assignee). The admin path doesn't require assignee match — useful when the assignee is unreachable.

#### 5.4d Force revision bump (debug only)

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/state/force-revision-bump/<slug>` |
| Body | `{ "reason": "..." }` |
| Effect | `revision += 1`. No other change. |
| Event in audit | `admin.force_revision_bump { slug, by_hf_id, reason }` |

For OCC-related recovery scenarios. Not normally used.

### 5.5 Discard / Undiscard (visibility flag)

**Use case:** reciter request was made in error, audio source is broken, etc. **`discarded` is NOT a state** — it's `visibility = 'discarded'` orthogonal to lifecycle (see [`inspector-state-management.md`](inspector-state-management.md) §4). Reversal preserves the original lifecycle position.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/discard/<slug>` |
| Body | `{ "reason": "...", "confirmation_phrase": "discard <slug>" }` |
| Preconditions | caller is maintainer+; `confirmation_phrase` matches `discard <slug>` exactly |
| Effect | `visibility = 'discarded'`, `visibility_reason = <reason>`. **Lifecycle state unchanged.** |
| Event in audit | `reciter.discarded { slug, by_hf_id, reason }` |
| Reversibility | `POST /api/admin/undiscard/<slug>` clears the visibility flag back to `'public'`; lifecycle position preserved |
| UI | "Discard" button only visible after typing `discard <slug>` in a confirmation field |

Discarded reciters are hidden from anonymous viewers and from the regular reciter list. Maintainers see them under "Internal" filter on the admin dashboard. The reciter retains its lifecycle position — un-discarding is just clearing the flag.

### 5.5b Archive / Unarchive (visibility flag — completed only)

**Use case:** rare — a `completed` reciter is permanently retired (e.g., audio source disappeared post-publish).

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/archive/<slug>` / `POST /api/admin/unarchive/<slug>` |
| Body | `{ "reason": "..." }` (typed confirmation also required for archive) |
| Preconditions | caller is maintainer+; lifecycle state is `completed` |
| Effect | `visibility = 'archived'` / `'public'`. Lifecycle unchanged. |
| Event in audit | `reciter.archived` / `reciter.unarchived` |
| UI | Distinct from discard — archive is for retired-but-once-live reciters; discard is for never-shipped or rejected requests. |

### 5.6 Catalog edit (revised — direct to bucket per H3+H4)

**Use case:** display name typo, riwayah classification correction, audio source URL change, adding a new variant.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/catalog/edit/<slug>` (edit existing) or `POST /api/admin/catalog/add` (new row) |
| Body | `{ "patch": { "name_en": "...", "riwayah": "...", ... }, "reason": "..." }` |
| Preconditions | caller is maintainer+; patch passes catalog schema validation; slug exists (for edit); patch does NOT touch immutable fields (`slug`, `reciter_id`) |
| Side effect | Direct write to `<bucket>/catalog/reciter_catalog.json` via `inspector/services/catalog.py::transition()` (mirrors `state.py` pattern: schema validate → atomic write → audit append → in-memory cache update). Fires `repository_dispatch reciter.catalog_changed` to trigger `update-reciters.yml`. |
| Event in audit | `catalog.edited { slug, by_login, patch, reason }` (in `<bucket>/catalog/audit.jsonl`) |
| Reversibility | Reverse via another `catalog.edited` (audit log preserves prior values) |
| UI | Catalog editor modal with form fields per schema; immutable fields rendered read-only |

**Why direct, not PR:** v2's whole architectural shift is "no per-reciter PRs." Keeping catalog on PRs would require a catalog-auto-merge workflow, a separate PR-create PAT, and a PR review queue — only for the one remaining PR surface. Catalog has the same write characteristics as state (low cadence, maintainer+ gated, schema-validated, audit-trailed) — so it belongs in the same operational model.

**What stays PR-reviewed:** the role files (`data/inspector_owners.json`, `data/inspector_maintainers.json`) — those govern *who can edit*, and CODEOWNERS-gated PR review is the right gate for changes to the role list.

### 5.7 Pipeline trigger

**Use case:** maintainer wants to kick off re-extraction or timestamps refresh from the web instead of CLI/HPC.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/pipeline/trigger` |
| Body | `{ "slug": "...", "kind": "extraction" \| "timestamps" \| "validation", "reason": "..." }` |
| Preconditions | caller is maintainer+; reciter is in a state compatible with the requested operation |
| Side effect | Fires `repository_dispatch pipeline.triggered { slug, by_login, kind, reason }` to GitHub. The corresponding pipeline workflow handles it. |
| Event in audit | `pipeline.triggered` (also recorded in audit) |
| Reversibility | None — pipelines, once started, run to completion |
| UI | "Run pipeline…" picker on the reciter card |

The web surface only triggers; the pipeline itself runs unchanged on Katana / HF Space / HF Job per existing wiring.

### 5.8 Re-run a failed publish HF Job

**Use case:** the publish fan-out fired three Jobs; one failed. Maintainer wants to re-run the failed one without re-firing the others.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/rerun-job` |
| Body | `{ "slug": "...", "job_type": "snapshot" \| "timestamps" \| "audio-dataset", "reason": "..." }` |
| Preconditions | caller is maintainer+; reciter has a failed Job of that type in the in-memory tracker |
| Side effect | Inspector POSTs to HF Jobs API to enqueue the same Job (with same payload) |
| Event in audit | `admin.job_rerun { slug, by_login, job_type, original_job_id, new_job_id, reason }` |
| Reversibility | Cancel the new Job before completion |
| UI | Per-Job retry button in the dashboard's "Active Publish Operations" section |

### 5.9 Send back from ready_for_merge

**Use case:** maintainer reviewed a `ready_for_merge` reciter, found issues, wants the reviewer to fix them rather than publishing.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/ready/send-back` |
| Body | `{ "slug": "...", "reason": "..." }` |
| Preconditions | reciter is `ready_for_merge`; caller is maintainer+ |
| State transition | `ready_for_merge → under_review` (assignee retained) |
| Event in audit | `reciter.merge_rejected { slug, by_login, original_assignee, reason }` |
| Reversibility | Reviewer can mark ready again after fixes |
| UI | "Send back…" button on the reciter card when state is `ready_for_merge` |
| Confirmation | Modal with required reason field (≥10 chars) |

The reason text is appended to the reciter's history entry in the state file; surfaced in the reviewer's dashboard banner.

## 6. Admin dashboard

A maintainer-gated SPA route at `/admin`. Hidden entirely (404) for non-maintainers — does not flash and disappear.

### 6.1 System health (top of page)

Live-refreshing card. Sources from `/api/admin/health`:

```jsonc
{
  "hf_oauth_session_count": 12,
  "bucket_mount": { "mounted": true, "rw": true, "writes_last_5m": 18 },
  "parsed_seg_cache": { "entries": 4, "bytes": 18000000, "hit_rate_5m": 0.94 },
  "active_sessions": 3,
  "inflight_publish_jobs": 1,
  "backend": { "version": "...", "commit": "...", "uptime_seconds": 184231 },
  "state_file": { "last_updated_at": "...", "reciters_count": 287 }
}
```

### 6.2 All reciters

Sortable, filterable table. Columns: slug, state pill, days-in-state, assignee, last activity, quick-action buttons.

Filters: state (multi), assignee (text), riwayah, source, "stalled only" toggle, "internal only" toggle (shows discarded).

Default sort: days-in-state desc.

### 6.3 Stalled reciters

Auto-populated from these rules (configurable per-state thresholds):

| State | Threshold |
|---|---|
| `awaiting_alignment` | >7 days since transition |
| `awaiting_review` | >30 days with `assignee == null` |
| `under_review` | >14 days since last save in audit log |
| `ready_for_merge` | >7 days awaiting maintainer publish |
| `awaiting_timestamps` | >7 days since transition |

Each row shows: slug, state, days stalled, recommended action, action button.

### 6.4 Active sessions

Real-time view of in-memory state:

| slug | assignee | claim_age | last_save_age | parsed_cache_hit |
|---|---|---|---|---|

Quick actions per row: force-release, view session details (recent saves from `edit_history.jsonl`).

### 6.5 Active publish operations

For any reciter in `awaiting_timestamps`, show the three subordinate Jobs and their status:

| slug | snapshot-bucket-to-dataset | timestamps-refresh | build-per-verse-audio | published_at |
|---|---|---|---|---|
| saad_al_ghamdi | ✓ done (12s) | ⟳ running (4m) | ✓ done (3m) | — |

Per-Job retry button if any is `failed`.

### 6.6 Recent events log

Sourced from `<bucket>/state/audit.jsonl`. Last 100 entries, sorted desc.

Filterable by event type, actor, slug. Each entry expandable to show the full payload.

### 6.7 Contributor activity

Per-user (last 30 days), derived from audit log:

- Claims made
- Saves performed (count of save batches)
- Reciters published
- Average days from claim to mark-ready

Sortable. Linkable to the user's HF profile.

### 6.8 Bulk actions (owner-only)

Separate tab. Operations:

- Discard all reciters in state X older than Y days (typed confirmation + 24h soft-lock)
- Bulk reassign all reciters from user A to user B (when a reviewer leaves)
- Bulk re-trigger pipeline for slugs matching a filter

Each bulk action lists affected slugs in a preview before firing. Soft-lock: clicking Run schedules the action 24h in the future; another owner can cancel during that window.

## 7. Audit log

### File

`<bucket>/state/audit/<YYYY>-<MM>.jsonl` (private metadata bucket). Append-only JSONL, partitioned per-month from day one. Written by Inspector backend on every state-mutating event via direct `huggingface_hub.upload_file()` (bypasses mount flush window — durability is the priority for state events).

A separate `<bucket>/catalog/audit/<YYYY>-<MM>.jsonl` (public data bucket) carries `catalog.*` events.

### Record schema

`schema_version` lives once per partition file in `<bucket>/state/audit/_meta.json`, NOT per record. Per-record version-stamping inflates every line for no read-time benefit.

```jsonc
// audit/2026-05.jsonl (one line per event)
{
  "ts": "2026-05-09T14:23:11Z",
  "event": "claim.force_released",
  "slug": "saad_al_ghamdi",
  "from_state": "under_review",
  "to_state": "awaiting_review",
  "actor": {
    "hf_user_id": "12345",                 // canonical (immutable)
    "login_at_time": "alice",              // display snapshot
    "role": "maintainer"                   // role snapshot — survives later role changes
  },
  "reason": "Reviewer unresponsive for 8 days, freeing for next contributor.",
  "payload": { "original_assignee_hf_id": "67890" },
  "request_id": "req_abc123",
  "prev_hash": "sha256:abc123...",         // sha256 of canonical(prev record); chain integrity
  "result": "ok"
}
```

Per-event `payload` shape lives alongside its event constant in `inspector/services/state.py` as a `TypedDict` — colocation, no separate schema-doc-by-grep.

### Field semantics

| Field | Required | Notes |
|---|---|---|
| `ts` | yes | ISO 8601 UTC |
| `event` | yes | Event name from §5 / §11; canonical `<noun>.<verb>` form |
| `slug` | yes when applicable | Null for non-reciter actions (e.g. bulk preview) |
| `from_state`, `to_state` | yes for state transitions | Both null for orthogonal-flag events (visibility, marked_ready) and admin events with no state change |
| `actor.hf_user_id` | yes | Canonical immutable identifier |
| `actor.login_at_time` | yes | Snapshot — survives login renames |
| `actor.role` | yes | Snapshot — survives role changes |
| `reason` | yes for admin actions | Free-form, ≥10 chars |
| `payload` | yes | Event-specific TypedDict from `services/state.py` |
| `request_id` | yes | For traceability across Inspector + HF Job + dispatch logs |
| `prev_hash` | yes | sha256 of canonical(prev record) — chain integrity. `replay_audit.py` validates. |
| `result` | yes | `ok` or `failed` |

### Integrity

`prev_hash` chains records. `scripts/lib/admin_audit.py::verify_chain()` walks the file end-to-end and reports any break. Chain breaks indicate either tampering or a bug; both are surfaced in the admin dashboard.

### Retention

Forever, partitioned monthly. ~3.6 MB/year sustained → ~300 KB/partition. No manual cleanup needed. Periodic backup (quarterly snapshot of the private bucket to a versioned location) provides tamper-recovery.

### Query

`scripts/lib/admin_audit.py::query()` for CLI / dashboard use. Plus the dashboard recent-events log §6.6.

## 8. UI surfaces summary

| Surface | Visibility | Component |
|---|---|---|
| `/admin` route | maintainer+ | Dashboard SPA |
| Inline force-release / reassign on reciter card | maintainer+ | `tabs/segments/components/reciter-card/AdminQuickActions.svelte` (new) |
| "Internal view" toggle | maintainer+ | adds `internal: true` to reciter list query — surfaces discarded |
| Banner: "You are editing a reciter held by …" | maintainer force-claiming | `lib/components/ForceClaimBanner.svelte` |
| Banner: "A maintainer is making corrections" | original assignee during force-claim | same component |
| Reason-required modals | every override | `lib/components/ConfirmWithReason.svelte` |
| Discard confirmation phrase | discard action | `lib/components/TypedConfirmation.svelte` |
| Per-Job retry buttons | maintainer+ | `tabs/admin/PublishOperations.svelte` |

## 9. Anti-creep design rules

Three rules, hard:

1. **Default flow handles 95% of cases.** Every override action must document the recurring problem it solves. No speculative admin features.
2. **No "edit anything" admin role.** Each override is a specific named action with a specific audit entry. No generic escape hatch.
3. **Maintainer count stays small.** Recommend 3–10. Reviewed via PR for `inspector_maintainers.json`. Onboarding doc explains expected response times.

Soft conventions:

- Every override requires a `reason` string ≥ 10 chars.
- Destructive actions (discard, mass-bulk) require typed confirmation matching the slug name.
- Bulk owner-only actions have a 24h soft-lock cancellable by another owner.
- No silent maintainer actions — everything lands in the audit log.

## 10. CLI parity

Web admin and CLI tools complement; they don't replace.

| Action | Web | CLI | Why |
|---|:---:|:---:|---|
| Force-release | ✓ | — | Web is faster; CLI dropped (no GitHub PR primitive to fall back to in v2) |
| Reassign | ✓ | — | Same |
| Force-claim edit | ✓ | — | Tied to a session, web-only |
| Manual state override | ✓ | ✓ | CLI for batch / scripted recovery (writes via `huggingface_hub` directly to bucket) |
| Discard | ✓ | ✓ | Same |
| Catalog edit | ✓ (web → bucket direct) | ✓ (`process_requests.py`, must be updated to write to bucket too) |
| Pipeline rerun | ✓ (trigger) | ✓ (full) | Web fires; CLI / HPC owns execution |
| Re-extraction with custom params | — | ✓ | Too many parameters for a sane web form |
| Param-rerun | — | ✓ | Same |
| Mass schema migration | — | ✓ | Repo-wide changes belong in version-controlled scripts |
| Edit `data/inspector_roles.json` | — | PR | Single canonical workflow (consolidated owners + maintainers) |
| Rotate Space `INSPECTOR_HF_TOKEN` | ✓ (owner-instructions) | ✓ | Web shows the runbook step; the actual rotation is in HF Space settings UI |

The CLI surfaces stay documented in the `process-requests` skill and `inspector/CLAUDE.md`.

## 11. Events introduced or extended by admin actions

All event names use canonical `<noun>.<verb>` namespacing. Full vocabulary lives in [`inspector-state-management.md`](inspector-state-management.md) §4. This table is the admin-facing slice.

| Event | Fired by | Required fields (in `payload` unless noted) | Effect |
|---|---|---|---|
| `reciter.marked_ready` | contributor endpoint | `slug, actor.hf_user_id` | `marked_ready = 1` (no state transition) |
| `reciter.unmarked_ready` | contributor endpoint | `slug, actor.hf_user_id` | `marked_ready = 0` |
| `reciter.merge_rejected` | maintainer endpoint | `slug, original_assignee_hf_id, reason` | `marked_ready = 0` (admin path) |
| `reciter.published` | maintainer endpoint | `slug` | `under_review (marked_ready=1) → awaiting_timestamps`; fires HF Jobs + GH Actions fan-out |
| `claim.force_released` | admin endpoint | `slug, original_assignee_hf_id, reason` | `under_review → awaiting_review`; clears assignee + marked_ready |
| `claim.reassigned` | admin endpoint | `slug, from_hf_id, to_hf_id, to_login, reason` | various → `under_review`; sets new assignee_* |
| `claim.force_acquired` | admin endpoint (implicit via first save on not-owned reciter) | `slug, original_assignee_hf_id` | Sets `force_assignee_hf_id`, `force_assignee_since` (persisted in SQLite, NOT ephemeral) |
| `claim.force_released_auto` | backend timer (or boot-time check) | `slug, original_assignee_hf_id` | Clears `force_assignee_*` after 30-min lease |
| `admin.force_set_state` | admin endpoint | `slug, from_state, to_state, reason` | Narrow allowed pairs only — see §5.4a. Returns 400 for any other pair. |
| `admin.force_clear_assignee` | admin endpoint | `slug, original_assignee_hf_id, reason` | Clear assignee_* + marked_ready. State unchanged. |
| `admin.force_unmark_ready` | admin endpoint | `slug, original_assignee_hf_id, reason` | `marked_ready = 0` (admin path; doesn't require assignee match) |
| `admin.force_revision_bump` | admin endpoint | `slug, reason` | `revision += 1` (debug-only) |
| `reciter.discarded` | admin endpoint | `slug, reason` | `visibility = 'discarded'`. **Lifecycle state unchanged.** |
| `reciter.undiscarded` | admin endpoint | `slug` | `visibility = 'public'` (from `'discarded'`) |
| `reciter.archived` | admin endpoint | `slug, reason` | `visibility = 'archived'`. Allowed only from `completed`. |
| `reciter.unarchived` | admin endpoint | `slug` | `visibility = 'public'` (from `'archived'`) |
| `catalog.added` | admin endpoint | `slug, row, reason` | New row in catalog SQLite |
| `catalog.edited` | admin endpoint | `slug, patch, reason` | Mutated mutable fields on existing row |
| `catalog.audio_source_added` | admin endpoint (rare) | `source_id, row, reason` | New row in `audio_sources` table |
| `pipeline.triggered` | admin endpoint | `slug, kind, reason` | None (state may transition later when pipeline emits its own event) |
| `admin.job_rerun` | admin endpoint | `slug, job_type, original_job_id, new_job_id, reason` | None (re-enqueues HF Job) |

**No `state.manual_override` wildcard.** Replaced by the discrete `admin.force_*` events above. If a recovery scenario doesn't fit any of them, add a new named event — that's the workflow. State-machine transition matrix in [`inspector-state-management.md`](inspector-state-management.md) §4 enforces this at the validator level.

**No `discarded` state.** Replaced by `visibility = 'discarded'` orthogonal to lifecycle ([`inspector-state-management.md`](inspector-state-management.md) §4). Round-trip preserves lifecycle position.

## 12. Phased rollout

Maps onto the parent doc's phases.

### Phase 4 — Read-only admin dashboard (was misslotted as Phase 1 in earlier drafts; needs OAuth from Phase 3)

- `/admin` route gated by maintainer role (resolved against `inspector_owners.json` + optional `inspector_maintainers.json`).
- System health, all-reciters, stalled-reciters, recent-events sections wired up (read-only).
- No override actions yet.
- Audit log file readable in dashboard, but no writers yet (the bucket has the file pre-seeded by the migration script with an initial entry).

**Acceptance:** maintainers see full state of the system; non-maintainers get 404 on `/admin`; dashboard renders in p99 ≤ 800 ms.

### Phase 3 — Claim overrides

- Force-release, reassign, force-claim, send-back-from-ready implemented as admin endpoints.
- All write through `state.transition()` with maintainer role check.
- Audit log writes flowing.

**Acceptance:** all four actions work end-to-end; audit entries appear; original assignees see appropriate UI feedback.

### Phase 5 — Lock overrides + publish

- Force-claim edit pathway implemented (parallel writes serialized by mutex).
- Publish endpoint live (`POST /api/admin/publish/<slug>` → state transition + fan-out).
- Banner UX for original assignee + force-claiming maintainer.

**Acceptance:** force-claim doesn't corrupt the original assignee's bucket state; auto-release after 30 min works; both parties' saves appear correctly attributed in audit log.

### Phase 6 — Catalog, state override, pipeline trigger, discard, bulk

- Catalog edit endpoint + opens PR flow.
- Manual state override.
- Pipeline trigger.
- Discard endpoint + new `discarded` state.
- Bulk actions tab (owner-only).
- 24h soft-lock implementation for owner-only destructive actions.
- Re-run failed publish Job endpoint.

**Acceptance:** every override reachable from the dashboard; audit log captures every action; bulk soft-lock can be cancelled by another owner mid-window.

## 13. Risks and open questions

### `data/inspector_roles.json` cache stale during emergency

Owner needs to revoke a role urgently. The 60 s cache means the change takes up to 60 s to propagate. Acceptable. Owner can additionally call `POST /api/admin/refresh-roles` (owner-only) to force-refresh.

### Audit log tampering

Even though Inspector only appends, an owner with bucket-write access could in principle truncate or rewrite. **Mitigation:** the `prev_hash` chain detects breaks (`scripts/lib/admin_audit.py::verify_chain()` runs in the dashboard); periodic backup of the private bucket's `state/` to a versioned location (quarterly). Real defense is process: the audit log is a check on maintainer behavior; tampering with it is itself a recordable event (chain break + absence of expected entries).

### Force-claim race with original assignee

Original assignee saves while maintainer force-claim is active. Mutex on `(slug)` serializes both. Each save commits to the bucket in turn. The only conflict is if both edit the same segment in the same window — the mutex orders them; the audit log records both. Acceptable.

### Bulk action mistakes

A maintainer accidentally clicks "Discard all `awaiting_review` older than 365 days" and walks away. Mitigation: 24h soft-lock + typed confirmation + preview list + another owner can cancel + restricted to owner role.

### Web admin replacing CLI

Risk: web becomes "good enough", CLI atrophies. Mitigation: §10 explicitly carves out which actions stay CLI-only.

<!-- Resolved by H3+H4: catalog moved to bucket, no PRs to merge. Section retained as historical note. -->

### Catalog edit PR review burden (resolved — no longer applicable)

Earlier draft routed catalog edits through GitHub PRs, which would have created an auto-merge queue burden. **Resolved by moving catalog to the bucket** (state-mgmt §3 + admin §5.6). No PRs, no auto-merge workflow, no PR-create token. Audit trail in `<bucket>/catalog/audit.jsonl` is the new review surface.

### Pipeline trigger from web vs HPC reality

The web button fires `pipeline.triggered` but the actual pipeline runs on Katana / HF Job. If those are down or the slug isn't on Katana, the trigger silently fails. Mitigation: the workflow validates pre-conditions and fires back a `pipeline.failed_to_start` event with reason. Visible in dashboard.

### `discarded` no longer a state — visibility flag instead

Earlier drafts modeled `discarded` as an 8th state value, requiring a schema bump and lifecycle-position loss on round-trip. v2 ships with `visibility: 'public' | 'discarded' | 'archived'` orthogonal to lifecycle. No schema bump needed; un-discard preserves the original state.

### Dashboard performance at scale

300 reciters × 20 history entries each + 100 audit entries fits in memory easily. But auto-refresh every 5 s × 50 maintainers = duplicate work. Mitigation: ETag on `/api/admin/health` and `/api/admin/reciters`; clients revalidate; backend caches the assembly for 1 s.

### Owner concentration

Too few owners (1) is bus-factor risk; too many (10+) dilutes accountability. Recommend 2–3.

### Action visibility for non-admin contributors

Should a reviewer see "this reciter was reassigned by maintainer X 2 days ago"? Soft-yes for transparency, but the audit log isn't anonymous-readable. Compromise: surface admin actions on the affected reciter's history panel in muted form, without actor names for non-maintainers.

### Self-assignment of admin role

The lookup needs to come from the file, not user-supplied data. Inspector resolves role server-side every request; never trusts client claims. Failure mode: GitHub raw fetch fails → fall back to baked-in snapshot (Phase 0 deploy includes a snapshot of the file in the image).

### Cross-tab session for maintainer

Maintainer opens dashboard in tab A and segments tab in tab B. Override actions in A should reflect in B. Mitigation: same state-refresh strategy as the rest of the app (30 s poll).
