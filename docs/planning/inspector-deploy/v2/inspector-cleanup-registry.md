# Inspector Cleanup Registry (v2)

Running ledger for the inspector deployment migration. Each item has a phase tag and a status. Edit as you go — strike out completed items with a commit reference.

This is **not** a design doc. For *why* something is being done, see [`inspector-deployment-plan.md`](inspector-deployment-plan.md), [`inspector-data-storage.md`](inspector-data-storage.md), [`inspector-state-management.md`](inspector-state-management.md), [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md). For deferred items see [`inspector-deferred.md`](inspector-deferred.md). This doc tracks *what's actually done* vs *what should not exist anymore*.

**Reference docs and schema-doc generation are NOT in v2 scope.** v2 ships pydantic models for runtime validation only. The hand-written reference docs and the auto-generation system (JSON Schema, TS types, rendered MD) land later under [`../../schema-docs.md`](../../schema-docs.md). Anything currently under `docs/reference/inspector/` is a pre-v2 sketch, not authoritative.

Status legend: `open` / `wip` / `done` (with commit short SHA in `[brackets]` once landed).

## 1. Mode policy

The Inspector supports **two modes only**, not three. Speculative third-mode hybrids are an explicit "do not add."

| Mode | Filesystem access | Audio proxy | TS source | Validation panel | Reciter catalog | State store | Invocation |
|---|---|---|---|---|---|---|---|
| `local` | Yes (repo `data/`) | On | Local files | On | Bundled JSON files in repo `data/` (during transition) or local fixtures | Local JSON file at `data/.cache/reciter_state.json` (gitignored) | `python3 inspector/app.py` OR `docker compose up` (bind-mounts data) |
| `deployed` | No (HF bucket mount via Inspector backend) | Off | Bucket | Off | `<bucket>/catalog/reciter_catalog.json` | `<bucket>/state/reciter_state.json` (single private bucket) | HF Space build |

`local Python` and `local Docker` are two ways to invoke the same `local` mode — the Dockerfile is single-image-two-profile via env vars (`INSPECTOR_TS_SOURCE`, `INSPECTOR_AUDIO_PROXY_ENABLED`, `INSPECTOR_DATA_DIR`, `INSPECTOR_QUA_DATA_PATH`, `INSPECTOR_BUCKET_MOUNT`). Code branches only on these env vars, never on "is this Docker?".

CLI tools that write to the prod bucket via `huggingface_hub` are maintainer scripts, NOT a third mode.

**Forbidden combinations** (do not add code paths to support):

- Docker without bind-mount (no longer reachable; deploy mode covers it)
- `INSPECTOR_TS_SOURCE=bucket` with `INSPECTOR_AUDIO_PROXY_ENABLED=1` (incoherent — deployed mode skips audio proxy)
- Any third "staging" tier between local and deployed — staging is a separate Space tracking `dev` branch, same code, different secrets, different bucket
- github-fetch (deleted in v2 — bucket replaces all under-review reads)
- Git Data API write path (deleted in v2 — bucket handles writes)
- Scratch dir as separate concept (deleted in v2 — bucket IS the scratch)
- HF dataset reads from Inspector frontend (deleted in v2 — Inspector reads from the bucket only; D4)
- SQLite-on-NFS for state or catalog (deleted in v2 — JSON files via direct upload_file; D2)

## 2. Code deletions

### From the v1 plan that never gets built in v2

| File / symbol | Reason | Phase | Status |
|---|---|---|---|
| `inspector/services/github_fetch.py` | Replaced by bucket mount; v1 plan introduced this; v2 never builds it | (never) | n/a |
| `inspector/services/github_commit.py` | Replaced by bucket file writes; v1 plan introduced; v2 never builds | (never) | n/a |
| `inspector/services/scratch.py` | Bucket mount is the working surface; no separate scratch lifecycle | (never) | n/a |
| `.github/workflows/update-reciter-state.yml` | Inspector backend is sole writer of state in v2 | (never) | n/a |
| `.github/workflows/pr-uniqueness.yml` | No PRs per reciter | (never) | n/a |
| GitHub App registration (Quranic Inspector App) | Replaced by HF OAuth | (never) | n/a |
| `cache-invalidate` webhook receiver | No cache to invalidate (bucket serves live state) | (never) | n/a |
| SQLite databases for state and catalog | Dropped — JSON files with direct `upload_file()` writes per D2 | (never) | n/a |
| `INSPECTOR_META_MOUNT` / `INSPECTOR_META_REPO` env vars | One private bucket per env, not two (D5) | (never) | n/a |

### From the existing repo (currently exist; will be removed)

