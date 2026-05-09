# Inspector Admin & Permissions

Companion to [`inspector-deployment-plan.md`](inspector-deployment-plan.md). Implementation-grade reference for user roles, the permission matrix, override actions, the admin dashboard, the audit log, and the new events the state workflow learns to handle. Pairs with [`inspector-state-management.md`](inspector-state-management.md) (events vocabulary), [`inspector-data-storage.md`](inspector-data-storage.md) (admin cache endpoints), and the future `inspector-auth-claim.md` (authentication mechanics, distinct from authorization handled here).

The parent doc's three roles (anonymous, contributor, claim-holder) are the happy path. This doc adds the elevated **maintainer** and **owner** tiers, the override surfaces they unlock, the dashboard that gives them visibility, and the audit trail that keeps them honest.

## 1. Model in one paragraph

Authorization is layered on top of authentication. Authentication answers "who is this user" (GitHub OAuth → login + id). Authorization answers "what can they do" — derived from a single source: a GitHub team membership check at request time. Anonymous users see public completed reciters. Logged-in contributors can claim one reciter at a time. Members of `<org>/inspector-maintainers` can override claim assignments, force-release stuck sessions, edit catalog entries, manually set state, and access an admin dashboard. A small set of owners (subset of maintainers, listed in `data/inspector_owners.json`) can additionally manage the maintainer team, rotate App credentials, and toggle feature flags. Every elevated action is named, audited, and confined to the smallest blast radius that solves a real recurring problem.

## 2. Roles

### `anonymous`

Not authenticated. Read-only access to public data — i.e. completed reciters, plus under-review reciters if the parent doc's "anonymous viewing of in-review PRs" defaults to yes (current default).

### `contributor`

Authenticated GitHub user. Can:

- Read everything an anonymous user can read.
- Claim one `awaiting_review` reciter at a time.
- Edit segments for the reciter they hold a claim on.
- Release their own claim.
- View their own contribution history (claims made, PRs merged).

A contributor becomes a **claim-holder** while a claim is active. The claim-holder distinction is implicit (derived from `data/reciter_state.json[<slug>].assignee == user.login`) and not a separate role.

### `maintainer`

Authenticated GitHub user who is a member of the `<org>/inspector-maintainers` GitHub team. Superset of contributor.

Adds: force-release, reassign, manual state override, catalog edit, pipeline triggers, cache invalidate, scratch flush, internal data views.

Cannot: manage the maintainer team itself, rotate App credentials, toggle feature flags.

### `owner`

Maintainer whose login appears in `data/inspector_owners.json`. Superset of maintainer.

Adds: manage the maintainer team (add/remove via state-changing PR to `inspector_owners.json` or via GitHub team UI), rotate App credentials, toggle feature flags, accept the irrecoverable destructive actions (e.g. mass discard).

Owners count is constrained — recommend 2–3 minimum for bus-factor, ≤5 maximum to keep responsibility concentrated.

## 3. Maintainer identity — decision

Three viable models. **Recommendation: GitHub team.**

| Model | Setup cost | Audit | Source-of-truth | Failure mode |
|---|---|---|---|---|
| **GitHub team** (`<org>/inspector-maintainers`) | Requires the org to exist + team UI access | Native — GitHub already logs team membership changes | The team itself (single API call) | If the team is deleted, lockout. Backup: `inspector_owners.json` always grants owner-level access regardless of team membership. |
| Config file (`data/inspector_maintainers.json`) | None | Repo PR history | A JSON file | Susceptible to merge-conflict drift if many maintainer changes; manual sync with reality |
| Repo admin role | None | Native | GitHub repo admin list | Couples Inspector privileges to repo write — far too broad; admins of the repo aren't necessarily Inspector reviewers |

**Adopted model:**

```
Maintainer = (member of <org>/inspector-maintainers) OR (login in inspector_owners.json)
Owner     = (login in inspector_owners.json)
```

The OR with `inspector_owners.json` ensures that if the GitHub team is misconfigured or deleted, owners can recover access via the repo file. Owners are also the only ones who can edit `inspector_owners.json` — the file's PR review is owner-only via a CODEOWNERS entry.

