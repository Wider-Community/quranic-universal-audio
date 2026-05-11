# Inspector Admin & Permissions (v2)

Companion to [`inspector-deployment-plan.md`](inspector-deployment-plan.md). Implementation-grade reference for user roles, the permission matrix, override actions, the admin dashboard, and the audit trail. Pairs with [`inspector-state-management.md`](inspector-state-management.md) (events vocabulary), [`inspector-data-storage.md`](inspector-data-storage.md) (bucket layout), and [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) (publish orchestration).

The parent doc's three roles (anonymous, contributor, claim-holder) are the happy path. This doc adds the elevated **maintainer** and **owner** tiers, the override surfaces they unlock, the dashboard that gives them visibility, and the audit trail that keeps them honest.

## 1. Model in one paragraph

Authorization is layered on top of authentication. Authentication answers "who is this user" (HF OAuth → `hf_user_id` canonical, `login` display-only). Authorization answers "what can they do" — derived from a single source: `<bucket>/access/inspector_roles.json` on GitHub (consolidated owners + maintainers — see §3). Anonymous users see public completed reciters. Logged-in contributors can claim one reciter at a time. Maintainers get a named, audited set of override actions — each one a discrete admin endpoint, **no `state.manual_override` wildcard**. Owners (small subset) can additionally rotate the Space's HF token, edit the roles file itself, and approve irrecoverable destructive actions. v2 ships only the admin operations enumerated in §5; deferred operations are explicitly flagged in §11. Every elevated action is named, audited to `<bucket>/audit/<YYYY>-<MM>.jsonl`, and confined to the smallest blast radius that solves a real recurring problem.

## 2. Roles

### `anonymous`

Not authenticated. Read-only access to public data — completed reciters, plus in-flight reciters if the parent doc's "anonymous viewing of in-review data" defaults to yes. All reads in deployed mode go through Inspector backend (which is the bucket-read path — anonymous users do not hit the bucket directly, since the bucket is private per D5).

### `contributor`

Authenticated HF user. Can:

- Read everything an anonymous user can read.
- Claim one `awaiting_review` reciter at a time.
- Edit segments for the reciter they hold a claim on.
- Release / mark-ready / unmark-ready their own claim.
- View their own contribution history (claims made, publishes, etc.) — sourced from `<bucket>/audit/<YYYY>-<MM>.jsonl`.

A contributor becomes a **claim-holder** while a claim is active. The claim-holder distinction is implicit (derived from `state.assignee_hf_id == user.hf_user_id`) and not a separate role.

### `maintainer`

Authenticated HF user with `role: maintainer` in `<bucket>/access/inspector_roles.json`. Adds: force-release, reassign, force-set-state on the narrow allowed pairs, catalog edit (direct to bucket), publish, send-back from `marked_ready=1`, discard/undiscard, internal data views.

Cannot: rotate the Space's HF token, edit the roles file, approve owner-only destructive actions.

### `owner`

Authenticated HF user with `role: owner` in `<bucket>/access/inspector_roles.json`. Superset of maintainer. Adds: edit `<bucket>/access/inspector_roles.json` via §5.7 access endpoints, rotate the Space's HF token, accept irrecoverable destructive actions (e.g. mass discard).

Owners count: recommend 2–3 minimum for bus-factor, ≤5 maximum to keep responsibility concentrated.

## 3. Role identity — single consolidated file on the bucket

**Sole source of role truth: `<bucket>/access/inspector_roles.json`** (was two separate files in earlier drafts; previously on GitHub raw — moved to the bucket).

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

Mutations via Inspector admin endpoints (§5.7); Inspector is the sole writer (same sole-writer pattern as state + catalog). Every mutation appends an `access.*` event to `<bucket>/audit/<YYYY>-<MM>.jsonl`. The first owner is hand-seeded at Phase 0 setup (see [`inspector-state-management.md`](inspector-state-management.md) §9 bootstrap).

### Why one file, why `hf_user_id` canonical, why soft-delete

- **One file** instead of two (`inspector_owners.json` + `inspector_maintainers.json`): collapses the failure mode where one file exists and the other doesn't, makes "promote to owner" a single-row edit instead of cross-file move.
- **`hf_user_id` canonical:** if a maintainer renames themselves on HF, login-keyed lookup silently revokes their role. The lookup is `member.hf_user_id == user.hf_user_id`, never `login`.
- **Soft-delete via `removed_at`:** historical role membership stays queryable. "Who was an owner when X bad action happened?" is a JSON scan + an `access.*` audit tail-grep, not a `git blame`.

### Backend resolution

