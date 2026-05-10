# Inspector Publish Pipeline (v2)

Companion to [`inspector-deployment-plan.md`](inspector-deployment-plan.md), [`inspector-data-storage.md`](inspector-data-storage.md), [`inspector-state-management.md`](inspector-state-management.md). This doc owns the **completion event fan-out**: what happens when a reciter is published, where each subordinate workflow runs, and how the trigger flows from Inspector through GH Actions and HF Jobs.

## 1. Model in one paragraph

The Inspector website is the only thing humans interact with. When a maintainer clicks **Publish** on a `ready_for_merge` reciter, Inspector backend writes the state transition to the bucket, then fires two parallel triggers: a `repository_dispatch` event into GitHub for workflows whose output lands on GitHub (`update-reciters.yml`, `release.yml`), and HF Jobs API calls for workflows whose output lands on HF (`snapshot-bucket-to-dataset`, `timestamps-refresh`, `build-per-verse-audio-dataset`). Each subordinate job runs independently, can fail independently, and can be retried independently. The principle: **GitHub for code, HF for data; each workflow runs where its output lands.**

## 2. Where each workflow runs

| Workflow | Runs on | Reads from | Writes to | Trigger |
|---|---|---|---|---|
| Inspector code CI (build, test, lint) | GH Actions | GitHub repo | GitHub PR statuses | Push to repo |
| `inspector-deploy.yml` (HF Space upload) | GH Actions | `inspector/`, `validators/`, `scripts/lib/`, static `data/` files | HF Space repo (`hetchyy/quranic-inspector{,-dev}`) | Push to `main` touching `inspector/**` |
| `update-reciters.yml` (regenerate `RECITERS.md`, `reciters_index.json`) | GH Actions | Bucket via `huggingface_hub` (state file) + GitHub repo (catalog) | GitHub repo (auto-PR) | `reciter.completed` dispatch from Inspector + scheduled cron + `data/reciter_catalog.json` push |
| `release.yml` (per-reciter GitHub Release zip) | GH Actions | Bucket + HF dataset | GitHub Release | `reciter.completed` dispatch from Inspector |
| `validate-catalog.yml` (catalog PR validation) | GH Actions | The PR's catalog | GitHub PR statuses | Push/PR touching `data/reciter_catalog.json` |
| `snapshot-bucket-to-dataset` | HF Job | Bucket | HF dataset (`inspector/segments/<slug>/`) | Inspector POSTs HF Jobs API on `reciter.published` |
| `timestamps-refresh` | HF Job | Bucket; calls MFA Aligner Space | HF dataset (`timestamps/<slug>/`) | Inspector POSTs HF Jobs API on `reciter.published` |
| `build-per-verse-audio-dataset` | HF Job | Bucket | HF dataset (per-verse audio rows) | Inspector POSTs HF Jobs API on `reciter.published` |
| `bucket-archive` | HF Job (or inline in snapshot) | Bucket | Bucket `_archive/` | Tail of `snapshot-bucket-to-dataset` |
| Reciter Requests intake (issue creation) | `reciter_requests/` Space (existing) | User submission | GitHub Issues + GH Actions dispatch into Inspector | User-initiated |

What stays on GitHub:
- Source code + code CI
- Reciter request issues (intake queue)
- `data/reciter_catalog.json` (curated metadata)
- `RECITERS.md` regeneration
- Per-reciter GitHub Release zips (consumer-facing offline distribution)
- `data/inspector_owners.json` (role mgmt)

What moves to HF:
- All per-reciter editable data (bucket)
- All published per-reciter data (dataset)
- All "completion → publish" data jobs (HF Jobs)
- Reciter state file (bucket)
- User identity (HF OAuth)
- Inspector deployment (Space repos)

What's dropped entirely:
- `update-reciter-state.yml` (Inspector is sole writer of state)
- `repository_dispatch` flow into a state-writing workflow
- `cache-invalidate` webhook (no cache to invalidate)
- `pr-assignee-sync.yml` (no PRs)
- `validate-segments-pr.yml` (no segments PRs)
- `segments-pr-merged.yml` (no merge gate; replaced by Inspector publish)
- `bot-create-pr.yml`, `bot-comment.yml` (no automated PRs/comments)
- `issue-commands.yml` (no `/claim`/`/confirm`)
- `find_segments_pr.py` (no PRs)
- GitHub App for inspector contribution flow (replaced by HF OAuth)

## 3. The publish event flow

When a maintainer clicks **Publish** on a `ready_for_merge` reciter:

