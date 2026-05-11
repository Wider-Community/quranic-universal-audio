# Phase 5 — Publish pipeline

> Maintainer can publish a `marked_ready` reciter end-to-end. Synchronous in-process: state transition + in-bucket move (`wip/<slug>/` → `published/<slug>/`) + one HF Job (`timestamps-refresh`). The job-completion webhook flips state to `released` and fires `repository_dispatch reciter.released` for GH workflows. **The `released → completed` transition (HF dataset publish) is a separate admin-gated action shipped in Phase 7.** A backend bucket-file sweep covers `awaiting_alignment → awaiting_review`.

**Status:** not started
**Depends on:** Phase 4 (Save migration + admin actions) complete
**Blocks:** Phase 6

## Goal

`POST /api/admin/publish/<slug>` is the gate. It runs synchronously in-process: state row transitions `(under_review, marked_ready=1) → awaiting_timestamps`, files move from `<bucket>/wip/<slug>/` to `<bucket>/published/<slug>/`, and ONE HF Job is enqueued for `timestamps-refresh`. The endpoint returns 200 with `{state: "awaiting_timestamps", timestamps_job_id}`. Job's last step POSTs `/api/internal/job-completed` (Bearer-auth) which flips state `awaiting_timestamps → released` and fires `repository_dispatch reciter.released` for `update-reciters.yml` + `release.yml`. A backend `alignment_watcher` thread sweeps `<bucket>/wip/<slug>/detailed.json` and transitions `awaiting_alignment → awaiting_review` when extraction outputs land. `update-reciters.yml` and `release.yml` are rewired to read state + catalog from the bucket via `huggingface_hub`. `sync-dataset.yml` is **decoupled** from `release.yml` and now triggers on `repository_dispatch reciter.dataset_published` (admin-gated, fired by Phase 7's "Add to dataset" action). v1 PR-flow workflows are decommissioned.

## Deliverables

- [ ] `inspector/services/publish.py` — orchestrates the full publish synchronously per publish-pipeline §7
- [ ] `inspector/services/github_dispatch.py` — fires `repository_dispatch` events via `INSPECTOR_GITHUB_DISPATCH_TOKEN` (~30 LoC)
- [ ] `inspector/services/hf_jobs.py` — enqueues HF Jobs via API; persists `timestamps_job_id` on the state row (no in-memory polling map)
- [ ] `inspector/services/hf_bucket.py::move_or_copy(src, dst)` — server-side in-bucket move/copy (per D7 — fallback to download+reupload while waiting on HF API)
- [ ] `POST /api/admin/publish/<slug>` — synchronous publish; gated by maintainer+ role; transitions to `awaiting_timestamps`; returns `{state, timestamps_job_id}`
- [ ] `POST /api/internal/job-completed` — Bearer-auth via `INSPECTOR_JOB_CALLBACK_SECRET`; transitions `awaiting_timestamps → released` on success; appends `timestamps_job_id` to state row's `timestamps_job_ids` list; fires `repository_dispatch reciter.released`
- [ ] `inspector/services/alignment_watcher.py` — background sweep (~60 s) scanning `awaiting_alignment` slugs for `<bucket>/wip/<slug>/detailed.json` + `segments.json`; transitions `awaiting_alignment → awaiting_review`; emits `alignment.completed` audit event. Single-replica safe (matches `-w 1`).
- [ ] `.github/workflows/sync-dataset.yml` — rewired to trigger on `repository_dispatch reciter.dataset_published` only (no longer auto-runs after `release.yml`)
- [ ] `inspector/utils/internal_auth.py::require_bearer(secret_env)` — constant-time compare decorator
- [ ] `INSPECTOR_JOB_CALLBACK_SECRET` configured on dev Space (single secret, no `_PREV`)
- [ ] HF Job image `hetchyy/inspector-jobs-image` (HF Space, Docker SDK, paused) — Python 3.11 + `huggingface_hub` + `requests` + `orjson` + `numpy` + `scripts/lib/` + `scripts/jobs/timestamps_refresh.py`
- [ ] `scripts/jobs/timestamps_refresh.py` — reads `<bucket>/published/<slug>/detailed.json`, calls MFA Aligner Space, writes `<bucket>/published/<slug>/timestamps/<chapter>.json`, POSTs `/api/internal/job-completed`
- [ ] **Shard-builder rewire (D20):** `scripts/lib/segments_shards.py` + `scripts/lib/timestamps_shards.py` read from v2 bucket paths (`<bucket>/published/<slug>/detailed.json` for the per-chapter segments slice, `<bucket>/published/<slug>/timestamps/<chapter>.json` for the per-chapter timestamps) instead of repo `data/`. Rebuild step hooked into `inspector/services/publish.py` so `manifest.json.gz` + `segments/<slug>/<chapter>.json.gz` + `timestamps/<slug>/<chapter>.json.gz` refresh on every publish. **Load-bearing for the universal aligner Space's Preload mode** and the Inspector deployed timestamps tab — both read from this layout via `huggingface_hub.hffs`. Phase 11 `data/` deletion gates on this builder rewire landing cleanly.
- [ ] `.github/workflows/inspector-jobs-deploy.yml` — selective rsync + push to `hetchyy/inspector-jobs-image` on push to `main` touching `scripts/jobs/**` or `scripts/lib/**`
- [ ] `.github/workflows/update-reciters.yml` — rewired to read state + catalog from bucket via `huggingface_hub`; triggers on `repository_dispatch reciter.released` + `reciter.dataset_published` + `reciter.catalog_changed` + cron
- [ ] `.github/workflows/release.yml` — rewired to read from `<bucket>/published/<slug>/` via `huggingface_hub`; triggered on `reciter.released` dispatch (timestamps are guaranteed present by then)
- [ ] `.github/scripts/list_reciters.py` — reads state + catalog from bucket; regenerates `RECITERS.md` only (no `reciters_index.json`)
- [ ] `.github/scripts/build_reciter.py --build-manifest` — reads identity from bucket catalog
- [ ] `.github/scripts/build_reciter.py` — drops `--build-inspector-segments` planning entirely (D4 — no HF dataset namespace for Inspector segments)
- [ ] Decommission these workflows (CI-disabled or deleted):
  - `bot-create-pr.yml`
  - `bot-comment.yml`
  - `issue-commands.yml`
  - `pr-assignee-sync.yml`
  - `validate-segments-pr.yml`
  - `segments-pr-merged.yml`
