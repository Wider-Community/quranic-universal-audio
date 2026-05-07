# Inspector Deployment Plan

Design for migrating the Inspector from a local-Docker-only tool to a hosted, frictionless contribution surface, while keeping GitHub as the canonical backend for state, data, and PR workflow.

This document captures architectural decisions only. It is not an implementation plan — concrete TODOs are derived from it later, phase by phase.

## Goals

- Public website, view-only by default for everyone — all three tabs (Audio, Segments, Timestamps).
- Editing requires a single click ("Claim") that handles GitHub authentication, collaborator invitation, and assignment in one flow.
- One reciter, one reviewer at a time. Locked at the API gate, not just hidden in UI.
- GitHub remains the source of truth for reciter state, PR review, edit history, and merge gating.
- The contributor's GitHub identity is preserved as the author of every commit.
- Existing CI for validation, timestamps refresh, and dataset publishing keeps working with minimal changes.

## Non-goals

- Real-time collaborative editing. One reviewer per reciter is enforced.
- A separate database. Git is the database. Backend caches; it does not own state.
- Public rejection / re-extraction / param-rerun flows. These remain internal-only operations performed by maintainers from the CLI; the website does not surface them as states.
- Schema migration of `edit_history.jsonl` for backwards compatibility. The hash chain is being removed (see §7); writes after rollout follow the new schema.

## 1. Reciter lifecycle (simplified)

Four states, derived live from labels + on-disk data + open PRs:

| State | Label combination | Data on disk | PR | Editable | Inspector behaviour |
|---|---|---|---|---|---|
| **Catalogued** | *(none — entry only in `reciters_index.json`)* | No | No | No | Hidden from segments tab. Surfaced via "Request alignment" button which dispatches to the existing Reciter Requests Space. |
| **Pending alignment** | `request-alignment` + `status:pending-alignment` | No | No | No | Tab card shows "Awaiting pipeline" with the issue link. Cannot be claimed for review. |
| **Available for review** | `request-alignment` + `status:awaiting-review` + `reviewer-needed` | Yes (PR head) | Yes (draft) | Claimable by anyone | Listed in "Available for review" tab. Claim button visible. |
| **Under review** | `request-alignment` + `status:awaiting-review` + `reviewer-assigned` | Yes (PR head) | Yes | **Yes** for the assignee. View-only for everyone else. | Listed in "Under review" tab. Lock banner for non-assignees. |
| **Completed** | `status:awaiting-timestamps` or `status:completed` | Yes (`main`) | Merged | No | Listed in "Completed" tab. View-only. |

Drops vs. the original proposal:

- No `status:awaiting-rerun` — re-extraction is internal only.
- No `status:rejected` / `status:discarded` surface in the Inspector — internal triage handles these and the reciter simply disappears from the website.
- No website-side "request again after rejection" path — handled by maintainer comment + manual re-trigger.
- No multi-reviewer / pair-review path.

## 2. Identity convention (slug as the canonical ID)

Today's identity is brittle: PR title is the display name, slug is buried in issue body, `find_segments_pr.py` exists as a four-way fuzzy fallback. The new convention puts the slug everywhere, machine-parseable.

| Artifact | Convention | Example |
|---|---|---|
| Issue title | `[request] <slug> — <Display Name> (<riwayah>, <style>)` | `[request] saad_al_ghamdi — Saad Al-Ghamdi (Hafs, Murattal)` |
| Issue body marker | HTML comment + structured frontmatter block | `<!-- reciter-task: slug=saad_al_ghamdi kind=segments issue=42 -->` |
| Segments branch | `reciter/<slug>/segments` | `reciter/saad_al_ghamdi/segments` |
| Timestamps branch | `reciter/<slug>/timestamps` | `reciter/saad_al_ghamdi/timestamps` |
| Inspector edit pushes | Same as segments branch — Inspector backend pushes onto the existing PR head | — |
| PR title (segments) | `[<slug>] segments — <Display Name>` | `[saad_al_ghamdi] segments — Saad Al-Ghamdi` |
| PR title (timestamps) | `[<slug>] timestamps — <Display Name>` | — |
| PR body | HTML comment marker + human header | `<!-- reciter-task: slug=... kind=segments issue=42 -->` |
| Commit subject | `[<slug>] <kind>: <message>` | `[saad_al_ghamdi] segments: trim 2:34:1 left edge` |

