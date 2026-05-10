# Inspector Deployment Plan (v2)

Design for migrating the Inspector from a local-Docker-only tool to a hosted, frictionless contribution surface. The v2 model puts an HF Storage Bucket at the centre: bucket-mounted into the Space replaces github-fetch + Git Data API + scratch dir + debounce machinery; HF OAuth replaces the GitHub App for user identity; HF Jobs replace GH Actions for HF-side data work; GitHub stays as the home of code, code CI, the reciter catalog, `RECITERS.md`, and per-reciter Releases.

This document captures architectural decisions only. Concrete TODOs are derived from it later, phase by phase.

**Companion docs:**
- [`inspector-data-storage.md`](inspector-data-storage.md) — file-IO model: bucket mount semantics, HF dataset namespace, server-image bake list, per-file specs, perf budget.
- [`inspector-state-management.md`](inspector-state-management.md) — state file in the bucket, embedded state machine, transition matrix, reciter catalog still on GitHub.
- [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) — completion event fan-out: GH Actions (output to GitHub) vs HF Jobs (output to HF) vs Inspector (in-process).
- [`inspector-deploy-runbook.md`](inspector-deploy-runbook.md) — operational runbook: HF Space + bucket setup, HF OAuth, upload pipeline, smoke tests, rollback.
- [`inspector-admin-perms.md`](inspector-admin-perms.md) — roles, override actions, admin dashboard, audit log.
- [`inspector-cleanup-registry.md`](inspector-cleanup-registry.md) — running ledger of code deletions, modifications, new files, doc amendments.

## Goals

- Public website, view-only by default for everyone — all three tabs (Audio, Segments, Timestamps).
- Editing requires a single click ("Claim") that signs in via HF OAuth and assigns the user as the active reviewer of that reciter.
- One reciter, one reviewer at a time. Locked at the API gate, not just hidden in UI.
- A single bucket file (`<bucket>/state/reciter_state.json`) is the source of truth for reciter state. Inspector backend is the sole writer.
- HF dataset (`hetchyy/quranic-universal-ayahs`) is the canonical archive for completed reciters.
- HF bucket is the canonical working store for in-flight reciters (mutable, mounted into the Space).
- GitHub remains the source of truth for code, the curated reciter catalog, and consumer-facing Releases.
- Existing offline alignment / TS extraction / per-verse audio dataset publishing keeps working; their inputs change from "git-tracked files" to "files in the bucket".

## Non-goals

- Real-time collaborative editing. One reviewer per reciter is enforced.
- A separate database. The bucket file IS the database. Inspector caches in memory; doesn't own state any more durably than the bucket.
- Public rejection / re-extraction / param-rerun flows. These remain internal-only operations; the website does not surface them as states.
- Schema migration of `edit_history.jsonl` for backwards compatibility. The hash chain is being removed (see §7); writes after rollout follow the new schema.
- Maintaining GitHub PR branches per reciter. The bucket is the working store; GitHub PRs were ceremony — the Inspector History tab is the diff-review surface.
- Per-edit GitHub commit attribution for contributors. Contribution is recorded in `<bucket>/state/audit.jsonl`. Future contributor-recognition surfaces (a "your contributions" page) read from there.

## 1. Reciter lifecycle (eight states — 7 happy-path + `discarded`)

State is owned by `<bucket>/state/reciter_state.json`. Inspector backend is the sole writer; embedded state machine validates every transition before persisting. See [`inspector-state-management.md`](inspector-state-management.md) §4 for the full state machine and event vocabulary.

| State | Editable | Assignee | Inspector behaviour |
|---|---|---|---|
| `catalogued` | No | — | Hidden from segments tab. Surfaced via "Request alignment" which routes to the Reciter Requests Space. |
| `awaiting_alignment` | No | — | Tab card shows "Pipeline running" with the issue link. Cannot be claimed. |
| `awaiting_review` | No (claimable) | — | Listed in "Available for review". Bucket entry exists with seeded alignment output. Claim button visible. |
| `under_review` | **Yes** for the assignee, view-only otherwise | set | Listed in "Under review". Lock banner for non-assignees. Reviewer's saves write directly to bucket-mounted files. |
| `ready_for_merge` | No (frozen) | retained | Listed in "Awaiting merge". Reviewer can unmark or release; maintainer publishes (snapshots bucket → HF dataset, drops bucket entry) or sends back. |
| `awaiting_timestamps` | No | — | Bucket → dataset snapshot done. TS pipeline running. Listed in "Completed" tab; view-only. |
| `completed` | No | — | TS done; reciter live in dataset. Listed in "Completed" tab. View-only. |
| `discarded` | No | — | Hidden from anonymous lists. Visible only to maintainers under "Internal" filter. Set via admin `reciter.discarded` event with typed confirmation. Recovery via `state.manual_override`. See [`inspector-admin-perms.md`](inspector-admin-perms.md) §5.5 + §11. |

