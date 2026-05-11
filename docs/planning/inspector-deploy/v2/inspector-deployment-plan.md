# Inspector Deployment Plan (v2)

Design for migrating the Inspector from a local-Docker-only tool to a hosted, frictionless contribution surface. The v2 model puts ONE private HF Storage Bucket per env at the centre: bucket-mounted into the Space replaces github-fetch + Git Data API + scratch dir + debounce machinery; HF OAuth replaces the GitHub App for user identity; HF Jobs replace GH Actions for HF-side data work; GitHub stays as the home of code, code CI, `RECITERS.md`, and per-reciter Releases. The reciter catalog and curated vocab also move into the bucket as a single JSON file — GitHub is no longer in the catalog read path.

This document captures architectural decisions only. Concrete TODOs are derived from it later, phase by phase.

**Companion docs:**
- [`inspector-data-storage.md`](inspector-data-storage.md) — file-IO model: bucket mount semantics, image bake list, per-file specs, perf budget.
- [`inspector-state-management.md`](inspector-state-management.md) — state JSON file in the bucket, embedded state machine, transition matrix, catalog JSON file in the bucket.
- [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) — publish fan-out: synchronous in-process bucket move + 1 async HF Job for timestamps.
- [`inspector-deploy-runbook.md`](inspector-deploy-runbook.md) — operational runbook: HF Space + bucket setup, HF OAuth, upload pipeline, smoke tests, rollback.
- [`inspector-admin-perms.md`](inspector-admin-perms.md) — roles, override actions, admin dashboard, audit log.
- [`inspector-cleanup-registry.md`](inspector-cleanup-registry.md) — running ledger of code deletions, modifications, new files, doc amendments.

## Goals

- Public website, view-only by default for everyone — all three tabs (Audio, Segments, Timestamps).
- Editing requires a single click ("Claim") that signs in via HF OAuth and assigns the user as the active reviewer of that reciter.
- One reciter, one reviewer at a time. Locked at the API gate, not just hidden in UI.
- A single bucket file (`<bucket>/state/reciter_state.json`) is the source of truth for reciter state. Inspector backend is the sole writer.
- One private HF bucket per env holds everything Inspector reads or writes — in-flight WIP, published, state, audit, and catalog. No public bucket; browser reads flow through the Inspector backend (which is in the path for auth/state/lock anyway).
- HF dataset (`hetchyy/quranic-universal-ayahs`) stays for downstream consumers (training parquet, GitHub release zips). Inspector never reads from it.
- GitHub remains the source of truth for code and consumer-facing Releases.
- Existing offline alignment / TS extraction keeps working; their inputs change from "git-tracked files" to "files in the bucket".

## Non-goals

- Real-time collaborative editing. One reviewer per reciter is enforced.
- A separate database. Plain JSON files in the bucket ARE the database; pydantic models at the service boundary do validation + schema migration.
- Public rejection / re-extraction / param-rerun flows. These remain internal-only operations; the website does not surface them as states.
- Schema migration of `edit_history.jsonl` for backwards compatibility. The file-hash chain is being removed (see §7); writes after rollout follow the new schema.
- Maintaining GitHub PR branches per reciter. The bucket is the working store; GitHub PRs were ceremony — the Inspector History tab is the diff-review surface.
- Per-edit GitHub commit attribution for contributors. Contribution is recorded in `<bucket>/audit/<YYYY>-<MM>.jsonl`. Future contributor-recognition surfaces (a "your contributions" page) read from there.

## 1. Reciter lifecycle (six states + `marked_ready` bool + `visibility` enum)

State is owned by `<bucket>/state/reciter_state.json`. Inspector backend is the sole writer; embedded state machine validates every transition before persisting. See [`inspector-state-management.md`](inspector-state-management.md) §4 for the full state machine and event vocabulary.

Six lifecycle states. **`ready_for_merge` is NOT a state** — it is a `marked_ready: bool` column on rows whose state is `under_review`. **`discarded` is NOT a state** — it is `visibility: 'discarded'`, an enum column orthogonal to lifecycle. Both are flag-style mutations on the same row, not separate state values.

| State | Editable | Assignee | Inspector behaviour |
|---|---|---|---|
| `catalogued` | No | — | Hidden from segments tab. Maintainer manually adds the row via `POST /api/admin/catalog/add` and triggers alignment. |
| `awaiting_alignment` | No | — | Tab card shows "Pipeline running". Cannot be claimed. |
| `awaiting_review` | No (claimable) | — | Listed in "Available for review". Bucket entry exists with seeded alignment output. Claim button visible. |
| `under_review` (with `marked_ready=0`) | **Yes** for the assignee, view-only otherwise | set | Listed in "Under review". Lock banner for non-assignees. Reviewer's saves write directly to bucket-mounted files. |
| `under_review` (with `marked_ready=1`) | No (frozen) | retained | Listed in "Awaiting merge". Reviewer can unmark; maintainer publishes (in-process bucket move `wip/<slug>/` → `published/<slug>/`) or sends back via `reciter.merge_rejected` (flips `marked_ready=0`, assignee retained). |
| `awaiting_timestamps` | No | — | Bucket move done. TS HF Job running. Listed in "Completed" tab; view-only. |
| `completed` | No | — | TS done; reciter live in `published/<slug>/`. Listed in "Completed" tab. View-only. |