```python
def resolve_role(user: AuthenticatedUser) -> Role:
    member = next(
        (m for m in ACCESS_STORE.values()
         if m.hf_user_id == user.hf_user_id and m.removed_at is None),
        None,
    )
    return member.role if member else Role.CONTRIBUTOR
```

`ACCESS_STORE` is an in-memory dict, hydrated from the bucket at startup, replaced atomically on every Inspector write (sole-writer pattern → no external refresh needed). No GitHub-raw fetch, no per-request HTTP, no force-refresh endpoint.

### Why the bucket (not GitHub)

Earlier drafts kept this on GitHub for CODEOWNERS-gated PR review. Moved to the bucket because:
- GitHub repo is public → maintainer HF IDs become a target list + privacy disclosure.
- Roles reference HF identifiers; everything else Inspector touches is HF-resident (state, catalog, audit). Keeping one file on GitHub adds an external availability dependency.
- Blast radius of a compromised Inspector is contained (audit log + reversibility); the "privilege-escalation" worst case doesn't match the actual editing-tool threat model.
- The bucket's audit log provides equivalent forensics to git history, in the same place as all other audit data.

## 4. Permission matrix

| Action | anon | contrib | maint | owner |
|---|:---:|:---:|:---:|:---:|
| View completed reciter | ✓ | ✓ | ✓ | ✓ |
| View in-flight reciter | ✓¹ | ✓ | ✓ | ✓ |
| View `discarded` reciter | — | — | ✓ | ✓ |
| View own claim history | — | ✓ | ✓ | ✓ |
| View any user's claim history | — | — | ✓ | ✓ |
| Claim a reciter | — | ✓ | ✓ | ✓ |
| Release own claim | — | ✓ | ✓ | ✓ |
| Edit segments (own claim) | — | ✓ | ✓ | ✓ |
| Mark own claim ready (`marked_ready=1`) | — | ✓ | ✓ | ✓ |
| Unmark own claim (`marked_ready=0`) | — | ✓ | ✓ | ✓ |
| **Publish a `(under_review, marked_ready=1)` reciter** | — | — | ✓ | ✓ |
| **Send back from `marked_ready=1`** | — | — | ✓ | ✓ |
| **Force-release someone else's claim** | — | — | ✓ | ✓ |
| **Reassign claim to specific user** | — | — | ✓ | ✓ |
| **Force-set state** (narrow allowed pairs only — see §5.4) | — | — | ✓ | ✓ |
| **Catalog entry edit** (direct to bucket, no PR) | — | — | ✓ | ✓ |
| **Discard / undiscard** (visibility flag, not a state) | — | — | ✓ | ✓ |
| View admin dashboard | — | — | ✓ | ✓ |
| View audit log | — | — | ✓ | ✓ |
| Edit `<bucket>/access/inspector_roles.json` | — | — | — | ✓ |
| Rotate the Space's `INSPECTOR_HF_TOKEN` | — | — | — | ✓ |
| Mass discard / bulk destructive | — | — | — | ✓ ² |

**No `state.manual_override` wildcard.** v2 ships discrete named operations (see §5 + state-mgmt §4). If a recovery scenario isn't covered by the listed admin events, the response is to add a new named one — not extend a wildcard. Discipline: write the use case, name the event, add to the matrix, ship.

¹ Default per parent doc Open Questions; can flip to maintainer-only later.
² Destructive bulk actions also require a typed confirmation phrase and a 24-hour soft-lock window before they fire (see §6.8).

**Deferred from v2** (no code, no events, no rows in this matrix until they ship — see §11 and D15):
- Edit-without-claim / force-claim
- Force-clear assignee
- Force-unmark-ready (admin path; reviewer-driven `reciter.unmarked_ready` still ships)
- Force revision bump (no `revision` column in v2)
- Archive / unarchive (`visibility = 'archived'` deferred; only `'public'` and `'discarded'` ship)
- Trigger pipeline rerun
- Re-run a publish HF Job

## 5. Override actions — full spec

Each override has: trigger, preconditions, request shape, side effects, audit-log entry, reversibility, UI affordance. **All overrides go through Inspector backend's `services/state.py::transition()` for state mutations** — same path as user actions, just gated by maintainer+ role. This keeps the state machine the single point of validation.

### 5.1 Force-release

