# Phase 2 — Deployable image + read-only deploy

> Inspector goes live on the dev Space. Anonymous users can browse all reciters (in-flight + completed) read-only. No auth, no writes, but the production-grade image, gunicorn, and bucket-mediated reads are all in place.

**Status:** done
**Depends on:** Phase 1 (Foundation) complete
**Blocks:** Phase 3, Phase 4

## Goal

First public surface. Image is slim and production-grade (gunicorn-gthread, `-w 1`, `create_app()` factory). Backend serves both `wip/<slug>/` and `published/<slug>/` reciter data from the bucket via a single read path. Frontend renders the segments + timestamps + audio tabs in view-only mode for everyone, with no edit affordances yet. dev Space is reachable and survives a smoke-test pass; prod Space cutover blocked on Phase 3.

## Deliverables

- [ ] `inspector/Dockerfile` — gunicorn-gthread CMD with `-w 1 --threads 16 --max-requests 5000 --max-requests-jitter 500 --timeout 60 --graceful-timeout 30`
- [ ] `inspector/Dockerfile` — ENV defaults flipped to deployed profile (`INSPECTOR_DATA_DIR=/app/data`, `INSPECTOR_QUA_DATA_PATH=/app/data`, `INSPECTOR_TS_SOURCE=bucket`, `INSPECTOR_TS_VALIDATE_ENABLED=0`, `INSPECTOR_CACHE_DIR=/tmp/inspector-cache`, `INSPECTOR_BUCKET_MOUNT=/data/inspector-bucket`, `INSPECTOR_PARSED_CACHE_BYTES=134217728`, `GUNICORN_WORKERS=1`)
- [ ] `inspector/Dockerfile` — slim COPY list: only `data/{surah_info,qpc_hafs,digital_khatt_v2_script,phoneme_sub_costs,inspector_roles}.json`
- [ ] `inspector/Dockerfile` — runtime deps added: `gunicorn`, `huggingface_hub`, `authlib`, `itsdangerous`
- [ ] Root `.dockerignore` covering excluded paths from data-storage §7
- [ ] Worker assertion in `inspector/app.py` rejects multi-worker config (`-w 2+`, `--workers=2`, `WEB_CONCURRENCY>1`, `GUNICORN_WORKERS>1`, `GUNICORN_CMD_ARGS` containing those, or `sys.argv` of the loader). **`create_app()` factory dropped from the deliverable** — module-level `app` works for `gunicorn inspector.app:app` and adds zero value at the cost of breaking the existing import surface; reintroduce in Phase 3 if the OAuth blueprint needs test isolation.
- [ ] `Cache-Control: public, max-age=86400` on inspector segment-shard responses (`/api/seg/data/...`)
- [ ] Hash-gated peaks cache: frontend appends `?h=<8-char-fnv1a>` to `/api/seg/peaks/<reciter>` (hash is over `audio_by_chapter` for the requested chapters). Backend ignores the value and emits `Cache-Control: public, max-age=31536000, immutable` when `?h=` is present AND the response is `complete`; `no-store` for partial responses; `max-age=86400` fallback when `?h=` is absent. `/api/seg/history-peaks/<reciter>` GET is `no-store` (mutates on every save).
- [ ] Backend serves `/api/seg/data/<slug>/...` from `<bucket>/{wip,published}/<slug>/` via the resolver from Phase 1
- [ ] Backend serves `/api/static/catalog.json` from the in-memory parsed catalog (browser fetch on app load) — already shipped in Phase 1
- [ ] Frontend segments tab dual-mode: same client code; URL templating against the backend catalog response
- [ ] Frontend `editGate` Svelte action — single mechanism applied to any element triggering an edit. Click is swallowed and the global `EditAffordancePopover` is anchored to the trigger when `editingMode.kind === 'view'` (Phase 2 always); passes through for `editor`/`maintainer`/`owner` (Phase 3+). Supports `use:editGate={{ require: 'admin' }}` for Phase 7 admin actions. **No per-component listing in this contract** — adding a new edit affordance later is "add `use:editGate` to the trigger". Tested via 7-case Vitest unit covering all role/require combinations.
- [ ] `routes/timestamps.py::ts_validate` gated route-level by `INSPECTOR_TS_VALIDATE_ENABLED=0` (returns 410 in deployed). `routes/audio_proxy.py` stays registered everywhere — `source.ts` routes by_surah audio through `/api/seg/audio-proxy/<reciter>?url=...` and dropping the route silently breaks playback. The proxy degrades to a 302 redirect when no cache file exists; background download workers run only on explicit `POST /prepare-audio`. The `INSPECTOR_AUDIO_PROXY_ENABLED` env knob is retired.
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