- [ ] `.github/scripts/find_segments_pr.py` deleted
- [ ] `INSPECTOR_GITHUB_DISPATCH_TOKEN` configured on dev Space; quarterly rotation reminder in runbook
- [ ] Catalog write firing `repository_dispatch reciter.catalog_changed` (already plumbed through `services/catalog.py` from Phase 1; verify it actually fires here)

## Out of scope

- `/admin` route + dashboard panels — Phase 7.
- `bucket-data-hygiene.yml` scheduled workflow — Phase 7.
- `forward-to-inspector.yml` deletion — Phase 7 (alongside Reciter Requests Space decommission).
- `data/{riwayat,sources,styles,reciters_index,.audio_meta,.audio_durations}.json`, `data/audio/`, `data/recitation_segments/` repo deletion — Phase 11 (carried from Phase 1; safe to land only after the workflow rewrites in this phase point `update-reciters.yml` / `release.yml` / `sync-dataset.yml` / `build_reciter.py` / `package_release.py` / `list_reciters.py` at the bucket via `huggingface_hub`).
- Per-job sub-status (D1) — deferred.
- Auto-retry / polling backstop for the timestamps job — deferred.

## Acceptance criteria

- [ ] Maintainer publishes a `_test_*` reciter that is `under_review` with `marked_ready=1`. `POST /api/admin/publish/<slug>` returns 200 within 5 s with `{state: "awaiting_timestamps", timestamps_job_id: "..."}`.
- [ ] Within seconds: `<bucket>/published/<slug>/*` populated; `<bucket>/wip/<slug>/*` removed (or moved to `_archive/<slug>/<ts>/` per `INSPECTOR_BUCKET_ARCHIVE_POLICY`).
- [ ] Within ~10 minutes: `<bucket>/published/<slug>/timestamps/<chapter>.json` shards exist; job's last step POSTs `/api/internal/job-completed` with Bearer secret; state transitions `awaiting_timestamps → released`.
- [ ] `repository_dispatch reciter.released` fires after the state transition; `update-reciters.yml` and `release.yml` runs visible in the GitHub Actions tab within minutes; `RECITERS.md` PR opened; GitHub Release created (with timestamps present in the package).
- [ ] `sync-dataset.yml` does **not** run automatically — verify no run appears in the GitHub Actions tab for this slug until the Phase 7 admin "Add to dataset" action is invoked.
- [ ] Alignment watcher: drop a `detailed.json` + `segments.json` into `<bucket>/wip/_test_alignment_watcher/` (slug must be in `awaiting_alignment`); within ~60 s state transitions to `awaiting_review` and an `alignment.completed` audit line appears.
- [ ] If the timestamps job fails: state stays in `awaiting_timestamps`; the dashboard's "Active timestamps refresh" panel (Phase 7) will surface it; for Phase 5 verification, maintainer can re-enqueue manually via CLI (`hf jobs run ...`).
- [ ] Catalog edit fires `repository_dispatch reciter.catalog_changed`; `update-reciters.yml` regenerates `RECITERS.md` accordingly.
- [ ] Audit log captures `reciter.published` (publish click), `reciter.timestamps_completed` (job callback), and `alignment.completed` (watcher transitions).
- [ ] No runs of decommissioned workflows in a 7-day observation window.
- [ ] `find_segments_pr.py` is gone from the repo.