A single helper module owns parsing and resolution:

- `scripts/lib/reciter_task.py` — given any of `(slug | issue_number | pr_number | branch_name)`, returns a `ReciterTask` dataclass with all four. Used by every CI script, `process_requests.py`, the Inspector backend, and the Reciter Requests Space.
- All workflows that today regex-parse `Ref #N` from PR bodies switch to reading the structured HTML comment marker.

Once adopted, `find_segments_pr.py` collapses to a single `gh pr list --head reciter/<slug>/segments --state open` call and can be deleted.

## 3. Deployment architecture (Inspector backend)

The Inspector backend stays Python (Flask) — its 11 validators, the phonemizer integration, peaks/ffmpeg, and the save flow's atomic-write + history append are too much code to port to the browser. The deployed backend is stateless, with a per-PR git working tree as its persistence layer.

### Read path

1. Browser requests data for reciter `X`.
2. Backend resolves `X`'s state via the live state computation (see §6).
3. If `Completed`: read from a cached `git worktree` of `main`.
4. If `Under review` or `Available for review`: read from a cached `git worktree` of `reciter/<slug>/segments`.
5. Subsequent reads served from `services/cache.py` exactly as today.

Worktrees live under `INSPECTOR_DATA_DIR/.worktrees/<slug>` on the deployed instance's persistent volume. Cold start on a worktree = `git fetch origin reciter/<slug>/segments && git worktree add ...`. Warm reads = filesystem cache + in-memory cache.

### Write path

1. Browser POSTs to `/api/seg/save/<reciter>/<chapter>` with the user's session cookie.
2. Backend's `@require_edit_lock(reciter)` decorator verifies the authenticated user is the assignee of this reciter's open PR. Returns 403 otherwise.
3. `save_seg_data()` runs unchanged inside the worktree — atomic write `detailed.json`, rebuild `segments.json`, snapshot validation, append `edit_history.jsonl`.
4. Backend marks the worktree dirty and starts/extends a debounce timer (default 30s of inactivity, hard cap 5 minutes).
5. When the timer fires, backend performs `git add -A && git commit && git push` against the PR branch. Multiple in-window saves coalesce into one commit.

### Commit attribution

Commits are authored as the contributor, not as a bot. Implementation:

- The user authorizes the Inspector via GitHub OAuth (or GitHub App user-token flow) at login.
- Backend stores the user's `(login, id)` for the session.
- Each commit sets `author.name = "<login>"`, `author.email = "<id>+<login>@users.noreply.github.com"`. This is the public no-reply form that GitHub recognizes — the commit appears on the user's contribution graph and `segments-pr-merged.yml`'s author roundup picks it up unchanged.
- The push itself uses the GitHub App installation token (the bot pushes; the commit is authored by the user). This is the standard GitHub App pattern and avoids needing the user's OAuth token to have `repo` write scope.

This contradicts the `process-requests` skill's "all bot artifacts appear as `github-actions[bot]`" rule for *Inspector edit pushes only*. The skill's rule still applies to maintenance commits (validation runs, dataset sync, reciter index updates). The distinction is documented as: "human edits → user attribution; pipeline artifacts → bot attribution."

### Hosting target

Fly.io with a small persistent volume is the path of least resistance: it supports Python + ffmpeg + git + persistent disk + websockets in a single small VM. Cloud Run/Render/Railway are also viable. The deployed image is the same `inspector/Dockerfile` artifact reviewers use locally (`docker-publish.yml` already builds and pushes it to GHCR).

## 4. Authentication & first-time contributor flow

### Anonymous

No login required. All three tabs render in view-only mode. The "Claim" button is disabled with a tooltip "Sign in with GitHub to claim".

### Logged-in contributor

GitHub OAuth via a GitHub App installed on the repo. Scopes: `read:user`, `user:email`. The App itself has `Contents: Write` and `Pull requests: Write` on the repo — that is what the backend uses to push.

### One-click claim flow

The current `/claim` issue-comment dance is preserved as a CLI fallback but **not surfaced to web users**. The website collapses it into one button:

1. Logged-in user clicks **Claim** on an Available reciter.
2. Backend calls `GET /repos/{owner}/{repo}/collaborators/{login}` (using PAT, since `GITHUB_TOKEN` lacks scope).
3. **If collaborator (204):** backend immediately calls `POST /repos/.../issues/<N>/assignees`. Done. The existing `issue-commands.yml` `assigned` handler swaps `reviewer-needed` → `reviewer-assigned` and the `pr-assignee-sync.yml` workflow propagates assignment to the PR. UI flips to edit mode.
4. **If not collaborator (404):** backend calls `PUT /repos/.../collaborators/{login}` to send the invite, then shows a modal:
   > *We've sent you a collaborator invite. [Accept invite ↗](https://github.com/{owner}/{repo}/invitations) — once accepted, return here and the page will auto-claim.*
5. The page polls `GET /api/me/collaborator-status` every few seconds. When `true`, it auto-fires the claim API call (step 3). User never has to re-click; never has to type `/claim` or `/confirm`.

CLI fallback (`/claim` and `/confirm` as issue comments) remains for users who prefer terminal flow or who can't run the web UI.

### Release flow (assigned reviewer changes mind)

A new **Release claim** button on the website calls `DELETE /repos/.../issues/<N>/assignees`. The existing `issue-commands.yml` `unassigned` handler restores `reviewer-needed`. The user's saved edits remain on the PR branch — a future reviewer continues from there.

### What CI gives us for free

The existing `issue-commands.yml`, `pr-assignee-sync.yml`, and `segments-pr-merged.yml` workflows already handle label transitions, assignee sync to the linked PR, and post-merge cleanup. The website's claim/release endpoints just trigger the right primitives; the workflows fan out the rest.

## 5. Locking model

Two layers, both required:

### API gate (load-bearing)

Every mutating endpoint is wrapped with `@require_edit_lock(reciter)`:

```python
def require_edit_lock(reciter_param='reciter'):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            reciter = kwargs[reciter_param]
            user = current_user()
            if not user:
                abort(401)
            task = resolve_reciter_task(reciter)
            if task.state != 'under_review' or task.assignee != user.login:
                abort(403, description="Reciter is not editable by this user")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
```

Endpoints to gate (audit checklist):

- `POST /api/seg/save/<reciter>/<chapter>`
- `POST /api/seg/undo-batch/<reciter>`
- `POST /api/seg/undo-ops/<reciter>`
- `POST /api/seg/trigger-validation/<reciter>` — gated even though "read-only side effect" because it warms a per-reciter cache that's expensive to compute and easy to abuse anonymously.

### Frontend hiding (cleanliness, not security)

A single `editingDisabled` derived store consumed by every component that has an edit affordance. Audit the following components — every entry point must check the store:

- `tabs/segments/components/list/SegmentRow.svelte` — inline trim/split/merge/delete buttons.
- `tabs/segments/components/validation/{ErrorCard,GenericIssueCard,MissingWordsCard,MissingVersesCard,ValidationPanel}.svelte` — accordion edit dispatchers.
- `tabs/segments/components/history/{EditChainRow,HistoryBatch}.svelte` — undo buttons.

The frontend hides the buttons; the backend rejects unauthorized POSTs even if the frontend is bypassed.

### Single-writer per reciter (server-side)

In-memory lock keyed on `(reciter, user)` with a short lease (~60s, refreshed on each save). Prevents the same user opening two tabs from racing on commits. If the deployment scales to multiple backend nodes later, this lock moves to Redis or to git itself (`git push --force-with-lease` semantics).

## 6. State computation (single workflow + helper)

Today, label transitions are scattered across four workflows (`segments-pr-merged.yml`, `timestamps-refresh.yml`, `issue-commands.yml`, `process_requests.py`). Centralizing into one helper + one workflow:

### Helper module

`scripts/lib/reciter_state.py` — given a `ReciterTask`, computes the current state from:

- The issue's labels.
- Whether an open PR with the matching `reciter/<slug>/segments` head exists.
- Whether `data/recitation_segments/<slug>/segments.json` is on `main`.
- Whether `data/timestamps/<cat>/<slug>/timestamps.json` is on `main`.

Returns one of `catalogued | pending_alignment | available_for_review | under_review | completed`. Pure function; no GitHub API calls inside (caller passes in fetched data).