| File / symbol | Reason | Phase | Status |
|---|---|---|---|
| `inspector/app.py:180` `app.run()` → gunicorn-gthread CMD in Dockerfile | werkzeug dev server is not production-grade; mandatory before public deploy | 1 | open |
| `.github/scripts/find_segments_pr.py` | No per-reciter PRs in v2 | 6 | open |
| `.github/workflows/pr-assignee-sync.yml` | No PRs to assign | 0 | open |
| `.github/workflows/bot-create-pr.yml` | No automated PR creation | 6 | open |
| `.github/workflows/bot-comment.yml` | No automated PR comments | 6 | open |
| `.github/workflows/issue-commands.yml` | `/claim` and `/confirm` retired; web is the contribution surface | 6 | open |
| `.github/workflows/segments-pr-merged.yml` | Replaced by Inspector `POST /api/admin/publish/<slug>` | 6 | open |
| `.github/workflows/validate-segments-pr.yml` | Validators run as libraries inside Inspector services on every relevant write; PR-gate workflow gone (D18) | 6 | open |
| `.github/workflows/forward-to-inspector.yml` | Reciter Requests Space cleanup brought forward (D17); intake is GH issue + maintainer admin add | 6 | open |
| `routes/timestamps.py::ts_validate` (excluded from deployed image only — kept for local) | No validation panel surface in deployed mode | 1 | open |
| `routes/audio_proxy.py` (excluded from deployed image only — kept for local) | Audio plays browser→origin direct in deployed mode | 1 | open |
| `app.py::serve_audio` (excluded from deployed image only — kept for local) | Same as audio proxy | 1 | open |
| `validators/validate_edit_history.py::check_file_hash` | File-hash chain dropped (D13) | 5 | open |
| `validators/validate_edit_history.py::check_genesis_record` | Genesis record dropped (no longer anchors anything; D13) | 5 | open |
| `inspector/utils/io.py::file_sha256` | Last caller is the file-hash chain | 5 | open |
| `inspector/services/save.py::backup_file()` calls in deployed save path | Audit log is the recovery; .bak files clutter the bucket | 5 | open |
| `inspector/services/save.py::_persist_and_record` `file_hash_after` write | Field dropped (D13) | 5 | open |
| `inspector/services/save.py` revert record `file_hash_after` write (any path that writes it) | Field dropped (D13) | 5 | open |
| `inspector/config.py::METADATA_PEEK_BYTES` | Now unused after `discover_ts_reciters` removal — delete the constant | 1 | open |
| `seg_save_chart` route + `analysis/*.png` writes | Debug-only, no UI surface | 5 | open |
| `inspector/app.py` ThreadPoolExecutor startup preload of timestamps | Lazy-load via TS bucket route; no eager preload (verify already removed in current code per app.py:171 comment) | 1 | open |
| `data/audio/<cat>/<src>/<slug>.json` (entire `data/audio/` tree) | Replaced by URL templates + `url_overrides` in `<bucket>/catalog/reciter_catalog.json` per D6 + D8 | 1 | open |
| `data/riwayat.json`, `data/sources.json`, `data/styles.json` | Merged into `vocab.*` of `<bucket>/catalog/reciter_catalog.json` per D6 + D8 | 1 | open |
| `data/reciters_index.json` | Bucket catalog is source of truth for releases + downstream consumers from day one (D8) | 1 | open |
| `data/.audio_meta.json` | Moved to `<bucket>/catalog/audio_meta.json` per D6 + D8 | 1 | open |
| `data/.audio_durations.json` | Moved to `<bucket>/catalog/audio_durations.json` per D6 + D8 | 1 | open |
| `INSPECTOR_FORWARD_SECRET` env var (Space + GH Actions) | Forward webhook removed (D14, D17) | 6 | open |
| `INSPECTOR_FORWARD_SECRET_PREV` rotation slot | Bearer single-secret model (D14) | 6 | open |
| `INSPECTOR_JOB_CALLBACK_SECRET_PREV` rotation slot | Bearer single-secret model (D14) | 6 | open |

## 3. Code modifications