Backend resolution at request time:

```python
def resolve_role(user: AuthenticatedUser) -> Role:
    if user.login in OWNERS_SET:           # from cached inspector_owners.json
        return Role.OWNER
    if github_app.is_team_member(
        org=ORG, team='inspector-maintainers', login=user.login
    ):
        return Role.MAINTAINER
    return Role.CONTRIBUTOR
```

Cache: 60 s. On a 401 / 403 from the team membership endpoint, fall back to `CONTRIBUTOR` (fail-closed for elevation).

## 4. Permission matrix

| Action | anon | contrib | maint | owner |
|---|:---:|:---:|:---:|:---:|
| View completed reciter | ✓ | ✓ | ✓ | ✓ |
| View under-review reciter | ✓¹ | ✓ | ✓ | ✓ |
| View `discarded` / internal-only reciter | — | — | ✓ | ✓ |
| View own claim history | — | ✓ | ✓ | ✓ |
| View any user's claim history | — | — | ✓ | ✓ |
| Claim a reciter | — | ✓ | ✓ | ✓ |
| Release own claim | — | ✓ | ✓ | ✓ |
| Edit segments (own claim) | — | ✓ | ✓ | ✓ |
| **Force-release someone else's claim** | — | — | ✓ | ✓ |
| **Reassign claim to specific user** | — | — | ✓ | ✓ |
| **Edit segments without holding claim** | — | — | ✓ ² | ✓ ² |
| **Manually set state (override workflow)** | — | — | ✓ | ✓ |
| **Catalog entry edit (display name, riwayah, …)** | — | — | ✓ | ✓ |
| **Discard / mark rejected** | — | — | ✓ | ✓ |
| **Trigger pipeline rerun** ³ | — | — | ✓ | ✓ |
| Cache invalidate (`/api/internal/cache-invalidate`) | — | — | ✓ | ✓ |
| Force flush stuck scratch dir | — | — | ✓ | ✓ |
| View admin dashboard | — | — | ✓ | ✓ |
| View audit log | — | — | ✓ | ✓ |
| Manage maintainer team | — | — | — | ✓ |
| Edit `inspector_owners.json` | — | — | — | ✓ |
| Rotate App credentials | — | — | — | ✓ |
| Toggle feature flags | — | — | — | ✓ |
| Mass discard / bulk destructive | — | — | — | ✓ ⁴ |

¹ Default per parent doc Open Questions; can flip to maintainer-only later.
² Maintainer edit-without-claim auto-acquires a temporary claim labelled `force_held_by=<login>` that fires `claim.force_acquired` for audit. Released on session end or after 30 min of inactivity.
³ Web surface fires the pipeline; the pipeline itself remains CLI/HPC-driven. The web button just dispatches the job.
⁴ Destructive bulk actions also require a typed confirmation phrase and a 24-hour soft-lock window before they fire (see §6.5).

## 5. Override actions — full spec

Each override has: trigger, preconditions, request shape, dispatch event fired, audit-log entry shape, reversibility, UI affordance.

### 5.1 Force-release

**Use case:** reviewer disappeared mid-session; reciter has been `under_review` with no commits for >7 days; need to free it up for someone else.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/claim/force-release` |
| Body | `{ "slug": "...", "reason": "..." }` |
| Preconditions | reciter is `under_review`; caller is maintainer+ |
| Dispatch event | `claim.force_released { slug, by_login, original_assignee, reason }` |
| State transition | `under_review → awaiting_review`, clears assignee |
| Audit entry | yes (see §7) |
| Reversibility | Soft — the original assignee can re-claim (no auto-restore); their unflushed scratch is lost (was flushed to PR branch on lock break) |
| UI | Button on reciter card in dashboard ("Force-release") + on the reciter's segments tab when viewed by a maintainer |
| Confirmation | Modal: "Force-release `<slug>` from `<assignee>`? Their unflushed edits will be flushed to the PR branch. Reason (required):" |

Implementation note: before firing the dispatch, the backend force-flushes the active reviewer's scratch dir (multi-file commit on the PR branch as authored by the original reviewer). Their edits are not lost — they're just no longer locked.

### 5.2 Reassign

**Use case:** maintainer wants to hand a stuck reciter to a specific contributor.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/claim/reassign` |
| Body | `{ "slug": "...", "to_login": "...", "reason": "..." }` |
| Preconditions | reciter is `awaiting_review` OR `under_review`; `to_login` exists on GitHub; if not a collaborator, an invite is sent first |
| Dispatch event | `claim.reassigned { slug, by_login, from_login, to_login, reason }` |
| State transition | (any) → `under_review`, sets assignee to `to_login` |
| Audit entry | yes |
| Reversibility | Soft — reassign back |
| UI | "Reassign…" button + searchable user picker |

