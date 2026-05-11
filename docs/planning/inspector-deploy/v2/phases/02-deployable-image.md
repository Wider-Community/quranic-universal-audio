# Phase 2 — Deployable image + read-only deploy

> Inspector goes live on the dev Space. Anonymous users can browse all reciters (in-flight + completed) read-only. No auth, no writes, but the production-grade image, gunicorn, and bucket-mediated reads are all in place.

**Status:** in progress
**Depends on:** Phase 1 (Foundation) complete
**Blocks:** Phase 3, Phase 4

## Goal

First public surface. Image is slim and production-grade (gunicorn-gthread, `-w 1`, `create_app()` factory). Backend serves both `wip/<slug>/` and `published/<slug>/` reciter data from the bucket via a single read path. Frontend renders the segments + timestamps + audio tabs in view-only mode for everyone, with no edit affordances yet. dev Space is reachable and survives a smoke-test pass; prod Space cutover blocked on Phase 3.

## Deliverables

- [ ] `inspector/Dockerfile` — gunicorn-gthread CMD with `-w 1 --threads 16 --max-requests 5000 --max-requests-jitter 500 --timeout 60 --graceful-timeout 30`
- [ ] `inspector/Dockerfile` — ENV defaults flipped to deployed profile (`INSPECTOR_DATA_DIR=/app/data`, `INSPECTOR_QUA_DATA_PATH=/app/data`, `INSPECTOR_TS_SOURCE=bucket`, `INSPECTOR_AUDIO_PROXY_ENABLED=0`, `INSPECTOR_TS_VALIDATE_ENABLED=0`, `INSPECTOR_CACHE_DIR=/tmp/inspector-cache`, `INSPECTOR_BUCKET_MOUNT=/data/inspector-bucket`, `INSPECTOR_PARSED_CACHE_BYTES=134217728`, `GUNICORN_WORKERS=1`)
- [ ] `inspector/Dockerfile` — slim COPY list: only `data/{surah_info,qpc_hafs,digital_khatt_v2_script,phoneme_sub_costs,inspector_roles}.json`
- [ ] `inspector/Dockerfile` — runtime deps added: `gunicorn`, `huggingface_hub`, `authlib`, `itsdangerous`
- [ ] Root `.dockerignore` covering excluded paths from data-storage §7
- [ ] `inspector/app.py::create_app()` factory + `GUNICORN_WORKERS == 1` startup assertion
- [ ] `Cache-Control: public, max-age=86400` on inspector segment-shard responses (`/api/seg/data/...`)
- [ ] Hash-gated peaks cache: frontend appends `?h=<8-char-fnv1a>` to `/api/seg/peaks/<reciter>` (hash is over `audio_by_chapter` for the requested chapters). Backend ignores the value and emits `Cache-Control: public, max-age=31536000, immutable` when `?h=` is present AND the response is `complete`; `no-store` for partial responses; `max-age=86400` fallback when `?h=` is absent. `/api/seg/history-peaks/<reciter>` GET is `no-store` (mutates on every save).
- [ ] Backend serves `/api/seg/data/<slug>/...` from `<bucket>/{wip,published}/<slug>/` via the resolver from Phase 1
- [ ] Backend serves `/api/static/catalog.json` from the in-memory parsed catalog (browser fetch on app load) — already shipped in Phase 1
- [ ] Frontend segments tab dual-mode: same client code; URL templating against the backend catalog response
- [ ] Frontend `editGate` Svelte action — single mechanism applied to any element triggering an edit. Click is swallowed and the global `EditAffordancePopover` is anchored to the trigger when `editingMode.kind === 'view'` (Phase 2 always); passes through for `editor`/`maintainer`/`owner` (Phase 3+). Supports `use:editGate={{ require: 'admin' }}` for Phase 7 admin actions. **No per-component listing in this contract** — adding a new edit affordance later is "add `use:editGate` to the trigger". Tested via 7-case Vitest unit covering all role/require combinations.
- [ ] `routes/timestamps.py::ts_validate` gated route-level by `INSPECTOR_TS_VALIDATE_ENABLED=0` (returns 410 in deployed). `routes/audio_proxy.py` blueprint not registered when `INSPECTOR_AUDIO_PROXY_ENABLED=0`.
- [ ] `.github/workflows/inspector-deploy.yml` — selective upload to dev Space on push to `dev` branch (paths-filtered). Prod-on-`main` trigger ships commented out, gated on Phase 3 sign-off.
- [ ] `scripts/upload_inspector.py` selective-push script (Python — uses `huggingface_hub.upload_folder`).
- [ ] dev Space configured via `scripts/inspector_v2_seed/setup_space.py` (idempotent, dry-run by default; `--apply` to mutate). Creates the private docker Space, writes README frontmatter (`hf_oauth: true`), attaches the bucket volume at `/data/inspector-bucket`, sets variables + secrets, factory-reboots.
- [ ] dev Space secrets handled by `setup_space.py`: `INSPECTOR_HF_TOKEN` (write scope on bucket — copied from local `.env`); `INSPECTOR_SESSION_SECRET` (auto-generated 32-byte hex; signs cookies in Phase 3); `INSPECTOR_GITHUB_DISPATCH_TOKEN` (placeholder `"PLACEHOLDER_REPLACE_BEFORE_PHASE_5"` — replace with a fine-grained PAT (`actions: write`) before Phase 5 fires `repository_dispatch reciter.completed`); `INSPECTOR_JOB_CALLBACK_SECRET` (auto-generated; HF Job webhook auth in Phase 5).