```
1. Browser → POST /api/admin/publish/<slug> (with maintainer session cookie)

2. Inspector backend:
   a. Verify caller is maintainer+
   b. Verify state == ready_for_merge
   c. state.transition(slug, PublishEvent(actor)) — writes:
      <bucket>/state/reciter_state.json (state ready_for_merge → awaiting_timestamps)
      <bucket>/state/audit.jsonl (one line)
   d. Fire two parallel triggers (best-effort, fire-and-forget for now):
      - repository_dispatch reciter.completed { slug } via GitHub PAT
      - HF Jobs API: enqueue snapshot-bucket-to-dataset { slug }
      - HF Jobs API: enqueue timestamps-refresh { slug }
      - HF Jobs API: enqueue build-per-verse-audio-dataset { slug }
   e. Return 200 with new authoritative state to the browser

3. In parallel, fan-out runs:
   GH Actions (triggered by repository_dispatch reciter.completed):
     - update-reciters.yml: regenerate RECITERS.md + reciters_index.json
     - release.yml: build per-reciter zip + create GitHub Release

   HF Jobs (each a separate Job invocation):
     - snapshot-bucket-to-dataset: gzip + upload bucket files to dataset; archive bucket entry
     - timestamps-refresh: call MFA Aligner Space, write TS shards to dataset
     - build-per-verse-audio-dataset: existing build_reciter.py logic

4. As HF Jobs complete:
   - snapshot-bucket-to-dataset finish → bucket entry archived/deleted
   - timestamps-refresh success → MFA Aligner Space provides timestamps; Inspector receives an internal webhook (POST /api/internal/job-completed?type=timestamps&slug=<slug>) → Inspector transitions awaiting_timestamps → completed

5. Inspector polls HF Jobs API every minute to detect failed/orphaned jobs; surfaces in admin dashboard if any subordinate fails.
```

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

The Inspector keeps a small in-memory map `job_id → (slug, type, fired_at)` — polled every minute to surface job status in the admin dashboard.

### From Reciter Requests Space to Inspector

