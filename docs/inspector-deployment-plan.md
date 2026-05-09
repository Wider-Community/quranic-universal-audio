# Inspector Deployment Plan

Design for migrating the Inspector from a local-Docker-only tool to a hosted, frictionless contribution surface, while keeping GitHub as the canonical backend for state, data, and PR workflow.

This document captures architectural decisions only. It is not an implementation plan — concrete TODOs are derived from it later, phase by phase.

**Companion docs:**
- [`inspector-data-storage.md`](inspector-data-storage.md) — implementation-grade reference for the deployed file-IO model: three-tier read path (HF static / github-fetch / server-image), scratch dir lifecycle, Git Data API write path, image build rules, perf budget, per-phase acceptance criteria.
- [`inspector-state-management.md`](inspector-state-management.md) — implementation-grade reference for reciter state: state file schema, catalog file schema, state machine + event vocabulary, the consolidated state workflow, identity convention with full marker/template registry, GitHub mirroring, per-phase acceptance criteria.
- [`inspector-deploy-runbook.md`](inspector-deploy-runbook.md) — operational runbook: HF Space setup (dev + prod), GitHub App setup, upload pipeline, test environment conventions, smoke tests per phase, rollback procedure, the three concrete file structures (HF dataset / HF Space repo / `/tmp` on the running container).
- [`inspector-admin-perms.md`](inspector-admin-perms.md) — implementation-grade reference for admin and permissions: roles, maintainer/owner identity, permission matrix, override actions (force-release, reassign, force-claim, manual state override, discard, catalog edit, pipeline trigger), admin dashboard, audit log, new state events, per-phase acceptance criteria.
- [`inspector-auth-claim.md`](inspector-auth-claim.md) — implementation-grade reference for authentication and the user-facing claim/release/mark-ready flow: GitHub App configuration, token lifecycle, endpoint contracts, optimistic UI reconciliation, identity attribution, edge cases.

## Goals

- Public website, view-only by default for everyone — all three tabs (Audio, Segments, Timestamps).
- Editing requires a single click ("Claim") that handles GitHub authentication, collaborator invitation, and assignment in one flow.
- One reciter, one reviewer at a time. Locked at the API gate, not just hidden in UI.
- A single repo file (`data/reciter_state.json`) is the source of truth for reciter state. GitHub primitives (labels, assignees, comments) mirror it for human UX but are not authoritative.
- GitHub remains the source of truth for review-content (PR diff, edit history on branch, merge events). The Inspector is the primary contribution surface; GitHub is the automation backend.
- The contributor's GitHub identity is preserved as the author of every commit.
- Existing CI for validation, timestamps refresh, and dataset publishing keeps working with minimal changes.

## Non-goals

- Real-time collaborative editing. One reviewer per reciter is enforced.
- A separate database. Git is the database. Backend caches; it does not own state.
- Public rejection / re-extraction / param-rerun flows. These remain internal-only operations performed by maintainers from the CLI; the website does not surface them as states.
- Schema migration of `edit_history.jsonl` for backwards compatibility. The hash chain is being removed (see §7); writes after rollout follow the new schema.

## 1. Reciter lifecycle (seven states)

State is owned by `data/reciter_state.json`. GitHub labels and assignees mirror the file. See [`inspector-state-management.md`](inspector-state-management.md) §4 for the full state machine, event vocabulary, and transition matrix.

| State | Editable | Assignee | Inspector behaviour |
|---|---|---|---|
| `catalogued` | No | — | Hidden from segments tab. Surfaced via "Request alignment" which fires `reciter.alignment_requested`. |
| `awaiting_alignment` | No | — | Tab card shows "Pipeline running" with the issue link. Cannot be claimed. |
| `awaiting_review` | No (claimable) | — | Listed in "Available for review". Claim button visible. |
| `under_review` | **Yes** for the assignee, view-only otherwise | set | Listed in "Under review". Lock banner for non-assignees. |
| `ready_for_merge` | No (frozen) | retained | Listed in "Awaiting merge". Reviewer can unmark or release; maintainer merges or sends back. |
| `awaiting_timestamps` | No | — | Segments on main; TS data not yet on main. Listed in "Completed" tab; view-only. |
| `completed` | No | — | Listed in "Completed" tab. View-only. |