| File / area | Change | Phase | Status |
|---|---|---|---|
| `inspector/Dockerfile` ENV defaults | Flip to `INSPECTOR_DATA_DIR=/app/data`, `INSPECTOR_QUA_DATA_PATH=/app/data` (was `/data`); add `INSPECTOR_AUDIO_PROXY_ENABLED=0`, `INSPECTOR_CACHE_DIR=/tmp/inspector-cache`, `INSPECTOR_BUCKET_MOUNT=/data/inspector-bucket`, `INSPECTOR_PARSED_CACHE_BYTES=134217728` | 1 | open |
| `inspector/Dockerfile` COPY list | Slim per D8: `data/{surah_info,qpc_hafs,digital_khatt_v2_script,phoneme_sub_costs}.json` only. No `audio_catalog.json.gz`, no `reciters_index.json`, no `riwayat/sources/styles.json`, no `audio/`, no `inspector_roles.json` (lives in bucket now). | 1 | open |
| `inspector/Dockerfile` CMD | `app.run()` → `gunicorn -k gthread -w 1 --threads 16 --max-requests 5000 --max-requests-jitter 500 --timeout 60 --graceful-timeout 30`. **`-w 1` is load-bearing** — every in-memory structure assumes single-process. App startup must assert workers==1 | 1 | open |
| Root `.dockerignore` | Create at repo root with the exclusion list from data-storage §7 | 1 | open |
| `inspector/services/cache.py` `_seg` dict | Replace with parsed seg cache layer keyed `(slug, "detailed_parsed")`, sized by `INSPECTOR_PARSED_CACHE_BYTES`. Both wip and published reciters read through this cache via the backend (D4 — frontend never bypasses backend). | 1 | open |
| `inspector/services/data_loader.py::load_timestamps` | Gate behind `INSPECTOR_TS_SOURCE=local`; deployed mode reads from `<bucket>/{wip,published}/<slug>/timestamps/...` via backend | 1 | open |
| `inspector/services/data_loader.py::load_audio_urls` | Gate behind `INSPECTOR_TS_SOURCE=local`; deployed mode resolves URLs from `<bucket>/catalog/reciter_catalog.json` (template + slug + optional `url_overrides`) per D6, D7 | 1 | open |
| `inspector/routes/timestamps.py::config` (`/api/ts/config`) | Extend response with same-origin URL templates for in-flight + completed reciter shards (browser hits Flask, never the bucket directly) | 1 | open |
| `inspector/services/save.py` data path resolution | Use `services/data_dir.py::resolve(slug)` helper. In deployed mode this returns `<INSPECTOR_BUCKET_MOUNT>/wip/<slug>/...` (flat, per D3) | 5 | open |
| `inspector/services/cache.py` / `inspector/services/data_loader.py` for completed reciters | Reads completed reciter data from `<bucket>/published/<slug>/...` via backend (no HF dataset hop, per D4). Same parsed-cache layer serves wip + published. | 1 | open |
| `.github/scripts/build_reciter.py` | Drop `--build-inspector-segments` planning entirely (D4: no `inspector/segments/<slug>/` dataset namespace). Other build targets (per-verse parquet) read from `<bucket>/published/<slug>/` via `huggingface_hub` | 1 | open |
| `.github/scripts/build_reciter.py --build-manifest` | Read identity from `<bucket>/catalog/reciter_catalog.json` and state from `<bucket>/state/reciter_state.json` via `huggingface_hub` | 0 | open |
| `.github/scripts/list_reciters.py` | Read state + catalog from bucket via `huggingface_hub`; regenerate `RECITERS.md` only (no `reciters_index.json` output — that file is dropped per D8) | 0 | open |
| `.github/workflows/sync-dataset.yml` | Drop the `--build-inspector-segments` step entirely; per-verse audio dataset build still runs but reads from `<bucket>/published/<slug>/` rather than git checkout | 1 | open |
| `.github/workflows/update-reciters.yml` | Read state + catalog from bucket via `huggingface_hub`; trigger on `repository_dispatch reciter.completed` + `reciter.catalog_changed` + 30-min cron | 1 | open |
| `.github/workflows/release.yml` | Read data from `<bucket>/published/<slug>/` via `huggingface_hub`; trigger on `repository_dispatch reciter.completed` | 6 | open |
| `inspector/services/peaks.py` | Add `Cache-Control: public, max-age=31536000, immutable; ETag: <hash>` headers to `/api/seg/segment-peaks` and `/api/seg/peaks` responses (peaks routes are hash-keyed, immutable is fine here) | 1 | open |
| `inspector/services/peaks.py` cache dir | Use `INSPECTOR_CACHE_DIR/<slug>/peaks/` (not the existing `inspector/.cache/...` repo-relative path); ephemeral on `/tmp` in deployed | 1 | open |
| Inspector segment-shard responses (Flask routes for `/api/seg/data/<slug>/...`) | `Cache-Control: public, max-age=86400` (1 day; NOT `immutable` per D3 — content can change on re-edits) | 1 | open |
| `inspector/services/save.py` validators-as-libraries | After every save, call `validate_segments` and `validate_edit_history` as library functions; surface findings inline | 5 | open |
| `inspector/services/catalog.py` validators-as-libraries | After every catalog write, call `validate_audio` (URL reachability) library; surface findings inline | 6 | open |

## 4. New code