## Verification

```bash
SPACE=https://hetchyy-quranic-inspector-dev.hf.space

# 1. Manual end-to-end (in browser)
#    - Sign in as maintainer
#    - On a _test_* reciter in (under_review, marked_ready=1), click Publish
#    - Wait for 200 response

# 2. State transition
hf buckets cp \
    hf://buckets/hetchyy/quranic-inspector-bucket-dev/state/reciter_state.json - \
  | jq '.reciters[] | select(.slug == "_test_<slug>") | .state'
# Expect "awaiting_timestamps" (job running) or "released" (job finished)
# NEVER "completed" from the publish flow alone — that requires the Phase 7 "Add to dataset" action

# 3. Bucket move
hf buckets ls hf://buckets/hetchyy/quranic-inspector-bucket-dev/published/_test_<slug>/
# Expect detailed.json, segments.json, edit_history.jsonl, low_confidence_v2.json

hf buckets ls hf://buckets/hetchyy/quranic-inspector-bucket-dev/wip/_test_<slug>/
# Expect: empty / not found

# 4. GH dispatch fired
gh run list --workflow update-reciters.yml --limit 5
gh run list --workflow release.yml --limit 5

# 5. Job completion (after ~10 min)
hf buckets ls hf://buckets/hetchyy/quranic-inspector-bucket-dev/published/_test_<slug>/timestamps/

# 6. Audit
hf buckets cp \
    hf://buckets/hetchyy/quranic-inspector-bucket-dev/audit/$(date +%Y-%m).jsonl - \
  | grep _test_<slug> | jq

# 7. Decommissioned-workflows quiet check (after Phase 5 sits ≥ 7 days)
gh run list --workflow validate-segments-pr.yml --limit 5
gh run list --workflow segments-pr-merged.yml --limit 5
gh run list --workflow bot-create-pr.yml --limit 5
# Expect no runs in the last 7 days

# 8. find_segments_pr.py gone
test ! -f .github/scripts/find_segments_pr.py
```

## Risks

- **HF Jobs API stability** — only one job per publish in v2 (`timestamps-refresh`); blast radius is one stuck reciter. Maintainer manually re-enqueues. Real risk: persistent HF Jobs outage. No automated backoff in v2 (per D16).
- **In-bucket server-side move not yet a dedicated API** — the publish flow falls back to download+reupload (~30 s for ~25 MB). Acceptable at ~10 publishes/month. Watch HF roadmap (D7).
- **`INSPECTOR_GITHUB_DISPATCH_TOKEN` silent expiry** — if rotated incorrectly or revoked, dispatch fails silently. Mitigation: 30-min cron in `update-reciters.yml` catches missed events; runbook §9 covers rotation.
- **Concurrency: only one Inspector replica fires dispatch** — single-replica assumption (`-w 1`) keeps this safe in v2; multi-replica risk deferred to D6.
- **Job's Bearer secret rotation** — single secret, no `_PREV` per D14. Rotation has a brief window where in-flight callbacks may fail; the manual "advance to completed" admin action covers it. Document rotation procedure in runbook §9.

## Reference

- [`inspector-publish-pipeline.md`](../inspector-publish-pipeline.md) — entire doc; primary reference
- [`inspector-deployment-plan.md`](../inspector-deployment-plan.md) §10 Phase 6 — phased migration narrative
- [`inspector-deploy-runbook.md`](../inspector-deploy-runbook.md) §6 Phase 6 smoke tests, §9 rotation procedures
- [`inspector-state-management.md`](../inspector-state-management.md) §4 — `reciter.published` and `reciter.timestamps_completed` events
- [`inspector-admin-perms.md`](../inspector-admin-perms.md) §11 — events shipping in v2
- [`inspector-cleanup-registry.md`](../inspector-cleanup-registry.md) §2 (workflows decommissioned), §4 (new code)
- [`inspector-deferred.md`](../inspector-deferred.md) D1, D7, D11, D13, D16