Deferred (schema flexible to add later, no automation today):

- Re-edits of completed reciters — the existing CI (segments change → TS regenerate) handles staleness implicitly; no explicit revision flow.
- Audio-source changes forcing realignment.
- Alignment-failed retry surfaces.
- `discarded` / abandon flow.
- Multi-reviewer / pair-review.

## 2. Identity convention (slug as the canonical ID)

Today's identity is brittle: PR title is the display name, slug is buried in the issue body, `find_segments_pr.py` exists as a four-way fuzzy fallback. The new convention puts the slug in a machine-parseable position on every artifact. Timestamps no longer get a separate branch/PR (TS is deterministic compute output, pushed direct to main), so there's no `kind` disambiguator anywhere.

| Artifact | Convention | Example |
|---|---|---|
| Issue title | `[request] <slug>: <Display Name>` | `[request] saad_al_ghamdi: Saad Al-Ghamdi` |
| PR title | `[<slug>] <description>` | `[saad_al_ghamdi] alignment for Saad Al-Ghamdi` |
| Branch | `reciter/<slug>` | `reciter/saad_al_ghamdi` |
| Commit (human edit) | `[<slug>] [wip] <op summary>` | `[saad_al_ghamdi] [wip] trim 2:34:1 left edge` |
| Commit (pipeline) | `[<slug>] [pipeline] <message>` | `[saad_al_ghamdi] [pipeline] timestamps refresh` |
| Commit (state file) | `[state] <slug>: <event>` | `[state] saad_al_ghamdi: claimed by alice` |
| Issue/PR body marker | HTML comment | `<!-- reciter-task: slug=saad_al_ghamdi schema=1 -->` |

`scripts/lib/reciter_task.py` is the single resolver — given any of `(slug | issue_number | pr_number | branch_name)`, returns a `ReciterTask` dataclass. Every CI script, `process_requests.py`, the Inspector backend, and the Reciter Requests Space go through it. Full marker registry, body templates, and squash-merge subject convention in [`inspector-state-management.md`](inspector-state-management.md) §6–§7.

Once adopted, `find_segments_pr.py` collapses to a single `gh pr list --head reciter/<slug>` call and can be deleted.

## 3. Deployment architecture (Inspector backend)

The Inspector backend stays Python (Flask) — its 11 validators, the phonemizer integration, peaks/ffmpeg, and the save flow's atomic-write + history append are too much code to port to the browser. The deployed backend is **stateless for reads** and **near-stateless for writes**: no git worktrees, no persistent disk for repo data. See [`inspector-data-storage.md`](inspector-data-storage.md) for the file-by-file specification, github-fetch service contract, scratch dir lifecycle, image build rules, and per-phase acceptance criteria.

### Read path

Three tiers based on reciter state, with the backend involved only for under-review reciters:

1. **Completed reciters** — browser fetches Inspector data direct from HF CDN at `inspector/segments/<slug>/<file>.gz` under the `hetchyy/quranic-universal-ayahs` dataset, parallel to the existing TS shards. Backend uninvolved on the read path.
2. **Under-review reciters** (PR branch `reciter/<slug>`) — backend's `services/github_fetch.py` serves files from raw.githubusercontent.com via the GitHub App installation token. ETag-revalidated, TTL'd 30 s with ±10% jitter, single-flight, two-layer caching (raw bytes + parsed Python objects).
3. **Static reference data** (Quran word text, controlled vocabularies, the consolidated audio URL catalog) — baked into the Space image, served same-origin via `/api/static/...`. Browser caches forever via `Cache-Control: immutable`. Audio playback browser → origin direct. Timestamps browser → HF CDN direct (already implemented per [`timestamps-tab-deployment-plan.md`](timestamps-tab-deployment-plan.md)).

No worktrees. No on-disk repo. github-fetch usage drops dramatically vs the original plan — only the ~20 in-flight reciters at any time consume GitHub rate budget; the long tail of completed reciters is on HF CDN.

