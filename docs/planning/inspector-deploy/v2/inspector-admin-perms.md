# Inspector Admin & Permissions (v2)

Companion to [`inspector-deployment-plan.md`](inspector-deployment-plan.md). Implementation-grade reference for user roles, the permission matrix, override actions, the admin dashboard, and the audit trail. Pairs with [`inspector-state-management.md`](inspector-state-management.md) (events vocabulary), [`inspector-data-storage.md`](inspector-data-storage.md) (bucket layout), and [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) (publish/HF Jobs orchestration).

The parent doc's three roles (anonymous, contributor, claim-holder) are the happy path. This doc adds the elevated **maintainer** and **owner** tiers, the override surfaces they unlock, the dashboard that gives them visibility, and the audit trail that keeps them honest.

## 1. Model in one paragraph

Authorization is layered on top of authentication. Authentication answers "who is this user" (HF OAuth → login + hf_user_id). Authorization answers "what can they do" — derived from a single source: `data/inspector_owners.json` on GitHub (and optionally `data/inspector_maintainers.json` if owners want a separate tier). Anonymous users see public completed reciters. Logged-in contributors can claim one reciter at a time. Maintainers can override claim assignments, force-release stuck sessions, edit catalog entries via PR, manually set state, publish, and access the admin dashboard. Owners (small subset) can additionally rotate the Space's HF token, edit the maintainers list itself, and approve irrecoverable destructive actions. Every elevated action is named, audited to `<bucket>/state/audit.jsonl`, and confined to the smallest blast radius that solves a real recurring problem.

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

Authenticated HF user whose login is in `data/inspector_maintainers.json` (or `data/inspector_owners.json`, since owners are a superset). Adds: force-release, reassign, manual state override, catalog edit (via PR), publish, send-back from ready, scratch flush, internal data views.

Cannot: rotate the Space's HF token, edit the owner/maintainer lists, approve owner-only destructive actions.

### `owner`

Maintainer whose login appears in `data/inspector_owners.json`. Superset of maintainer. Adds: edit `inspector_owners.json` and `inspector_maintainers.json` (CODEOWNERS-gated), rotate the Space's HF token, accept the irrecoverable destructive actions (e.g. mass discard).

Owners count: recommend 2–3 minimum for bus-factor, ≤5 maximum to keep responsibility concentrated.

## 3. Maintainer identity — file-only

**Sole source of role truth: `data/inspector_owners.json` (and optional `data/inspector_maintainers.json`) on GitHub.**

Schema:

```jsonc
// data/inspector_owners.json
{
  "schema_version": 1,
  "owners": [
    { "login": "ahmed", "added_at": "...", "added_by": "..." },
    { "login": "alice", "added_at": "...", "added_by": "..." }
  ]
}
```

```jsonc
// data/inspector_maintainers.json (optional; if absent, all maintainer power belongs to owners)
{
  "schema_version": 1,
  "maintainers": [
    { "login": "bob",   "added_at": "...", "added_by": "..." },
    { "login": "carol", "added_at": "...", "added_by": "..." }
  ]
}
```

Both files are PR-reviewed (CODEOWNERS gates them to existing owners). Adding/removing maintainers/owners is a deliberate audited action.

### Backend resolution

```python
def resolve_role(user: AuthenticatedUser) -> Role:
    if user.login in OWNERS_SET:           # cached from inspector_owners.json
        return Role.OWNER
    if user.login in MAINTAINERS_SET:      # cached from inspector_maintainers.json (if file exists)
        return Role.MAINTAINER
    return Role.CONTRIBUTOR
```

Cache: 60 s. Sources are GitHub raw URLs (no auth needed for public repo). Refreshed via `huggingface_hub`-equivalent simple HTTP fetch.

If both files are unreachable on Inspector startup, fall back to a stale snapshot baked into the Space image (`data/inspector_owners.json` is in the COPY list of the Dockerfile). If the file in the image disagrees with the live one (e.g. live has new entries), live wins on next refresh.

### Why not GitHub team