| Path | Purpose | Phase | Status |
|---|---|---|---|
| `inspector/services/hf_bucket.py` | Mount path resolver, atomic-write helper for the bucket, direct-`huggingface_hub.upload_file()` wrapper for state JSON + audit append + catalog write (bypasses mount flush window for durability); ~50 LoC | 0 | open |
| `inspector/services/state.py` | State machine + JSON file persistence + audit append; sole writer of `<bucket>/state/reciter_state.json`. Per-slug `threading.Lock` for write serialization. Asserts `GUNICORN_WORKERS == 1` at boot. Pydantic models in `scripts/lib/schemas/` validate at the boundary. | 0 | open |
| `inspector/services/catalog.py` | Catalog state-machine-style writer for `<bucket>/catalog/reciter_catalog.json`; mirrors state.py pattern (validate → atomic upload_file → audit append). Rejects mutations to immutable `slug`, `reciter_id`. Vocab additions (`riwayat`, `styles`, `audio_sources`) handled here. | 0 | open |
| `inspector/services/data_dir.py` | Per-mode data dir resolver: local returns `{INSPECTOR_DATA_DIR}/data/recitation_segments/{slug}/`; deployed returns flat `{INSPECTOR_BUCKET_MOUNT}/wip/{slug}/` for in-flight or `{INSPECTOR_BUCKET_MOUNT}/published/{slug}/` for completed | 5 | open |
| `inspector/services/github_dispatch.py` | Fire `repository_dispatch` events to GitHub via `INSPECTOR_GITHUB_DISPATCH_TOKEN`; ~30 LoC | 6 | open |
| `inspector/services/hf_jobs.py` | Enqueue HF Jobs via API (only `timestamps-refresh` in v2); persist `timestamps_job_id` on the state row for the dashboard to surface. No in-memory polling map. | 6 | open |
| `inspector/services/publish.py` | Orchestrate publish event synchronously: state transition + in-bucket `wip/<slug>/` → `published/<slug>/` move/copy + dispatch + 1 timestamps job enqueue | 6 | open |
| `inspector/services/auth.py` | HF OAuth login/callback/logout; self-contained signed-cookie session (Flask `itsdangerous`) — no server-side session record per D11 | 3 | open |
| `inspector/services/access.py` | Sole-writer for `<bucket>/access/inspector_roles.json`; in-memory cache hydrated at startup + replaced on every write; admin grant/revoke/update endpoints; emits `access.*` audit events | 3 | open |
| `scripts/lib/schemas/` | Pydantic models for `state`, `catalog`, `audit`, `edit_history` shapes; used by `services/*.py` for runtime validation + schema-version handling | 0 | open |
| `inspector/routes/admin.py` (or extend existing) | Admin endpoints (v2 ship list): claim force-release, claim reassign, force-set-state (narrow allowed pairs), publish, send-back, discard/undiscard, catalog edit/add, vocab add | 3, 5, 6 | open |
| `inspector/routes/internal.py` | `/api/internal/job-completed` (Bearer-auth via `INSPECTOR_JOB_CALLBACK_SECRET`). No `/api/internal/inspector-event` per D14, D17. | 6 | open |
| `inspector/routes/static_data.py` | Flask static route for `/api/static/qpc_hafs.json.gz`, `/api/static/digital_khatt_v2_script.json.gz`, etc. with `Cache-Control: immutable`. No audio catalog file (D7). | 1 | open |
| `scripts/seed_state.py` | Generate `<bucket>/state/reciter_state.json` from on-disk file presence per state-mgmt §3 mapping rules. JSON output, not SQL. Run at v2 cutover. | 0 | open |
| `scripts/seed_catalog.py` | Generate `<bucket>/catalog/reciter_catalog.json` from existing `data/reciters_index.json` + per-reciter manifest `_meta` blocks + `data/{riwayat,sources,styles}.json`. JSON output, not SQL. Includes `vocab.audio_sources` rows. | 0 | open |
| `scripts/upload_inspector.sh` | Selective rsync into Space repo + frontend build + commit/push to HF Space (no audio-catalog build step) | 1 | open |
| `scripts/jobs/timestamps_refresh.py` | The one HF Job entry point: read `<bucket>/published/<slug>/detailed.json` → call MFA Aligner Space → write TS shards under `<bucket>/published/<slug>/timestamps/<chapter>.json` → POST job-completed | 6 | open |
| `scripts/jobs/bucket_hygiene.py` | Library-call sweep across all reciters in the bucket: validate_segments, validate_audio, validate_edit_history, validate_timestamps. Outputs report.json + report.md for the workflow to consume. | 6 | open |
| `scripts/lib/admin_audit.py` | Read audit log from bucket; query helpers for dashboard. No `verify_chain()` (chain dropped per D12). | 1 | open |
| `scripts/lib/replay_audit.py` | Rebuild `reciter_state.json` from `audit/<YYYY>-<MM>.jsonl` partitions; disaster recovery | 0 | open |
| `scripts/validate_reciter_state.py` | Pydantic-based schema validation for state JSON; runs inside Inspector after every transition + as a CI smoke test | 0 | open |
| `scripts/validate_reciter_catalog.py` | Pydantic-based schema validation for catalog JSON; CLI wrapper for ad-hoc maintainer use | 0 | open |
| `<bucket>/access/inspector_roles.json` (NOT in repo) | Consolidated owners + maintainers. `hf_user_id` canonical, `login` display, `removed_at` soft-delete. Bootstrapped via hand-uploaded seed at Phase 0; Inspector sole writer thereafter. See [`inspector-state-management.md`](inspector-state-management.md) §9. | 0 | open |
| `.github/workflows/inspector-deploy.yml` | Selective Space upload on push to `main` (prod) or `dev` (dev Space) | 1 | open |
| `.github/workflows/inspector-jobs-deploy.yml` | Selective rsync to `hetchyy/inspector-jobs-image` HF Space repo (Docker SDK, paused) on push to `scripts/jobs/**` or `scripts/lib/**`. HF builds the image; Jobs pull via `hf://spaces/hetchyy/inspector-jobs-image:latest`. **Not GHCR.** | 6 | open |
| `.github/workflows/bucket-data-hygiene.yml` | Weekly scheduled + manual-dispatch validators sweep across the bucket; opens GH issue for CRITICAL findings; surfaces in admin dashboard (D18) | 6 | open |

## 5. Doc amendments triggered by code changes

These need updating *when* the code change lands.

