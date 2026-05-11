# Inspector Publish Pipeline (v2)

Companion to [`inspector-deployment-plan.md`](inspector-deployment-plan.md), [`inspector-data-storage.md`](inspector-data-storage.md), [`inspector-state-management.md`](inspector-state-management.md). This doc owns the **completion event fan-out**: what happens when a reciter is published, where each subordinate workflow runs, and how the trigger flows from Inspector through GH Actions and the one HF Job.

## 1. Model in one paragraph

The Inspector website is the only thing humans interact with. When a maintainer clicks **Publish** on a reciter that is `under_review` with `marked_ready=1`, Inspector backend runs the publish synchronously in-process: state transition → in-bucket copy/move (`wip/<slug>/` → `published/<slug>/`) → fire `repository_dispatch reciter.completed` into GitHub for `update-reciters.yml` + `release.yml` → enqueue ONE HF Job (`timestamps-refresh`). The endpoint returns 200 with the new state and the timestamps job id. The principle: **GitHub for code, HF for data; do everything you can in-process so the publish is one atomic-feeling operation.**

## 2. Where each workflow runs

| Workflow | Runs on | Reads from | Writes to | Trigger |
|---|---|---|---|---|
| Inspector code CI (build, test, lint) | GH Actions | GitHub repo | GitHub PR statuses | Push to repo |
| `inspector-deploy.yml` (HF Space upload) | GH Actions | `inspector/`, `validators/`, `scripts/lib/`, static `data/` files | HF Space repo (`hetchyy/quranic-inspector{,-dev}`) | Push to `main` touching `inspector/**` |
| `update-reciters.yml` (regenerate `RECITERS.md`) | GH Actions | Bucket via `huggingface_hub` (state + catalog) | GitHub repo (auto-PR) | `reciter.completed` dispatch from Inspector + scheduled cron |
| `release.yml` (per-reciter GitHub Release zip) | GH Actions | Bucket (`published/<slug>/`) via `huggingface_hub` | GitHub Release | `reciter.completed` dispatch from Inspector |
| `bucket-data-hygiene.yml` (scheduled validators across all reciters) | GH Actions | Bucket | Admin dashboard signal + GH issue for CRITICALs | Weekly cron + manual dispatch |
| `timestamps-refresh` | HF Job | Bucket; calls MFA Aligner Space | Bucket (`published/<slug>/timestamps/...`) | Inspector POSTs HF Jobs API on `reciter.published` |

What stays on GitHub:
- Source code + code CI
- Reciter request issues (intake queue) — body marker `<!-- reciter-task: slug=... schema=1 -->`
- `RECITERS.md` regeneration
- Per-reciter GitHub Release zips (consumer-facing offline distribution)
- `data/inspector_roles.json` (role mgmt)

What moves to HF:
- All per-reciter editable data (bucket `wip/<slug>/`)
- All per-reciter completed data (same bucket, `published/<slug>/`)
- Reciter catalog (`<bucket>/catalog/reciter_catalog.json`)
- State + audit (`<bucket>/state/`, `<bucket>/audit/`)
- Timestamps refresh (the one HF Job)
- User identity (HF OAuth)
- Inspector deployment (Space repos)