Active reviewers reading their own slug's data go through scratch (so they see in-flight pre-debounce state); anyone else reading the same slug's data goes through the standard tier path (HF CDN or github-fetch), seeing the last-debounce-flushed state — see [`inspector-data-storage.md`](inspector-data-storage.md) §4.

### Write path

Writes are gated to the one active reviewer per reciter (locking model in §5). For that reviewer:

1. Browser POSTs to `/api/seg/save/<reciter>/<chapter>` with the user's session cookie.
2. Backend's `@require_edit_lock(reciter)` decorator verifies the authenticated user is the assignee of this reciter's open PR. Returns 403 otherwise.
3. On first save of a session, backend materialises a small **scratch dir** at `<INSPECTOR_SCRATCH_DIR>/<slug>/data/recitation_segments/<slug>/` populated with the 4–5 editable files fetched from the PR branch via github-fetch.
4. `save_seg_data()` runs unchanged against the scratch dir — atomic write `detailed.json`, rebuild `segments.json`, snapshot validation, append `edit_history.jsonl`.
5. Backend marks the scratch dirty and starts/extends a debounce timer (30 s inactivity, 5 min hard cap).
6. When the timer fires, backend issues a **multi-file commit via the GitHub Git Data API** (blobs → tree → commit → ref update) against the PR branch. Multiple in-window saves coalesce into one commit. No `git push`, no worktree.

Scratch dir is per-active-reviewer and ephemeral — backend restart loses at most the unflushed debounce window, recovered on next session by re-fetching from the PR branch. Total scratch footprint: ~9–19 MB per active reviewer.

### Commit attribution

Commits are authored as the contributor, not as a bot. Implementation:

- The user authorizes the Inspector via GitHub OAuth (or GitHub App user-token flow) at login.
- Backend stores the user's `(login, id)` for the session.
- Each commit sets `author.name = "<login>"`, `author.email = "<id>+<login>@users.noreply.github.com"`. This is the public no-reply form that GitHub recognizes — the commit appears on the user's contribution graph and `segments-pr-merged.yml`'s author roundup picks it up unchanged.
- The push itself uses the GitHub App installation token (the bot pushes; the commit is authored by the user). This is the standard GitHub App pattern and avoids needing the user's OAuth token to have `repo` write scope.

This contradicts the `process-requests` skill's "all bot artifacts appear as `github-actions[bot]`" rule for *Inspector edit pushes only*. The skill's rule still applies to maintenance commits (validation runs, dataset sync, reciter index updates). The distinction is documented as: "human edits → user attribution; pipeline artifacts → bot attribution."

### Hosting target

**Hugging Face Spaces (Docker SDK, free CPU-basic tier)** is the chosen starting host. Same operational pattern as the existing three project Spaces (`reciter_requests/`, `mfa_aligner/`, `quranic_universal_aligner/`), zero new ops surface, free at the targeted scale (2 vCPU, 16 GB RAM, ephemeral disk, 48-hour idle sleep timeout that effectively never fires for an active project). Fly.io is the migration path if/when sleep latency or CPU saturation forces it; same image transplants directly.

**No persistent volume required** — github-fetch LRU is in-memory, scratch is ephemeral `/tmp` disk, audio/timestamps/completed-segments all bypass the backend entirely. Single-image / two-profile Dockerfile (env-driven mode, see [`inspector-data-storage.md`](inspector-data-storage.md) §7): one image works for both local-Docker maintainer use (data bind-mounted at `/data`) and the deployed Space (data baked into `/app/data` and fetched on demand for everything else).

**Image footprint** ~300–400 MB (~89 MB static reference data including the consolidated `audio_catalog.json.gz` + Python deps + Alpine static ffmpeg + frontend dist). Image rebuilds on code or static-data changes only; per-reciter data changes never trigger a redeploy.

**Operational topology:** dev Space (`hetchyy/quranic-inspector-dev`) tracks the `dev` branch with `INSPECTOR_ALLOWED_SLUGS_REGEX=^_test_` to gate writes to test reciters; prod Space (`hetchyy/quranic-inspector`) tracks `main`. Both are stable URLs (`https://hetchyy-quranic-inspector{,-dev}.hf.space`); custom domain is supported on Spaces if/when desired. See [`inspector-deploy-runbook.md`](inspector-deploy-runbook.md) for the full setup procedure.