v1 considered a `<org>/inspector-maintainers` GitHub team queried via the App's team-membership API at request time. v2 drops this:

- We dropped the GitHub App entirely (HF OAuth replaces it).
- A small `huggingface_hub`-style HTTP fetch of one file is simpler than authed GitHub team API calls + caching.
- The PR-reviewed file is more transparent than team membership changes (visible in `git log`).
- Recovery: if the file is misconfigured, an owner edits it via PR; no need for a backup mechanism.

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
| **Manually set state (override state machine)** | — | — | ✓ | ✓ |
| **Catalog entry edit** (opens PR to GitHub) | — | — | ✓ | ✓ |
| **Discard / mark rejected** | — | — | ✓ | ✓ |
| **Trigger pipeline rerun** ³ | — | — | ✓ | ✓ |
| Re-run a failed publish HF Job | — | — | ✓ | ✓ |
| View admin dashboard | — | — | ✓ | ✓ |
| View audit log | — | — | ✓ | ✓ |
| Edit `inspector_owners.json` / `inspector_maintainers.json` | — | — | — | ✓ |
| Rotate the Space's `INSPECTOR_HF_TOKEN` | — | — | — | ✓ |
| Mass discard / bulk destructive | — | — | — | ✓ ⁴ |

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

### 5.4 Manual state override

**Use case:** state machine rejected a transition that should have happened, or a manual operational fix is needed.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/state/set` |
| Body | `{ "slug": "...", "to_state": "...", "reason": "..." }` |
| Preconditions | caller is maintainer+; `to_state` is in the closed enum |
| State transition | from-state → to-state (no automatic side effects) |
| Event in audit | `state.manual_override { slug, by_login, from_state, to_state, reason }` |
| Reversibility | Manual — set back |
| UI | Dropdown in admin dashboard for the reciter, listing all states. Confirmation modal repeats the slug name and target state |

Manual overrides do **not** automatically clean up assignee fields if the target state implies they should be null. The maintainer is responsible for setting them via separate admin endpoints (`/api/admin/claim/clear`, etc.). Intentional friction.

### 5.5 Discard

**Use case:** reciter request was made in error, audio source is broken, etc.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/discard` |
| Body | `{ "slug": "...", "reason": "...", "confirmation_phrase": "discard <slug>" }` |
| Preconditions | caller is maintainer+; `confirmation_phrase` matches `discard <slug>` exactly |
| State transition | (any) → `discarded` (new state — see §11) |
| Event in audit | `reciter.discarded { slug, by_login, reason }` |
| Reversibility | Manual state override back; bucket entry preserved unless owner deletes |
| UI | "Discard" button only visible after typing `discard <slug>` in a confirmation field |

Discarded reciters are hidden from anonymous viewers and from the regular reciter list. Maintainers see them in an "Internal" filter on the admin dashboard. Bucket entry stays; recovery is `state.manual_override` back.

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

`<bucket>/state/audit.jsonl` — append-only JSONL. Written by Inspector backend on every state-mutating event. **Bucket is mutable but Inspector only ever appends** to this file — there's no Inspector code path that rewrites it.

### Schema

```jsonc
{
  "schema_version": 1,
  "ts": "2026-05-09T14:23:11Z",
  "actor": { "login": "alice", "hf_user_id": "12345", "role": "maintainer" },
  "event": "claim.force_released",
  "slug": "saad_al_ghamdi",
  "from_state": "under_review",
  "to_state": "awaiting_review",
  "reason": "Reviewer unresponsive for 8 days, freeing for next contributor.",
  "payload": {
    "original_assignee": "bob"
  },
  "result": "ok",
  "request_id": "req_abc123",
  "replica": "inspector-prod"
}
```

Fields:

| Field | Required | Notes |
|---|---|---|
| `schema_version` | yes | Bump on schema change |
| `ts` | yes | ISO 8601 |
| `actor` | yes | Authenticated user; populated from session |
| `event` | yes | Event name from §5 / §11 |
| `slug` | yes (or `null` for non-reciter actions like bulk) | |
| `from_state`, `to_state` | yes for state transitions | Otherwise null |
| `reason` | yes for admin actions | Free-form, ≥10 chars |
| `payload` | yes | Event-specific |
| `result` | yes | `ok` or `failed` |
| `request_id` | yes | For traceability across logs |
| `replica` | yes | Inspector instance id (multi-replica future) |

### Retention

Forever, in bucket. ~3.6 MB/year sustained at typical scale. If pathological growth ever appears, archive to dated subdirs quarterly (`<bucket>/state/audit/<YYYY>/<MM>.jsonl`).

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
| Edit `inspector_owners.json` | — | PR | Single canonical workflow |
| Rotate Space `INSPECTOR_HF_TOKEN` | ✓ (owner-instructions) | ✓ | Web shows the runbook step; the actual rotation is in HF Space settings UI |

The CLI surfaces stay documented in the `process-requests` skill and `inspector/CLAUDE.md`.

## 11. New events for the state-management vocabulary

Extends [`inspector-state-management.md`](inspector-state-management.md) §4 events list:

| Event | Fired by | Required fields | Allowed transitions |
|---|---|---|---|
| `reciter.marked_ready` | contributor endpoint | `slug, login` | `under_review → ready_for_merge` (assignee retained) |
| `reciter.unmarked_ready` | contributor endpoint | `slug, login` | `ready_for_merge → under_review` (assignee retained) |
| `reciter.merge_rejected` | maintainer endpoint | `slug, by_login, original_assignee, reason` | `ready_for_merge → under_review` (assignee retained) |
| `reciter.published` | maintainer endpoint | `slug, by_login` | `ready_for_merge → awaiting_timestamps`, fires HF Jobs + GH Actions fan-out |
| `claim.force_released` | admin endpoint | `slug, by_login, original_assignee, reason` | `under_review → awaiting_review`, `ready_for_merge → awaiting_review` |
| `claim.reassigned` | admin endpoint | `slug, by_login, from_login, to_login, reason` | various → `under_review` |
| `claim.force_acquired` | admin endpoint (implicit via first save) | `slug, by_login, original_assignee` | none (ephemeral) |
| `claim.force_released_auto` | backend timer | `slug, by_login, original_assignee` | none (ephemeral) |
| `state.manual_override` | admin endpoint | `slug, by_login, from_state, to_state, reason` | any → any |
| `reciter.discarded` | admin endpoint | `slug, by_login, reason` | any → `discarded` |
| `catalog.edited` | admin endpoint (via PR) | `slug, by_login, patch, reason` | none (catalog file is on GitHub; bucket state unchanged until catalog PR merges) |
| `pipeline.triggered` | admin endpoint | `slug, by_login, kind, reason` | none (state may transition later when pipeline emits its own event) |
| `admin.job_rerun` | admin endpoint | `slug, by_login, job_type, original_job_id, new_job_id, reason` | none |

Plus a new state value:

| State | Description | Editable | Inspector behaviour |
|---|---|---|---|
| `discarded` | Reciter request rejected / abandoned. Hidden from anonymous lists. | No | Visible only to maintainers under "Internal" filter. |

The state-management transition matrix needs updating to allow `* → discarded` and to document `discarded → *` only via `state.manual_override`.

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

### `inspector_owners.json` cache stale during emergency

Owner needs to revoke a maintainer's role urgently. The 60 s cache means the change takes up to 60 s to propagate. Acceptable. Owner can additionally call `POST /api/admin/refresh-roles` (owner-only) to force-refresh.

### Audit log tampering

Even though Inspector only appends, an owner with bucket-write access could in principle truncate or rewrite. Mitigation: periodic backup to a versioned location (quarterly snapshot to a dataset). Real defense is process: the audit log is a check on maintainer behavior; tampering with it is itself a recordable event (the resulting absence of expected entries).

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

### `discarded` state and existing reciters

Adding `discarded` to the state enum is a schema bump. Migration: increment `schema_version`, update validator to accept both old and new for one cycle, then drop old.

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