What's dropped entirely:
- `update-reciter-state.yml` (Inspector is sole writer of state)
- `repository_dispatch` flow into a state-writing workflow
- `cache-invalidate` webhook (no cache to invalidate)
- `pr-assignee-sync.yml` (no PRs)
- `validate-segments-pr.yml` (validators are libraries; called by inspector services on writes)
- `validate-catalog.yml` (catalog isn't git-tracked anymore)
- `segments-pr-merged.yml` (no merge gate; replaced by Inspector publish)
- `bot-create-pr.yml`, `bot-comment.yml` (no automated PRs/comments)
- `issue-commands.yml` (no `/claim`/`/confirm`)
- `forward-to-inspector.yml` (Reciter Requests Space cleanup brought forward; see D17)
- `find_segments_pr.py` (no PRs)
- `snapshot-bucket-to-dataset` HF Job (publish snapshot is in-bucket move/copy, in-process)
- `build-per-verse-audio-dataset` from the publish path (downstream consumers — training parquet build — may still run separately, scheduled or triggered by `update-reciters.yml`; not Inspector's concern)
- GitHub App for inspector contribution flow (replaced by HF OAuth)

## 3. The publish event flow

When a maintainer clicks **Publish** on a reciter in `under_review` with `marked_ready=1`:

```
1. Browser → POST /api/admin/publish/<slug> (with maintainer session cookie)

2. Inspector backend (synchronous, in-process):
   a. Verify caller is maintainer+
   b. Verify state == under_review AND marked_ready == 1
   c. Acquire per-slug threading.Lock
   d. state.transition(slug, PublishEvent(actor)) — writes via huggingface_hub.upload_file():
      <bucket>/state/reciter_state.json (under_review → awaiting_timestamps)
      <bucket>/audit/<YYYY>-<MM>.jsonl (one line)
   e. Bucket move/copy: <bucket>/wip/<slug>/* → <bucket>/published/<slug>/*
      (in-bucket server-side copy when available; download+reupload fallback today.
       Either way: same bucket, no cross-repo transfer.)
   f. Fire trigger: repository_dispatch reciter.completed { slug } via GitHub PAT
   g. Enqueue ONE HF Job: timestamps-refresh { slug }; remember its job_id on the state row
   h. Release lock
   i. Return 200 with { state: "awaiting_timestamps", timestamps_job_id }

3. In parallel, fan-out runs:
   GH Actions (triggered by repository_dispatch reciter.completed):
     - update-reciters.yml: regenerate RECITERS.md (reads state + catalog from bucket)
     - release.yml: build per-reciter zip + create GitHub Release (reads from bucket published/<slug>/)

   HF Job:
     - timestamps-refresh: read bucket published/<slug>/detailed.json, call MFA Aligner Space,
       write timestamps shards to <bucket>/published/<slug>/timestamps/<chapter>.json,
       POST /api/internal/job-completed on success.

4. On timestamps-refresh completion:
   - HF Job entry-point POSTs to /api/internal/job-completed (Bearer-auth, see §4a)
   - Inspector transitions awaiting_timestamps → completed
```

If the maintainer needs to know whether the timestamps job actually finished, the dashboard shows the tracked `timestamps_job_id` and its status. If something is wrong, the maintainer manually re-triggers from a "check status" / "rerun timestamps" flow (which is just kicking off another `timestamps-refresh` invocation against the same slug; the publish path itself is not retried — state is already in `awaiting_timestamps` or `completed`).

Note: there is no `pending_jobs` map, no polling backstop, no `/api/admin/rerun-job/` endpoint in v2 scope (see D15, D16). Per-job sub-status is deferred to D1 in [`inspector-deferred.md`](inspector-deferred.md).

## 4. Trigger sources

### From Inspector to GH Actions: `repository_dispatch`

Inspector backend holds a small `INSPECTOR_GITHUB_DISPATCH_TOKEN` (a personal access token with `repo` scope on the project repo) — used solely to fire `repository_dispatch` events:

```python
# inspector/services/github_dispatch.py
def dispatch(event_type: str, payload: dict):
    requests.post(
        f"https://api.github.com/repos/{OWNER}/{REPO}/dispatches",
        headers={"Authorization": f"Bearer {INSPECTOR_GITHUB_DISPATCH_TOKEN}",
                 "Accept": "application/vnd.github+json"},
        json={"event_type": event_type, "client_payload": payload},
        timeout=10,
    )
```

Events fired by Inspector:

| Event | When | Listening workflows |
|---|---|---|
| `reciter.completed` | After `publish` transition | `update-reciters.yml`, `release.yml` |
| `reciter.catalog_changed` | After catalog edit | `update-reciters.yml` |

Caveat: this is a thin GitHub PAT with `repo` scope. Rotate quarterly; `INSPECTOR_GITHUB_DISPATCH_TOKEN` is a Space secret. If rotated, dispatch firing fails silently — covered by the polling backstop in `update-reciters.yml` (scheduled cron picks up missed publish events).

Alternative considered and rejected: a GitHub App with `Contents: write` just for dispatch firing. Adds JWT-mint-and-rotate machinery for a one-shot trigger. PAT is simpler.

### From Inspector to HF Jobs: API call

Inspector backend POSTs to `https://api.endpoints.huggingface.cloud/...` (or wherever the HF Jobs control plane lives — verify exact endpoint at impl time; likely `https://huggingface.co/api/jobs`) using `INSPECTOR_HF_TOKEN`:

```python
# inspector/services/hf_jobs.py
def enqueue(job_name: str, payload: dict) -> str:
    """Returns the job id."""
    resp = requests.post(
        f"https://huggingface.co/api/jobs",
        headers={"Authorization": f"Bearer {INSPECTOR_HF_TOKEN}"},
        json={
            "image": JOB_IMAGES[job_name],
            "command": JOB_COMMANDS[job_name],
            "env": {"SLUG": payload["slug"]},
            "volumes": [f"hf://buckets/{INSPECTOR_BUCKET_REPO}:/data"],
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["job_id"]
```

In v2, the only job ever enqueued via this path is `timestamps-refresh`. The `job_id` is recorded on the state row's `timestamps_job_id` field for the dashboard to surface; nothing polls it on a timer.

### 4a. Internal endpoint auth (Bearer token, ONE secret)

The internal endpoint (`POST /api/internal/job-completed`) uses a **Bearer shared secret** over TLS. Threat model is "trusted infra calling trusted infra over HTTPS" — the caller is a bot-account-owned HF Job container, TLS protects the wire, and Bearer is dead-simple to validate. Constant-time compare; no HMAC, no body signing.

| Field | Value |
|---|---|
| Header | `Authorization: Bearer <secret>` |
| Validation | Constant-time compare (`hmac.compare_digest`) |
| Body | Plain JSON, no signing |
| Replay protection | None (relies on TLS + caller infra trust) |

**ONE secret** for the only internal endpoint:

| Secret | Used by | Endpoint |
|---|---|---|
| `INSPECTOR_JOB_CALLBACK_SECRET` | HF Job entry-point script (`scripts/jobs/timestamps_refresh.py`) | `POST /api/internal/job-completed` |

(`INSPECTOR_FORWARD_SECRET` and the previous `_PREV` rotation slot are dropped — see D14, D17.)

**Rotation.** Mint a new value, update the Space secret, redeploy. The job-completion webhook is best-effort: if a callback arrives during the redeploy window with the old secret it gets rejected, the job's retry-on-401 hook re-fires once after a short delay; if it still fails the maintainer sees a "timestamps job done but state stuck in `awaiting_timestamps`" indicator on the dashboard and clicks the manual advance button. Not worth a `_PREV` slot for this rare case.

**Sender (HF Job script):**
```python
import requests, os

def post_internal(url: str, payload: dict, secret: str) -> None:
    r = requests.post(url, json=payload, timeout=10, headers={
        "Authorization": f"Bearer {secret}",
    })
    r.raise_for_status()
```

**Receiver decorator (Flask):**
```python
import hmac, os
from functools import wraps
from flask import request, abort

def require_bearer(secret_env: str):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer "):
                abort(401, "missing bearer")
            token = auth[len("Bearer "):]
            expected = os.environ.get(secret_env, "")
            if not expected or not hmac.compare_digest(token, expected):
                abort(401, "invalid bearer")
            return fn(*a, **kw)
        return wrapper
    return deco

# usage
@app.post("/api/internal/job-completed")
@require_bearer("INSPECTOR_JOB_CALLBACK_SECRET")
def job_completed(): ...
```

Lives in `inspector/utils/internal_auth.py::require_bearer(secret_env: str)`.

## 5. HF Job specifications

In v2 there is exactly one HF Job: `timestamps-refresh`. The image is a small Docker build with `huggingface_hub` + `requests` + the relevant pipeline code from `scripts/lib/` and `scripts/jobs/`.

### Job: `timestamps-refresh`

```bash
hf jobs run \
  --image hf://spaces/hetchyy/inspector-jobs-image:latest \
  -v hf://buckets/hetchyy/quranic-inspector-bucket:/data/bucket \
  -e SLUG=<slug> \
  python scripts/jobs/timestamps_refresh.py
```

Inside the container:

1. Read `/data/bucket/published/<slug>/detailed.json` (publish snapshot has already moved files there in-process).
2. Call MFA Aligner Space (`hetchyy/Quran-phoneme-mfa-dev` by default) for each verse — same flow as the existing `extract_timestamps.py`.
3. Compute timestamps; write per-chapter shards to `/data/bucket/published/<slug>/timestamps/<chapter>.json`.
4. POST `/api/internal/job-completed` body `{ slug, status: "success" | "failed", error?: "..." }` (Bearer auth).

Cost: ~5–10 min per reciter (MFA alignment is the bottleneck). The MFA Aligner Space is the actual compute; the HF Job is just orchestration.

### Job image (`hf://spaces/hetchyy/inspector-jobs-image`)

A small Docker image hosted as an **HF Space (Docker SDK, paused)**. The Space doesn't run anything user-facing — it just exists so HF Jobs can pull the image directly from HF infrastructure (`hf jobs run --image hf://spaces/hetchyy/inspector-jobs-image:latest`). Avoids GHCR-as-third-party-registry and the round-trip of building elsewhere then asking HF Jobs to pull from outside.

Contents:

- Python 3.11
- `huggingface_hub`, `requests`, `orjson`, `numpy`
- `scripts/lib/` (timestamps shards, reciter task, internal_auth_sender)
- `scripts/jobs/timestamps_refresh.py`

The image rebuilds automatically on push to its Space repo. CI deploys via the same selective-rsync pattern as Inspector — `inspector-jobs-deploy.yml` GH Actions workflow on push to `main` touching `scripts/jobs/**` or `scripts/lib/**`. The Space stays in `paused` state — only its built image artifact matters.

GHCR is **not** used.

## 6. Workflow specifications

### `update-reciters.yml`

```yaml
name: Update Reciters Index
on:
  repository_dispatch:
    types: [reciter.completed, reciter.catalog_changed]
  schedule:
    - cron: '*/30 * * * *'
  workflow_dispatch:

permissions:
  contents: write
  pull-requests: write

jobs:
  regenerate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install huggingface_hub
      - name: Regenerate
        env:
          INSPECTOR_HF_TOKEN: ${{ secrets.INSPECTOR_HF_TOKEN }}
          INSPECTOR_BUCKET_REPO: hetchyy/quranic-inspector-bucket
        run: |
          # Reads state + catalog from bucket via huggingface_hub
          python .github/scripts/list_reciters.py --write
      - name: Open PR if changes
        run: |
          if ! git diff --quiet; then
            gh pr create ...
          fi
```

The script reads both state and catalog from the bucket via:

```python
from huggingface_hub import HfFileSystem
fs = HfFileSystem()
with fs.open("buckets/hetchyy/quranic-inspector-bucket/state/reciter_state.json", "r") as f:
    state = json.load(f)
with fs.open("buckets/hetchyy/quranic-inspector-bucket/catalog/reciter_catalog.json", "r") as f:
    catalog = json.load(f)
```

### `release.yml`

```yaml
name: Per-Reciter Release
on:
  repository_dispatch:
    types: [reciter.completed]
  workflow_dispatch:
    inputs:
      slug:

jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install huggingface_hub
      - name: Build zip
        env:
          INSPECTOR_HF_TOKEN: ${{ secrets.INSPECTOR_HF_TOKEN }}
        run: |
          python .github/scripts/package_release.py "${{ github.event.client_payload.slug }}"
      - name: Create GitHub Release
        run: |
          gh release create "$TAG" "$ZIP" --title "..." --notes "..."
```

`package_release.py` reads the relevant data files from `<bucket>/published/<slug>/` via `huggingface_hub`, zips them with audio (if including), uploads to a new GitHub Release.

### `inspector-deploy.yml`

```yaml
name: Deploy Inspector to HF Space
on:
  push:
    branches: [main]
    paths:
      - 'inspector/**'
      - 'validators/**'
      - 'scripts/lib/**'
      - 'data/{surah_info,qpc_hafs,digital_khatt_v2_script,phoneme_sub_costs,inspector_roles}.json'
      - 'inspector/Dockerfile'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '20' }
      - name: Build frontend
        run: cd inspector/frontend && npm ci && npm run build
      - name: Push to HF Space
        env:
          HF_TOKEN: ${{ secrets.HF_DEPLOY_TOKEN }}
        run: |
          # rsync selective tree into a local clone of hetchyy/quranic-inspector
          # commit + push (triggers Space rebuild)
          ./scripts/upload_inspector.sh prod
```

The `upload_inspector.sh` script implements the selective-push logic from [`inspector-deploy-runbook.md`](inspector-deploy-runbook.md) §4.

A separate `inspector-deploy-dev.yml` triggers on push to `dev` branch and pushes to `hetchyy/quranic-inspector-dev`.

### `bucket-data-hygiene.yml`

```yaml
name: Bucket Data Hygiene
on:
  schedule:
    - cron: '0 6 * * 0'   # weekly, Sunday 06:00 UTC
  workflow_dispatch:

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - run: pip install huggingface_hub
      - name: Run validators across all reciters in bucket
        env:
          INSPECTOR_HF_TOKEN: ${{ secrets.INSPECTOR_HF_TOKEN }}
          INSPECTOR_BUCKET_REPO: hetchyy/quranic-inspector-bucket
        run: |
          python scripts/jobs/bucket_hygiene.py --report-out report.json
      - name: Open issue for CRITICAL findings
        if: ${{ steps.validate.outputs.has_critical == 'true' }}
        run: |
          gh issue create --title "Bucket hygiene CRITICAL findings $(date +%F)" \
            --body-file report.md --label hygiene
```

The hygiene job invokes `validate_segments`, `validate_audio`, `validate_edit_history`, `validate_timestamps` as libraries against every reciter in the bucket; CRITICAL findings produce a GH issue and surface in the admin dashboard's hygiene panel.

## 7. Inspector backend's role in publish

`inspector/services/publish.py` orchestrates the publish event synchronously:

```python
def publish(slug: str, actor: User) -> PublishResult:
    with state.lock_for(slug):
        # 1. State transition (atomic; writes via huggingface_hub.upload_file)
        state.transition(slug, PublishEvent(actor))

        # 2. In-bucket move/copy: wip/<slug>/* -> published/<slug>/*
        bucket.move_or_copy(f"wip/{slug}/", f"published/{slug}/")

        # 3. Fire repository_dispatch (best-effort; failure logged, surfaced in response)
        try:
            github_dispatch.dispatch("reciter.completed", {"slug": slug})
            dispatch_ok = True
        except Exception as e:
            log.warning("dispatch failed: %s", e)
            dispatch_ok = False

        # 4. Enqueue ONE timestamps job; persist its id on the state row
        try:
            ts_job_id = hf_jobs.enqueue("timestamps-refresh", {"slug": slug})
            state.set_timestamps_job_id(slug, ts_job_id)
        except Exception as e:
            log.error("timestamps-refresh enqueue failed: %s", e)
            ts_job_id = None

    return PublishResult(
        state="awaiting_timestamps",
        timestamps_job_id=ts_job_id,
        dispatch_ok=dispatch_ok,
    )
```

If the dispatch firing or the job-enqueue step fails, the maintainer sees a degraded result in the publish dialog; they can re-fire the dispatch from the cron in `update-reciters.yml` (it picks up `awaiting_timestamps` rows missing a job id) or kick off a fresh `timestamps-refresh` from the dashboard. The state transition itself is independent — once it commits to the bucket, `awaiting_timestamps` is the truth even if downstream steps haven't caught up yet.

## 8. Job completion callback

The `timestamps-refresh` Job's last step POSTs to Inspector via the Bearer sender from §4a:

```python
# inside the job
import os, requests

requests.post(
    f"{os.environ['INSPECTOR_CALLBACK_URL']}/api/internal/job-completed",
    json={"slug": os.environ["SLUG"], "status": "success"},
    headers={"Authorization": f"Bearer {os.environ['INSPECTOR_JOB_CALLBACK_SECRET']}"},
    timeout=10,
).raise_for_status()
```

`INSPECTOR_CALLBACK_URL` is **passed into the Job invocation as an env var per environment** (dev or prod), so dev Jobs callback to dev Inspector. See `hf_jobs.enqueue()` payload in §4.

Inspector's handler:

```python
@app.post("/api/internal/job-completed")
@require_bearer("INSPECTOR_JOB_CALLBACK_SECRET")
def job_completed():
    body = request.json
    slug = body["slug"]
    if body["status"] == "success":
        state.transition(slug, TimestampsCompletedEvent())
    else:
        # surface in admin dashboard; do not auto-transition
        state.flag_timestamps_failed(slug, body.get("error"))
    return {"ok": True}
```

There is no polling backstop. If the webhook never arrives, the slug sits in `awaiting_timestamps`; the maintainer sees it on the dashboard's stalled-reciters panel and can manually advance or re-fire.

## 9. Phased rollout

Maps onto the parent doc's [§10 phased migration](inspector-deployment-plan.md). This doc's scope lands primarily in Phase 6.

### Phase 0 — Foundation

- Land `INSPECTOR_GITHUB_DISPATCH_TOKEN` secret on the dev Space.
- Land `inspector/services/github_dispatch.py` and `inspector/services/hf_jobs.py` (stub implementations; not yet called from the publish path).

### Phase 5 — Writes

- Add `inspector/services/publish.py` (state transition + in-bucket move + fan-out trigger), but feature-flag the dispatch/enqueue calls off behind `INSPECTOR_PUBLISH_FANOUT_ENABLED=0` so the state transition can be exercised standalone.

### Phase 6 — Publish pipeline

**In scope:**
- Build the inspector-jobs Docker image + push to `hetchyy/inspector-jobs-image` HF Space.
- Land `scripts/jobs/timestamps_refresh.py` and `scripts/jobs/bucket_hygiene.py`.
- Land `update-reciters.yml`, `release.yml`, `inspector-deploy.yml`, `bucket-data-hygiene.yml` GH Actions workflows.
- Wire `publish.py` to actually fire dispatch + enqueue the timestamps job (flip the feature flag).
- Land `/api/internal/job-completed` handler.
- Decommission the v1 workflows: `bot-create-pr.yml`, `bot-comment.yml`, `issue-commands.yml`, `pr-assignee-sync.yml`, `validate-segments-pr.yml`, `segments-pr-merged.yml`, `validate-edit-history.yml` (all retired; validators now run as libraries inside Inspector services). Delete `forward-to-inspector.yml` (D17).
- Delete `find_segments_pr.py`.

**Acceptance:**
- Maintainer publishes a `_test_*` reciter end-to-end. Within 1 minute of clicking Publish:
  - Bucket move/copy complete: `published/<slug>/` populated, `wip/<slug>/` removed (or archived to `_archive/<slug>/<ts>/` per policy)
  - GitHub Release `<slug>-v0.X.Y` exists with the zip attached
  - `RECITERS.md` has been auto-PR'd with the slug marked completed
- Within ~10 minutes:
  - `<bucket>/published/<slug>/timestamps/<chapter>.json` shards exist
  - State transitions to `completed` (Inspector's `/api/internal/job-completed` handler advances it)

## 10. Risks and open questions

### Subordinate Job failures

`timestamps-refresh` fails mid-run. State sits at `awaiting_timestamps`; nothing automatically retries. **Mitigation:** the maintainer dashboard shows the tracked `timestamps_job_id` and its current HF Jobs API status when checked on demand. If failed, maintainer can re-enqueue manually. No background polling in v2 (per D15, D16). Per-job sub-status is deferred to D1.

### `INSPECTOR_GITHUB_DISPATCH_TOKEN` rotation

The PAT used to fire `repository_dispatch` events expires per its own settings (no auto-rotation like a GitHub App). **Mitigation:** quarterly rotation reminder in the runbook. If expired silently, the scheduled cron in `update-reciters.yml` (every 30 min) catches missed events.

### Bucket archive policy

Should we archive `wip/<slug>/` to `<bucket>/_archive/<slug>/<published_at>/` post-publish, or delete? **Recommend archive** for the first month (recovery option if publish has a bug); **delete** after that (storage cost is small but accumulates). Configurable via `INSPECTOR_BUCKET_ARCHIVE_POLICY` env var. See D13 in `inspector-deferred.md` for the cleanup-automation deferral.

### Job image distribution (resolved — uses HF Space)

The image is hosted as an HF Space (Docker SDK, paused) at `hetchyy/inspector-jobs-image`. HF Jobs pulls from `hf://spaces/...` natively. No GHCR / Docker Hub / Quay involvement; one less third-party registry to maintain credentials for.

### Transactional ordering

What if `state.transition(slug, PublishEvent)` succeeds but the in-bucket move or the dispatch/enqueue fails? Mitigations stack: the per-slug lock means no other writer interleaves; the move/copy is the next step (if it fails the state is `awaiting_timestamps` but `published/<slug>/` is missing — the dashboard surfaces this and the maintainer can manually retry the move via a `POST /api/admin/republish/<slug>` operation). Dispatch failures are absorbed by `update-reciters.yml`'s 30-min cron. Enqueue failures show as a missing `timestamps_job_id` and the maintainer kicks off a fresh job. Manual recovery is fine for these rare cases at the publish cadence (~10/month).

### Multiple Inspector replicas firing duplicate dispatch

If we ever scale to multi-replica, two replicas might each see the publish event and both fire. **Mitigation:** the per-slug `threading.Lock` is only intra-process — multi-replica is explicitly deferred (see D6 in `inspector-deferred.md`) and would require moving coordination to bucket-side optimistic concurrency or Redis. In v2's single-replica model the question doesn't arise.

### In-bucket move/copy semantics

In-bucket server-side copy/move on HF Storage Buckets is the preferred path; if the API isn't yet available for the move/rename pattern we want, the fallback is download+reupload from the running container (~30 s for ~25 MB). Either way, both source and destination live in the same private bucket — no cross-repo transfer. See D7 in `inspector-deferred.md`.