### Live endpoint

`GET /api/reciter-task/<slug>` on the Inspector backend returns the full `ReciterTask` plus computed state plus `can_edit_for_current_user`. Cached 30s. Drives every UI affordance (claim button, lock banner, data-fetch path).

### Workflow consolidation

| Existing | Action | Notes |
|---|---|---|
| `bot-create-issue.yml`, `bot-create-pr.yml`, `bot-comment.yml` | Keep | Generic primitives. |
| `issue-commands.yml` (`/claim`, `/confirm`) | Keep | CLI fallback. Website calls assignee API directly. |
| `pr-assignee-sync.yml` | Keep, simplify | Linked-PR lookup uses branch convention `reciter/<slug>/segments` instead of body regex. |
| `validate-segments-pr.yml` | Keep, gate | Skip on commits whose subject contains `[wip]`. Inspector debounced pushes use that prefix; full validation only fires when the PR is marked ready for review. |
| `segments-pr-merged.yml` | Keep, simplify | Slug parsed from PR title prefix `[<slug>]` (with file-diff fallback). |
| `timestamps-refresh.yml` | Keep | Unchanged. |
| `update-reciters.yml` | Extend | Generated `reciters_index.json` carries `state`, `issue_number`, `pr_number`, `assignee`, `last_updated`. Triggered also on `issues.types: [labeled, unlabeled]` so state updates land within seconds. |
| `validate-audio-pr.yml` | Keep | Unchanged. |
| `release.yml`, `sync-dataset.yml` | Keep | Unchanged. |
| `docker-publish.yml` | Keep | Unchanged. |
| `validate-edit-history.py` | **Remove the file-hash check** (see §7). Keep batch-id chain + tampering checks. | |
| `find_segments_pr.py` | **Delete** | Replaced by branch-name lookup. |
| `pr-uniqueness.yml` (NEW) | Add | Fail PR if any other open PR already touches `data/recitation_segments/<slug>/`. Prevents two PRs racing on one reciter. With branch convention this is also enforced at the git level (one branch per slug per kind), so the workflow is a belt-and-suspenders check. |
| `inspector-deploy.yml` (NEW) | Add | On push to `main` of `inspector/**`, deploys the new Docker image to the hosted environment. |

## 7. Edit-history simplifications

The current schema and validators evolved organically and carry weight that the new deployment model makes obsolete.

### Remove the file-hash chain

`edit_history.jsonl` carries `file_hash_after` per batch. `validate_edit_history.py` checks that the *latest* record's hash matches the current `detailed.json` — and was designed to detect manual tampering with the JSON between Inspector saves.

In the deployed model:

- All writes go through `save_seg_data()` running on the backend. There is no out-of-band path.
- Manual file edits are no longer a supported workflow.
- Re-extraction (which previously broke the chain) is internal-only and can rotate the history file at the source.

So the file-hash field and its validator check go away. What remains useful and should be kept:

- `batch_id` — needed for undo lookup.
- `schema_version` — for future migrations.
- `validation_summary_before` / `validation_summary_after` — drives the in-app history viewer.
- `operations` array with patches — needed for undo.
- `reverts_batch_id` / `reverts_op_ids` — needed for filtering reverted batches.

The genesis record can also go — it exists to anchor the hash chain and has no other purpose.

### Drop `edit_history_peaks.jsonl`

Today's `edit_history_peaks.jsonl` exists so cross-session History viewing can show the waveform shape of an op's affected region without recomputing peaks from audio. In the deployed model:

- The backend has the audio cached and ffmpeg installed.
- Peak compute for one op's region is ~50ms.
- Recomputing on demand is faster than fetching a 20MB+ JSONL on cold load.

Drop the file, drop `services/peaks_history.py`, drop the `op_peaks` payload field on save. The history viewer fetches peaks via the existing `/api/peaks` endpoint when an op row is expanded.

### Drop the `_meta.audio_source` peek

`discover_ts_reciters` opens each `timestamps.json` and reads the first 512 bytes to extract `audio_source`. In the new model, the reciter index has this field directly (see §6). The peek can be deleted.

## 8. Other simplifications worth considering

These are not strictly required for deployment but reduce surface area while we're here:

- **Squash-merge always.** Already standard — keeps the per-edit commit noise off `main` and means the `[wip]` prefixed commits never pollute history.
- **`docker-compose.yml` becomes the offline-only path.** Document it as "for maintainers reviewing locally without internet" in `inspector/CLAUDE.md`. The default contributor experience is the website.
- **`update-reciters.yml`'s auto-PR + auto-merge cycle.** Currently it opens a docs PR every time a state changes. In the new model, the live `/api/reciter-task/<slug>` endpoint serves the website, so the index file's role shrinks to "snapshot for the Reciter Requests Space + RECITERS.md badge generator." Run it on a slower cadence (every 30 min instead of every push) to cut Action minutes.
- **Drop the validate-segments comment edit/insert dance.** Post one comment per push, let GitHub collapse the timeline. Saves ~30 lines of yaml.
- **Drop the audio proxy** (`routes/audio_proxy.py`) for the deployed instance. The backend's only role for audio is to set `Access-Control-Allow-Origin: *`, which the browser can get directly from origin if origin permits CORS, or from a small CDN-cached pass-through. Local Docker keeps the proxy.

## 9. First-time-contributor bootstrapping

The flow with the new website:

1. Visitor lands on the Inspector website. Sees the segments tab with three sub-tabs (Available / Under review / Completed).
2. Browses freely without auth.
3. Finds an Available reciter, clicks **Claim**.
4. Redirected to GitHub OAuth (one click — authorize the Inspector App).
5. Returns to the page. Backend checks collaborator status:
   - If they were a collaborator → assigned immediately, page reloads in edit mode.
   - If not → invite sent, page shows the accept-invite link with auto-poll.
6. They accept. Page detects, auto-claims, switches to edit mode.

Total clicks: **3 maximum** (Claim → Authorize → Accept invite). Two for returning collaborators. No CLI knowledge required. No `/claim` comment to remember.

The OAuth/App install also gives us:

- The user's identity for commit attribution (no separate prompt).
- A way to signal in the UI when their session expires.
- A path forward for a future "your contributions" page (issues/PRs assigned to you, work in progress).

## 10. Phased migration

1. **Phase 0 — preparation**
   - Adopt the slug-first identity convention. Update `process_requests.py::cmd_prepare_pr` to use the new branch and title format.
   - Add `scripts/lib/reciter_task.py` and `scripts/lib/reciter_state.py`.
   - Add `editingDisabled` store and `@require_edit_lock` decorator (no-op until states are wired up).

2. **Phase 1 — read-only deployment**
   - Deploy the Inspector image to Fly.io.
   - GitHub OAuth on the website. Anonymous = view-only on `main` data only.
   - `/api/reciter-task/<slug>` endpoint live; UI shows reciter status pills.

3. **Phase 2 — PR-branch reads**
   - Backend learns to clone `reciter/<slug>/segments` worktrees.
   - Available and Under review tabs render data from PR branches.
   - Edit affordances still hidden globally.

4. **Phase 3 — claim flow**
   - Wire the Claim button + collaborator-invite + auto-poll modal.
   - Enforce single-writer lock.

5. **Phase 4 — writes**
   - Enable saves with debounced commit-and-push.
   - Drop the file-hash chain, drop `edit_history_peaks.jsonl`, drop genesis record.
   - Test end-to-end with one volunteer reciter.

6. **Phase 5 — workflow consolidation**
   - Add `pr-uniqueness.yml`, `inspector-deploy.yml`.
   - Delete `find_segments_pr.py`.
   - Update `validate-edit-history.py` to drop the hash check.
   - Slow `update-reciters.yml` cadence.

7. **Phase 6 — docs and decommission**
   - Update contributor docs to point to the website as the primary path.
   - Local Docker is now the offline / maintainer fallback.

## Open questions

- **Anonymous viewing of in-review PRs.** Default to yes (transparent process). Can flip later if maintainers prefer to keep WIP private.
- **Persistent volume size on Fly.io.** With ~300 reciters and ~50MB of data per active worktree, plus audio caches, expect to start at 5–10GB. Tune after measuring.
- **OAuth App vs. GitHub App.** GitHub App is preferred (server-side installation token avoids needing user OAuth tokens to have `repo` scope), but a small OAuth App is easier to bootstrap. Decide before Phase 1.