If `to_login` isn't a collaborator, the flow auto-invites and sets the state to `awaiting_review` with a `pending_invite_for: to_login` field — claim auto-fires when the invite is accepted.

### 5.3 Edit-without-claim (force-claim)

**Use case:** maintainer needs to make a quick correction on a reciter under someone else's claim without disrupting them long-term.

| Field | Value |
|---|---|
| HTTP | none — implicit; first save under maintainer auth on a reciter they don't own auto-acquires |
| Dispatch event | `claim.force_acquired { slug, by_login, original_assignee }` |
| State transition | none (assignee field unchanged); a separate `force_assignee` field is added with a 30-min lease |
| Audit entry | yes |
| Reversibility | Auto-released after 30 min inactivity or maintainer explicit release |
| UI | Banner: "You are editing a reciter held by `<assignee>`. Your edits will commit as you and auto-release in 30 min." |

The original assignee retains their claim. Force-claim is a parallel write lock with strict precedence: original assignee's saves are queued behind the maintainer's debounced commit until the maintainer releases. Visible to original assignee as: "A maintainer is making corrections — your saves will queue."

### 5.4 Manual state override

**Use case:** workflow rejected a transition that should have happened (e.g. rare race), or a manual operational fix is needed.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/state/set` |
| Body | `{ "slug": "...", "to_state": "...", "reason": "..." }` |
| Preconditions | caller is maintainer+; `to_state` is in the closed enum from `inspector-state-management.md` §4; transition is not strictly forbidden by §5 business rules (warn, do not block) |
| Dispatch event | `state.manual_override { slug, by_login, from_state, to_state, reason }` |
| State transition | from-state → to-state (no automatic side effects) |
| Audit entry | yes; includes prior state file diff |
| Reversibility | Manual — set back to the prior state |
| UI | Dropdown in admin dashboard for the reciter, listing all states. Confirmation modal repeats the slug name and target state |

Manual overrides do **not** automatically clean up assignee/PR fields if the target state implies they should be null. The maintainer is responsible for setting them via separate endpoints (`/api/admin/claim/clear`, etc.). This is intentional friction.

### 5.5 Discard

**Use case:** reciter request was made in error, audio source is broken, etc. Currently CLI-only per parent doc non-goals; this surfaces it on the web.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/discard` |
| Body | `{ "slug": "...", "reason": "...", "confirmation_phrase": "discard <slug>" }` |
| Preconditions | caller is maintainer+; `confirmation_phrase` matches `discard <slug>` exactly |
| Dispatch event | `reciter.discarded { slug, by_login, reason }` |
| State transition | (any) → `discarded` (new state — see §11 for vocabulary additions) |
| Audit entry | yes |
| Reversibility | Manual state override back; PR remains closed but can be reopened |
| UI | "Discard" button only visible after typing `discard <slug>` in a confirmation field |

Discarded reciters are hidden from anonymous viewers and from the regular reciter list. Maintainers see them in an "Internal" filter on the admin dashboard.

### 5.6 Catalog edit