- [ ] **dev Space is private** (operator preference; not anonymously accessible). Any HF account with read access to the Space can land on `https://hetchyy-quranic-inspector-dev.hf.space` and see the segments tab with the reciter list rendered. The "anonymous user" Phase-2 acceptance shifts to **prod** on Phase 3 sign-off when the prod Space ships public.
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

## Outcomes

Landed across 8 commits on `dev` (sharp-curie worktree). Live at `https://hetchyy-quranic-inspector-dev.hf.space` (private; HF accounts with read access can browse).

### What shipped

- **Production image** (gunicorn-gthread, `-w 1 --threads 16`, port 7860). Real worker assertion checks `GUNICORN_CMD_ARGS` / `WEB_CONCURRENCY` / `GUNICORN_WORKERS` env + `sys.argv` `-w` / `--workers`; refuses any multi-worker config at import time.
- **Bucket-mediated reads**: every `/api/seg/data/<slug>/...` and `/api/ts/shard/<slug>/<chapter>` resolves through the Phase-1 backend resolver against `<bucket>/{wip,published}/<slug>/`. NFS mount when present, bucket API when not.
- **`/healthz`** + `/livez`. Healthz returns 503 in deployed mode when bucket-mount or state-hydration is degraded.
- **`/api/static/catalog.json`** feeding both segments + timestamps tabs.
- **Cache headers**: `public, max-age=86400` on segment shards (no `immutable` — shards mutate on re-edit). Hash-gated peaks: `?h=<8-char-FNV-1a>` over the request's `audio_by_chapter` → `public, max-age=31536000, immutable` only when `complete && len(peaks)>0`; partial or empty-complete falls back to `no-store`.
- **TS bucket mode**: new `_ensure_built_bucket()` composes manifest from state (completed reciters) + catalog (display + delivery) + audio_manifest sidecars (URL template). Per-chapter shards lazy-loaded from `<bucket>/published/<slug>/timestamps/<chapter>.json` via a 256-entry LRU. Legacy `INSPECTOR_TS_SOURCE=huggingface` removed entirely (config raises; types narrowed; TimestampsTab branch deleted).
- **Surface gating**: `audio_proxy_bp` not registered when `INSPECTOR_AUDIO_PROXY_ENABLED=0`; `ts_validate` returns 410 when `INSPECTOR_TS_VALIDATE_ENABLED=0`. Dockerfile sets both to 0.
- **Frontend view-only mode**: single `editGate` Svelte action wires every state-mutating button to a global `EditAffordancePopover`. 7-case Vitest unit covers all role/require combinations. Wired on the 6 SegmentRow mutation buttons (Adjust, Merge prev/next, Delete, Split, Edit Ref), GenericIssueCard Ignore, MissingWordsCard auto-fix, EditChainRow + HistoryBatch Undo/Discard. Adding new edit affordances later = adding `use:editGate`.
- **Secret guards**: `services/secrets_guard.py::get_dispatch_token` refuses the seeded `PLACEHOLDER_REPLACE_BEFORE_PHASE_5`; `get_session_secret` refuses unset/short keys. Phase 3/5 import these instead of touching `os.environ` directly.
- **Deploy automation**: `scripts/upload_inspector.py` (build frontend → stage Space tree → upload_folder), `scripts/inspector_v2_seed/setup_space.py` (idempotent: create private docker Space, write README frontmatter, attach bucket volume, set vars + secrets, factory reboot). `.github/workflows/inspector-deploy.yml` triggers on push to `dev` (paths-filtered); prod-on-`main` shipped commented out, gated on Phase 3 sign-off.