The Reciter Requests Space currently fires `repository_dispatch reciter.alignment_requested` into the project repo. In v2, this is **kept** — but the dispatch event is consumed by Inspector via an internal webhook receiver (since GH Actions doesn't write state in v2). The flow:

```
1. User submits a request → Reciter Requests Space
2. Space fires repository_dispatch reciter.alignment_requested { slug, ... }
3. .github/workflows/forward-to-inspector.yml runs:
   - POST https://hetchyy-quranic-inspector.hf.space/api/internal/inspector-event
        Body: { event: "reciter.alignment_requested", payload: { ... } }
        Auth: HMAC of body with INSPECTOR_FORWARD_SECRET
4. Inspector validates HMAC and applies the state transition
   (catalogued → awaiting_alignment, sets issue_number)
```

Why route through GH Actions: the Reciter Requests Space already fires dispatch; rewiring it to talk to Inspector directly is more change. The forward workflow is a 10-line yaml.

## 5. HF Job specifications

Each Job is a small Docker image with `huggingface_hub` + `requests` + the relevant pipeline code. Built from the main repo (`scripts/lib/` + relevant entry points).

### Job: `snapshot-bucket-to-dataset`

```bash
hf jobs run \
  --image hetchyy/inspector-jobs:latest \
  -v hf://buckets/hetchyy/quranic-inspector-wip:/data/bucket \
  -e SLUG=<slug> \
  python scripts/jobs/snapshot_bucket_to_dataset.py
```

Inside the container:

1. Read `/data/bucket/inspector-wip/<slug>/data/recitation_segments/<slug>/{segments,detailed,edit_history,edit_history_peaks,low_confidence_v2}.{json,jsonl}`.
2. Gzip each file (compresslevel 9, mtime=0 for deterministic output).
3. Upload to `hetchyy/quranic-universal-ayahs/inspector/segments/<slug>/<file>.gz` via `HfApi.upload_file`.
4. Compute SHA-256 of each upload, write into `manifest.json.gz`'s `inspector_shard_hashes`.
5. On success: archive `/data/bucket/inspector-wip/<slug>/` to `/data/bucket/_archive/<slug>/<published_at>/` (or delete if archive policy is "delete").
6. POST `https://hetchyy-quranic-inspector.hf.space/api/internal/job-completed?type=snapshot&slug=<slug>` (with HMAC auth).

Cost: ~30 s per reciter. ~25 MB transfer. Cheap.

### Job: `timestamps-refresh`

```bash
hf jobs run \
  --image hetchyy/inspector-jobs:latest \
  -v hf://buckets/hetchyy/quranic-inspector-wip:/data/bucket \
  -e SLUG=<slug> \
  python scripts/jobs/timestamps_refresh.py
```

Inside:

1. Read `/data/bucket/inspector-wip/<slug>/data/recitation_segments/<slug>/detailed.json`.
2. Call MFA Aligner Space (`hetchyy/Quran-phoneme-mfa-dev` by default) for each verse — same flow as the existing `extract_timestamps.py`.
3. Compute timestamps; gzip per chapter.
4. Upload to `hetchyy/quranic-universal-ayahs/timestamps/<slug>/<chapter>.json.gz`.
5. POST `/api/internal/job-completed?type=timestamps&slug=<slug>` on success.

Cost: ~5–10 min per reciter (MFA alignment is the bottleneck). The MFA Aligner Space is the actual compute; the HF Job is just orchestration.

This is the slowest Job — Inspector tracks it in the admin dashboard.

### Job: `build-per-verse-audio-dataset`

```bash
hf jobs run \
  --image hetchyy/inspector-jobs:latest \
  -v hf://buckets/hetchyy/quranic-inspector-wip:/data/bucket \
  -e SLUG=<slug> \
  python scripts/jobs/build_per_verse_audio.py
```

Inside: same logic as the existing `.github/scripts/build_reciter.py` main path — slice audio per verse, build parquet rows with word timestamps, upload to dataset. Reads inputs from bucket instead of git checkout.

Cost: ~5 min per reciter (audio download + slicing).

Trigger source for re-runs: maintainer can manually re-run any of these jobs from the admin dashboard if a step fails — Inspector exposes `POST /api/admin/rerun-job/<slug>?job=<type>`.

### Job image (`hetchyy/inspector-jobs:latest`)

A small Docker image with:

- Python 3.11
- `huggingface_hub`, `requests`, `orjson`, `numpy`
- `scripts/lib/` (segment shards, timestamps shards, reciter task)
- `scripts/jobs/` (job entry points)
- ffmpeg (for `build-per-verse-audio-dataset`)

Image is published to GHCR by `inspector-jobs-image.yml` (a tiny GH Actions workflow on push to `main` touching `scripts/jobs/**` or `scripts/lib/**`).

## 6. Workflow specifications

### `update-reciters.yml`

```yaml
name: Update Reciters Index
on:
  repository_dispatch:
    types: [reciter.completed]
  push:
    branches: [main]
    paths:
      - 'data/reciter_catalog.json'
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
          INSPECTOR_BUCKET_REPO: hetchyy/quranic-inspector-wip
        run: |
          # Reads catalog from local checkout, state from bucket via huggingface_hub
          python .github/scripts/list_reciters.py --write
      - name: Open PR if changes
        run: |
          if ! git diff --quiet; then
            gh pr create ...
          fi
```

The script reads catalog from the local checkout (catalog is on GitHub) and state from bucket via:

```python
from huggingface_hub import HfFileSystem
fs = HfFileSystem()
with fs.open(f"buckets/hetchyy/quranic-inspector-wip/state/reciter_state.json", "r") as f:
    state = json.load(f)
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

`package_release.py` reads the relevant data files from HF dataset (now that completed reciters are there), zips them with audio (if including), uploads to a new GitHub Release.

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
      - 'data/{surah_info,qpc_hafs,digital_khatt_v2_script,phoneme_sub_costs,reciters_index,riwayat,sources,styles}.json'
      - 'data/.audio_meta.json'
      - 'data/.audio_durations.json'
      - 'data/audio/**'  # because audio_catalog.json.gz is rebuilt
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
      - name: Build audio catalog
        run: python scripts/build_audio_catalog.py --output data/audio_catalog.json.gz
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

## 7. Inspector backend's role in the fan-out

`inspector/services/publish.py` orchestrates the publish event:

```python
def publish(slug: str, actor: User) -> PublishResult:
    # 1. State transition (synchronous, atomic)
    state.transition(slug, PublishEvent(actor))

    # 2. Fan-out trigger (best-effort; failures logged, not propagated)
    failures = []
    try:
        github_dispatch.dispatch("reciter.completed", {"slug": slug})
    except Exception as e:
        failures.append(("github_dispatch", str(e)))

    job_ids = {}
    for job_name in ["snapshot-bucket-to-dataset", "timestamps-refresh", "build-per-verse-audio-dataset"]:
        try:
            job_ids[job_name] = hf_jobs.enqueue(job_name, {"slug": slug})
        except Exception as e:
            failures.append((job_name, str(e)))

    # 3. Track jobs in memory for admin dashboard
    pending_jobs[slug] = job_ids

    return PublishResult(state="awaiting_timestamps", job_ids=job_ids, dispatch_failures=failures)
```

If any of the dispatch/job-enqueue calls fail, the maintainer sees the failure in the admin dashboard with a "retry" button. The state transition is independent — once it commits to the bucket, `awaiting_timestamps` is the truth even if all the subordinate jobs fail. (They'll be retried by the maintainer.)

## 8. Job completion callbacks

HF Jobs don't deliver completion events natively (yet). Two patterns to bridge:

### Pattern A: Job-side webhook

Each Job's last step POSTs to Inspector:

```bash
# inside the job
curl -fsS -X POST \
  -H "Authorization: Bearer $INSPECTOR_FORWARD_SECRET" \
  "https://hetchyy-quranic-inspector.hf.space/api/internal/job-completed" \
  -d "{\"type\": \"snapshot\", \"slug\": \"$SLUG\", \"status\": \"success\"}"
```

Inspector's handler:

```python
@require_internal_secret
@app.post("/api/internal/job-completed")
def job_completed():
    body = request.json
    if body["type"] == "timestamps" and body["status"] == "success":
        state.transition(body["slug"], TimestampsCompletedEvent())
    # update pending_jobs map; surface in admin dashboard
```

### Pattern B: Inspector polls HF Jobs API

Inspector periodically polls `GET https://huggingface.co/api/jobs/<job_id>` for each tracked job. On status change, advances state.

**Decision: Pattern A as primary, Pattern B as backstop.** Pattern A is fast and event-driven; Pattern B catches anything Pattern A drops (network glitch on the curl, etc.). Polling cadence: 1 minute, with exponential backoff after 10 minutes idle.

## 9. Bucket → dataset copy semantics

Per HF docs: "transferring data from a Bucket to a repository (model, dataset, Space) without reuploading is **not yet available**, but is on the roadmap."

So `snapshot-bucket-to-dataset` does **download + reupload** today:

```python
from huggingface_hub import download_bucket_files, HfApi

def snapshot(slug: str):
    # 1. Download from bucket
    download_bucket_files(
        BUCKET_REPO,
        files=[
            (f"inspector-wip/{slug}/data/recitation_segments/{slug}/segments.json",     "/tmp/segments.json"),
            (f"inspector-wip/{slug}/data/recitation_segments/{slug}/detailed.json",     "/tmp/detailed.json"),
            (f"inspector-wip/{slug}/data/recitation_segments/{slug}/edit_history.jsonl", "/tmp/edit_history.jsonl"),
            (f"inspector-wip/{slug}/data/recitation_segments/{slug}/edit_history_peaks.jsonl", "/tmp/edit_history_peaks.jsonl"),
            (f"inspector-wip/{slug}/data/recitation_segments/{slug}/low_confidence_v2.json", "/tmp/low_confidence_v2.json"),
        ],
    )
    # 2. Gzip
    for name in ["segments.json", "detailed.json", "edit_history.jsonl", "edit_history_peaks.jsonl", "low_confidence_v2.json"]:
        with open(f"/tmp/{name}", "rb") as src, gzip.open(f"/tmp/{name}.gz", "wb", compresslevel=9, mtime=0) as dst:
            shutil.copyfileobj(src, dst)
    # 3. Upload to dataset
    api = HfApi()
    for name in [...]:
        api.upload_file(
            path_or_fileobj=f"/tmp/{name}.gz",
            path_in_repo=f"inspector/segments/{slug}/{name}.gz",
            repo_id=DATASET_REPO,
            repo_type="dataset",
        )
```

When server-side Xet copy lands, this collapses to one `api.copy_files(...)` call with no local round-trip.

## 10. Phased rollout

Maps onto the parent doc's [§10 phased migration](inspector-deployment-plan.md). This doc's scope lands primarily in Phase 6.

### Phase 0 — Foundation

- Land `INSPECTOR_GITHUB_DISPATCH_TOKEN` secret on the dev Space.
- Land `inspector/services/github_dispatch.py` and `inspector/services/hf_jobs.py` (stub implementations; not yet called from the publish path).
- Reciter Requests Space → forward-to-inspector workflow set up.

### Phase 5 — Writes

- Add `inspector/services/publish.py` (state transition + fan-out trigger), but without firing any subordinate jobs yet (only the state transition runs in this phase).

### Phase 6 — Publish pipeline

**In scope:**
- Build the inspector-jobs Docker image + GHCR publish.
- Land `scripts/jobs/snapshot_bucket_to_dataset.py`, `scripts/jobs/timestamps_refresh.py`, `scripts/jobs/build_per_verse_audio.py`.
- Land `update-reciters.yml`, `release.yml`, `inspector-deploy.yml` GH Actions workflows.
- Wire `publish.py` to actually fire the dispatch + Jobs.
- Land `/api/internal/job-completed` handler.
- Decommission the v1 workflows: `bot-create-pr.yml`, `bot-comment.yml`, `issue-commands.yml`, `pr-assignee-sync.yml`, `validate-segments-pr.yml`, `segments-pr-merged.yml`, `validate-edit-history.yml` (keep as opt-in CI for catalog PRs).
- Delete `find_segments_pr.py`.

**Acceptance:**
- Maintainer publishes a `_test_*` reciter end-to-end. Within 1 minute of clicking Publish:
  - Bucket entry is at `_archive/<slug>/<ts>/...`
  - HF dataset has `inspector/segments/<slug>/...` shards
  - GitHub Release `<slug>-v0.X.Y` exists with the zip attached
  - `RECITERS.md` has been auto-PR'd with the slug marked completed
- Within ~10 minutes:
  - HF dataset `timestamps/<slug>/...` shards exist
  - Per-verse audio rows exist for the slug
  - State transitions to `completed` (Inspector's `/api/internal/job-completed` handler advances it)

## 11. Risks and open questions

### HF Jobs dispatch reliability

HF Jobs is relatively new (2025–2026). If the API has hiccups, the publish event can land in state `awaiting_timestamps` with no jobs fired. **Mitigation:** the maintainer sees the dispatch failure in the publish dialog and can manually retry from the admin dashboard. Reconciler workflow flags `awaiting_timestamps` older than 30 min for re-trigger.

### `INSPECTOR_GITHUB_DISPATCH_TOKEN` rotation

The PAT used to fire `repository_dispatch` events expires per its own settings (no auto-rotation like a GitHub App). **Mitigation:** quarterly rotation reminder in the runbook. If expired silently, the scheduled cron in `update-reciters.yml` (every 30 min) catches missed events.

### Subordinate Job failures

A subordinate Job (e.g., `timestamps-refresh`) fails mid-run. State sits at `awaiting_timestamps` forever without intervention. **Mitigation:** Inspector polls HF Jobs API every minute; flags failed jobs in the admin dashboard. Maintainer can re-run via `/api/admin/rerun-job/<slug>?job=timestamps-refresh`.

### Bucket archive policy

Should we archive bucket entries to `<bucket>/_archive/<slug>/<published_at>/` post-snapshot, or delete? **Recommend archive** for the first month (recovery option if dataset publish has a bug); **delete** after that (storage cost is small but accumulates). Configurable via `INSPECTOR_BUCKET_ARCHIVE_POLICY` env var.

### Job image distribution

The `hetchyy/inspector-jobs` image lives on GHCR. HF Jobs needs to pull it; confirm HF Jobs supports GHCR (it does for public images). If not, mirror to Docker Hub or Quay.

### Forward-to-Inspector workflow as a single point of failure

If `forward-to-inspector.yml` is down or misconfigured, alignment requests from the Reciter Requests Space don't reach Inspector — slugs never enter the state file. **Mitigation:** the daily reconciler walks the catalog and adds any missing slugs with state `catalogued`. Worst-case latency: 24h.

### Bucket → dataset copy speed

Today's download + reupload ≈ ~30 s per reciter. When server-side Xet copy lands (HF roadmap), drops to seconds. **No action needed** — code naturally upgrades when HF rolls out the API.

### Transactional ordering

What if `state.transition(slug, PublishEvent)` succeeds but the fan-out triggers all fail? The reciter is in `awaiting_timestamps` with nothing happening. **Mitigation:** the publish handler returns the failures to the maintainer; the admin dashboard surfaces a "stuck publish" indicator with a retry button. Manual recovery is fine for this rare case.

### Multiple Inspector replicas firing duplicate dispatch

If we ever scale to multi-replica, two replicas might each see the publish event and both fire. **Mitigation:** the bucket state mutex serializes the publish transition itself; only one replica's transition succeeds, the other sees `awaiting_timestamps` and skips. The fan-out triggers must be idempotent — `repository_dispatch` events fired twice are harmless (workflow runs twice, second is a no-op); HF Job duplicates are visible but cheap. Acceptable.