**Use case:** display name typo, riwayah classification correction, audio source URL change.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/catalog/edit` |
| Body | `{ "slug": "...", "patch": { "display_name": "...", ... }, "reason": "..." }` |
| Preconditions | caller is maintainer+; patch passes catalog schema validation; slug already exists |
| Dispatch event | `catalog.edited { slug, by_login, patch, reason }` |
| Side effect | Workflow opens a PR against `data/reciter_catalog.json` with the patch applied (does NOT push directly to main — catalog edits are normal PRs) |
| Audit entry | yes |
| Reversibility | Reverse PR |
| UI | Catalog editor modal with form fields per schema |

Catalog edits flow through a PR rather than direct-to-main because they're rare, deserve scrutiny, and the existing PR review affordances are valuable. State edits go direct because they're frequent and the workflow validation is the review.

### 5.7 Pipeline trigger

**Use case:** maintainer wants to kick off re-extraction or timestamps refresh from the web instead of CLI/HPC.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/pipeline/trigger` |
| Body | `{ "slug": "...", "kind": "extraction" \| "timestamps" \| "validation", "reason": "..." }` |
| Preconditions | caller is maintainer+; reciter is in a state compatible with the requested operation |
| Dispatch event | `pipeline.triggered { slug, by_login, kind, reason }` |
| Side effect | Workflow dispatches the corresponding pipeline job (existing CLI/HPC job, no new infra) |
| Audit entry | yes |
| Reversibility | None — pipelines, once started, run to completion |
| UI | "Run pipeline…" picker on the reciter card |

The web surface only triggers; the pipeline itself runs unchanged on Katana / HF Space / GitHub Actions per existing wiring. Status visible in the dashboard's "CI health" section.

### 5.8 Cache invalidate

**Use case:** stale data after a manual fix or unusual event. Already exists in `inspector-data-storage.md` §3 as an internal endpoint; this doc spells out who's allowed.

| Field | Value |
|---|---|
| HTTP | `POST /api/internal/cache-invalidate?slug=<slug>` |
| HTTP (broad) | `POST /api/internal/cache-invalidate-all` |
| Auth | shared internal secret (existing — used by `segments-pr-merged.yml`) **OR** maintainer+ session cookie |
| Audit entry | yes (when triggered by user; not when triggered by webhook) |
| Reversibility | none needed (cache repopulates) |
| UI | "Invalidate cache" button on reciter card; "Flush all caches" button in dashboard system-health section (owner-only) |

### 5.9 Force flush scratch

**Use case:** scratch dir got into a weird state; want to discard pending in-memory changes and restart from PR branch.

| Field | Value |
|---|---|
| HTTP | `POST /api/admin/scratch/flush` |
| Body | `{ "slug": "...", "mode": "commit" \| "discard" }` |
| Preconditions | caller is maintainer+; reciter has an active scratch dir |
| Dispatch event | none (backend-internal) |
| Side effect | `commit` → fires the debounced commit then deletes scratch; `discard` → deletes scratch without committing |
| Audit entry | yes |
| Reversibility | `commit` mode: edits are now on PR branch; `discard` mode: edits are gone |
| UI | "Flush scratch" button on active session in dashboard |

`discard` mode requires a typed confirmation. Used for recovery from rare corruption.

## 6. Admin dashboard

A maintainer-gated SPA route at `/admin`. Hidden entirely (404) for non-maintainers — does not flash and disappear.

### 6.1 System health (top of page)

Live-refreshing card. Sources from `/api/admin/health`:

```jsonc
{
  "app_token": { "issued_at": "...", "expires_at": "...", "seconds_to_refresh": 480 },
  "github_rate_limit": { "limit": 5000, "remaining": 4612, "reset_at": "..." },
  "github_fetch_cache": { "entries": 184, "bytes": 312000000, "hit_rate_5m": 0.94 },
  "scratch": { "active_sessions": 3, "total_bytes": 28000000, "max_bytes": 524288000 },
  "debounce": { "queued": 1, "oldest_age_seconds": 12 },
  "backend": { "version": "...", "commit": "...", "uptime_seconds": 184231 },
  "state_file": { "last_updated_at": "...", "last_workflow_run": 1234, "reciters_count": 287 }
}
```