`visibility` column values:

- `public` (default) — visible everywhere.
- `discarded` — hidden from anonymous + non-maintainer lists. Surfaced under the admin "Internal" filter. Reversal restores `public`. See [`inspector-admin-perms.md`](inspector-admin-perms.md) §5.5 + §11.

Deferred (no automation, no events, no columns in v2; see [`inspector-deferred.md`](inspector-deferred.md)):

- Re-edits of completed reciters — re-claim re-creates the WIP entry from `published/<slug>/`.
- Audio-source changes forcing realignment.
- Alignment-failed retry surfaces.
- `visibility = 'archived'` (post-publish soft-delete) — only `public` and `discarded` ship in v2.
- Multi-reviewer / pair-review.
- Force-claim (admin overrides assignee on an active row) — the `force_assignee_*` fields, the 30-min lease, and `claim.force_acquired` / `claim.force_released_auto` events are all deferred.

## 2. Identity convention (slug as the canonical ID)

The slug is just a unique ID string. **No parser ever extracts semantic meaning from it.** All dimensions that matter — name, riwayah, style, source, year, variant grouping — are catalog fields in `<bucket>/catalog/reciter_catalog.json` (single bucket file, see [`inspector-state-management.md`](inspector-state-management.md) §3).

Surviving conventions:

| Artifact | Convention | Example |
|---|---|---|
| Reciter request issue title | `[request] <slug>: <Display Name>` | `[request] saad_al_ghamdi: Saad Al-Ghamdi` |
| Issue body marker | `<!-- reciter-task: slug=<slug> schema=1 -->` | `<!-- reciter-task: slug=saad_al_ghamdi schema=1 -->` |
| Bucket path, in-flight | `<bucket>/wip/<slug>/` | `<bucket>/wip/saad_al_ghamdi/` |
| Bucket path, published | `<bucket>/published/<slug>/` | `<bucket>/published/saad_al_ghamdi/` |
| Inspector URL path | `/r/<slug>` | `/r/saad_al_ghamdi` |

Dropped vs v1:

- Branch convention `reciter/<slug>` — no branches, bucket is the working store
- PR title convention — no per-reciter PRs
- Commit subject conventions (`[<slug>] [wip] ...`, `[<slug>] [pipeline] ...`, `[state] <slug>: <event>`) — no per-edit commits
- Squash-merge subject convention — no merges
- `find_segments_pr.py` — nothing to find
- HTML-comment markers in PR bodies — no PR bodies

`scripts/lib/reciter_task.py` simplifies dramatically: given a slug, returns `{slug, state, assignee_hf_id, ...}` from the bucket state file. No PR/branch resolution paths.

## 3. Deployment architecture

The Inspector backend stays Python (Flask + gunicorn-gthread). Its 12 validators (the load-bearing accordion order), the phonemizer integration, peaks/ffmpeg, and the save flow's atomic-write + history append are too much code to port to the browser. The deployed backend is **always in the read path** (the bucket is private — browser → backend → bucket for both in-flight and published reciter data) and **stateful for writes** through the mounted bucket — the bucket IS the persistence layer, not a remote API the backend calls.

See [`inspector-data-storage.md`](inspector-data-storage.md) for the file-by-file specification, bucket mount semantics, image build rules, and per-phase acceptance criteria.

### Read path

Two tiers based on file kind, not reciter state:

1. **Per-reciter data (both in-flight and published)** — browser → Inspector backend → bucket. Backend reads `<INSPECTOR_BUCKET_MOUNT>/wip/<slug>/...` for active rows and `<INSPECTOR_BUCKET_MOUNT>/published/<slug>/...` for completed rows. NFS lazy-fetches bytes the first time; local cache absorbs repeat reads. The bucket is **private**; the backend is the gate. Inspector segment shard responses use `Cache-Control: public, max-age=86400` (1 day; not `immutable` since shards mutate on re-edit). Peaks responses can stay `immutable` because their content is hash-keyed.
2. **Static reference data** (Quran word text, controlled vocabularies) — baked into the Space image, served same-origin via `/api/static/...`. Browser caches forever via `Cache-Control: immutable`. Audio playback browser → origin direct. Timestamps browser → HF CDN direct (already implemented per [`timestamps-tab-deployment-plan.md`](../../timestamps-tab-deployment-plan.md)) since they are part of the public dataset, not the private bucket.