Deferred (state machine flexible to add later, no automation today):

- Re-edits of completed reciters — re-claim re-creates the bucket entry from the dataset snapshot.
- Audio-source changes forcing realignment.
- Alignment-failed retry surfaces.
- `discarded` / abandon flow.
- Multi-reviewer / pair-review.

## 2. Identity convention (slug as the canonical ID)

The slug is just a unique ID string. **No parser ever extracts semantic meaning from it.** All dimensions that matter — name, riwayah, style, source, year, variant grouping — are catalog fields in `data/reciter_catalog.json` (still on GitHub, see [`inspector-state-management.md`](inspector-state-management.md) §3).

Surviving conventions:

| Artifact | Convention | Example |
|---|---|---|
| Reciter request issue title | `[request] <slug>: <Display Name>` | `[request] saad_al_ghamdi: Saad Al-Ghamdi` |
| Issue body marker | `<!-- reciter-task: slug=<slug> schema=1 -->` | `<!-- reciter-task: slug=saad_al_ghamdi schema=1 -->` |
| Bucket path for in-flight data | `<bucket>/wip/<slug>/` | `<bucket>/wip/saad_al_ghamdi/` |
| HF dataset path for completed data | `inspector/segments/<slug>/` | `inspector/segments/saad_al_ghamdi/` |
| Inspector URL path | `/r/<slug>` | `/r/saad_al_ghamdi` |

Dropped vs v1:

- Branch convention `reciter/<slug>` — no branches, bucket is the working store
- PR title convention — no per-reciter PRs
- Commit subject conventions (`[<slug>] [wip] ...`, `[<slug>] [pipeline] ...`, `[state] <slug>: <event>`) — no per-edit commits
- Squash-merge subject convention — no merges
- `find_segments_pr.py` — nothing to find
- HTML-comment markers in PR bodies — no PR bodies

`scripts/lib/reciter_task.py` simplifies dramatically: given a slug, returns `{slug, state, assignee, ...}` from the bucket state file. No PR/branch resolution paths.

## 3. Deployment architecture

The Inspector backend stays Python (Flask + gunicorn-gthread). Its 12 validators (the load-bearing accordion order), the phonemizer integration, peaks/ffmpeg, and the save flow's atomic-write + history append are too much code to port to the browser. The deployed backend is **stateless for reads** (HF CDN serves completed reciters direct to the browser) and **mostly stateful for writes** through the mounted bucket — the bucket IS the persistence layer, not a remote API the backend calls.

See [`inspector-data-storage.md`](inspector-data-storage.md) for the file-by-file specification, bucket mount semantics, image build rules, and per-phase acceptance criteria.

### Read path

Three tiers based on reciter state:

1. **Completed reciters** — browser fetches Inspector data direct from HF CDN at `inspector/segments/<slug>/<file>.gz` under the `hetchyy/quranic-universal-ayahs` dataset, parallel to the existing TS shards and slim Aligner shards. Backend uninvolved on the read path.
2. **Under-review / awaiting-review reciters** — backend reads from `<INSPECTOR_BUCKET_MOUNT>/wip/<slug>/...` like any local file. NFS lazy-fetches bytes the first time; local cache absorbs repeat reads.
3. **Static reference data** (Quran word text, controlled vocabularies, the consolidated audio URL catalog) — baked into the Space image, served same-origin via `/api/static/...`. Browser caches forever via `Cache-Control: immutable`. Audio playback browser → origin direct. Timestamps browser → HF CDN direct (already implemented per [`timestamps-tab-deployment-plan.md`](../../timestamps-tab-deployment-plan.md)).

No worktrees. No github-fetch. No GitHub rate-limit budget consumed for any per-reciter read. The Space backend is in the read path only for under-review reciters, where it's already going to be involved in auth/state/lock checks.

Active reviewer reading their own slug's data goes through the same bucket mount as anyone else — there's no separate "scratch" concept. Mount-managed flush window (2–30 s, see data-storage §3) is the bound on staleness for non-owner viewers.

### Write path

Writes are gated to the one active reviewer per reciter. For that reviewer:

1. Browser POSTs to `/api/seg/save/<reciter>/<chapter>` with the user's session cookie.
2. Backend's `@require_edit_lock(reciter)` decorator verifies the authenticated user is the assignee in the bucket state file. Returns 403 otherwise.
3. `save_seg_data()` runs against `<INSPECTOR_BUCKET_MOUNT>/wip/<slug>/data/recitation_segments/<slug>/...` — **same code path as local mode**, only `INSPECTOR_DATA_DIR` differs. Atomic write `detailed.json`, rebuild `segments.json`, snapshot validation, append `edit_history.jsonl`, append `edit_history_peaks.jsonl`.
4. Mount handles flush. Advanced mode (NFS default) buffers to local disk, flushes async on a 2–30 s window.

That's it. No debounce timer in Inspector code, no Git Data API client, no scratch lifecycle, no commit attribution machinery. The save flow's existing semantics (atomic local write) are preserved; the path just points at a mount.

### Attribution

Per-edit attribution lives in `<bucket>/state/audit.jsonl` — one append per state-changing event:

```jsonc
{ "ts": "2026-05-08T14:23:11Z",
  "slug": "saad_al_ghamdi",
  "event": "claimed",
  "actor": { "login": "alice", "hf_user_id": "...", "noreply_email": "..." } }
```

Per-edit save activity within an active claim is not separately audited at the state level — the existing `edit_history.jsonl` (which lives in the bucket alongside the segments files) is the per-edit ledger, and was already designed for in-app History panel browsing.

For external recognition (contributor profiles, contribution graphs): future feature, reads from `audit.jsonl` and surfaces a "your contributions" page on the Inspector website.

### Hosting target

**Hugging Face Spaces (Docker SDK, free CPU-basic tier)** with one HF bucket mounted as a read-write volume. Same operational pattern as the existing project Spaces, plus the new bucket primitive. Free at the targeted scale (2 vCPU, 16 GB RAM, ephemeral disk + bucket-mount). Migration target if/when CPU saturation forces it: HF CPU-upgrade ($0.03/h) or Fly.io shared-cpu-2x@2GB ($5/mo).

**No persistent volume required beyond the bucket mount itself** — the bucket is the persistence layer; everything else is ephemeral.

**Image footprint** ~300–400 MB (~89 MB static reference data including the consolidated `audio_catalog.json.gz` + Python deps + Alpine static ffmpeg + frontend dist). Image rebuilds on code or static-data changes only.

**Operational topology:** dev Space (`hetchyy/quranic-inspector-dev`, private) tracks the `dev` branch; prod Space (`hetchyy/quranic-inspector`, public) tracks `main`. Each Space mounts its own buckets (data: `hetchyy/quranic-inspector-bucket{,-dev}`; private metadata: `hetchyy/quranic-inspector-meta{,-dev}`). Dev and prod are completely independent — no shared catalog, no shared state, no cross-contamination possible. Stable URLs (`https://hetchyy-quranic-inspector{,-dev}.hf.space`); custom domain supported.

### Free-tier prerequisites

The deploy is **blocked** on two changes before exposing to the public on free CPU-basic. Without them, p95 latency at 10 concurrent users runs 2–4 s during scrubbing bursts.

1. **Replace `app.run()` with `gunicorn -k gthread -w 1 --threads 16`** in the Dockerfile CMD. Werkzeug dev server is not production-grade. **One worker × 16 threads** (not `-w 2`) — every in-memory structure in v2 (state_store, per-slug mutex, signed-cookie verification, `pending_jobs`, force-claim leases, role cache) assumes single-process. Multi-worker requires a shared coordinator that v2 does not include. Add a startup assertion (`if workers != 1: raise`).
2. **`Cache-Control: public, max-age=31536000, immutable` on peaks routes** (`/api/seg/segment-peaks`, `/api/seg/peaks`). First bottleneck on free tier is **ffmpeg subprocess fork on the per-segment peaks route** during scrubbing; CDN-fronting absorbs the burst.

(The v1 third prerequisite — single-flight + parsed-cache layer in github-fetch — is gone with github-fetch.)

## 4. Authentication & claim flow

### HF OAuth (Sign in with Hugging Face)

Auto-managed via `hf_oauth: true` in the Space `README.md` frontmatter. Adding it injects `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET`, `OPENID_PROVIDER_URL` as runtime env vars; no separate OAuth client registration. Default scopes (`openid profile`) cover user identity. Token lifetime configurable via `hf_oauth_expiration_minutes` (default 8 h, max 30 days).