### 6.2 All reciters

Sortable, filterable table. Columns: slug, state pill, days-in-state, assignee, pr_number, last activity, quick-action buttons.

Filters: state (multi), assignee (text), riwayah, source, "stalled only" toggle, "internal only" toggle (shows discarded).

Default sort: days-in-state desc.

### 6.3 Stalled reciters

Auto-populated from these rules (configurable per-state thresholds):

| State | Threshold |
|---|---|
| `awaiting_alignment` | >7 days since transition |
| `awaiting_review` | >30 days with `assignee == null` |
| `under_review` | >14 days since last commit on PR head |
| `awaiting_timestamps` | >7 days since transition |

Each row shows: slug, state, days stalled, recommended action, action button.

### 6.4 Active sessions

Real-time view of in-memory state:

| slug | assignee | claim_age | last_save_age | scratch_size | debounce_in |
|---|---|---|---|---|---|

Quick actions per row: force-release, force-flush, view session details (recent saves).

### 6.5 Recent events log

Merged stream of:

- Last 100 entries from `data/reciter_state.json` history arrays (across all reciters, sorted by `at` desc).
- Last 100 entries from `data/admin_audit.jsonl`.

Filterable by event type, actor, slug. Each entry expandable to show the full payload.

### 6.6 CI health

Last 7 days of failed runs grouped by workflow + reciter. Quick-link to the GitHub run, retry button (calls `gh run rerun` via the App).

### 6.7 Contributor activity

Per-user (last 30 days):

- Claims made
- Edits committed (count of `[wip]` commits on PR branches authored by them)
- PRs merged
- Pending invitations
- Average days from claim to merge

Sortable. Linkable to the user's GitHub profile.

### 6.8 Pending invitations

Issued via `PUT /repos/.../collaborators/{login}` from the claim flow. Tracked in `data/reciter_state.json[<slug>].pending_invite_for` (new optional field). Dashboard shows: invitee, slug, invited_at, status (pending / accepted / expired). Action: cancel invitation.

### 6.9 Bulk actions (owner-only)

A separate tab. Operations like:

- Discard all reciters in state X older than Y days (with typed confirmation + 24h soft-lock)
- Bulk reassign all reciters from user A to user B (e.g. when a reviewer leaves)
- Bulk re-trigger pipeline for slugs matching a filter

Each bulk action lists the affected slugs in a preview before firing. Soft-lock means: clicking Run schedules the action 24h in the future; another owner can cancel during that window. Designed to make accidental mass-action recoverable.

## 7. Audit log

### File

`data/admin_audit.jsonl` — repo-tracked, append-only JSONL. Written by `update-reciter-state.yml` (which adds entries when admin-triggered events come through dispatch). Owner-only edit via CODEOWNERS — even maintainers can't tamper with the audit log.

### Schema

```jsonc
{
  "schema_version": 1,
  "at": "2026-05-09T14:23:11Z",
  "actor": "alice",
  "actor_role": "maintainer",
  "action": "claim.force_released",
  "slug": "saad_al_ghamdi",
  "reason": "Reviewer unresponsive for 8 days, freeing for next contributor.",
  "payload": {
    "original_assignee": "bob",
    "scratch_was_dirty": true,
    "scratch_flushed_to_branch": true
  },
  "result": "ok",
  "workflow_run_id": 1234
}
```

Fields:

| Field | Required | Notes |
|---|---|---|
| `schema_version` | yes | Bump on schema change |
| `at` | yes | ISO 8601 |
| `actor` | yes | GitHub login |
| `actor_role` | yes | `maintainer` or `owner` |
| `action` | yes | Event name from §5 / §11 |
| `slug` | yes (or `null` for non-reciter actions like cache flush all) | |
| `reason` | yes | Free-form maintainer-supplied; required by every override endpoint |
| `payload` | yes | Action-specific structured data |
| `result` | yes | `ok` or `failed` |
| `workflow_run_id` | yes | For traceability |

### Retention

Forever, in repo. Truncate to last 100k entries with archive-to-release if it ever bloats — not expected for years at the maintainer-action rate.