The audio URL catalog is embedded inside `<bucket>/catalog/reciter_catalog.json` and fetched once on app load (via a backend endpoint that serves a cached copy).

No worktrees. No github-fetch. No GitHub rate-limit budget consumed for any per-reciter read. The Inspector backend is always involved in per-reciter read traffic, which is consistent with its already being in the path for auth/state/lock checks.

Active reviewer reading their own slug's data goes through the same bucket mount as anyone else — there's no separate "scratch" concept. Mount-managed flush window (2–30 s, see data-storage §3) is the bound on staleness for non-owner viewers; per-write `huggingface_hub.upload_file()` calls bypass it for state, catalog, and audit.

### Write path

Writes are gated to the one active reviewer per reciter. For that reviewer:

1. Browser POSTs to `/api/seg/save/<reciter>/<chapter>` with the user's session cookie.
2. Backend's `@require_edit_lock(reciter)` decorator verifies the authenticated user is the assignee in the bucket state file. Returns 403 otherwise.
3. `save_seg_data()` runs against `<INSPECTOR_BUCKET_MOUNT>/wip/<slug>/...` (flat layout — no `data/recitation_segments/<slug>/` nesting) — **same code path as local mode**, only the resolver in `services/data_dir.py` differs. Atomic write `detailed.json`, rebuild `segments.json`, snapshot validation, append `edit_history.jsonl`, append `edit_history_peaks.jsonl`.
4. Mount handles flush. Advanced mode (NFS default) buffers to local disk, flushes async on a 2–30 s window. Save endpoints additionally call `huggingface_hub.upload_file()` per save for durability (mount flush is best-effort).

That's it. No debounce timer in Inspector code, no Git Data API client, no scratch lifecycle, no commit attribution machinery. The save flow's existing semantics (atomic local write) are preserved; the path just points at a mount.

### Attribution

Per-edit attribution lives in `<bucket>/audit/<YYYY>-<MM>.jsonl` (single audit folder, partitioned monthly) — one append per state-changing event:

```jsonc
{ "ts": "2026-05-08T14:23:11Z",
  "slug": "saad_al_ghamdi",
  "event": "reciter.claimed",
  "from_state": "awaiting_review",
  "to_state": "under_review",
  "actor": { "hf_user_id": "12345", "login_at_time": "alice", "role": "contributor" },
  "payload": { },
  "request_id": "req_abc123",
  "result": "ok" }
```

Per-edit save activity within an active claim is also recorded in `edit_history.jsonl` (alongside the segments files) — that's the per-edit ledger, designed for in-app History panel browsing. Both files now carry an `actor: {hf_user_id, login_at_time, role}` block per record/batch.

For external recognition (contributor profiles, contribution graphs): future feature, reads from `audit/<YYYY>-<MM>.jsonl` and surfaces a "your contributions" page on the Inspector website.

### Hosting target

**Hugging Face Spaces (Docker SDK, free CPU-basic tier)** with one HF bucket mounted as a read-write volume. Same operational pattern as the existing project Spaces, plus the new bucket primitive. Free at the targeted scale (2 vCPU, 16 GB RAM, ephemeral disk + bucket-mount). Migration target if/when CPU saturation forces it: HF CPU-upgrade ($0.03/h) or Fly.io shared-cpu-2x@2GB ($5/mo).

**No persistent volume required beyond the bucket mount itself** — the bucket is the persistence layer; everything else is ephemeral.

**Image footprint** ~300–400 MB (Python deps + Alpine static ffmpeg + frontend dist + a small static reference data slice — see data-storage §7). Image rebuilds on code or static-data changes only. The audio catalog ships in the bucket, not the image.

**Operational topology:** dev Space (`hetchyy/quranic-inspector-dev`, private) tracks the `dev` branch; prod Space (`hetchyy/quranic-inspector`, public) tracks `main`. Each Space mounts its own single private bucket (`hetchyy/quranic-inspector-bucket-dev` for dev, `hetchyy/quranic-inspector-bucket` for prod). Dev and prod are completely independent — no shared catalog, no shared state, no cross-contamination possible. Stable URLs (`https://hetchyy-quranic-inspector{,-dev}.hf.space`); custom domain supported.

### Free-tier prerequisites

The deploy is **blocked** on two changes before exposing to the public on free CPU-basic. Without them, p95 latency at 10 concurrent users runs 2–4 s during scrubbing bursts.