Frontmatter:

```yaml
hf_oauth: true
hf_oauth_expiration_minutes: 480
# scopes default to openid profile; explicit scope add not needed for our flow
```

The Space's bucket-write authority comes from the Space-level `INSPECTOR_HF_TOKEN` secret — that's how the Space writes to the bucket regardless of which user is logged in. User identity is HF OAuth; bucket-write authority is the Space's own HF token. Two separate concerns.

### Anonymous

No login required. All three tabs render in view-only mode. The "Claim" button is disabled with a tooltip "Sign in with HF to claim".

### Logged-in contributor

HF OAuth login establishes a **self-contained signed-cookie session** carrying `{login, hf_user_id, role, expires_at, csrf}` — no server-side session table. (Authlib's OAuth-state store between authorize and callback uses Flask-Session on tmpfs; cleared on container restart but only needed for ~30 s during the OAuth round-trip.) After sign-in, identity comes from the verified cookie. The user's HF token is not stored or used by the backend — bucket writes use the Space's token. Cookie max-age = `hf_oauth_expiration_minutes` (default 8 h); on expiry, force re-auth (no refresh-token storage in Inspector).

`hf_user_id` is sourced from the OIDC `sub` field returned by `https://huggingface.co/oauth/userinfo` — stable across HF username renames. The `login` field can change; lock-ownership checks compare `hf_user_id`, not `login`. See [`inspector-deploy-runbook.md`](inspector-deploy-runbook.md) §3 for the full OAuth flow.

### One-click claim flow

1. Logged-in user clicks **Claim** on an Available reciter.
2. Backend's API gate validates state and one-claim-per-user, then:
   - Acquires an in-process mutex on the slug.
   - Re-validates inside the mutex.
   - Writes the new state to `<bucket>/state/reciter_state.json` (transitions `awaiting_review → under_review`, sets `assignee`, `assignee_since`).
   - Appends to `<bucket>/state/audit.jsonl`.
   - Returns 200 with the authoritative new state. **No optimism needed** — the write is synchronous; the response is the truth.
3. UI flips to edit mode immediately.

A first-time visitor sees a sign-in modal once; thereafter the flow is one click.

**Total clicks: 3 max** (Claim → modal Continue → HF authorize). **1** for returning users with an active session.

### Mark ready

When the reviewer is done, they click **Mark ready** in the banner. Backend writes `state = ready_for_merge` to the bucket state file. State transitions; assignee retained. The reciter is frozen from edits and surfaced to the maintainer queue under "Awaiting merge". A maintainer clicks **Publish** in the admin dashboard which transitions to `awaiting_timestamps` and fires the `reciter.completed` event (see [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md)).

The reviewer can pull the claim back with **Continue editing** before the maintainer publishes (transitions back to `under_review`). A maintainer can send it back via [`inspector-admin-perms.md`](inspector-admin-perms.md) §5.10.

### Release flow (assigned reviewer changes mind)

The **Release claim** button calls `POST /api/release/<slug>` which writes the state (clears assignee, transitions `under_review` or `ready_for_merge` → `awaiting_review`). Saved edits remain in the bucket — a future reviewer continues from there.

### What HF Spaces gives us for free

- OAuth client auto-registration (`hf_oauth: true`)
- Token issuance, refresh, revocation, callback handling
- Org gating via `hf_oauth_authorized_org` (e.g., restrict logins to specific HF orgs if maintainer-only routes ever need it)
- User profile data (`login`, avatar, etc.)

The user's HF token is never seen by the backend. The Space's own `INSPECTOR_HF_TOKEN` is the only HF write credential.

### Endpoints (mutating, all return 200 with authoritative state)

| Endpoint | Action |
|---|---|
| `GET /api/auth/login` | Initiates HF OAuth flow. Captures `?return=<path>` for post-login redirect. |
| `GET /api/auth/callback` | Handles HF redirect. Verifies CSRF, exchanges code, fetches `/api/whoami`, creates session, redirects. |
| `POST /api/auth/logout` | Clears session cookie. Does NOT release any active claim. |
| `GET /api/me` | Returns `{ login, hf_user_id, role, active_claim }`. |
| `POST /api/claim/<slug>` | One-claim-per-user check; acquires mutex; writes bucket state; appends audit. |
| `POST /api/release/<slug>` | Verifies caller is current assignee; writes state; appends audit. Idempotent. |
| `POST /api/mark-ready/<slug>` | Verifies caller is current assignee on `under_review`; writes state. |
| `POST /api/unmark-ready/<slug>` | Verifies caller is current assignee on `ready_for_merge`; writes state. |
| `GET /api/reciter-task/<slug>` | Returns full state + `can_*_for_current_user` predicates. |
| `POST /api/admin/publish/<slug>` | Maintainer-only. Transitions `ready_for_merge → awaiting_timestamps`. Fires `reciter.completed` to GH Actions + HF Jobs (see [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md)). |

All mutating endpoints are gated by the API lock (§5).

### Edge cases

| Scenario | Behavior |
|---|---|
| **Concurrent claims** on same `awaiting_review` | In-process mutex serializes. First wins. Second sees authoritative `under_review` and rejects with 409 + toast "Already claimed by @other." |
| **One claim per user** violation | API returns 409 `existing_claim: <slug>`. Frontend toast: "Release [other] first to claim [this]." |
| **Same user, two tabs, same reciter** | Mutex on `(slug, login)` serializes save bursts. Both tabs see identical state. |
| **Mark-ready with save in flight** | Save POST holds the lock on `(slug, login)`; mark-ready waits. |
| **Bucket write fails** (HF outage, token revoked) | API returns 503 with retry hint. Backend logs the failure with full request payload for replay. |
| **HF OAuth revoked by user mid-session** | Backend's session is still valid (cookie-signed). Next time user signs in fresh, gets new token. Their claim survives. |
| **Two reviewers' clocks differ** | Backend writes `state_since` from `time.time()` on the Space; immune to client clock skew. |
| **Reviewer marks ready, walks away forever** | Maintainer publishes, sends back, or force-releases via admin actions. |

### Security model

| Threat | Mitigation |
|---|---|
| Session theft | HttpOnly + Secure + SameSite=Lax cookie, signed with HMAC. Server-side session record holds identity; cookie is opaque. Logout invalidates server-side. |
| CSRF on mutating endpoints | Same-site cookie + origin/referer check. `state` parameter on OAuth callback prevents auth CSRF. |
| Malicious reviewer destructive edits | Edit lock enforces one writer per reciter. Append-only `audit.jsonl` per-state and `edit_history.jsonl` per-edit. State writes are server-side only; client cannot forge transitions. |
| `INSPECTOR_HF_TOKEN` leak | Stored as Space secret (encrypted at rest). Rotation = generate new HF token, update Space secret, restart. ~5 min operation. Revokes the old token. |
| Maintainer impersonation | Roles resolved against `data/inspector_owners.json` (cached from GitHub raw). Backend never trusts user-supplied claims. |

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
            entry = state_store.get(reciter)  # parsed bucket state file
            if entry is None or entry.state != 'under_review' or entry.assignee != user.login:
                abort(403, description="Reciter is not editable by this user")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
```

The lookup is a dict access on the in-memory parsed state — `state_store` is hydrated on startup from the bucket file and refreshed on every state write (Inspector is the sole writer, so cache invalidation is local).

Endpoints to gate (audit checklist):

- `POST /api/seg/save/<reciter>/<chapter>`
- `POST /api/seg/undo-batch/<reciter>`
- `POST /api/seg/undo-ops/<reciter>`
- `POST /api/seg/trigger-validation/<reciter>` — gated even though "read-only side effect" because it warms a per-reciter cache that's expensive to compute and easy to abuse anonymously.

**Single-worker assumption.** All locking and `state_store` invariants below assume one gunicorn worker process. The Dockerfile CMD ships `gunicorn -k gthread -w 1 --threads 16` and the app asserts `workers == 1` at startup. Multi-worker scale-out is deferred until a shared coordinator (Redis or bucket-CAS) is added — see [`inspector-data-storage.md`](inspector-data-storage.md) §11 scaling triggers.

### Frontend hiding (cleanliness, not security)

A single `editingDisabled` derived store consumed by every component that has an edit affordance. Audit checklist:

- `tabs/segments/components/list/SegmentRow.svelte` — inline trim/split/merge/delete buttons.
- `tabs/segments/components/validation/{ErrorCard,GenericIssueCard,MissingWordsCard,MissingVersesCard,ValidationPanel}.svelte` — accordion edit dispatchers.
- `tabs/segments/components/history/{EditChainRow,HistoryBatch}.svelte` — undo buttons.

The frontend hides the buttons; the backend rejects unauthorized POSTs even if the frontend is bypassed.

### Single-writer per reciter (server-side)

In-process mutex keyed on `(reciter, user)` with a short lease (~60 s, refreshed on each save). Prevents the same user opening two tabs from racing on bucket writes. If the deployment scales to multiple Space replicas later, this lock moves to a small Redis or to bucket-side optimistic concurrency (read-version → write-if-version).

## 6. State management (bucket file is source of truth)

Pipeline state, assignee, issue numbers, and per-reciter event history live in **`<bucket>/state/reciter_state.json`** — Inspector backend is the sole writer; embedded state machine in `services/state.py` validates every transition before persisting. **No GitHub workflow is involved** in state writes.

Static identity (display name, riwayah, audio source, `url_template`) lives separately in **`data/reciter_catalog.json`** on GitHub, updated by manual PRs from the Reciter Requests intake. Two stores, two cadences, two clean histories.

Inspector reads both files (catalog from GitHub raw on startup, state from bucket on startup, both refreshed on demand) and bases every UI affordance on them.

### Why a flat bucket file beats labels-as-state, a database, and a GitHub-tracked file

- Labels drift (manual edits, race conditions). The bucket file does not — Inspector serializes writes through the in-process mutex.
- A database adds operational surface (auth, backups, schema migrations, connection management) for a sub-1/sec write rate. A JSON file in a bucket with `audit.jsonl` as the audit trail is simpler at every level. ~150 KB at 300 reciters.
- GitHub-tracked: every state change would have been a commit, which v1 had. v2 drops it because (a) `repository_dispatch` propagation latency made claim/release feel laggy, (b) every state change cluttered `git log`, (c) merge conflicts on the state file required workflow `concurrency: singleton`. Bucket has none of these problems.

### Inspector is the sole writer

There's no `update-reciter-state.yml` workflow in v2. The state machine, transition validation, and mirroring (where applicable) all live in Inspector backend code. The only consumers of state outside Inspector are:

- GH Actions (`update-reciters.yml`, `release.yml`) — read state via `huggingface_hub` to know which reciters to include
- HF Jobs (`snapshot-bucket-to-dataset`, etc.) — same
- Reciter Requests Space — fires events into Inspector's webhook to add new slugs to catalog

External consumers fetch state read-only; they don't write.

### Workflow consolidation

| Existing workflow | Action |
|---|---|
| `bot-create-issue.yml` | Keep — used by Reciter Requests Space to file new request issues |
| `bot-create-pr.yml`, `bot-comment.yml` | **Delete** — no PRs to create, no automated PR comments |
| `issue-commands.yml` (`/claim`, `/confirm`) | **Delete** — Inspector website is the contribution surface; CLI fallback retired |
| `pr-assignee-sync.yml` | **Delete** — no PRs |
| `validate-segments-pr.yml` | **Delete** — no segments PRs; validation runs in Inspector + at publish-time in HF Job |
| `segments-pr-merged.yml` | **Delete** — replaced by Inspector `POST /api/admin/publish/<slug>` |
| `timestamps-refresh.yml` | **Move to HF Job**; kept temporarily for manual runs |
| `update-reciters.yml` | **Keep** — regenerates `RECITERS.md` from bucket state read via `huggingface_hub` |
| `release.yml` | **Keep** — per-reciter GitHub Release zips, reads from bucket via `huggingface_hub` |
| `sync-dataset.yml` | **Move audio-data publishing to HF Job**; the dataset-card refresh stays on GH Actions |
| `validate-edit-history.py` | Keep, drop file-hash check (§7) |
| `update-reciter-state.yml` (v1 plan) | **Never built** — Inspector is sole writer |
| `pr-uniqueness.yml` (v1 plan) | **Never built** — no PRs |
| `inspector-deploy.yml` (NEW) | Add — on `inspector/**` push to `main`, push to prod Space |
| `find_segments_pr.py` | **Delete** — nothing to find |

The post-completion fan-out (snapshot to dataset, refresh timestamps, build audio dataset) is documented in [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md).

## 7. Edit-history simplifications

The current schema and validators evolved organically and carry weight that the new deployment model makes obsolete.

### Remove the file-hash chain

`edit_history.jsonl` carries `file_hash_after` per batch. `validate_edit_history.py` checks that the *latest* record's hash matches the current `detailed.json` — designed to detect manual tampering with the JSON between Inspector saves.

In the deployed model:

- All writes go through `save_seg_data()` running on the backend. There is no out-of-band path.
- Manual file edits are no longer a supported workflow.
- Re-extraction (which previously broke the chain) is internal-only and can rotate the history file at the source.

The file-hash field and its validator check go away. Kept:

- `batch_id` — needed for undo lookup.
- `schema_version` — for future migrations.
- `validation_summary_before` / `validation_summary_after` — drives the in-app history viewer.
- `operations` array with patches — needed for undo.
- `reverts_batch_id` / `reverts_op_ids` — needed for filtering reverted batches.

The genesis record can also go — it exists to anchor the hash chain and has no other purpose.

### Keep `edit_history_peaks.jsonl`

Real file size is ~1–2 MB per reciter (not 20 MB). Read path exists at `routes/peaks.py:90` (`seg_history_peaks_get`) wired to the History panel via `tabs/segments/utils/data/reciter-actions.ts:73` (parallel fetch on session load) and `tabs/segments/utils/playback/preview.ts:209` (lazy POST during playback). The feature lets anyone — including anonymous viewers — open a reciter's History panel and see waveform shapes render instantly without recomputing from audio. Dropping it would regress that UX.

### Drop the `_meta.audio_source` peek

`discover_ts_reciters` opens each `timestamps.json` and reads the first 512 bytes to extract `audio_source`. In the new model, the catalog file carries this directly. The peek can be deleted.

## 8. Other simplifications worth considering

These reduce surface area while we're here:

- **`docker-compose.yml` becomes the offline-only path.** Document it as "for maintainers reviewing locally without internet" in `inspector/CLAUDE.md`. The default contributor experience is the website.
- **Drop the audio proxy** (`routes/audio_proxy.py`) for the deployed instance. The backend's only role for audio is to set CORS, which the browser can get directly from origin. Local Docker keeps the proxy.
- **Drop the validation panel in deployed mode.** `routes/timestamps.py::ts_validate` is removed from the deployed image entirely. Validation remains in local mode for maintainers. Removes the cross-file timestamps↔segments dependency.
- **Audio manifests consolidated into `audio_catalog.json.gz`** and baked into the Space image (~6 MB gzipped). Browser fetches once on Audio-tab mount; switching reciters is zero-fetch.

## 9. First-time-contributor bootstrapping

The flow with the new website:

1. Visitor lands on the Inspector website. Sees the segments tab with sub-tabs (Available / Under review / Awaiting merge / Completed).
2. Browses freely without auth.
3. Finds an Available reciter, clicks **Claim**.
4. Modal: "Sign in with Hugging Face to claim. [Continue]".
5. HF OAuth authorize page — approve.
6. Returns to the page in edit mode. Banner: "You're reviewing X. [Mark ready] [Release]".

Total clicks: **3 max** (Claim → Continue → Authorize). **1** for returning users with an active session. No GitHub account needed. No `/claim` comment to remember. No collaborator invite.

The OAuth flow gives us:

- The user's HF identity for audit attribution
- A way to signal in the UI when their session expires
- A path forward for a future "your contributions" page reading from `audit.jsonl`

CLI fallback is dropped — the v1 plan kept `/claim` and `/confirm` issue commands for terminal users, but the website is now low-friction enough that maintaining a parallel CLI surface costs more than it's worth. Power users who want to push directly via git: not supported in v2; see admin docs for manual workflows.

## 10. Phased migration

Detailed per-phase scope, acceptance criteria, and risks live in [`inspector-data-storage.md`](inspector-data-storage.md) §9, [`inspector-state-management.md`](inspector-state-management.md) §11, and [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md). High-level shape:

1. **Phase 0 — Foundation (no deploy)**
   - Adopt the slug-rules-only identity convention (drop branch/PR conventions).
   - Land `scripts/lib/reciter_task.py` (slug resolver against catalog + state).
   - Create `data/reciter_catalog.json` v2 schema with `reciter_id`, variant fields.
   - Create the HF buckets (dev + prod).
   - **Manually seed** the bucket state file at v2 cutover (~15 reciters; mapping rules in [`inspector-state-management.md`](inspector-state-management.md) §3 "State seeding"). No migration script — too few rows to justify.
   - Land `inspector/services/state.py` (state machine + bucket persistence).
   - Land `inspector/services/hf_bucket.py` (mount path resolver + write helpers).

2. **Phase 1 — Read-only deploy (anonymous, completed reciters via HF)**
   - **Free-tier prerequisites:** swap `app.run()` → gunicorn-gthread; add `Cache-Control: immutable` to peaks routes.
   - HF dataset extension: `build_reciter.py --build-inspector-segments <slug>` publishes the 5 per-reciter completed-reciter files under `inspector/segments/<slug>/`. One-shot bootstrap for current eligible reciters.
   - Frontend: `services/segments_hf_client.ts` fetches completed-reciter data direct from HF CDN.
   - Image build: `.dockerignore` + extended COPY list + `audio_catalog.json.gz`.
   - Dockerfile env defaults flipped: `INSPECTOR_DATA_DIR=/app/data`, `INSPECTOR_QUA_DATA_PATH=/app/data`, `INSPECTOR_TS_SOURCE=huggingface`, `INSPECTOR_AUDIO_PROXY_ENABLED=0`, `INSPECTOR_BUCKET_MOUNT=/data/inspector-bucket`.
   - Deploy to dev Space first; bucket mounted but empty; production cutover after dev validation.
   - `/api/reciter-task/<slug>` endpoint live; UI shows reciter status pills (state read from bucket).

3. **Phase 2 — Bucket reads for under-review reciters**
   - Backend reads under-review data from `<bucket>/wip/<slug>/...`.
   - One-shot migration: copy current `data/recitation_segments/<slug>/` for any in-flight reciter into the bucket.
   - Available + Under-review tabs render data from the bucket.
   - Edit affordances still hidden globally.

4. **Phase 3 — Auth + claim flow**
   - HF OAuth via `hf_oauth: true` frontmatter.
   - `/api/claim`, `/api/release`, `/api/mark-ready`, `/api/unmark-ready` write directly to the bucket state file.
   - In-process mutex per slug (single-worker assumption — see §5).
   - One-claim-per-user enforcement (maintainer/owner bypass with audit).
   - No saves yet — writes still 403.

5. **Phase 4 — Read-only admin dashboard + role resolution**
   - `/admin` route gated by maintainer+ role; 404 for everyone else (does not flash).
   - `services/role.py` resolves role from `data/inspector_owners.json` (and optional `inspector_maintainers.json`) on GitHub raw with 60 s cache + bake-in fallback for offline boot.
   - Read-only sections: System health, all reciters, stalled reciters, recent events log, contributor activity. **No override actions yet.**
   - Audit-log reader UI; `<bucket>/state/audit.jsonl` populated by Phase 3 already.
   - **No save endpoint yet** — Phase 5 work.

   *Why a separate phase:* admin UX needs role resolution, which needs OAuth (Phase 3). It's strictly easier to validate read-only views before adding override mutations. Earlier drafts of this plan tried to slot admin views into Phase 1 (no auth) — that doesn't work.

6. **Phase 5 — Writes + claim overrides**
   - Save flow points at `<bucket>/wip/<slug>/...`.
   - Existing `save_seg_data()` runs unchanged — only the data path differs.
   - Mount handles flush. No debounce code in Inspector.
   - Test end-to-end with one volunteer reviewer on a `_test_*` reciter.
   - Drop `file_hash_after`, genesis record, `backup_file()` calls in deployed save path.

7. **Phase 6 — Publish pipeline + cleanup**
   - `POST /api/admin/publish/<slug>` triggers HF Jobs (snapshot-to-dataset, timestamps-refresh, build-per-verse-audio) and GH Actions (`update-reciters.yml`, `release.yml`).
   - Decommission v1 workflows: `bot-create-pr.yml`, `bot-comment.yml`, `issue-commands.yml`, `pr-assignee-sync.yml`, `validate-segments-pr.yml`, `segments-pr-merged.yml`.
   - Delete v1 scripts: `find_segments_pr.py`.
   - Update contributor docs to point to the website as the primary path.
   - Local Docker is now the offline / maintainer fallback.

## Open questions

- **CDN in front of Inspector.** Cold-start cache miss after a deploy hits backend reads for every active user's first request. Fronting `/api/seg/data/*` with Cloudflare or Fly's edge cache makes only the first global user pay. Decision deferred to Phase 1 measurements.
- **Bucket mount backend (NFS vs FUSE).** NFS is the default and recommended; FUSE is an option for Spaces that need streaming-mode appends. Decide based on Phase 2 measurements — if `edit_history.jsonl` appends feel slow, switch to streaming-mode FUSE for that file.
- **Multi-Space replica scale-out.** Single Space replica handles ≤50 concurrent reviewers per the perf budget. Beyond that, the in-process mutex needs to move to bucket-side optimistic concurrency or a small Redis. Defer until measured.

Detailed file-storage and perf risks live in [`inspector-data-storage.md`](inspector-data-storage.md) §10–§11.