### Query

`scripts/lib/admin_audit.py::query()` for CLI / dashboard use. Plus the dashboard recent-events log §6.5.

## 8. UI surfaces summary

| Surface | Visibility | Component |
|---|---|---|
| `/admin` route | maintainer+ | Dashboard SPA (Svelte tab + sub-routes) |
| Inline force-release / reassign on reciter card | maintainer+ | `tabs/segments/components/reciter-card/AdminQuickActions.svelte` (new) |
| "Internal view" toggle | maintainer+ | adds `internal: true` to reciter list query — surfaces discarded etc. |
| Banner: "You are editing a reciter held by …" | maintainer force-claiming | `lib/components/ForceClaimBanner.svelte` |
| Banner: "A maintainer is making corrections" | original assignee during force-claim | same component |
| Reason-required modals | every override | `lib/components/ConfirmWithReason.svelte` |
| Discard confirmation phrase | discard action | `lib/components/TypedConfirmation.svelte` |

## 9. Anti-creep design rules

Three rules, hard:

1. **Default flow handles 95% of cases.** Every override action must document the recurring problem it solves. No speculative admin features — add when there's a real recurring problem the normal flow can't handle.
2. **No "edit anything" admin role.** Each override is a specific named action with a specific dispatch event with a specific audit entry. There is no generic "as admin, do X" escape hatch.
3. **Maintainer count stays small.** Recommend 3–10. Reviewed via PR for the team config (or via GitHub team UI with owner approval). Onboarding doc explains expected response times and revocation criteria.

Soft conventions:

- Every override requires a `reason` string ≥ 10 chars. The dashboard logs short reasons in red as a soft signal of carelessness.
- Destructive actions (discard, mass-bulk) require typed confirmation matching the slug name.
- Bulk owner-only actions have a 24h soft-lock cancellable by another owner.
- No silent maintainer actions — everything fires a dispatch event and lands in the audit log.

## 10. CLI parity

Web admin and CLI tools complement; they don't replace. The split:

| Action | Web | CLI | Why |
|---|:---:|:---:|---|
| Force-release | ✓ | ✓ | High-frequency, low-risk; web is faster |
| Reassign | ✓ | ✓ | Same |
| Force-claim edit | ✓ | — | Tied to a session, web-only |
| Manual state override | ✓ | ✓ | CLI for batch / scripted recovery |
| Discard | ✓ | ✓ | Same |
| Catalog edit | ✓ | ✓ | CLI exists today (`process_requests.py`) |
| Pipeline rerun | ✓ (trigger) | ✓ (full) | Web fires; CLI / HPC owns execution |
| Re-extraction with custom params | — | ✓ | Too many parameters for a sane web form |
| Param-rerun | — | ✓ | Same |
| Mass schema migration | — | ✓ | Repo-wide changes belong in version-controlled scripts |
| Cache invalidate | ✓ | ✓ | Both useful |
| Scratch flush | ✓ | — | Backend-internal — only meaningful while session is live |
| Manage maintainer team | GitHub team UI | — | Lives outside Inspector |
| Edit `inspector_owners.json` | — | PR | Single canonical workflow |
| Rotate App credentials | ✓ (owner) | ✓ | Both useful |

The CLI surfaces stay documented in the `process-requests` skill and `inspector/CLAUDE.md`.

## 11. New events for the state-management vocabulary

Extends [`inspector-state-management.md`](inspector-state-management.md) §4 events list:

| Event | Fired by | Required fields | Allowed transitions |
|---|---|---|---|
| `claim.force_released` | admin endpoint | `slug, by_login, original_assignee, reason` | `under_review → awaiting_review` |
| `claim.reassigned` | admin endpoint | `slug, by_login, from_login, to_login, reason` | `awaiting_review → under_review`, `under_review → under_review` (assignee swap) |
| `claim.force_acquired` | admin endpoint (implicit via first save) | `slug, by_login, original_assignee` | none (ephemeral; no state file change) |
| `claim.force_released_auto` | backend timer | `slug, by_login, original_assignee` | none (ephemeral) |
| `state.manual_override` | admin endpoint | `slug, by_login, from_state, to_state, reason` | any → any |
| `reciter.discarded` | admin endpoint | `slug, by_login, reason` | any → `discarded` |
| `catalog.edited` | admin endpoint (via PR) | `slug, by_login, patch, reason` | none (state file unchanged; catalog file changes via PR) |
| `pipeline.triggered` | admin endpoint | `slug, by_login, kind, reason` | none (state may transition later when the pipeline emits its own event) |
| `admin.cache_invalidated` | admin endpoint | `by_login, scope (slug or 'all'), reason` | none |
| `admin.scratch_flushed` | admin endpoint | `slug, by_login, mode` | none |

Plus a new state value:

| State | Description | Editable | Inspector behaviour |
|---|---|---|---|
| `discarded` | Reciter request rejected / abandoned. Hidden from anonymous lists. | No | Visible only to maintainers under "Internal" filter. |

The state-management transition matrix (§4 of that doc) needs updating to allow `* → discarded` and to document `discarded → *` only via `state.manual_override` (i.e. the recovery path is the manual override).

## 12. GitHub App permissions delta

Already-required (per `inspector-state-management.md` §9):

- `Contents: Write` (state file commits, edit pushes)
- `Pull requests: Write` (creating / updating review PRs)
- `Issues: Write` (label/assignee mirroring)
- `Members: Read` on the org (team membership lookup)

Added by this doc:

- `Administration: Read` — needed for `/api/admin/pipeline/trigger` to dispatch GitHub Actions workflows (or use existing `Actions: Write` if already there). Confirm before Phase 3.

No additional user-token scopes — admin authorization is derived from the App's team-membership lookup, not from broader OAuth scopes on the user side.

## 13. Phased rollout

Maps onto the parent doc's phases. Admin work lands incrementally — the dashboard ships in Phase 1 (read-only visibility), override actions phase in alongside the underlying operations they override.

### Phase 1 — Read-only admin dashboard

- `/admin` route gated by maintainer team membership.
- System health, all-reciters, stalled-reciters, recent-events sections wired up (read-only).
- No override actions yet.
- Audit log file created and read in dashboard, but no writers yet.

**Acceptance:** maintainers can see the full state of the system; non-maintainers get a 404 on `/admin`; performance tests show dashboard renders in p99 ≤ 800 ms.

### Phase 3 — Claim overrides

- Force-release, reassign, force-claim implemented as admin endpoints.
- Dispatch events `claim.force_released`, `claim.reassigned`, `claim.force_acquired` added to the state workflow.
- Dashboard quick-action buttons wired up.
- Audit log writes flowing.

**Acceptance:** all three actions work end-to-end, audit entries appear, dispatch events update state file correctly, original assignees see appropriate UI feedback.

### Phase 5a — Lock overrides

- Force-claim edit pathway implemented (parallel write lock).
- Force flush scratch endpoint live.
- Banner UX for original assignee + force-claiming maintainer.

**Acceptance:** force-claim doesn't corrupt the original assignee's edits; auto-release after 30 min works; both parties' commits are properly attributed.

### Phase 6 — Catalog, state override, pipeline trigger, discard, bulk

- Catalog edit endpoint + opens PR flow.
- Manual state override endpoint + dispatch event.
- Pipeline trigger endpoint.
- Discard endpoint + new `discarded` state.
- Bulk actions tab (owner-only).
- 24h soft-lock implementation for owner-only destructive actions.

**Acceptance:** every override is reachable both from the dashboard and from CLI parity tests; audit log captures every action; bulk soft-lock can be cancelled by another owner mid-window.

## 14. Risks and open questions

### Maintainer team setup dependency

Phase 1 depends on the GitHub team existing. If the org doesn't have one yet, that's a Phase 0 prerequisite (create the team, add 2–3 trusted users, document onboarding). Recover via `inspector_owners.json` if the team is misconfigured later.

### Audit log tampering