| Doc / file | Trigger | Action | Status |
|---|---|---|---|
| `CLAUDE.md` mention of `find_segments_pr.py` | When `find_segments_pr.py` is deleted (Phase 6) | Drop the reference; update the "ground truth" paragraph; remove `data/{riwayat,sources,styles}.json` references; remove `data/audio/` references | open |
| `.claude/skills/quranic-universal-audio/references/automations.md` | When workflows are consolidated (Phases 0, 1, 6) | Update workflow inventory; remove `pr-assignee-sync.yml`, `find_segments_pr.py`, `bot-create-pr.yml`, `bot-comment.yml`, `issue-commands.yml`, `segments-pr-merged.yml`, `validate-segments-pr.yml`, `forward-to-inspector.yml`; add `inspector-deploy.yml`, `inspector-jobs-deploy.yml`, `bucket-data-hygiene.yml` | open |
| `.claude/skills/quranic-universal-audio/references/hpc-and-requests.md` | When slug-rules-only identity convention adopted (Phase 0) | Update branch naming references — drop `reciter/<slug>` branch convention. Reciter Requests Space is being decommissioned; new requests are GH issues with the body marker `<!-- reciter-task: slug=... schema=1 -->` (D17) | open |
| `.claude/skills/quranic-universal-audio/references/validators.md` | When edit-history schema simplified (Phase 5) and validators become libraries (Phase 5–6) | Update `validate_edit_history.py` description (drop file-hash, drop genesis); document the libraries-called-from-services pattern; document `bucket-data-hygiene.yml` | open |
| `.claude/skills/segments-extraction/SKILL.md` | When `find_segments_pr.py` is deleted (Phase 6) | Update PR-resolution narrative — there are no per-reciter PRs in v2 | open |
| `inspector/CLAUDE.md` | When deployed mode lands (Phase 1+) | Add deployed-mode operational notes; clarify two-mode policy from §1 of this registry; document HF bucket mount; document JSON state file (not SQLite) | open |
| `data/README.md` | When migration completes (Phase 1) | Document the slim `data/` (D8) — only static files remain; vocab + reciters + audio info live in the bucket catalog | open |
| `process-requests` skill (if exists in `.claude/skills/`) | When v2 is live (Phase 6) | Document the v2 flow: GH issue body marker → maintainer admin add via `POST /api/admin/catalog/add`; CLI is for maintainer-only ops against the bucket | open |
| `docs/hf_dataset_card.md` | (no longer triggered by Inspector — dataset namespace `inspector/segments/<slug>/` is dropped per D4) | n/a | n/a |

## 6. Open questions consolidated

Pulled from "Open questions" sections across the design docs. Items resolved by the canonical decisions D1–D19 are dropped from this list.