### Free-tier prerequisites

The deploy is **blocked** on three changes before exposing to the public on free CPU-basic. Without them, p95 latency at 10 concurrent users runs 2–4 s during scrubbing bursts. With them, 10 concurrent is comfortable.

1. **Replace `app.run()` with `gunicorn -k gthread -w 2 --threads 8`** in the Dockerfile CMD. `inspector/app.py:180` runs werkzeug dev server, which is explicitly not production-grade. Two worker processes (one per vCPU) × 8 threads each gives proper request scheduling.
2. **Implement `services/github_fetch.py` with single-flight + parsed-cache layer** as [`inspector-data-storage.md`](inspector-data-storage.md) §3 specifies. Without single-flight, 10 concurrent cold viewers of the same reciter trigger 10 redundant GitHub fetches and 10 redundant 5 MB JSON parses on the GIL.
3. **`Cache-Control: public, max-age=31536000, immutable` on peaks routes** (`/api/seg/segment-peaks`, `/api/seg/peaks`). First bottleneck on free tier is **ffmpeg subprocess fork on the per-segment peaks route** during scrubbing; CDN-fronting the deterministic peaks responses (Cloudflare free or HF edge cache) absorbs the burst and lets backend ffmpeg stay idle except on first global hit. Headers must be set even if a CDN isn't fronted yet, so the addition is a config flip rather than a code change.

## 4. Authentication & first-time contributor flow

Full mechanics — App configuration, token lifecycle, endpoint contracts, optimistic UI, identity attribution, edge cases — live in [`inspector-auth-claim.md`](inspector-auth-claim.md). Sketch only here.

### Anonymous

No login required. All three tabs render in view-only mode. The "Claim" button is disabled with a tooltip "Sign in with GitHub to claim".

### Logged-in contributor

GitHub App user-to-server auth. The App's installation token does all repo writes; the user-to-server token identifies the contributor for commit attribution. **Contributors never become repo collaborators** — author attribution comes from the `<id>+<login>@users.noreply.github.com` no-reply email pattern, which credits the contributor in the contribution graph regardless of repo membership. The App needs `Contents: write`, `Pull requests: write`, `Issues: write`, `Metadata: read`, `Actions: read` (and `Members: read` on the org for team-membership lookup). No `Administration: write`.

### One-click claim flow

The current `/claim` issue-comment dance is preserved as a CLI fallback but **not surfaced to web users**. The website collapses it into one button:

1. Logged-in user clicks **Claim** on an Available reciter.
2. Backend's API gate validates state and one-claim-per-user, then fires `repository_dispatch reciter.claimed { slug, login }` and returns 202 with optimistic state.
3. `update-reciter-state.yml` validates the transition, writes `data/reciter_state.json`, and mirrors to GitHub primitives (best-effort `POST /issues/.../assignees` — silently skipped for non-collabs — plus body re-render and label flip).
4. UI flips to edit mode optimistically; backend reconciles within ~10 s via `/api/internal/state-changed` webhook + 30 s polling backstop on `/api/reciter-task/<slug>`.

A first-time visitor sees a sign-in modal once; thereafter the flow is one click. **No collaborator invite, no second tab, no waiting modal, no polling for collaborator status.**

CLI fallback (`/claim` and `/confirm` as issue comments) remains for users who prefer terminal flow or who can't run the web UI; these go through `issue-commands.yml`, which fires the same `reciter.claimed` / `reciter.released` dispatch events. CLI users who push directly via git are invited as collaborators by a maintainer manually, on request — not auto-invited by the website.

### Mark ready (primary completion path)

When the reviewer is done, they click **Mark ready** in the banner. Backend flushes any pending debounced edits, fires `reciter.marked_ready { slug, login }`, returns 202. State transitions `under_review → ready_for_merge`; assignee retained. The reciter is frozen from edits and surfaced to the maintainer queue under "Awaiting merge". Maintainer clicks Squash & Merge on github.com → `segments-pr-merged.yml` fires `reciter.review_merged` → state advances to `awaiting_timestamps`. The reviewer can pull the claim back themselves with **Continue editing** (fires `reciter.unmarked_ready`), and a maintainer can send it back via [`inspector-admin-perms.md`](inspector-admin-perms.md) §5.10.