Even though CODEOWNERS gates `data/admin_audit.jsonl` to owners, an owner could in principle edit it. Mitigation: the audit log is **append-only** in the workflow that writes it (any commit that deletes lines from the file fails CI). The check lives in `validate_admin_audit.py`. Owner-side tampering would require disabling CI, which is loud.

### Force-claim race with original assignee

Original assignee saves while maintainer force-claim is active. Two writers, one PR branch. Mitigation: the parallel-lock model serialises both through the same debounce timer — original assignee's saves queue behind the maintainer's debounced commit. Worst case: the original assignee sees a "queued" indicator until the maintainer's debounce fires. Edge case: if both have unflushed work and the maintainer's session crashes, the original assignee's queue remains queued until cleanup. Acceptance test required for this scenario in Phase 5a.

### Bulk action mistakes

A maintainer accidentally clicks "Discard all `awaiting_review` older than 365 days" and walks away. Mitigation: 24h soft-lock + typed confirmation + preview list of affected slugs + another owner can cancel + restricted to owner role. Combined, this should make it very hard to do real damage. But not impossible — recovery path is the manual state override (per discarded reciter).

### Maintainer churn

Inactive maintainers with stale GitHub team membership are a soft security risk. Soft mitigation: quarterly review by an owner of the team list. No automated revocation — manual is fine at this scale.

### Web admin replacing CLI

Risk: web becomes "good enough" for most things, CLI atrophies, edge cases requiring CLI become unreachable. Mitigation: §10 explicitly carves out which actions stay CLI-only. CLI parity test runs on every release.

### Catalog edit PR review burden

Every catalog edit opens a PR. If many small typo corrections come through, the PR queue becomes noise. Mitigation: catalog edit PRs auto-merge after a delay (e.g. 1h) if no maintainer requests review and a CI validation passes. Tunable per-field — display name typos auto-merge; riwayah reclassifications require manual review.

### Pipeline trigger from web vs HPC reality

The web button fires `pipeline.triggered` but the actual pipeline runs on Katana / HF Space. If those are down or the slug isn't on Katana, the trigger silently fails. Mitigation: the workflow that handles `pipeline.triggered` validates pre-conditions and fires back a `pipeline.failed_to_start` event with a reason. Visible in dashboard CI health.

### `discarded` state and existing reciters

Adding `discarded` to the state enum is a schema bump (per `inspector-state-management.md` §2 validation rules). Migration: increment `schema_version`, update validator to accept both old and new for one cycle, then drop old. Existing reciters never transition automatically — discard is always explicit.

### Dashboard performance at scale

300 reciters × 20 history entries each + 100 audit entries fits in memory easily. But if the dashboard auto-refreshes every 5s and 50 maintainers are watching, the backend could see significant duplicate work. Mitigation: ETag on the `/api/admin/health` and `/api/admin/reciters` responses; clients revalidate; backend caches the assembly for 1s.

### Owner concentration

Having too few owners (1) is a bus-factor risk; too many (10+) dilutes accountability. Recommend 2–3. Documented in onboarding.

### Action visibility for non-admin contributors

Should a reviewer see "this reciter was reassigned by maintainer X 2 days ago" in their UI? Soft-yes for transparency, but the audit log isn't anonymous-readable. Compromise: surface admin actions on the affected reciter's history panel in muted form, without actor names for non-maintainers.

### Self-assignment of admin role

The team-membership lookup needs to be the App's view, not the user's. A user could in theory present a forged "I'm a maintainer" claim if the backend trusts user-supplied data. Mitigation: every authorization check goes through `github_app.is_team_member()` — backend never trusts the user's claim. Failure mode: GitHub team API outage → fail-closed (treat user as contributor).

### Cross-tab session for maintainer

Maintainer opens dashboard in tab A and segments tab in tab B. Override actions in A should reflect in B without a refresh. Mitigation: same state-refresh strategy as the rest of the app (SSE / 30s poll / webhook). Edge: tab B's stale UI state may show actions that are no longer permitted. The backend rejecting the action with the proper error is the safety net.