**Use case:** reviewer disappeared mid-session; reciter has been `under_review` with no edits for >7 days; need to free it up for someone else.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/claim/force-release` |
| Body | `{ "slug": "...", "reason": "..." }` |
| Preconditions | reciter is `under_review`; caller is maintainer+ |
| State transition | `under_review → awaiting_review`; clears assignee + `marked_ready=0` |
| Event in audit | `claim.force_released { slug, actor: {hf_user_id, login_at_time, role}, original_assignee_hf_id, reason }` |
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
| Preconditions | reciter is `awaiting_review` or `under_review`; `to_login` resolves via `GET https://huggingface.co/api/users/<to_login>/overview` (returns 200 with stable `_id`; 404 → `BadRequest`) |
| State transition | → `under_review`, sets `assignee_hf_id = _id`, `assignee_login = canonical_login` (the API's casing wins over user input) |
| Event in audit | `claim.reassigned { slug, actor: {hf_user_id, login_at_time, role}, from_hf_id, to_hf_id, to_login, reason }` |
| Reversibility | Soft — reassign back |
| UI | "Reassign…" button + free-text login input (no public typeahead API exists). On blur, the UI calls `/api/admin/users/lookup?login=<x>` (a thin proxy to the HF endpoint) and shows `fullname + avatarUrl` from the response so the maintainer can confirm before submit. |

No invitation needed in v2 — HF users don't need any specific repo permission to use the Inspector; the reassign just sets the assignee fields.

**Why store both `to_login` and `to_hf_user_id`:** the HF `_id` (= OIDC `sub`) is **stable across username renames**; the `login` is mutable display only. All claim-ownership checks compare `assignee_hf_id`, never `assignee_login`. If a reviewer renames their HF account mid-claim, their existing claim survives.

### 5.3 Force-set state (narrow allowed targets)

**Use case:** state machine rejected a transition that should have happened, or a manual operational fix is needed.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/state/force-set/<slug>` |
| Body | `{ "to_state": "...", "reason": "..." }` |
| Preconditions | caller is maintainer+; `(from, to)` is in the allowed-pairs list (see below) |
| State transition | from → to (no automatic side effects) |
| Event in audit | `admin.force_set_state { slug, actor: {hf_user_id, login_at_time, role}, from_state, to_state, reason }` |
| Reversibility | Manual — set back via the reverse-pair if allowed |
| UI | Dropdown in admin dashboard restricted to the allowed targets for the row's current state |

**Allowed `(from, to)` pairs** (intentionally narrow — extend by adding to this list, not by widening the endpoint):
- `catalogued ↔ awaiting_alignment` (maintainer kicks off / unwinds an alignment run while Inspector-native intake is still deferred)
- `awaiting_alignment ↔ awaiting_review` (alignment recovery; also used to advance state once a maintainer-triggered Katana run finishes)
- `awaiting_timestamps ↔ completed` (timestamps-job recovery)
- `under_review → awaiting_review` (alternative path to `claim.force_released` that doesn't bump force-release-count)

Any other pair returns 400 with the message "use a discrete operation: see admin §5.X." If a real use case appears for a missing pair, add it to the list and to the state-mgmt matrix; do NOT widen this endpoint to "any → any."

### 5.4 Discard / Undiscard (visibility flag)

**Use case:** reciter request was made in error, audio source is broken, etc. **`discarded` is NOT a state** — it's `visibility = 'discarded'` orthogonal to lifecycle (see [`inspector-state-management.md`](inspector-state-management.md) §4). Reversal preserves the original lifecycle position.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/discard/<slug>` |
| Body | `{ "reason": "...", "confirmation_phrase": "discard <slug>" }` |
| Preconditions | caller is maintainer+; `confirmation_phrase` matches `discard <slug>` exactly |
| Effect | `visibility = 'discarded'`, `visibility_reason = <reason>`. **Lifecycle state unchanged.** |
| Event in audit | `reciter.discarded { slug, actor: {hf_user_id, login_at_time, role}, reason }` |
| Reversibility | `POST /api/admin/undiscard/<slug>` clears the visibility flag back to `'public'`; lifecycle position preserved |
| UI | "Discard" button only visible after typing `discard <slug>` in a confirmation field |

Discarded reciters are hidden from anonymous viewers and from the regular reciter list. Maintainers see them under "Internal" filter on the admin dashboard. The reciter retains its lifecycle position — un-discarding is just clearing the flag.

In v2 only `visibility ∈ {'public', 'discarded'}` ships. `'archived'` is deferred (see §11 and D15).

### 5.5 Catalog edit (direct to bucket)

**Use case:** display name typo, riwayah classification correction, audio source URL change, adding a new variant, adding a new vocab term (`riwayat`, `styles`, `audio_sources`).

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/catalog/edit/<slug>` (edit existing reciter row), `POST /api/admin/catalog/add` (new reciter row), `POST /api/admin/catalog/vocab/add` (new vocab term) |
| Body (edit) | `{ "patch": { "name_en": "...", "riwayah": "...", ... }, "reason": "..." }` |
| Body (add reciter) | `{ "row": { "slug": "...", "reciter_id": "...", ... }, "reason": "..." }` |
| Body (add vocab) | `{ "kind": "riwayat" \| "styles" \| "audio_sources", "value": ..., "reason": "..." }` |
| Preconditions | caller is maintainer+; payload passes catalog schema validation; for edit, slug exists; patch does NOT touch immutable fields (`slug`, `reciter_id`) |
| Side effect | Direct write to `<bucket>/catalog/reciter_catalog.json` via `inspector/services/catalog.py::transition()` (mirrors `state.py` pattern: schema validate → atomic upload_file → audit append → in-memory cache update). Fires `repository_dispatch reciter.catalog_changed` to trigger `update-reciters.yml`. |
| Event in audit | `catalog.edited` / `catalog.added` / `catalog.vocab_added` `{ slug?, actor: {hf_user_id, login_at_time, role}, patch | row | kind+value, reason }` (in `<bucket>/audit/<YYYY>-<MM>.jsonl`) |
| Reversibility | Reverse via another `catalog.edited` (audit log preserves prior values) |
| UI | Catalog editor modal with form fields per schema; immutable fields rendered read-only |

**Why direct, not PR:** v2's whole architectural shift is "no per-reciter PRs." Keeping catalog on PRs would require a catalog-auto-merge workflow, a separate PR-create PAT, and a PR review queue — only for the one remaining PR surface. Catalog has the same write characteristics as state (low cadence, maintainer+ gated, schema-validated, audit-trailed) — so it belongs in the same operational model.

**Role mutations** (`<bucket>/access/inspector_roles.json`) flow through admin endpoints §5.7 below — Inspector is the sole writer; PR-review path is dropped.

### 5.6 Send back from `marked_ready=1`

**Use case:** maintainer reviewed a `(under_review, marked_ready=1)` reciter, found issues, wants the reviewer to fix them rather than publishing.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/ready/send-back` |
| Body | `{ "slug": "...", "reason": "..." }` |
| Preconditions | reciter is `under_review` with `marked_ready=1`; caller is maintainer+ |
| State transition | `marked_ready` flips to 0; lifecycle stays `under_review`; assignee retained |
| Event in audit | `reciter.merge_rejected { slug, actor: {hf_user_id, login_at_time, role}, original_assignee_hf_id, reason }` |
| Reversibility | Reviewer can mark ready again after fixes |
| UI | "Send back…" button on the reciter card when `marked_ready=1` |
| Confirmation | Modal with required reason field (≥10 chars) |

The reason text is appended to the reciter's history entry in the state file; surfaced in the reviewer's dashboard banner.

### 5.7 Access grant / revoke / update (role-mutation endpoints)

**Use case:** maintainer-or-owner promotes/demotes/removes users in `<bucket>/access/inspector_roles.json`.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/access/grant` · `POST /api/admin/access/revoke` · `POST /api/admin/access/update` |
| Body (grant) | `{ "hf_user_id": "...", "login": "...", "role": "owner|maintainer", "reason": "..." }` |
| Body (revoke) | `{ "hf_user_id": "...", "reason": "..." }` (soft-delete) |
| Body (update) | `{ "hf_user_id": "...", "login": "...", "role": "..." }` (login refresh OR tier change) |
| Preconditions | Owner-only to grant `owner`; maintainer+ to grant/revoke `maintainer`. Reason ≥10 chars on grant/revoke. |
| Audit event | `access.role_granted` / `access.role_revoked` / `access.role_updated` |
| Reversibility | Revoke is soft-delete (sets `removed_at`); grant re-issue restores. |

### 5.8 Unlock for revision

**Use case:** maintainer wants to re-edit a `released` or `completed` reciter (typo fix, audio replacement, schema migration).

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/unlock/<slug>` |
| Body | `{ "reason": "..." }` (≥10 chars) |
| Preconditions | reciter state ∈ {`released`, `completed`}; caller is maintainer+ |
| State transition | `released | completed → awaiting_review`; sets `revision_in_progress = {unlocked_from_state, unlocked_at, unlocked_by_hf_id, original_assignee_hf_id}`; clears assignee_*; `marked_ready=0` |
| Side effects | Copies `<bucket>/published/<slug>/` → `<bucket>/wip/<slug>/` (published files retained so the public continues seeing the current version). |
| Audit event | `admin.unlocked_for_revision { slug, actor, unlocked_from_state, original_assignee_hf_id, reason }` |
| Re-publish behavior | When the row next reaches `released`, if `revision_in_progress.unlocked_from_state == "completed"` the row auto-transitions to `completed` + fires `reciter.dataset_published`. If it was `released`, it stays at `released`. `revision_in_progress` is cleared on re-publish. |

### 5.9 Publish to dataset

**Use case:** maintainer promotes a `released` reciter to the public HF dataset.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/publish-to-dataset/<slug>` · batch via `POST /api/admin/publish-to-dataset` body `{"slugs": [...]}` |
| Preconditions | reciter state == `released`; caller is maintainer+ |
| State transition | `released → completed` |
| Side effects | Dispatches `repository_dispatch sync-dataset.yml` to add the slug to the HF dataset |
| Audit event | `reciter.dataset_published { slug, actor }` |

### 5.10 Remove from dataset

**Use case:** maintainer pulls a `completed` reciter back out of the dataset without unpublishing (keep files on bucket, drop from dataset).

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/remove-from-dataset/<slug>` |
| Body | `{ "reason": "..." }` (≥10 chars) |
| Preconditions | reciter state == `completed`; caller is maintainer+ |
| State transition | `completed → released` |
| Side effects | Dispatches dataset rebuild dropping the slug; bucket files retained |
| Audit event | `reciter.removed_from_dataset { slug, actor, reason }` |

### 5.11 Unpublish

**Use case:** full unpublish — remove from public + dataset; reciter goes back to `awaiting_review` for a fresh re-review.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/unpublish/<slug>` |
| Body | `{ "reason": "...", "confirmation_phrase": "unpublish <slug>" }` |
| Preconditions | reciter state ∈ {`released`, `completed`}; caller is maintainer+; reason ≥10 chars; typed confirmation matches exactly. |
| State transition | `released | completed → awaiting_review` |
| Side effects | Moves `<bucket>/published/<slug>/` → `<bucket>/wip/<slug>/`. If was `completed`, also dispatches dataset rebuild dropping slug. |
| Audit event | `reciter.unpublished { slug, actor, original_state, reason }` |
| Reversibility | Re-edit + re-publish (or `admin.force_set_state` if maintainer wants to skip review) |

### 5.12 Refresh timestamps

**Use case:** new MFA model version; maintainer wants fresh timestamps for one or many published reciters.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/refresh-timestamps/<slug>` · batch via `POST /api/admin/refresh-timestamps` body `{"slugs": [...]}` or filter `{"riwayah": "hafs"}` |
| Body | `{ "reason": "..." }` (optional for single, encouraged for batch) |
| Preconditions | reciter state ∈ {`released`, `completed`} for target slugs; caller is maintainer+ |
| State transition | None (state stays); appends new job_id(s) to `timestamps_job_ids` on each row |
| Side effects | Enqueues HF Job(s); upon completion, `reciter.timestamps_completed` fires per slug (state stays the same since it's already `released`/`completed`); job-completion webhook updates the row. |
| Audit event | `admin.batch_timestamps_refresh { slugs, actor, reason }` — single audit line for the whole batch |

### 5.13 Direct admin edit on published reciters

**Use case:** maintainer needs to fix a small issue (typo, mis-segmented ayah) without going through the unlock + re-review flow.

| Field | Value |
|---|---|
| HTTP | `POST /api/seg/save/<slug>/<chapter>` (same endpoint as contributor saves; gated to maintainer+ when state ∈ {`released`, `completed`}) |
| Preconditions | reciter state ∈ {`released`, `completed`}; caller is maintainer+; state ≠ `awaiting_timestamps` (saves return 409 during MFA job) |
| Target | Saves write to `<bucket>/published/<slug>/` directly |
| Edit history | Batch records `actor.role = "maintainer"` |
| Audit event | `published.edited { slug, chapter, actor, batch_id }` per save batch |
| UI | Banner: "You're editing a published reciter — changes apply immediately. Click 'Refresh timestamps' when done." |
| Note | Use the unlock-for-revision flow (§5.8) for substantial changes that need a re-review; this surface is for trivial fixes. |

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
  "active_timestamps_jobs": 1,
  "backend": { "version": "...", "commit": "...", "uptime_seconds": 184231 },
  "state_file": { "last_updated_at": "...", "reciters_count": 287 }
}
```

### 6.2 All reciters

Sortable, filterable table. Columns: slug, state pill, `marked_ready` flag, days-in-state, assignee, last activity, quick-action buttons.

Filters: state (multi), assignee (text), riwayah, source, "stalled only" toggle, "discarded only" toggle.

Default sort: days-in-state desc.

### 6.3 Stalled reciters

Auto-populated from these rules (configurable per-state thresholds):

| State / signal | Threshold |
|---|---|
| `awaiting_alignment` | >7 days since transition |
| `awaiting_review` | >30 days with `assignee_hf_id == null` |
| `under_review` (`marked_ready=0`) | >14 days since last save in audit log |
| `under_review` (`marked_ready=1`) | >7 days awaiting maintainer publish |
| `awaiting_timestamps` | >7 days since transition (timestamps-job likely failed silently) |

Each row shows: slug, state, days stalled, recommended action, action button.

### 6.4 Active sessions

Real-time view of in-memory state:

| slug | assignee_login | claim_age | last_save_age | parsed_cache_hit |
|---|---|---|---|---|

Quick actions per row: force-release, view session details (recent saves from `edit_history.jsonl`).

### 6.5 Active timestamps refresh

For any reciter in `awaiting_timestamps`, show the tracked `timestamps_job_id` and on-demand fetch of its current HF Jobs API status:

| slug | timestamps_job_id | dispatch | status (on demand) | published_at |
|---|---|---|---|---|
| saad_al_ghamdi | job_abcd | ✓ | (click to check) | — |

Manual "re-enqueue" button on each row if the maintainer wants a fresh attempt; this fires a new `timestamps-refresh` invocation against the same slug. Auto-polling and a background failed-job tracker are deferred (D1, D15).

### 6.6 Recent events log

Sourced from `<bucket>/audit/<YYYY>-<MM>.jsonl`. Last 100 entries, sorted desc.

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

Each bulk action lists affected slugs in a preview before firing. Soft-lock: clicking Run schedules the action 24h in the future; another owner can cancel during that window. Bulk archive is deferred (per §11); bulk pipeline-trigger is deferred.

## 7. Audit log

### File

`<bucket>/audit/<YYYY>-<MM>.jsonl`. Append-only JSONL, partitioned per-month from day one. Written by Inspector backend on every state-mutating event via direct `huggingface_hub.upload_file()` (bypasses mount flush window — durability is the priority for state events).

There is exactly one `audit/` folder under the single bucket per env (per D5). Reciter / claim / catalog / admin events all share it; the `event` field discriminates.

### Record schema

`schema_version` lives once per partition file in `<bucket>/audit/_meta.json`, NOT per record.

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
| `from_state`, `to_state` | yes for state transitions | Both null for orthogonal-flag events (`visibility`, `marked_ready`) and admin events with no state change |
| `actor.hf_user_id` | yes | Canonical immutable identifier |
| `actor.login_at_time` | yes | Snapshot — survives login renames |
| `actor.role` | yes | Snapshot — survives role changes |
| `reason` | yes for admin actions | Free-form, ≥10 chars |
| `payload` | yes | Event-specific TypedDict from `services/state.py` |
| `request_id` | yes | For traceability across Inspector + HF Job + dispatch logs |
| `result` | yes | `ok` or `failed` |

`prev_hash` is **not** a field. Tamper-detection-via-chain is dropped (per D12); offsite versioned snapshots are the recovery mechanism.

### Integrity

Tamper detection relies on two practices:

1. Inspector backend is the only writer — no other code path appends to `audit/`.
2. Periodic offsite snapshot: `bucket-data-hygiene.yml` (or a dedicated workflow) takes a quarterly versioned copy of `audit/` to a separate bucket / GitHub release. Differences between the live audit and the snapshot during overlap windows are the tamper signal.

No per-record hash chain — every line is independent JSON, easier to query and tail.

### Retention

Forever, partitioned monthly. ~3.6 MB/year sustained → ~300 KB/partition. No manual cleanup needed. Periodic backup (quarterly snapshot) is the tamper-recovery mechanism (per above).

### Query

`scripts/lib/admin_audit.py::query()` for CLI / dashboard use. Plus the dashboard recent-events log §6.6.

## 8. UI surfaces summary

| Surface | Visibility | Component |
|---|---|---|
| `/admin` route | maintainer+ | Dashboard SPA |
| Inline force-release / reassign on reciter card | maintainer+ | `tabs/segments/components/reciter-card/AdminQuickActions.svelte` (new) |
| "Internal view" toggle | maintainer+ | adds `internal: true` to reciter list query — surfaces discarded |
| Reason-required modals | every override | `lib/components/ConfirmWithReason.svelte` |
| Discard confirmation phrase | discard action | `lib/components/TypedConfirmation.svelte` |

## 9. Anti-creep design rules

Three rules, hard:

1. **Default flow handles 95% of cases.** Every override action must document the recurring problem it solves. No speculative admin features.
2. **No "edit anything" admin role.** Each override is a specific named action with a specific audit entry. No generic escape hatch.
3. **Maintainer count stays small.** Recommend 3–10. Mutations via §5.7 access endpoints; every change audited. Onboarding doc explains expected response times.

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
| Force-set state | ✓ | ✓ | CLI for batch / scripted recovery (writes via `huggingface_hub` directly to bucket) |
| Discard | ✓ | ✓ | Same |
| Catalog edit / add | ✓ (web → bucket direct) | ✓ (maintainer scripts that write via `huggingface_hub`) |
| Validators against bucket | — | ✓ | `validators/*.py` keep CLI wrappers for ad-hoc checks against the bucket; auto-runs are inside Inspector services + the scheduled `bucket-data-hygiene.yml` |
| Grant / revoke / update access roles | ✓ | ✓ | Web for normal use; CLI (writes via `huggingface_hub`) is the bootstrap path for the first owner before the admin UI is reachable |
| Rotate Space `INSPECTOR_HF_TOKEN` | ✓ (owner-instructions) | ✓ | Web shows the runbook step; the actual rotation is in HF Space settings UI |

The CLI surfaces stay documented in `inspector/CLAUDE.md`.

## 11. Events introduced or extended by admin actions

All event names use canonical `<noun>.<verb>` namespacing. Full vocabulary lives in [`inspector-state-management.md`](inspector-state-management.md) §4. This table is the admin-facing slice for v2.

| Event | Fired by | Required fields (in `payload` unless noted) | Effect |
|---|---|---|---|
| `reciter.marked_ready` | contributor endpoint | `slug, actor.hf_user_id` | `marked_ready = 1` (no state transition) |
| `reciter.unmarked_ready` | contributor endpoint | `slug, actor.hf_user_id` | `marked_ready = 0` (reviewer-driven) |
| `reciter.merge_rejected` | maintainer endpoint | `slug, original_assignee_hf_id, reason` | `marked_ready = 0` (admin path) |
| `reciter.published` | maintainer endpoint | `slug` | `(under_review, marked_ready=1) → awaiting_timestamps`; in-bucket move + dispatch + 1 timestamps job |
| `claim.force_released` | admin endpoint | `slug, original_assignee_hf_id, reason` | `under_review → awaiting_review`; clears assignee + `marked_ready=0` |
| `claim.reassigned` | admin endpoint | `slug, from_hf_id, to_hf_id, to_login, reason` | various → `under_review`; sets new assignee_* |
| `admin.force_set_state` | admin endpoint | `slug, from_state, to_state, reason` | Narrow allowed pairs only — see §5.3. Returns 400 for any other pair. |
| `reciter.discarded` | admin endpoint | `slug, reason` | `visibility = 'discarded'`. **Lifecycle state unchanged.** |
| `reciter.undiscarded` | admin endpoint | `slug` | `visibility = 'public'` (from `'discarded'`) |
| `catalog.added` | admin endpoint | `slug, row, reason` | New reciter row in `reciter_catalog.json` |
| `catalog.edited` | admin endpoint | `slug, patch, reason` | Mutated mutable fields on existing reciter row |
| `catalog.vocab_added` | admin endpoint (rare) | `kind, value, reason` | New entry under `vocab.riwayat` / `vocab.styles` / `vocab.audio_sources` / `vocab.channels` / `vocab.recording_contexts` |
| `reciter.dataset_published` | admin endpoint | `slug` | `released → completed`; dispatches dataset rebuild adding slug. (§5.9) |
| `reciter.removed_from_dataset` | admin endpoint | `slug, reason` | `completed → released`; dispatches dataset rebuild dropping slug. (§5.10) |
| `reciter.unpublished` | admin endpoint | `slug, original_state, reason` | `released | completed → awaiting_review`; moves published/ → wip/. (§5.11) |
| `admin.unlocked_for_revision` | admin endpoint | `slug, unlocked_from_state, original_assignee_hf_id, reason` | `released | completed → awaiting_review`; sets `revision_in_progress`. (§5.8) |
| `admin.batch_timestamps_refresh` | admin endpoint | `slugs[], reason` | Re-enqueues MFA timestamps job(s); appends to `timestamps_job_ids`. (§5.12) |
| `published.edited` | save endpoint | `slug, chapter, batch_id` | Maintainer direct edit on a `released` / `completed` reciter. (§5.13) |
| `access.role_granted` | admin endpoint | `target_hf_user_id, role, reason` | New entry in `<bucket>/access/inspector_roles.json`. (§5.7) |
| `access.role_revoked` | admin endpoint | `target_hf_user_id, reason` | Soft-delete via `removed_at`. (§5.7) |
| `access.role_updated` | admin endpoint | `target_hf_user_id, patch` | Login refresh or tier change. (§5.7) |

**Deferred from v2** (no events shipped, no endpoints, no audit-log entries until they're added):
- `claim.force_acquired` / `claim.force_released_auto` — force-claim is deferred entirely (no `force_assignee_*` columns, no 30-min lease, no auto-clear timer).
- `admin.force_clear_assignee`
- `admin.force_unmark_ready` (reviewer's `reciter.unmarked_ready` still ships)
- `admin.force_revision_bump` — no `revision` column; OCC is multi-replica forward-compat that's deferred (see D6 in `inspector-deferred.md`).
- `pipeline.triggered`
- `admin.job_rerun`
- `reciter.archived` / `reciter.unarchived` — `visibility = 'archived'` is deferred; only `'public'` and `'discarded'` ship in v2.
- `reciter.alignment_requested` — pipeline-triggered `awaiting_alignment` transitions are now a maintainer action via `admin.force_set_state` until Inspector-native intake lands (per D17 in canonical decisions; see also the new deferred entry in `inspector-deferred.md`).

**No `state.manual_override` wildcard.** Replaced by the discrete `admin.force_*` events above.

**No `discarded` state.** Replaced by `visibility = 'discarded'` orthogonal to lifecycle ([`inspector-state-management.md`](inspector-state-management.md) §4). Round-trip preserves lifecycle position.

## 12. Phased rollout

Maps onto the parent doc's phases.

### Phase 4 — Read-only admin dashboard (was misslotted as Phase 1 in earlier drafts; needs OAuth from Phase 3)

- `/admin` route gated by maintainer role (resolved against `<bucket>/access/inspector_roles.json`).
- System health, all-reciters, stalled-reciters, recent-events sections wired up (read-only).
- No override actions yet.
- Audit log file readable in dashboard, but no writers yet (the bucket has the file pre-seeded by the migration script with an initial entry).

**Acceptance:** maintainers see full state of the system; non-maintainers get 404 on `/admin`; dashboard renders in p99 ≤ 800 ms.

### Phase 3 — Claim overrides

- Force-release, reassign, send-back-from-ready implemented as admin endpoints.
- All write through `state.transition()` with maintainer role check.
- Audit log writes flowing.

**Acceptance:** all three actions work end-to-end; audit entries appear; original assignees see appropriate UI feedback.

### Phase 5 — Publish

- Publish endpoint live (`POST /api/admin/publish/<slug>` → state transition + in-bucket move + fan-out).
- `force-set-state` endpoint live with the narrow allowed pairs.
- Reason-required modal UX.

**Acceptance:** publishing a `_test_*` reciter end-to-end produces the right state, the right bucket layout, and the expected audit entries.

### Phase 6 — Catalog, discard, bulk

- Catalog edit / add / vocab-add endpoints live.
- Discard endpoint + visibility flag.
- Bulk actions tab (owner-only).
- 24h soft-lock implementation for owner-only destructive actions.

**Acceptance:** every override reachable from the dashboard; audit log captures every action; bulk soft-lock can be cancelled by another owner mid-window.

## 13. Risks and open questions

### `<bucket>/access/inspector_roles.json` cache stale during emergency

Owner needs to revoke a role urgently. The 60 s cache means the change takes up to 60 s to propagate. Acceptable. Owner can additionally call `POST /api/admin/refresh-roles` (owner-only) to force-refresh.

### Bulk action mistakes

A maintainer accidentally clicks "Discard all `awaiting_review` older than 365 days" and walks away. Mitigation: 24h soft-lock + typed confirmation + preview list + another owner can cancel + restricted to owner role.

### Web admin replacing CLI

Risk: web becomes "good enough", CLI atrophies. Mitigation: §10 explicitly carves out which actions stay CLI-only.

### Catalog edit PR review burden (resolved — no longer applicable)

Earlier draft routed catalog edits through GitHub PRs, which would have created an auto-merge queue burden. **Resolved by moving catalog to the bucket** (state-mgmt §3 + admin §5.5). No PRs, no auto-merge workflow, no PR-create token. Audit trail in `<bucket>/audit/<YYYY>-<MM>.jsonl` is the new review surface.

### `discarded` no longer a state — visibility flag instead

Earlier drafts modeled `discarded` as an extra state value, requiring a schema bump and lifecycle-position loss on round-trip. v2 ships with `visibility: 'public' | 'discarded'` orthogonal to lifecycle. No schema bump needed; un-discard preserves the original state. `'archived'` is a deferred third value.

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