1. **Replace `app.run()` with `gunicorn -k gthread -w 1 --threads 16`** in the Dockerfile CMD. Werkzeug dev server is not production-grade. **One worker × 16 threads** (not `-w 2`) — every in-memory structure in v2 (state_store, per-slug mutex, signed-cookie verification, role cache) assumes single-process. Multi-worker requires a shared coordinator that v2 does not include. Add a startup assertion (`if workers != 1: raise`).
2. **`Cache-Control: public, max-age=31536000, immutable` on peaks routes** (`/api/seg/segment-peaks`, `/api/seg/peaks`). First bottleneck on free tier is **ffmpeg subprocess fork on the per-segment peaks route** during scrubbing; CDN-fronting absorbs the burst. Inspector segment shard responses use `max-age=86400` (not `immutable`) since shards mutate on re-edit.

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
   - Acquires an in-process per-slug mutex (single lock per slug; no per-(slug, login) sub-mutex).
   - Re-validates inside the mutex.
   - Writes the new row to `<bucket>/state/reciter_state.json` (transitions `awaiting_review → under_review`, sets `assignee_hf_id`, `assignee_login`, `assignee_since`).
   - Appends to `<bucket>/audit/<YYYY>-<MM>.jsonl`.
   - Returns 200 with the authoritative new state. **No optimism needed** — the write is synchronous; the response is the truth.
3. UI flips to edit mode immediately.

A first-time visitor sees a sign-in modal once; thereafter the flow is one click.

**Total clicks: 3 max** (Claim → modal Continue → HF authorize). **1** for returning users with an active session.

### Mark ready

When the reviewer is done, they click **Mark ready** in the banner. Backend flips `marked_ready = 1` on the row (state stays `under_review`). The reciter is frozen from edits and surfaced to the maintainer queue under "Awaiting merge". A maintainer clicks **Publish** in the admin dashboard, which transitions to `awaiting_timestamps`, moves `wip/<slug>/` → `published/<slug>/` in-bucket, and enqueues the timestamps HF Job (see [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md)).

The reviewer can pull the claim back with **Continue editing** before the maintainer publishes (flips `marked_ready = 0`). A maintainer can send it back via `reciter.merge_rejected` ([`inspector-admin-perms.md`](inspector-admin-perms.md) §5.10) which flips `marked_ready = 0` and retains the assignee.

### Release flow (assigned reviewer changes mind)

The **Release claim** button calls `POST /api/release/<slug>` which writes the state (clears `assignee_*`, sets `marked_ready = 0`, transitions `under_review → awaiting_review`). Saved edits remain in the bucket — a future reviewer continues from there.

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
| `GET /api/auth/callback` | Handles HF redirect. Verifies CSRF, exchanges code, fetches `/api/whoami`, sets signed-cookie session, redirects. |
| `POST /api/auth/logout` | Clears the session cookie. Does NOT release any active claim. |
| `GET /api/me` | Returns `{ login, hf_user_id, role, active_claim }`. |
| `POST /api/claim/<slug>` | One-claim-per-user check; acquires per-slug mutex; writes bucket state; appends audit. |
| `POST /api/release/<slug>` | Verifies caller is current assignee (`assignee_hf_id == user.hf_user_id`); clears assignee_*; appends audit. Idempotent. |
| `POST /api/mark-ready/<slug>` | Verifies caller is current assignee on `under_review`; sets `marked_ready=1`. |
| `POST /api/unmark-ready/<slug>` | Verifies caller is current assignee on `under_review` with `marked_ready=1`; sets `marked_ready=0`. |
| `GET /api/reciter-task/<slug>` | Returns full row + `can_*_for_current_user` predicates. |
| `POST /api/admin/publish/<slug>` | Maintainer-only. Transitions `under_review` (with `marked_ready=1`) → `awaiting_timestamps`. Synchronous in-process bucket move + 1 HF Job enqueue (see [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md)). |

All mutating endpoints are gated by the API lock (§5).

### Edge cases