## Out of scope

- HF OAuth flow / signed-cookie session (Phase 3).
- Any `/api/claim`, `/api/release`, `/api/save` endpoints (Phase 3, Phase 4).
- `/admin` route (Phase 7).
- prod Space cutover — only dev in Phase 2.
- CDN front (deferred — D12).
- HF dataset reads from frontend (gone for good per D4).

## Acceptance criteria

- [ ] Anonymous user lands on `https://hetchyy-quranic-inspector-dev.hf.space` and sees the segments tab with the reciter list rendered.
- [ ] p99 cold page load for a completed reciter ≤ 800 ms.
- [ ] p99 warm page load ≤ 50 ms.
- [ ] Image size ≤ 400 MB.
- [ ] gunicorn process visible in container — Werkzeug dev server is gone.
- [ ] `GUNICORN_WORKERS == 1` startup assertion verified (boot fails if `-w 2+` is set).
- [ ] Image discipline check passes: no `data/recitation_segments/`, `data/timestamps/`, `data/audio/`, `data/reciters_index.json`, `data/{riwayat,sources,styles}.json`, `audio_catalog.json.gz` inside `/app/data`.
- [ ] Bucket mount visible at `/data/inspector-bucket` inside the container.
- [ ] State + catalog parsed at startup; `/healthz` returns `bucket_mounted: true, state_loaded: true, reciters_count: <N>`.
- [ ] 10 concurrent same-file requests don't degrade p95 below 1 s once warm.
- [ ] Edit-affordance buttons are visible but clicking any of them shows `EditAffordancePopover`; nothing mutates server state in Phase 2.
- [ ] No `Cache-Control: immutable` on segment-shard responses (only on hash-keyed peaks).

## Verification

```bash
SPACE=https://hetchyy-quranic-inspector-dev.hf.space

# Health
curl -fsS $SPACE/healthz | jq

# Anonymous reciter list
curl -fsS $SPACE/api/reciters | jq 'length'

# Anonymous reciter task
curl -fsS $SPACE/api/reciter-task/saad_al_ghamdi | jq '.state'  # expect "completed"

# Backend → bucket round-trip for a completed reciter shard
curl -fsSI $SPACE/api/seg/data/saad_al_ghamdi/1 | head -10
# Expect Cache-Control: public, max-age=86400 (NOT immutable)

# Peaks immutable header
curl -fsSI "$SPACE/api/seg/segment-peaks?slug=saad_al_ghamdi&seg=...&hash=..." | head -10
# Expect Cache-Control: public, max-age=31536000, immutable

# Image discipline
docker run --rm hetchyy/quranic-inspector-dev:latest sh -c '
  find /app/data \( \
    -path "*/recitation_segments/*" -o -path "*/timestamps/*" -o -path "*/audio/*" -o \
    -name "audio_catalog.json.gz" -o -name "reciters_index.json" -o \
    -name "riwayat.json" -o -name "sources.json" -o -name "styles.json" \
  \) -print | head -1
' | grep -q . && echo "FAIL" || echo "OK"

# Concurrent burst
for i in {1..10}; do curl -fsS "$SPACE/api/seg/data/saad_al_ghamdi/1" >/dev/null & done; wait
```

## Risks

- **Bucket mount cold-fetch latency** — first read per reciter per Space replica pays NFS lazy-fetch (~100–300 ms estimated). Acceptable; CDN front (D12) is the lever if measurement shows otherwise.
- **HF outage blast radius** — the bucket is now in the read path for everything. `/healthz` will report it; runbook §7 documents pause/disable rollback.
- **Image rebuild time** — 1–5 min on free tier; users get 503s during. Document in runbook §1.

## Reference

- [`inspector-deployment-plan.md`](../inspector-deployment-plan.md) §3 — read path, free-tier prerequisites
- [`inspector-data-storage.md`](../inspector-data-storage.md) §6, §7 — env config, image build
- [`inspector-deploy-runbook.md`](../inspector-deploy-runbook.md) §1, §2, §4, §6 (Phase 1 smoke tests)
- [`inspector-cleanup-registry.md`](../inspector-cleanup-registry.md) §3 (Dockerfile/COPY/CMD modifications)