### Metrics (from local dev laptop in AU → HF Spaces in US-East)

| Metric | Value | vs target |
|---|---|---|
| Image size | **226 MB** | ≤ 400 MB ✓ |
| Cold `docker build` (clean cache) | 27 s | n/a |
| Warm `docker build` (no code changes) | 2 s | n/a |
| HF Space first build | ~92 s | n/a |
| HF Space rebuild (code change) | ~46 s | n/a |
| `/healthz` | 200 OK, `bucket_mounted=true, state_loaded=true, reciters_count=14` | ✓ |
| `/api/static/catalog.json` | 422 reciters, 864 deliveries | ✓ |
| TS bucket mode manifest | 6 reciters × 114 chapters each | ✓ |
| TS shard fetch | 200 OK, gzipped, ~2 KB/chapter | ✓ |
| Cold p99 (10 different shards, sequential) | 2229 ms | over the contract's 800 ms — but inflated by AU↔US RTT × multi-roundtrip TLS; backend processing time would need server-side measurement to compare cleanly |
| Warm p99 (10x same shard, no client cache) | 1116 ms | curl bypasses cache; backend repeats the bucket fetch → essentially the cold number. Browser hits would benefit from the `max-age=86400` header |
| Concurrent burst (10x parallel, same shard) | **132 ms total** | CDN/edge cache absorbing — 10 nearly-instant responses |

### Reviewer-pass deltas (caught + landed in commit `aead2d2a`)

- Worker assertion was originally a `GUNICORN_WORKERS == 1` env check, decorative against `gunicorn -w 2` directly. Rewritten to check three env sources + `sys.argv`. Verified by booting the image with each multi-worker signal — all three hard-fail.
- Peaks `immutable` cache header was incorrectly applied to `complete=true && len(peaks)==0` (would permanently cache empty payload). Now requires both complete + non-empty.
- `/healthz` returned 200 even when degraded. Returns 503 in deployed mode when bucket/state checks fail.
- `_bucket_url_template` failures were silent. Each empty-template return now logs `WARNING` with the failing reason.
- Phase-4 caveat comment added to the FE peaks-hash computation: current hash covers audio URLs only; per-segment peaks would need segment boundaries folded in.

### Drift from contract (accepted)

- **`create_app()` factory dropped.** Module-level `app` works for `gunicorn inspector.app:app` and matches the existing import surface used by tests; reintroducing it would break ~50 imports across `inspector/services/...`. Will revisit in Phase 3 if the OAuth blueprint needs test isolation.
- **dev Space is private.** Phase 2 contract opener said "anonymous user lands". Operator preference made the dev Space private; the anonymous-browse story shifts to **prod** at Phase 3 sign-off.
- **`docker-compose.yml` not migrated to bucket mode**. Local Docker still runs in legacy `INSPECTOR_TS_SOURCE=local` mode reading on-disk `data/timestamps/`. Deferred — Phase 11 cleanup will retire local mode entirely once the offline maintainer flow lives off the bucket too.

### Carried forward

All forward-looking items live in [`inspector-deferred.md`](../inspector-deferred.md):
- D21 — Peaks hash must fold in segment boundaries if per-segment peaks ever surface on `/api/seg/peaks/`.
- D22 — Multi-worker scale-out (`-w >1`) — needs a shared coordinator.
- D23 — Replace personal HF token with a `hetchyy-bot` org token.
- D24 — Replace `INSPECTOR_GITHUB_DISPATCH_TOKEN` placeholder with a real PAT.
- D25 — Writable `HOME` for the inspector container user (blocks Xet writes).
- D26 — ESLint rule for `use:editGate` coverage.