| Scenario | Behavior |
|---|---|
| **Concurrent claims** on same `awaiting_review` | Per-slug mutex serializes. First wins. Second sees authoritative `under_review` and rejects with 409 + toast "Already claimed by @other." |
| **One claim per user** violation | API returns 409 `existing_claim: <slug>`. Frontend toast: "Release [other] first to claim [this]." |
| **Same user, two tabs, same reciter** | Per-slug mutex serializes save bursts. Both tabs see identical state. |
| **Mark-ready with save in flight** | Save POST holds the per-slug mutex; mark-ready waits. |
| **Bucket write fails** (HF outage, token revoked) | API returns 503 with retry hint. Backend logs the failure with full request payload for replay. |
| **HF OAuth revoked by user mid-session** | The signed-cookie session keeps working until expiry (we never store the user's HF token). Next sign-in mints a fresh cookie. Their claim survives. |
| **Two reviewers' clocks differ** | Backend writes `state_since` from `time.time()` on the Space; immune to client clock skew. |
| **Reviewer marks ready, walks away forever** | Maintainer publishes, sends back, or force-releases via admin actions. |

### Security model

| Threat | Mitigation |
|---|---|
| Session theft | HttpOnly + Secure + SameSite=Lax signed cookie. The cookie IS the session — `{login, hf_user_id, role, expires_at, csrf}` signed via Flask `itsdangerous`. No server-side session record. Logout simply clears the cookie. |
| CSRF on mutating endpoints | Same-site cookie + origin/referer check + per-session `csrf` token in the cookie. OAuth `state` parameter prevents auth CSRF (stored in a short-lived Flask-Session tmpfs entry between authorize and callback only). |
| Malicious reviewer destructive edits | Edit lock enforces one writer per reciter, keyed on `assignee_hf_id`. Append-only `audit/<YYYY>-<MM>.jsonl` per-state and `edit_history.jsonl` per-edit. State writes are server-side only; client cannot forge transitions. |
| `INSPECTOR_HF_TOKEN` leak | Stored as Space secret (encrypted at rest). Rotation = generate new HF token, update Space secret, restart. ~5 min operation. Revokes the old token. |
| Maintainer impersonation | Roles resolved against `<bucket>/access/inspector_roles.json` (in-memory cache hydrated at startup + replaced on Inspector writes; Inspector is sole writer). Backend never trusts user-supplied claims; `hf_user_id` is the canonical key. |

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
            if (entry is None
                    or entry.state != 'under_review'
                    or entry.marked_ready
                    or entry.visibility != 'public'
                    or entry.assignee_hf_id != user.hf_user_id):
                abort(403, description="Reciter is not editable by this user")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
```

The lookup is a dict access on the in-memory parsed state — `state_store` is hydrated on startup from the bucket JSON file and refreshed on every state write (Inspector is the sole writer, so cache invalidation is local). The ownership check uses `assignee_hf_id`, never `login` (logins are mutable on HF; renames would silently break login-keyed comparisons).

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

One in-process `threading.Lock` per slug — single lock, no `(slug, login)` sub-mutex, no force-claim sub-mutex coordination. The lock is acquired around `(read row, validate, write row, append audit, upload_file)` for every state-changing endpoint and around the save flow. If the deployment scales to multiple Space replicas later, this lock moves to a small Redis or to bucket-side optimistic concurrency (read-version → write-if-version) — deferred.

## 6. State management (bucket file is source of truth)

Pipeline state, assignee, and per-reciter lifecycle live in **`<bucket>/state/reciter_state.json`** — Inspector backend is the sole writer; embedded state machine in `services/state.py` validates every transition before persisting via pydantic models. **No GitHub workflow is involved** in state writes.

Curated identity (display name, riwayah, audio source, `url_template`, controlled vocab for riwayat / styles / audio sources) lives in **`<bucket>/catalog/reciter_catalog.json`** — same private bucket, single file. Inspector backend writes it via maintainer admin endpoints. Two stores, two cadences, two clean histories.

Inspector reads both files (state from bucket on startup, catalog from bucket on startup, both refreshed on demand) and bases every UI affordance on them.

### Why a flat bucket JSON file beats labels-as-state, SQLite, and a GitHub-tracked file

- Labels drift (manual edits, race conditions). The bucket file does not — Inspector serializes writes through the per-slug mutex.
- SQLite was an earlier draft; rejected because the operational surface (WAL semantics on NFS, `-wal`/`-shm` sidecars, mount-flush interaction with the WAL file) outweighed any indexing benefit at sub-1/sec write rate and ~300 rows. Plain JSON files validated by pydantic at the service boundary have zero NFS-semantics gotchas, parse in milliseconds, and migrate via a function (`schema_v2 = upgrade(schema_v1)`).
- GitHub-tracked: every state change would have been a commit, which v1 had. v2 drops it because (a) `repository_dispatch` propagation latency made claim/release feel laggy, (b) every state change cluttered `git log`, (c) merge conflicts on the state file required workflow `concurrency: singleton`. Bucket has none of these problems.

### Inspector is the sole writer

There's no `update-reciter-state.yml` workflow in v2. The state machine, transition validation, and mirroring (where applicable) all live in Inspector backend code. The only consumers of state outside Inspector are:

- GH Actions (`update-reciters.yml`, `release.yml`) — read state via `huggingface_hub` to know which reciters to include
- HF Jobs (`timestamps-refresh`) — same
- A scheduled `bucket-data-hygiene.yml` GH Action — runs validators across all reciters in the bucket weekly (or on-demand), surfaces findings to the admin dashboard, opens a GH issue for CRITICALs

External consumers fetch state read-only; they don't write.

### Workflow consolidation

| Existing workflow | Action |
|---|---|
| `bot-create-issue.yml` | Keep — maintainers manually open new request issues containing the slug body marker |
| `bot-create-pr.yml`, `bot-comment.yml` | **Delete** — no PRs to create, no automated PR comments |
| `issue-commands.yml` (`/claim`, `/confirm`) | **Delete** — Inspector website is the contribution surface; CLI fallback retired |
| `pr-assignee-sync.yml` | **Delete** — no PRs |
| `validate-segments-pr.yml` | **Delete** — no segments PRs; validators run in Inspector services on every relevant write |
| `validate-catalog.yml` (v2 plan) | **Never built** — catalog isn't git-tracked anymore |
| `forward-to-inspector.yml` (v2 plan) | **Delete** — request-intake forwarding is gone (D17) |
| `segments-pr-merged.yml` | **Delete** — replaced by Inspector `POST /api/admin/publish/<slug>` |
| `timestamps-refresh.yml` | **Move to HF Job**; kept temporarily for manual runs |
| `update-reciters.yml` | **Keep** — regenerates `RECITERS.md` from bucket state + catalog read via `huggingface_hub` |
| `release.yml` | **Keep** — per-reciter GitHub Release zips, reads from bucket via `huggingface_hub` |
| `sync-dataset.yml` | **Keep** — pushes published-reciter slices into the public HF dataset; dataset-card refresh stays on GH Actions |
| `bucket-data-hygiene.yml` (NEW) | Add — scheduled validator pass across all bucket reciters; surfaces to admin dashboard + opens GH issues for CRITICALs |
| `validate-edit-history.py` | Keep as a library; CLI wrapper for ad-hoc maintainer use against the bucket |
| `update-reciter-state.yml` (v1 plan) | **Never built** — Inspector is sole writer |
| `pr-uniqueness.yml` (v1 plan) | **Never built** — no PRs |
| `inspector-deploy.yml` (NEW) | Add — on `inspector/**` push to `main`, push to prod Space |
| `find_segments_pr.py` | **Delete** — nothing to find |

The post-completion fan-out is documented in [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md).

## 7. Edit-history simplifications

The current schema and validators evolved organically and carry weight that the new deployment model makes obsolete.

### Remove the file-hash chain

`edit_history.jsonl` carries `file_hash_after` per batch. `validate_edit_history.py` checks that the *latest* record's hash matches the current `detailed.json` — designed to detect manual tampering with the JSON between Inspector saves.

In the deployed model:

- All writes go through `save_seg_data()` running on the backend. There is no out-of-band path.
- Manual file edits are no longer a supported workflow.
- Re-extraction (which previously broke the chain) is internal-only and can rotate the history file at the source.

The file-hash field, the genesis record, and the chain validator check all go away. Kept:

- `batch_id` — needed for undo lookup.
- `schema_version` — for future migrations.
- `validation_summary_before` / `validation_summary_after` — drives the in-app history viewer.
- `operations` array with patches — needed for undo.
- `reverts_batch_id` / `reverts_op_ids` — needed for filtering reverted batches.

Added:

- `actor: {hf_user_id, login_at_time, role}` per batch — gives the per-edit ledger first-class attribution.

**No `record_hash` per record.** Adding a per-record hash would re-introduce a watered-down version of the chain we just removed; tamper detection is handled by offsite versioned snapshots of the bucket, not by in-record chaining.

Backend `parse_history_file` already tolerates missing genesis; mixed v1/v2 schema reading works without a migration script. Existing on-disk files keep their old shape; new writes use the new schema.

### Keep `edit_history_peaks.jsonl`

Real file size is ~1–2 MB per reciter (not 20 MB). Read path exists at `routes/peaks.py:90` (`seg_history_peaks_get`) wired to the History panel via `tabs/segments/utils/data/reciter-actions.ts:73` (parallel fetch on session load) and `tabs/segments/utils/playback/preview.ts:209` (lazy POST during playback). The feature lets anyone — including anonymous viewers — open a reciter's History panel and see waveform shapes render instantly without recomputing from audio. Dropping it would regress that UX.

### Drop the `_meta.audio_source` peek

`discover_ts_reciters` opens each `timestamps.json` and reads the first 512 bytes to extract `audio_source`. In the new model, the catalog file carries this directly. The peek can be deleted.

## 8. Other simplifications worth considering

These reduce surface area while we're here:

- **`docker-compose.yml` becomes the offline-only path.** Document it as "for maintainers reviewing locally without internet" in `inspector/CLAUDE.md`. The default contributor experience is the website. Two modes only — `local` (filesystem-only, repo `data/`, no bucket dependency, no HF OAuth, all-permissions) and `deployed` (bucket-mounted, HF OAuth, role-gated). CLI tools that write to prod bucket via `huggingface_hub` are maintainer scripts, not a third mode.
- **Drop the audio proxy** (`routes/audio_proxy.py`) for the deployed instance. The backend's only role for audio is to set CORS, which the browser can get directly from origin. Local Docker keeps the proxy.
- **Drop the validation panel in deployed mode.** `routes/timestamps.py::ts_validate` is removed from the deployed image entirely. Validation remains in local mode for maintainers. Removes the cross-file timestamps↔segments dependency.
- **Audio URL catalog lives in `<bucket>/catalog/reciter_catalog.json`** under `vocab.audio_sources[]` (template per source) plus per-row `audio_source` + `url_template_override` + optional `url_overrides` per-chapter map. Browser fetches the catalog once on app load (via a backend endpoint that serves a cached copy); switching reciters is zero-fetch. The 381 per-reciter `data/audio/<cat>/<src>/<slug>.json` manifests are gone — eliminated by the source-template factoring.

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
- A path forward for a future "your contributions" page reading from `<bucket>/audit/<YYYY>-<MM>.jsonl`

CLI fallback is dropped — the v1 plan kept `/claim` and `/confirm` issue commands for terminal users, but the website is now low-friction enough that maintaining a parallel CLI surface costs more than it's worth. Power users who want to push directly via git: not supported in v2; see admin docs for manual workflows.

## 10. Phased migration

Detailed per-phase scope, acceptance criteria, and risks live in [`inspector-data-storage.md`](inspector-data-storage.md) §9, [`inspector-state-management.md`](inspector-state-management.md) §11, and [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md). High-level shape:

1. **Phase 0 — Foundation (no deploy)**
   - Adopt the slug-rules-only identity convention (drop branch/PR conventions).
   - Land `scripts/lib/reciter_task.py` (slug resolver against catalog + state).
   - Create the single private HF bucket per env (`hetchyy/quranic-inspector-bucket-dev`, `hetchyy/quranic-inspector-bucket`).
   - Land `scripts/lib/schemas/` (pydantic models for state, catalog, audit, edit_history v2; cross-consumer location).
   - Land `inspector/services/state.py` (state machine + bucket persistence; per-slug `threading.Lock`; `huggingface_hub.upload_file()` per write).
   - Land `inspector/services/catalog.py` (mirrors `state.py` write pattern; vocab + reciters + aliases in one file).
   - Land `inspector/services/hf_bucket.py` (mount path resolver + write helpers).
   - **Manually seed** at v2 cutover (~15 reciters): hand-author `<bucket>/state/reciter_state.json` and `<bucket>/catalog/reciter_catalog.json` per [`inspector-state-management.md`](inspector-state-management.md) §3 mapping rules. No migration script — too few rows to justify.
   - Hand-seed `<bucket>/access/inspector_roles.json` (consolidated owners + maintainers; bucket-resident, Inspector sole writer; see [`inspector-state-management.md`](inspector-state-management.md) §9 bootstrap).

2. **Phase 1 — Read-only deploy (anonymous, all reciters via bucket)**
   - **Free-tier prerequisites:** swap `app.run()` → gunicorn-gthread; add `Cache-Control: immutable` to peaks routes; `Cache-Control: max-age=86400` on inspector segment shards.
   - Backend serves both `wip/<slug>/...` and `published/<slug>/...` reads through `/api/seg/data/...` from the mounted bucket.
   - Image build: `.dockerignore` + extended COPY list. (No `audio_catalog.json.gz` build step — catalog lives in the bucket.)
   - Dockerfile env defaults flipped: `INSPECTOR_DATA_DIR=/app/data`, `INSPECTOR_QUA_DATA_PATH=/app/data`, `INSPECTOR_TS_SOURCE=huggingface`, `INSPECTOR_AUDIO_PROXY_ENABLED=0`, `INSPECTOR_BUCKET_MOUNT=/data/inspector-bucket`, `INSPECTOR_BUCKET_REPO=hetchyy/quranic-inspector-bucket{,-dev}`.
   - Deploy to dev Space first; bucket mounted; production cutover after dev validation.
   - `/api/reciter-task/<slug>` endpoint live; UI shows reciter status pills (state read from bucket).

3. **Phase 2 — Bucket reads for in-flight reciters**
   - Backend reads in-flight data from `<bucket>/wip/<slug>/...` (flat layout — no `data/recitation_segments/<slug>/` nesting).
   - One-shot migration: copy current `data/recitation_segments/<slug>/` files into the dev bucket's flat `wip/<slug>/` layout for any in-flight reciter.
   - Available + Under-review tabs render data from the bucket.
   - Edit affordances still hidden globally.

4. **Phase 3 — Auth + claim flow**
   - HF OAuth via `hf_oauth: true` frontmatter.
   - Self-contained signed-cookie session (Flask `itsdangerous`) carrying `{login, hf_user_id, role, expires_at, csrf}`. No server-side session record. Authlib's OAuth-state store between authorize and callback uses Flask-Session on tmpfs (~30 s lifetime).
   - `/api/claim`, `/api/release`, `/api/mark-ready`, `/api/unmark-ready` write directly to the bucket state file.
   - Per-slug `threading.Lock` (single lock per slug).
   - One-claim-per-user enforcement (maintainer/owner bypass with audit).
   - No saves yet — writes still 403.

5. **Phase 4 — Read-only admin dashboard + role resolution**
   - `/admin` route gated by maintainer+ role; 404 for everyone else (does not flash).
   - `services/access.py` resolves role from `<bucket>/access/inspector_roles.json`; in-memory cache hydrated at startup and replaced on every Inspector write (sole-writer pattern → no refresh needed).
   - Read-only sections: System health, all reciters, stalled reciters, recent events log, contributor activity. **No override actions yet.**
   - Audit-log reader UI; `<bucket>/audit/<YYYY>-<MM>.jsonl` populated by Phase 3 already.
   - **No save endpoint yet** — Phase 5 work.

   *Why a separate phase:* admin UX needs role resolution, which needs OAuth (Phase 3). It's strictly easier to validate read-only views before adding override mutations.

6. **Phase 5 — Writes + the 4 admin events**
   - Save flow points at `<bucket>/wip/<slug>/...`.
   - Existing `save_seg_data()` runs unchanged — only the resolver in `services/data_dir.py` differs.
   - Mount handles flush; backend additionally calls `huggingface_hub.upload_file()` per save for durability.
   - Test end-to-end with one volunteer reviewer on a `_test_*` reciter.
   - Drop `file_hash_after`, genesis record, `backup_file()` calls in deployed save path; add `actor` per batch.
   - Ship the 4 v2 admin events: `claim.force_released`, `claim.reassigned`, `admin.force_set_state` (narrow allowed pairs only), `reciter.merge_rejected`. All other admin events are deferred — see [`inspector-admin-perms.md`](inspector-admin-perms.md) §11.
   - Validators (`validate_segments`, `validate_audio`, `validate_edit_history`, `validate_timestamps`) become libraries called by Inspector services on every relevant write; CLI wrappers retained for ad-hoc maintainer use.

7. **Phase 6 — Publish pipeline + cleanup**
   - `POST /api/admin/publish/<slug>` runs synchronously: state transition + in-process bucket move `wip/<slug>/` → `published/<slug>/` + `repository_dispatch reciter.completed` for `update-reciters.yml` / `release.yml` + 1 HF Job enqueue for `timestamps-refresh`. The job-completion webhook (`POST /api/internal/job-completed`, Bearer-auth via single `INSPECTOR_JOB_CALLBACK_SECRET`) flips `awaiting_timestamps → completed`.
   - Decommission v1 workflows: `bot-create-pr.yml`, `bot-comment.yml`, `issue-commands.yml`, `pr-assignee-sync.yml`, `validate-segments-pr.yml`, `segments-pr-merged.yml`, `forward-to-inspector.yml`.
   - Delete `find_segments_pr.py`.
   - Drop `data/reciters_index.json`, `data/riwayat.json`, `data/sources.json`, `data/styles.json`, `data/audio/` — all subsumed by `<bucket>/catalog/reciter_catalog.json`.
   - Drop the `inspector/segments/<slug>/` namespace from the HF dataset (it never lands — was on the planning board, gone with D4).
   - Add `bucket-data-hygiene.yml` (scheduled validators across all bucket reciters; surfaces to admin dashboard; opens GH issues for CRITICALs).
   - Update contributor docs to point to the website as the primary path.
   - Local Docker is now the offline / maintainer fallback.

## Open questions

- **CDN in front of Inspector.** Cold-start cache miss after a deploy hits backend reads for every active user's first request — and now those reads include published reciters too (single read path through the backend, since the bucket is private). Fronting `/api/seg/data/*` with Cloudflare or Fly's edge cache makes only the first global user pay. Decision deferred to Phase 1 measurements.
- **Bucket mount backend (NFS vs FUSE).** NFS is the default and recommended; FUSE is an option for Spaces that need streaming-mode appends. Decide based on Phase 2 measurements — if `edit_history.jsonl` appends feel slow, switch to streaming-mode FUSE for that file.
- **Multi-Space replica scale-out.** Single Space replica handles ≤50 concurrent reviewers per the perf budget. Beyond that, the per-slug `threading.Lock` needs to move to bucket-side optimistic concurrency or a small Redis. Defer until measured.
- **HF Jobs reliability for the single timestamps job.** The publish flow enqueues exactly one HF Job per publish; if Jobs are flaky, the maintainer can re-trigger from a "check status" button on the admin dashboard. No automated retry/backoff in v2.

Detailed file-storage and perf risks live in [`inspector-data-storage.md`](inspector-data-storage.md) §10–§11.