| Question | Source | Decision gate | Status |
|---|---|---|---|
| Anonymous viewing of in-flight reciters | [`inspector-deployment-plan.md`](inspector-deployment-plan.md) Open questions | Default yes (transparency); flip later if maintainers prefer; reads flow through Flask either way (D4) | open |
| CDN front for Inspector (Cloudflare free vs HF edge vs none) | [`inspector-deployment-plan.md`](inspector-deployment-plan.md) Open questions | Phase 1 measurement; even more relevant since all reciter reads go through Flask now (D4) | open |
| Bucket mount backend (NFS Advanced vs FUSE) | [`inspector-data-storage.md`](inspector-data-storage.md) §3 | NFS Advanced default; revisit only if `edit_history.jsonl` appends feel slow | open |
| Bucket archive policy (keep vs delete after publish) | [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) §10 | Default archive for first month; delete thereafter; configurable via env var | open |
| `detailed.json` size cap revisit | [`inspector-data-storage.md`](inspector-data-storage.md) §10 | Monitor; raise to 25 MB if growth observed | open |
| Multi-Space replica scale-out | [`inspector-deployment-plan.md`](inspector-deployment-plan.md) Open questions | Defer until measured; in-process mutex moves to bucket-side optimistic concurrency or Redis (D6 in deferred) | open |
| Persistent volume for caches (vs ephemeral) | [`inspector-data-storage.md`](inspector-data-storage.md) §10 | Defer; bucket itself is persistent so the cache is the only ephemeral concern | open |
| Per-source manifest schema variation (some carry `_timing`, some don't) | (raised this cycle) | Surface as `timing_supported` flag on each `vocab.audio_sources[]` entry; catalog write rejects mismatched payloads | open |
| Re-edits of completed reciters | [`inspector-state-management.md`](inspector-state-management.md) §4 | Deferred (D5 in deferred); admin re-claim re-creates `wip/<slug>/` from `published/<slug>/` snapshot | open, deferred |
| HF Jobs API stability | [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) §10 | Monitor; only one job per publish in v2 (D16) limits blast radius | open |
| `INSPECTOR_GITHUB_DISPATCH_TOKEN` rotation cadence | (raised this cycle) | Quarterly; failure backstopped by 30-min cron in `update-reciters.yml` | open |
| Bucket roles file durability vs in-memory cache | [`inspector-admin-perms.md`](inspector-admin-perms.md) §3 | Sole-writer pattern + per-write `upload_file()` makes cache correct-by-construction; no force-refresh endpoint needed | closed |

## 7. Audit checklist

Run before marking each phase complete.

### Phase 0 — Foundation

- [ ] One private bucket per env created (dev + prod) — single bucket each, not two (D5)
- [ ] Bucket state JSON manually seeded via `seed_state.py` (~15 reciters) per state-mgmt §3 mapping rules
- [ ] Catalog JSON seeded via `seed_catalog.py` (includes `vocab.riwayat`, `vocab.styles`, `vocab.audio_sources`, `reciters[]`, `aliases[]`)
- [ ] `<bucket>/access/inspector_roles.json` exists with at least 2 owners (hand-seeded at bootstrap); `hf_user_id` populated
- [ ] `inspector/services/hf_bucket.py` lands (mount + direct-upload helpers)
- [ ] `inspector/services/state.py` lands; passes unit tests for every transition in the matrix; `GUNICORN_WORKERS == 1` startup assertion in place; per-slug `threading.Lock` works
- [ ] `inspector/services/catalog.py` lands; rejects mutations to immutable fields; vocab-add path covered
- [ ] `scripts/lib/schemas/` pydantic models cover state, catalog, audit, edit_history
- [ ] `list_reciters.py` rewritten to read state + catalog JSON from bucket via `huggingface_hub`
- [ ] `build_reciter.py --build-manifest` rewritten to read identity from catalog JSON
- [ ] All §2 entries tagged Phase 0 are `done`

### Phase 1 — Read-only deploy

- [ ] All §2/§3/§4 entries tagged Phase 1 are `done`
- [ ] gunicorn (`-w 1 --threads 16`, not werkzeug) running in deployed Space
- [ ] `GUNICORN_WORKERS == 1` startup assertion verified
- [ ] Image discipline check passes (no `recitation_segments/`, `timestamps/`, `audio_catalog.json.gz`, `reciters_index.json`, `riwayat/sources/styles.json`, `audio/` in `/app/data`)
- [ ] Slim `data/` baked: only `surah_info.json`, `qpc_hafs.json`, `digital_khatt_v2_script.json`, `phoneme_sub_costs.json` (no `inspector_roles.json` — bucket-resident now)
- [ ] Browser → Flask → bucket round-trip serves completed reciter shards (no HF dataset hop, per D4)
- [ ] `Cache-Control: public, max-age=86400` on segment-shard responses; `immutable` only on hash-keyed peaks routes
- [ ] Smoke tests in [`inspector-deploy-runbook.md`](inspector-deploy-runbook.md) §6 Phase 1 pass
- [ ] §5 doc amendments triggered by Phase 1 work are landed

### Phase 2 — Bucket reads for in-flight

- [ ] In-flight reciter renders via bucket mount (flat `wip/<slug>/` layout, no nested `data/recitation_segments/<slug>/`)
- [ ] One-shot migration of current in-flight reciter data into dev bucket complete (flat layout)
- [ ] Edit affordances hidden globally (`editingDisabled` store wired)
- [ ] Smoke tests Phase 2 pass

### Phase 3 — HF OAuth + claim flow

- [ ] HF OAuth + self-contained signed-cookie session live; ≤ 3 clicks for new contributors, 1 for returning
- [ ] State writes via direct `huggingface_hub.upload_file()` (durable; bypasses mount flush window)
- [ ] `<bucket>/audit/<YYYY>-<MM>.jsonl` populated correctly (no `prev_hash` chain — D12)
- [ ] In-process per-slug single-writer lock works
- [ ] All claim-ownership checks use `hf_user_id`, NOT `login`
- [ ] Smoke tests Phase 3 pass

### Phase 4 — Read-only admin dashboard + role resolution

- [ ] `<bucket>/access/inspector_roles.json` resolution working (in-memory cache replaced on every Inspector write); grant/revoke/update admin endpoints functional; `access.*` audit events appearing
- [ ] `/admin` route 404s for non-maintainers; renders for maintainer+
- [ ] System health, all-reciters, stalled-reciters, recent-events panels render
- [ ] Audit log tail viewable in dashboard

### Phase 5 — Writes

- [ ] Volunteer round-trips an edit on a `_test_*` reciter
- [ ] `INSPECTOR_FORCE_FLUSH_ON_SAVE=1` is the default (verified)
- [ ] Backend restart mid-session is harmless (bucket has last-durable state)
- [ ] All §2/§3 entries tagged Phase 5 are `done`
- [ ] New `edit_history.jsonl` lines have no `file_hash_after`, no genesis record; have `actor: {hf_user_id, login_at_time, role}` per batch (D13)
- [ ] Validators called as libraries from `services/save.py` after every relevant write
- [ ] Publish endpoint live (state transition + in-bucket move only; full fan-out fires in Phase 6)

### Phase 6 — Publish pipeline + cleanup

- [ ] All §2/§3/§4 entries tagged Phase 6 are `done`
- [ ] HF Jobs image published as `hetchyy/inspector-jobs-image` Space (Docker SDK, paused); not GHCR
- [ ] `forward-to-inspector.yml` workflow deleted (D17); `INSPECTOR_FORWARD_SECRET` removed from Space + GH Actions
- [ ] Publishing a `_test_*` reciter end-to-end: in-bucket move + GH dispatch + 1 timestamps job → GitHub Release, RECITERS.md PR all complete within 10–15 min
- [ ] Decommissioned workflows (`bot-create-pr.yml`, `bot-comment.yml`, `issue-commands.yml`, `pr-assignee-sync.yml`, `validate-segments-pr.yml`, `segments-pr-merged.yml`, `forward-to-inspector.yml`, `find_segments_pr.py`) produced no runs in a 7-day observation window
- [ ] **Pre-drop audit (Phase 1):** before deleting `data/reciters_index.json`, grep all repos / Spaces / external scripts for any read of the file. Confirmed read sites either migrated to `huggingface_hub.hf_hub_download(<bucket>/catalog/reciter_catalog.json)` or accept the drop. The Reciter Requests Space is being decommissioned in v2 cleanup so its dependency dies with it.
- [ ] `bucket-data-hygiene.yml` running on schedule; CRITICAL findings produce GH issue + admin dashboard signal
- [ ] Skill audit: re-grep `.claude/skills/` for `find_segments_pr`, `pr-assignee-sync`, `file_hash_after`, `bot-only attribution`, `repository_dispatch reciter.claimed`, `update-reciter-state.yml`, `forward-to-inspector`, `inspector_owners.json`, `inspector_maintainers.json`, `INSPECTOR_FORWARD_SECRET`, `inspector/segments/<slug>/`, `audio_catalog.json.gz`, `reciter_state.sqlite`, `reciter_catalog.sqlite`, `reciters_index.json`, `riwayat.json`, `sources.json`, `styles.json`, `data/audio/` — all should be either gone or documented as v1-archive references
- [ ] Contributor docs point at the website as primary path
- [ ] Local Docker is documented as the offline / maintainer fallback in `inspector/CLAUDE.md`
- [ ] §5 doc amendments triggered by Phase 6 work are landed

## 8. Post-deploy measurements appendix

To be filled in after Phase 1 has been live ≥ 1 week. Each measurement replaces an estimate in [`inspector-data-storage.md`](inspector-data-storage.md) §11.

| Measurement | Estimated | Measured | Source |
|---|---|---|---|
| Cold p95 — completed reciter end-to-end (browser → Flask → bucket → render) | < 800 ms | _tbd_ | _tbd_ |
| Validator cold cost on CPU-basic | 300–600 ms | _tbd_ | _tbd_ |
| Bucket mount cold-fetch p95 (5 MB JSON) | 100–300 ms | _tbd_ | _tbd_ |
| Bucket mount flush window (write to bucket-visible) | 2–30 s | _tbd_ | _tbd_ |
| 24h memory growth (workers w/ `--max-requests` recycling) | flat | _tbd_ | _tbd_ |
| Image size (final) | 250–350 MB | _tbd_ | _tbd_ |
| HF bucket storage sustained working set (`wip/` + `published/` + `_archive/`) | ~600 MB-1.5 GB | _tbd_ | _tbd_ |
| HF Job: timestamps-refresh wall time | ~5–10 min/reciter | _tbd_ | _tbd_ |
| HF Jobs monthly cost at full scale (~10 publishes/month, 1 job each) | < $0.50 | _tbd_ | _tbd_ |

## 9. v1 → v2 architectural delta summary

For quick reference. Anything not listed: unchanged.

| Concept | v1 | v2 |
|---|---|---|
| User identity | GitHub OAuth (App user-to-server) | HF OAuth (`hf_oauth: true`); self-contained signed-cookie session (D11) |
| Repo-write authority | GitHub App installation token | Space-level `INSPECTOR_HF_TOKEN` (HF user token) |
| Per-reciter under-review reads | github-fetch service + LRU + parsed-cache + single-flight | Bucket via Inspector backend (NFS Advanced, native local cache) |
| Per-reciter under-review writes | Git Data API blob+tree+commit+ref → PR branch | Direct `huggingface_hub.upload_file()` to bucket; per-slug `threading.Lock` (D2) |
| Scratch dir | `/tmp/inspector-scratch/<slug>/` per active reviewer | None — bucket IS the working surface |
| Inspector frontend read source for completed reciters | HF dataset CDN (`inspector/segments/<slug>/`) | Same bucket, `published/<slug>/`, served via Flask (D4) |
| State store | `data/reciter_state.json` (GitHub repo) | **`<bucket>/state/reciter_state.json`** (private bucket; D2 — no SQLite) |
| State writer | `update-reciter-state.yml` workflow | Inspector backend `services/state.py` (sole writer) |
| Audit trail | `git log -- data/reciter_state.json` + `data/admin_audit.jsonl` | `<bucket>/audit/<YYYY>-<MM>.jsonl` (append-only, partitioned monthly, no `prev_hash` chain — D12) |
| Catalog store | `data/reciters_index.json` + per-reciter `data/audio/<cat>/<src>/<slug>.json` + `data/{riwayat,sources,styles}.json` | **`<bucket>/catalog/reciter_catalog.json`** (single consolidated JSON: vocab + reciters + aliases — D6) |
| Audio URL info | Per-reciter manifest files baked into image | URL templates + `url_overrides` in `reciter_catalog.json` (D6, D7); no `audio_catalog.json.gz` baked |
| Roles file | n/a (GitHub team) | **Single `<bucket>/access/inspector_roles.json`** (consolidated owners + maintainers; `hf_user_id` canonical; soft-delete; Inspector sole writer) |
| Admin override | `state.manual_override` wildcard (any → any) | **Discrete named operations** — `admin.force_set_state` (narrow allowed pairs only), plus `claim.force_released`, `claim.reassigned`, `reciter.merge_rejected` for v2. No wildcard. (D15) |
| Lifecycle of `discarded` reciters | New 8th state value with schema bump | **`visibility = 'discarded'` orthogonal to lifecycle** (no schema bump; round-trip preserves position; only `'public'` and `'discarded'` ship in v2) |
| `ready_for_merge` | Separate state | **`marked_ready: bool` column on `under_review`** (D1) |
| Bucket WIP layout | `wip/<slug>/data/recitation_segments/<slug>/...` | **Flat `wip/<slug>/...`** (D3) |
| Completed reciter URL | `inspector/segments/<slug>/<file>.gz` on HF dataset | **`<bucket>/published/<slug>/<file>` on the bucket**, served via Flask; no `v<n>/` versioning, no `CURRENT` pointer (D3) |
| Per-reciter PR branches | `reciter/<slug>` | None |
| Per-edit GitHub commit attribution | `<id>+<login>@users.noreply.github.com` author + bot committer | None — attribution is in audit log |
| Per-reciter merge gate | Maintainer clicks Squash & Merge on github.com | Maintainer clicks Publish in Inspector admin dashboard |
| Snapshot to HF dataset on publish | `segments-pr-merged.yml` → `--build-inspector-segments` | None — publish is in-bucket `wip/<slug>/` → `published/<slug>/` move/copy in-process (D4, D16) |
| Maintainer team identity | GitHub team `<org>/inspector-maintainers` (App team-API call) | `<bucket>/access/inspector_roles.json` (single consolidated file on the private bucket) |
| Reciter request intake | Reciter Requests Space → `repository_dispatch` → `update-reciter-state.yml` | GH issue with body marker `<!-- reciter-task: slug=... schema=1 -->`; maintainer adds catalog row via `POST /api/admin/catalog/add` (D17). Reciter Requests Space is being decommissioned; Inspector-native intake is deferred. |
| `forward-to-inspector.yml` | Bridge from Space to Inspector | Deleted (D17) |
| Internal endpoint auth | HMAC over body, two secrets, `_PREV` rotation | Single `INSPECTOR_JOB_CALLBACK_SECRET` Bearer; constant-time compare; no `_PREV` (D14) |
| Cache-invalidate webhook | Required (`segments-pr-merged.yml` POSTs to Inspector) | Not needed (no cache; bucket serves live state) |
| Validator workflows | `validate-segments-pr.yml`, `validate-edit-history.yml` PR-gates | Validators are libraries called by Inspector services on every relevant write; scheduled `bucket-data-hygiene.yml` sweeps the whole bucket (D18) |
| GitHub App permissions | Contents/Pull-requests/Issues/Members write | None (App removed) |
| GitHub PAT used by Inspector | None | `INSPECTOR_GITHUB_DISPATCH_TOKEN` (small, only fires `repository_dispatch`) |
| Code in `services/github_*.py` (deleted in v2) | ~450 LoC | 0 |
| New code in `services/state.py + catalog.py + hf_bucket.py + auth.py + role.py + publish.py + hf_jobs.py + github_dispatch.py + data_dir.py + schemas/` | n/a | ~700 LoC |

## 10. Reference docs and schema doc generation — deferred

**Not in v2 scope.** See [`../../schema-docs.md`](../../schema-docs.md) for the post-v2 plan covering:

- Schema placement: single cross-consumer location at `scripts/lib/schemas/` (used by Inspector, dataset builder, GH Actions, training pipeline) — no inspector-internal tier in v2.
- `scripts/gen_schemas.py` generator for JSON Schema, rendered MD, TS types
- CI drift gate
- VS Code JSON-schema association
- Trigger conditions to start (v2 stable + actual contributor/frontend pain)

What v2 ships at the schema layer:

- **Pydantic models** for `state`, `catalog`, `audit`, `edit_history` shapes — used by `services/*.py` for runtime validation. Lives at `scripts/lib/schemas/`. ~150 LoC total for Phase 0.
- Nothing else. No generator, no rendered MD per schema, no TS types, no `.vscode` config, no audit script, no per-phase doc landing gate.

What's already at `docs/reference/inspector/`:

- `README.md`, `state-machine.md`, `schemas/README.md` exist as **pre-v2 sketches**. They are reference-quality but not authoritative — code is the contract while v2 is in flight. The schema-docs plan revisits them when it lands; until then they're best-effort design exploration.

**Why deferred:** v2 is on the critical path. Pydantic models used directly by services is enough until a second contributor or the frontend feels actual drift pain. Solving "the next person needs nice rendered docs" before that person exists is premature optimization.