### Release flow (assigned reviewer changes mind)

The **Release claim** button calls `POST /api/release/<slug>` which fires `reciter.released { slug, login }`. Allowed from both `under_review` and `ready_for_merge`. The state workflow clears assignee, transitions to `awaiting_review`, mirrors to issue + PR. Saved edits remain on the PR branch — a future reviewer continues from there.

### What CI gives us for free

Every contribution event (claim, release, alignment complete, PR merge, TS complete) flows through `repository_dispatch` into the single `update-reciter-state.yml` workflow. Other workflows shrink to event emitters: `issue-commands.yml` parses comments and fires dispatch, `segments-pr-merged.yml` fires `reciter.review_merged`, `timestamps-refresh.yml` fires `reciter.timestamps_completed`. The state workflow handles label/body/assignee mirroring in one place.

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
            entry = state_store.get(reciter)  # parsed data/reciter_state.json
            if entry is None or entry.state != 'under_review' or entry.assignee != user.login:
                abort(403, description="Reciter is not editable by this user")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
```

The lookup is a dict access on the parsed state file — no live GitHub calls. Freshness is bounded by the in-memory cache TTL (~30 s) plus the state-workflow propagation latency (~10 s).

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

## 6. State management (file is source of truth)

Pipeline state, assignee, issue/PR numbers, and event history for every reciter live in **`data/reciter_state.json`** — a repo-tracked file written only by `update-reciter-state.yml`. GitHub labels and assignees are one-way mirrors of that file, displayed for human UX in the issues list but **not authoritative**. Manual edits to GitHub labels/assignees get reverted on the next workflow run.

Static identity (display name, riwayah, audio source, url_template) lives separately in **`data/reciter_catalog.json`**, updated by manual PRs from the Reciter Requests intake. Two files, two cadences, two clean git histories. Mixing state-change auto-commits with catalog PR-edits would race on the same file and noise up `git blame`.

Inspector reads both files (parsed once on startup, refreshed on webhook or 30 s poll) and bases every UI affordance on them.

### Why a flat file beats labels-as-state and a database

- Labels drift (manual edits, race conditions across workflows). The file does not — one workflow, declared `concurrency: singleton`, is the only writer.
- Database adds operational surface (auth, backups, schema migrations, connection management) for a sub-1/sec write rate. A JSON file with `git log` as the audit trail is simpler at every level. ~150 KB at 300 reciters.
- Inspector ingests it as parsed JSON; trivial to cache in memory.

### One workflow, all transitions

`update-reciter-state.yml` is the only writer. It listens for `repository_dispatch` events emitted by every other workflow (`reciter.alignment_requested`, `reciter.alignment_completed`, `reciter.claimed`, `reciter.released`, `reciter.review_merged`, `reciter.timestamps_completed`, plus `catalog_synced` from `push` triggers on the catalog file). For each event it validates the transition, applies it to `data/reciter_state.json`, commits with subject `[state] <slug>: <event>`, then mirrors the new state to GitHub primitives (issue body re-render, label flip, assignee set/unset).

All other workflows fire dispatch events; **none of them write state directly.** Full event vocabulary, transition matrix, dispatch payload schemas, and mirror logic in [`inspector-state-management.md`](inspector-state-management.md) §4–§5.

### Inspector reads the file, not the GitHub API

`/api/reciter-task/<slug>` is a thin lookup into the parsed state file — no live GitHub API calls. The "is current user the assignee?" check the API gate (§5) does is `state.reciters[slug].assignee == user.login`. State-mutating endpoints (`/api/claim/<slug>`, `/api/release/<slug>`) **fire `repository_dispatch`** and return 202; the workflow does the actual work; the file changes propagate back via webhook or poll within ~10 s.

### Workflow consolidation

| Existing | Action |
|---|---|
| `bot-create-issue.yml`, `bot-create-pr.yml`, `bot-comment.yml` | Keep as primitives — they create artifacts, then fire dispatch events; never write state |
| `issue-commands.yml` (`/claim`, `/confirm`) | Reduce to comment parser; fire `reciter.claimed` / `reciter.released` |
| `pr-assignee-sync.yml` | **Delete** — state workflow mirrors assignment to issue + PR in one shot |
| `validate-segments-pr.yml` | Keep, gate on `[wip]` commit prefix — Inspector debounced pushes skip full validation |
| `segments-pr-merged.yml` | Reduce to "fire `reciter.review_merged`"; state workflow handles label/body cleanup |
| `timestamps-refresh.yml` | Keep as pipeline runner; on completion fire `reciter.timestamps_completed` |
| `update-reciters.yml` | Repurpose — regenerate `RECITERS.md` and badge files **from the state file**. Doesn't write state itself |
| `validate-audio-pr.yml`, `release.yml`, `sync-dataset.yml`, `docker-publish.yml` | Keep, unchanged |
| `validate-edit-history.py` | Drop file-hash check (§7); keep batch-id chain + tampering checks |
| `find_segments_pr.py` | **Delete** — replaced by branch-name lookup (`gh pr list --head reciter/<slug>`) |
| `update-reciter-state.yml` (NEW) | Add — sole writer of `data/reciter_state.json`, dispatches in, mirrors out |
| `pr-uniqueness.yml` (NEW) | Add — fail PR if another open PR already touches `data/recitation_segments/<slug>/` |
| `inspector-deploy.yml` (NEW) | Add — on `inspector/**` push to main, deploy new Docker image |

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

### Keep `edit_history_peaks.jsonl` (corrected)

An earlier draft of this plan proposed dropping `edit_history_peaks.jsonl` on the assumption that it was a 20+ MB file with no read path. Both assumptions were wrong:

- Real file size in the repo today is ~1–2 MB per reciter (not 20 MB).
- The read path **does** exist at `routes/peaks.py:82` (`seg_history_peaks_get`) and is wired to the History panel via `tabs/segments/utils/data/reciter-actions.ts:72` (parallel fetch on session load) and `tabs/segments/utils/playback/preview.ts:209` (lazy POST during playback).

The feature lets anyone — including anonymous viewers — open a reciter's History panel and see waveform shapes render instantly without recomputing from audio. Dropping it would regress that UX. So the file, `services/peaks_history.py`, and the `op_peaks` save-payload field all stay. The file ships in scratch alongside the other 4 editable files (~2 MB extra) and is fetched by anonymous viewers via github-fetch like every other per-reciter data file. See [`inspector-data-storage.md`](inspector-data-storage.md) §8.

### Drop the `_meta.audio_source` peek

`discover_ts_reciters` opens each `timestamps.json` and reads the first 512 bytes to extract `audio_source`. In the new model, the reciter index has this field directly (see §6). The peek can be deleted.

## 8. Other simplifications worth considering

These are not strictly required for deployment but reduce surface area while we're here:

- **Squash-merge always.** Already standard — keeps the per-edit commit noise off `main` and means the `[wip]` prefixed commits never pollute history.
- **`docker-compose.yml` becomes the offline-only path.** Document it as "for maintainers reviewing locally without internet" in `inspector/CLAUDE.md`. The default contributor experience is the website.
- **`update-reciters.yml`'s auto-PR + auto-merge cycle.** Currently it opens a docs PR every time a state changes. In the new model, the live `/api/reciter-task/<slug>` endpoint serves the website, so the index file's role shrinks to "snapshot for the Reciter Requests Space + RECITERS.md badge generator." Run it on a slower cadence (every 30 min instead of every push) to cut Action minutes.
- **Drop the validate-segments comment edit/insert dance.** Post one comment per push, let GitHub collapse the timeline. Saves ~30 lines of yaml.
- **Drop the audio proxy** (`routes/audio_proxy.py`) for the deployed instance. The backend's only role for audio is to set `Access-Control-Allow-Origin: *`, which the browser can get directly from origin if origin permits CORS, or from a small CDN-cached pass-through. Local Docker keeps the proxy.
- **Drop the validation panel in deployed mode.** `routes/timestamps.py::ts_validate` is removed from the deployed image entirely — there is no UI surface for it on the website. Validation remains in local mode for maintainers. This kills the cross-file timestamps↔segments dependency and removes the only Inspector code path that would otherwise need to fetch from HF for a server-side compute.
- **Audio manifests via github-fetch, not bundled in the image.** All 391 `data/audio/<cat>/<src>/<reciter>.json` files are pulled per-reciter from GitHub raw on demand (cached server-side). Adding/changing a reciter's audio config no longer triggers a Docker image rebuild + redeploy. See [`inspector-data-storage.md`](inspector-data-storage.md) §3 and §8.

## 9. First-time-contributor bootstrapping

The flow with the new website:

1. Visitor lands on the Inspector website. Sees the segments tab with sub-tabs (Available / Under review / Awaiting merge / Completed).
2. Browses freely without auth.
3. Finds an Available reciter, clicks **Claim**.
4. Modal: "Sign in with GitHub to claim. [Continue]".
5. GitHub App authorize page — approve.
6. Returns to the page in optimistic edit mode. No invite, no waiting tab.

Total clicks: **3 max** (Claim → Continue → Authorize). **1** for returning users with an active session. No collaborator status check. No `/claim` comment to remember.

The OAuth/App install also gives us:

- The user's identity for commit attribution (no separate prompt).
- A way to signal in the UI when their session expires.
- A path forward for a future "your contributions" page (issues/PRs assigned to you, work in progress).

## 10. Phased migration

Detailed per-phase file-IO scope, acceptance criteria, and risks live in [`inspector-data-storage.md`](inspector-data-storage.md) §9. High-level shape:

1. **Phase 0 — preparation (foundational, no deploy)**
   - Adopt the slug-first identity convention: branch `reciter/<slug>`, new title formats, marker registry, commit-subject prefixes. Update `process_requests.py::cmd_prepare_pr` accordingly.
   - Land `scripts/lib/reciter_task.py` (resolver) and `scripts/lib/reciter_state.py` (file parser + transition machine + mirror helpers).
   - Land `scripts/lib/markers.py` (parse/render every HTML-comment marker in [`inspector-state-management.md`](inspector-state-management.md) §6).
   - Create `data/reciter_catalog.json` (v2 schema with `reciter_id`, variant fields — see [`inspector-state-management.md`](inspector-state-management.md) §3).
   - Create `data/reciter_state.json` (seeded from current GitHub state via a one-shot script).
   - Add `update-reciter-state.yml` workflow handling all `repository_dispatch` event types.
   - Migrate other workflows to fire dispatch events instead of writing state. Decommission `pr-assignee-sync.yml`, `find_segments_pr.py`.
   - **Rewrite downstream producers** (`list_reciters.py`, `build_reciter.py --build-manifest`) to read identity from the catalog and status from the state file. Extend `sync-dataset.yml` and `update-reciters.yml` triggers. Land all producer rewrites in one merge group with a regression test against the pre-migration `reciters_index.json` shape — see [`inspector-state-management.md`](inspector-state-management.md) §10.
   - Add `@require_edit_lock` decorator (lookups state file; no-op while state file is unpopulated).

2. **Phase 1 — read-only deployment on HF Space, completed reciters via HF dataset**
   - **Free-tier prerequisites (deploy-blockers):** swap `app.run()` → `gunicorn -k gthread -w 2 --threads 8`; implement `services/github_fetch.py` with single-flight + parsed-cache layer (128 MB raw LRU + 128 MB parsed); add `Cache-Control: immutable` to peaks routes (CDN-front decision deferred).
   - HF dataset extension: `build_reciter.py --build-inspector-segments <slug>` publishes the 5 per-reciter completed-reciter files (segments, detailed, edit_history, edit_history_peaks, low_confidence_v2) under `inspector/segments/<slug>/` parallel to the existing TS shards. `sync-dataset.yml` extended; one-shot bootstrap seeds the dataset for currently-eligible reciters.
   - Frontend: `services/segments_hf_client.ts` fetches completed-reciter data direct from HF CDN. `/api/ts/config` extended to return `inspector_shard_url_template` and `globals_url_template` (globals served same-origin in deployed mode, not from HF).
   - Image build: root `.dockerignore` excludes `data/audio/`, `data/recitation_segments/`, `data/timestamps/`, `data/qul_downloads/`, `data/.cache/`, `inspector/frontend/src/`. Static data ~89 MB (extends current Dockerfile COPY list to all 10 reference files + the new consolidated `audio_catalog.json.gz`).
   - Audio catalog build: `scripts/build_audio_catalog.py` consolidates 391 per-reciter manifests into `data/audio_catalog.json.gz` (compact + gzipped, ~6 MB) at image build time.
   - Dockerfile env defaults flipped to deployed profile: `INSPECTOR_DATA_DIR=/app/data`, `INSPECTOR_QUA_DATA_PATH=/app/data`, `INSPECTOR_TS_SOURCE=huggingface`, `INSPECTOR_AUDIO_PROXY_ENABLED=0`. Local `docker-compose.yml` overrides back to `/data` + bind mount.
   - Deploy to HF Space (`hetchyy/quranic-inspector-dev` first); production cutover follows after dev validation. No persistent volume.
   - `routes/timestamps.py::ts_validate`, `routes/audio_proxy.py`, `app.py::serve_audio` excluded from deployed image (gated by env flags).
   - `/api/reciter-task/<slug>` endpoint live; UI shows reciter status pills.
   - Anonymous = view-only on completed reciters via HF CDN direct (no backend on the read path).

3. **Phase 2 — PR-branch reads (under-review reciters)**
   - github-fetch (already implemented in Phase 1) wired to the route handlers serving under-review data at `reciter/<slug>` ref.
   - Available + Under-review tabs render data from PR branches via github-fetch.
   - Edit affordances still hidden globally.
   - Add `editingDisabled` store consumed by every edit-affordance component.

4. **Phase 3 — auth and claim flow** (see [`inspector-auth-claim.md`](inspector-auth-claim.md) §11 for full acceptance criteria)
   - GitHub App user-to-server flow + session cookies.
   - `/api/claim`, `/api/release`, `/api/mark-ready`, `/api/unmark-ready` endpoints firing `repository_dispatch`.
   - Optimistic UI + reconciliation polling on `/api/reciter-task/<slug>`.
   - One-claim-per-user enforcement (maintainer/owner bypass with audit).
   - Enforce single-writer lock (no writes yet — saves still 403).

5. **Phase 5a — writes against existing edit_history schema**
   - `services/scratch.py` for scratch dir lifecycle.
   - `services/github_commit.py` for Git Data API multi-file commits.
   - Save flow rewired through scratch + debounced commit + user-attributed authorship.
   - Test end-to-end with one volunteer reviewer.

6. **Phase 5b — edit_history schema simplification**
   - Drop the file-hash chain (`file_hash_after`, `check_file_hash`, `file_sha256`).
   - Drop genesis record write + check.
   - Drop `backup_file()` calls in deployed save path.
   - Keep `edit_history_peaks.jsonl` (corrected — see §7).

7. **Phase 6 — workflow consolidation + decommission**
   - Add `pr-uniqueness.yml`, `inspector-deploy.yml`.
   - Cache invalidation webhook from `segments-pr-merged.yml` to `/api/internal/cache-invalidate`.
   - Delete `find_segments_pr.py`.
   - Slow `update-reciters.yml` cadence to every 30 min.
   - Update contributor docs to point to the website as the primary path.
   - Local Docker is now the offline / maintainer fallback.

## Open questions

- **Anonymous viewing of in-review PRs.** Default to yes (transparent process). Can flip later if maintainers prefer to keep WIP private.
- **CDN in front of Inspector.** Cold-start cache miss after a deploy hits github-fetch for every active user's first request. Fronting `/api/seg/data/*` with Cloudflare or Fly's edge cache makes only the first global user pay. Decision deferred to Phase 1 measurements.

The OAuth-App-vs-GitHub-App question is resolved: **GitHub App** (see [`inspector-auth-claim.md`](inspector-auth-claim.md) §2).

Detailed file-storage risks (rate limits, `detailed.json` size cap, single-flight semantics, App token expiry, scratch crash recovery, etc.) live in [`inspector-data-storage.md`](inspector-data-storage.md) §10.
