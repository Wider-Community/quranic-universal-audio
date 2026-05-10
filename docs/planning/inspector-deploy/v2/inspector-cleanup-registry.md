# Inspector Cleanup Registry (v2)

Running ledger for the inspector deployment migration. Each item has a phase tag and a status. Edit as you go — strike out completed items with a commit reference.

This is **not** a design doc. For *why* something is being done, see [`inspector-deployment-plan.md`](inspector-deployment-plan.md), [`inspector-data-storage.md`](inspector-data-storage.md), [`inspector-state-management.md`](inspector-state-management.md), [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md). For deferred items see [`inspector-deferred.md`](inspector-deferred.md). This doc tracks *what's actually done* vs *what should not exist anymore*.

**Reference docs and schema-doc generation are NOT in v2 scope.** v2 ships pydantic models for runtime validation only. The hand-written reference docs and the auto-generation system (JSON Schema, TS types, rendered MD) land later under [`../../schema-docs.md`](../../schema-docs.md). Anything currently under `docs/reference/inspector/` is a pre-v2 sketch, not authoritative.

Status legend: `open` / `wip` / `done` (with commit short SHA in `[brackets]` once landed).

## 1. Mode policy

The Inspector supports **two modes**, not three. Speculative third-mode hybrids are an explicit "do not add."

| Mode | Filesystem access | Audio proxy | TS source | Validation panel | Audio manifests | State store | Invocation |
|---|---|---|---|---|---|---|---|
| `local` | Yes (repo `data/`) | On | Local files | On | Individual `data/audio/<cat>/<src>/<slug>.json` | Local SQLite at `data/reciter_state.sqlite` (gitignored; for local testing only) | `python3 inspector/app.py` OR `docker compose up` (bind-mounts data) |
| `deployed` | No (HF dataset / bucket mount) | Off | HF CDN | Off | Consolidated `audio_catalog.json.gz` from `/app/data` | `<bucket>/state/reciter_state.sqlite` (private metadata bucket); `<bucket>/catalog/reciter_catalog.sqlite` (public data bucket) | HF Space build |

`local Python` and `local Docker` are two ways to invoke the same `local` mode — the Dockerfile is single-image-two-profile via env vars (`INSPECTOR_TS_SOURCE`, `INSPECTOR_AUDIO_PROXY_ENABLED`, `INSPECTOR_DATA_DIR`, `INSPECTOR_QUA_DATA_PATH`, `INSPECTOR_BUCKET_MOUNT`). Code branches only on these env vars, never on "is this Docker?".

**Forbidden combinations** (do not add code paths to support):

- Docker without bind-mount (no longer reachable; deploy mode covers it)
- `INSPECTOR_TS_SOURCE=huggingface` with `INSPECTOR_AUDIO_PROXY_ENABLED=1` (incoherent — deployed mode skips audio proxy)
- Any third "staging" tier between local and deployed — staging is a separate Space tracking `dev` branch, same code, different secrets, different bucket
- github-fetch (deleted in v2 — bucket mount replaces all under-review reads)
- Git Data API write path (deleted in v2 — bucket mount handles writes)
- Scratch dir as separate concept (deleted in v2 — bucket mount IS the scratch)

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
| `.github/workflows/validate-segments-pr.yml` | No segments PRs to validate; in-Inspector validation runs at save + at publish-time HF Job | 6 | open |
| `routes/timestamps.py::ts_validate` (excluded from deployed image only — kept for local) | No validation panel surface in deployed mode | 1 | open |
| `routes/audio_proxy.py` (excluded from deployed image only — kept for local) | Audio plays browser→origin direct in deployed mode | 1 | open |
| `app.py::serve_audio` (excluded from deployed image only — kept for local) | Same as audio proxy | 1 | open |
| `validators/validate_edit_history.py::check_file_hash` | File-hash chain dropped (data-storage §7) | 5 | open |
| `validators/validate_edit_history.py::check_genesis_record` | Genesis record dropped (no longer anchors anything) | 5 | open |
| `inspector/utils/io.py::file_sha256` | Last caller is the file-hash chain | 5 | open |
<!-- duplicate removed; covered above next to discover_ts_reciters note -->
| `inspector/services/save.py::backup_file()` calls in deployed save path | Audit log is the recovery; .bak files clutter the bucket | 5 | open |
| `inspector/services/save.py::_persist_and_record` `file_hash_after` write | Field dropped | 5 | open |
<!-- removed: _append_revert_record does not exist in save.py (verified) -->
| `inspector/services/save.py` revert record `file_hash_after` write (any path that writes it) | Field dropped | 5 | open |
<!-- removed: discover_ts_reciters already deleted (verified). METADATA_PEEK_BYTES const still present, see next line. -->
| `inspector/config.py::METADATA_PEEK_BYTES` | Now unused after `discover_ts_reciters` removal — delete the constant | 1 | open |
| `seg_save_chart` route + `analysis/*.png` writes | Debug-only, no UI surface | 5 | open |
| `inspector/app.py` ThreadPoolExecutor startup preload of timestamps | Lazy-load via TS HF static; no eager preload (verify already removed in current code per app.py:171 comment) | 1 | open |
| `data/audio/<cat>/<src>/<slug>.json` from Docker image (kept in repo, excluded from image via `.dockerignore`) | Replaced by `audio_catalog.json.gz` | 1 | open |

## 3. Code modifications

| File / area | Change | Phase | Status |
|---|---|---|---|
| `inspector/Dockerfile` ENV defaults | Flip to `INSPECTOR_DATA_DIR=/app/data`, `INSPECTOR_QUA_DATA_PATH=/app/data` (was `/data`); add `INSPECTOR_AUDIO_PROXY_ENABLED=0`, `INSPECTOR_CACHE_DIR=/tmp/inspector-cache`, `INSPECTOR_BUCKET_MOUNT=/data/inspector-bucket`, `INSPECTOR_PARSED_CACHE_BYTES=134217728` | 1 | open |
| `inspector/Dockerfile` COPY list | Extend from current 3 static files to all static reference files (incl. `inspector_roles.json`, `audio_catalog.json.gz`) — single consolidated roles file, not two | 1 | open |
| `inspector/Dockerfile` CMD | `app.run()` → `gunicorn -k gthread -w 1 --threads 16 --max-requests 5000 --max-requests-jitter 500 --timeout 60 --graceful-timeout 30`. **`-w 1` is load-bearing** — every in-memory structure assumes single-process. App startup must assert workers==1 | 1 | open |
| Root `.dockerignore` | Create at repo root with the exclusion list from data-storage §7 | 1 | open |
| `inspector/services/cache.py` `_seg` dict | Replace with parsed seg cache layer keyed `(slug, "detailed_parsed")`, sized by `INSPECTOR_PARSED_CACHE_BYTES` | 1 | open |
| `inspector/services/data_loader.py::load_timestamps` | Gate behind `INSPECTOR_TS_SOURCE=local`; deployed mode browser-fetches HF CDN direct | 1 | open |
| `inspector/services/data_loader.py::load_audio_urls` | Gate behind `INSPECTOR_TS_SOURCE=local`; deployed mode reads from `audio_catalog.json.gz` | 1 | open |
| `inspector/routes/timestamps.py::config` (`/api/ts/config`) | Extend response with `inspector_shard_url_template`, `globals_url_template` (same-origin in deployed, HF in local) | 1 | open |
| `inspector/services/save.py` data path resolution | Use `services/data_dir.py::resolve(slug)` helper instead of hard-coded `INSPECTOR_DATA_DIR/data/recitation_segments/<slug>`. In deployed mode this returns `<INSPECTOR_BUCKET_MOUNT>/wip/<slug>/...` | 5 | open |
| `.github/scripts/build_reciter.py` | Add `--build-inspector-segments <slug>` build target; mirror existing `--build-timestamps` and `--build-segments` patterns | 1 | open |
| `.github/scripts/build_reciter.py --build-manifest` | Read identity from catalog (GitHub) and state from bucket via `huggingface_hub` | 0 | open |
| `.github/scripts/list_reciters.py` | Read identity from catalog (GitHub) and state from bucket via `huggingface_hub` | 0 | open |
| `.github/workflows/sync-dataset.yml` | Add `--build-inspector-segments` step (one-shot bootstrap + per-completion in HF Job); move per-verse audio dataset build to HF Job | 1 | open |
| `.github/workflows/update-reciters.yml` | Read state from bucket via `huggingface_hub`; trigger on `repository_dispatch reciter.completed` + 30-min cron | 1 | open |
| `.github/workflows/release.yml` | Read data from bucket + HF dataset via `huggingface_hub`; trigger on `repository_dispatch reciter.completed` | 6 | open |
| `inspector/services/peaks.py` | Add `Cache-Control: public, max-age=31536000, immutable; ETag: <hash>` headers to `/api/seg/segment-peaks` and `/api/seg/peaks` responses | 1 | open |
| `inspector/services/peaks.py` cache dir | Use `INSPECTOR_CACHE_DIR/<slug>/peaks/` (not the existing `inspector/.cache/...` repo-relative path); ephemeral on `/tmp` in deployed | 1 | open |

## 4. New code

| Path | Purpose | Phase | Status |
|---|---|---|---|
| `inspector/services/hf_bucket.py` | Mount path resolver, atomic-write helper for the bucket, direct-`upload_file` wrapper for state SQLite + audit append (bypasses mount flush window for durability); ~50 LoC | 0 | open |
| `inspector/services/state.py` | State machine + SQLite persistence + audit append + `prev_hash` chain; sole writer of `<bucket>/state/reciter_state.sqlite`. Asserts `GUNICORN_WORKERS == 1` at boot. | 0 | open |
| `inspector/services/catalog.py` | Catalog state-machine-style writer for `<bucket>/catalog/reciter_catalog.sqlite`; mirrors state.py pattern (validate → SQL transaction → audit append). Rejects mutations to immutable `slug`, `reciter_id`. | 0 | open |
| `inspector/services/data_dir.py` | Per-mode data dir resolver: local returns `{INSPECTOR_DATA_DIR}/data/recitation_segments/{slug}/`; deployed returns flat `{INSPECTOR_BUCKET_MOUNT}/wip/{slug}/` | 5 | open |
| `inspector/services/github_dispatch.py` | Fire `repository_dispatch` events to GitHub via `INSPECTOR_GITHUB_DISPATCH_TOKEN`; ~30 LoC | 6 | open |
| `inspector/services/hf_jobs.py` | Enqueue HF Jobs via API; track in-memory `job_id → (slug, type, fired_at)` for admin dashboard | 6 | open |
| `inspector/services/publish.py` | Orchestrate publish event: state transition + fan-out trigger | 6 | open |
| `inspector/services/auth.py` | HF OAuth login/callback/logout; session record management | 3 | open |
| `inspector/services/role.py` | Resolve role from `inspector_owners.json` + `inspector_maintainers.json` (60 s cache) | 3 | open |
| `inspector/frontend/src/services/segments_hf_client.ts` | Browser fetch from HF CDN for completed-reciter Inspector data | 1 | open |
| `inspector/routes/admin.py` (or extend existing) | Admin endpoints: claim overrides, publish, send-back, manual override, discard, catalog edit, pipeline trigger, rerun job | 3, 5, 6 | open |
| `inspector/routes/internal.py` | `/api/internal/job-completed`, `/api/internal/inspector-event` (HMAC-auth) | 6 | open |
| `inspector/routes/static_data.py` | Flask static route for `/api/static/audio_catalog.json.gz`, `/api/static/qpc_hafs.json.gz`, etc. with `Cache-Control: immutable` | 1 | open |
| `scripts/build_audio_catalog.py` | Walk `data/audio/**/*.json`, drop `_timing`, compact + gzip into `data/audio_catalog.json.gz` (~6 MB) | 1 | open |
| `scripts/seed_state.py` | Generate `seed.sql` for `reciter_state.sqlite` from on-disk file presence per state-mgmt §3 mapping rules. Run at v2 cutover. | 0 | open |
| `scripts/seed_catalog.py` | Generate `seed.sql` for `reciter_catalog.sqlite` from `data/reciters_index.json` + per-reciter manifest `_meta`. Includes `audio_sources` rows. | 0 | open |

| `scripts/upload_inspector.sh` | Selective rsync into Space repo + frontend build + audio catalog + commit/push to HF Space | 1 | open |
| `scripts/jobs/snapshot_bucket_to_dataset.py` | HF Job entry point: download bucket → gzip → upload to dataset (writes versioned `inspector/segments/<slug>/v<n>/` + updates `CURRENT` pointer) → archive bucket | 6 | open |
| `scripts/jobs/timestamps_refresh.py` | HF Job entry point: read bucket → call MFA Aligner Space → write TS shards to dataset | 6 | open |
| `scripts/jobs/build_per_verse_audio.py` | HF Job entry point: existing `build_reciter.py` main path, reads from bucket | 6 | open |
| `scripts/lib/admin_audit.py` | Read audit log from bucket; query helpers for dashboard; `verify_chain()` walks `prev_hash` chain | 1 | open |
| `scripts/lib/replay_audit.py` | Rebuild `reciter_state.sqlite` from `audit/<YYYY>-<MM>.jsonl` partitions; disaster recovery + chain verification | 0 | open |
| `scripts/validate_reciter_state.py` | Schema validation for state SQLite; runs inside Inspector after every transition + as a CI smoke test | 0 | open |
| `scripts/validate_reciter_catalog.py` | Schema validation for catalog SQLite; runs in `validate-catalog.yml` on PRs touching the seed scripts or `audio_sources` data | 0 | open |
| `data/inspector_roles.json` | Consolidated owners + maintainers (replaces two separate files). `hf_user_id` canonical, `login` display, `removed_at` soft-delete. CODEOWNERS-gated. | 0 | open |
| `.github/workflows/inspector-deploy.yml` | Selective Space upload on push to `main` (prod) or `dev` (dev Space) | 1 | open |
| `.github/workflows/inspector-deploy-dev.yml` | Same as above but for `dev` branch / dev Space | 1 | open |
| `.github/workflows/forward-to-inspector.yml` | Receives `reciter.alignment_requested` from Reciter Requests Space; HMAC-POSTs to Inspector `/api/internal/inspector-event` | 6 | open |
| `.github/workflows/inspector-jobs-deploy.yml` | Selective rsync to `hetchyy/inspector-jobs-image` HF Space repo (Docker SDK, paused) on push to `scripts/jobs/**` or `scripts/lib/**`. HF builds the image; Jobs pull via `hf://spaces/hetchyy/inspector-jobs-image:latest`. **Not GHCR.** | 6 | open |
| `.github/workflows/validate-catalog.yml` | Run `validate_reciter_catalog.py` on PRs touching `data/reciter_catalog.json` | 0 | open |

## 5. Doc amendments triggered by code changes

These need updating *when* the code change lands.

| Doc / file | Trigger | Action | Status |
|---|---|---|---|
| `CLAUDE.md` mention of `find_segments_pr.py` | When `find_segments_pr.py` is deleted (Phase 6) | Drop the reference; update the "ground truth" paragraph | open |
| `.claude/skills/quranic-universal-audio/references/automations.md` | When workflows are consolidated (Phases 0, 1, 6) | Update workflow inventory; remove `pr-assignee-sync.yml`, `find_segments_pr.py`, `bot-create-pr.yml`, `bot-comment.yml`, `issue-commands.yml`, `segments-pr-merged.yml`, `validate-segments-pr.yml`; add `inspector-deploy.yml`, `forward-to-inspector.yml`, `inspector-jobs-image.yml`, `validate-catalog.yml` | open |
| `.claude/skills/quranic-universal-audio/references/hpc-and-requests.md` | When slug-rules-only identity convention adopted (Phase 0) | Update branch naming references — drop `reciter/<slug>` branch convention. Reciter Requests intake is unchanged in v2 | open |
| `.claude/skills/quranic-universal-audio/references/validators.md` | When edit-history schema simplified (Phase 5) | Update `validate_edit_history.py` description (drop file-hash, drop genesis) | open |
| `.claude/skills/segments-extraction/SKILL.md` | When `find_segments_pr.py` is deleted (Phase 6) | Update PR-resolution narrative — there are no per-reciter PRs in v2 | open |
| `inspector/CLAUDE.md` | When deployed mode lands (Phase 1+) | Add deployed-mode operational notes; clarify two-mode policy from §1 of this registry; document HF bucket mount | open |
| `data/README.md` | When `audio_catalog.json.gz` lands in image (Phase 1) | Note the catalog file alongside other static data files | open |
| `process-requests` skill (if exists in `.claude/skills/`) | When v2 is live (Phase 6) | Document the v2 flow: Inspector website is the contribution surface; CLI is for maintainer-only ops | open |
| `docs/hf_dataset_card.md` | When inspector segment shards land (Phase 1) | Document the `inspector/segments/<slug>/...` namespace | open |

## 6. Open questions consolidated

Pulled from "Open questions" sections across the design docs.

| Question | Source | Decision gate | Status |
|---|---|---|---|
| Anonymous viewing of in-flight reciters | [`inspector-deployment-plan.md`](inspector-deployment-plan.md) Open questions | Default yes (transparency); flip later if maintainers prefer | open |
| CDN front for Inspector (Cloudflare free vs HF edge vs none) | [`inspector-deployment-plan.md`](inspector-deployment-plan.md) Open questions | Phase 1 measurement | open |
| Bucket mount backend (NFS Advanced vs FUSE) | [`inspector-data-storage.md`](inspector-data-storage.md) §3 | NFS Advanced default; revisit only if `edit_history.jsonl` appends feel slow | open |
| Bucket archive policy (keep vs delete after publish) | [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) §11 | Default archive for first month; delete thereafter; configurable via env var | open |
| `detailed.json` size cap revisit | [`inspector-data-storage.md`](inspector-data-storage.md) §10 | Monitor; raise to 25 MB if growth observed | open |
| Multi-Space replica scale-out | [`inspector-deployment-plan.md`](inspector-deployment-plan.md) Open questions, [`inspector-data-storage.md`](inspector-data-storage.md) §10 | Defer until measured; in-process mutex moves to bucket-side optimistic concurrency or Redis | open |
| Persistent volume for caches (vs ephemeral) | [`inspector-data-storage.md`](inspector-data-storage.md) §10 | Defer; bucket itself is persistent so the cache is the only ephemeral concern | open |
| `_meta` block back-compat in inspector shards published to HF | (raised this cycle) | Verify schema_version + clients-ignore-unknown-fields contract works | open |
| Per-source manifest schema variation (some carry `_timing`, some don't) | (raised this cycle) | `build_audio_catalog.py` handles by stripping; do not propagate | open |
| Re-edits of completed reciters | [`inspector-state-management.md`](inspector-state-management.md) §4 | Deferred to Phase 6+; admin re-claim re-creates bucket entry from dataset snapshot | open, deferred |
| HF Jobs API stability | [`inspector-publish-pipeline.md`](inspector-publish-pipeline.md) §11 | Monitor; fallback to publisher Space if API issues | open |
| `INSPECTOR_GITHUB_DISPATCH_TOKEN` rotation cadence | (raised this cycle) | Quarterly; failure backstopped by 30-min cron in `update-reciters.yml` | open |
| `inspector_owners.json` snapshot vs live for emergency role revocation | [`inspector-admin-perms.md`](inspector-admin-perms.md) §13 | 60 s cache + force-refresh endpoint covers it; no further work needed | open |

## 7. Audit checklist

Run before marking each phase complete.

### Phase 0 — Foundation

- [ ] HF buckets created (dev + prod, both data + metadata = 4 buckets total)
- [ ] **Spike** — SQLite WAL on NFS Advanced mount: 100 rapid writes + concurrent reader + container kill mid-write retains consistent file (Phase 0 acceptance gate)
- [ ] Bucket state SQLite manually seeded via `seed_state.py` (~15 reciters) per state-mgmt §3 mapping rules
- [ ] Catalog SQLite seeded via `seed_catalog.py` (includes `audio_sources` rows for ~6 known sources)
- [ ] `data/inspector_roles.json` exists with at least 2 owners; `hf_user_id` populated
- [ ] `inspector/services/hf_bucket.py` lands (mount + direct-upload helpers)
- [ ] `inspector/services/state.py` lands; passes unit tests for every transition in the matrix; `GUNICORN_WORKERS == 1` startup assertion in place
- [ ] `inspector/services/catalog.py` lands; rejects mutations to immutable fields
- [ ] `list_reciters.py` rewritten to read state + catalog SQLite via `huggingface_hub`; regenerated `reciters_index.json` is byte-equivalent (modulo new fields) to pre-migration
- [ ] `build_reciter.py --build-manifest` rewritten to read identity from catalog SQLite
- [ ] `validate-catalog.yml` workflow lands (validates `seed_catalog.py` output + `audio_sources` data)
- [ ] All §2 entries tagged Phase 0 are `done`
- [ ] Pydantic models for state, catalog, audit shapes used by `services/state.py` + `services/catalog.py` for runtime validation (no doc generation — see [`../../schema-docs.md`](../../schema-docs.md))

### Phase 1 — Read-only deploy

- [ ] All §2/§3/§4 entries tagged Phase 1 are `done`
- [ ] gunicorn (`-w 1 --threads 16`, not werkzeug) running in deployed Space
- [ ] `GUNICORN_WORKERS == 1` startup assertion verified
- [ ] Image discipline check passes (no `data/recitation_segments/`, etc., in `/app/data`)
- [ ] `audio_catalog.json.gz` baked in, ~6 MB
- [ ] HF dataset has `inspector/segments/<slug>/v1/...` for currently-eligible reciters + `CURRENT` pointer files
- [ ] Smoke tests in [`inspector-deploy-runbook.md`](inspector-deploy-runbook.md) §6 Phase 1 pass
- [ ] §5 doc amendments triggered by Phase 1 work are landed

### Phase 2 — Bucket reads for in-flight

- [ ] In-flight reciter renders via bucket mount (flat `wip/<slug>/` layout)
- [ ] One-shot migration of current in-flight reciter data into dev bucket complete (flat layout, not nested)
- [ ] Edit affordances hidden globally (`editingDisabled` store wired)
- [ ] Smoke tests Phase 2 pass

### Phase 3 — HF OAuth + claim flow

- [ ] HF OAuth + claim flow live; ≤ 3 clicks for new contributors, 1 for returning
- [ ] State writes transactional (SQLite WAL + direct-upload for durability)
- [ ] `<bucket>/state/audit/<YYYY>-<MM>.jsonl` populated correctly with `prev_hash` chain
- [ ] In-process single-writer mutex per slug works
- [ ] All claim-ownership checks use `hf_user_id`, NOT `login`
- [ ] Smoke tests Phase 3 pass

### Phase 4 — Read-only admin dashboard + role resolution

- [ ] `data/inspector_roles.json` resolution working (60s cache + force-refresh endpoint)
- [ ] `/admin` route 404s for non-maintainers; renders for maintainer+
- [ ] System health, all-reciters, stalled-reciters, recent-events panels render
- [ ] Audit log `verify_chain()` runs in dashboard

### Phase 5 — Writes

- [ ] Volunteer round-trips an edit on a `_test_*` reciter
- [ ] `INSPECTOR_FORCE_FLUSH_ON_SAVE=1` is the default (verified)
- [ ] Backend restart mid-session is harmless (bucket has last-durable state)
- [ ] All §2/§3 entries tagged Phase 5 are `done`
- [ ] New `edit_history.jsonl` lines have no `file_hash_after`, no genesis record
- [ ] Edit-history schema refinement landed (validation_summary shape, op patch dialect, per-record `record_hash`, `actor` column)
- [ ] Force-claim parallel-write scenario tested; `force_assignee_*` survives Space restart
- [ ] Publish endpoint live (state transition only; fan-out fires in Phase 6)

### Phase 6 — Publish pipeline + cleanup

- [ ] All §2/§3/§4 entries tagged Phase 6 are `done`
- [ ] HF Jobs image published to GHCR (or HF Spaces fallback)
- [ ] `forward-to-inspector.yml` workflow live; Reciter Requests Space's `alignment_requested` events flow through correctly (until D2 deprecates the Space)
- [ ] Publishing a `_test_*` reciter end-to-end: bucket → dataset (`v1/` shards + `CURRENT` pointer), timestamps, audio dataset, GitHub Release, RECITERS.md PR all complete within 15 min
- [ ] Decommissioned workflows (`bot-create-pr.yml`, `bot-comment.yml`, `issue-commands.yml`, `pr-assignee-sync.yml`, `validate-segments-pr.yml`, `segments-pr-merged.yml`, `find_segments_pr.py`) produced no runs in a 7-day observation window
- [ ] Skill audit: re-grep `.claude/skills/` for `find_segments_pr`, `pr-assignee-sync`, `file_hash_after`, `bot-only attribution`, `repository_dispatch reciter.claimed`, `update-reciter-state.yml` — should be either gone or documented as v1-archive references
- [ ] Contributor docs point at the website as primary path
- [ ] Local Docker is documented as the offline / maintainer fallback in `inspector/CLAUDE.md`
- [ ] §5 doc amendments triggered by Phase 6 work are landed

## 8. Post-deploy measurements appendix

To be filled in after Phase 1 has been live ≥ 1 week. Each measurement replaces an estimate in [`inspector-data-storage.md`](inspector-data-storage.md) §11.

| Measurement | Estimated | Measured | Source |
|---|---|---|---|
| Cold p95 — completed reciter end-to-end (browser → HF → render) | < 800 ms | _tbd_ | _tbd_ |
| Validator cold cost on CPU-basic | 300–600 ms | _tbd_ | _tbd_ |
| Bucket mount cold-fetch p95 (5 MB JSON) | 100–300 ms | _tbd_ | _tbd_ |
| Bucket mount flush window (write to bucket-visible) | 2–30 s | _tbd_ | _tbd_ |
| 24h memory growth (workers w/ `--max-requests` recycling) | flat | _tbd_ | _tbd_ |
| Image size (final) | 300–400 MB | _tbd_ | _tbd_ |
| `audio_catalog.json.gz` size | ~6 MB | _tbd_ | _tbd_ |
| `inspector/segments/<slug>/...` total HF storage at full bootstrap | ~1–2 GB | _tbd_ | _tbd_ |
| HF bucket storage sustained working set | ~300 MB | _tbd_ | _tbd_ |
| HF Job: snapshot-bucket-to-dataset wall time | ~30 s/reciter | _tbd_ | _tbd_ |
| HF Job: timestamps-refresh wall time | ~5–10 min/reciter | _tbd_ | _tbd_ |
| HF Jobs monthly cost at full scale (~10 publishes/month) | < $1 | _tbd_ | _tbd_ |

## 9. v1 → v2 architectural delta summary

For quick reference. Anything not listed: unchanged.

| Concept | v1 | v2 |
|---|---|---|
| User identity | GitHub OAuth (App user-to-server) | HF OAuth (`hf_oauth: true`) |
| Repo-write authority | GitHub App installation token | Space-level `INSPECTOR_HF_TOKEN` (HF user token) |
| Per-reciter under-review reads | github-fetch service + LRU + parsed-cache + single-flight | bucket mount (NFS Advanced, native local cache) |
| Per-reciter under-review writes | Git Data API blob+tree+commit+ref → PR branch | bucket file write (mount handles flush 2–30 s) |
| Scratch dir | `/tmp/inspector-scratch/<slug>/` per active reviewer | None — bucket mount IS the working surface |
| Debounce loop | Inspector code, 30 s inactivity / 5 min hardcap | Mount handles; same window characteristics |
| State store | `data/reciter_state.json` (GitHub repo) | **`<bucket>/state/reciter_state.sqlite`** (SQLite WAL on private metadata bucket) |
| State writer | `update-reciter-state.yml` workflow | Inspector backend `services/state.py` (sole writer, transactional via SQLite WAL) |
| Audit trail | `git log -- data/reciter_state.json` + `data/admin_audit.jsonl` | `<bucket>/state/audit/<YYYY>-<MM>.jsonl` (append-only, partitioned monthly, `prev_hash` chain) |
| Catalog store | n/a (per-reciter audio manifests + `reciters_index.json`) | **`<bucket>/catalog/reciter_catalog.sqlite`** (Inspector-managed, audio_sources factored into separate table) |
| Roles file | n/a (GitHub team) | **Single `data/inspector_roles.json`** (consolidated owners + maintainers; `hf_user_id` canonical; soft-delete) |
| Admin override | `state.manual_override` wildcard (any → any) | **Discrete named operations** — `admin.force_set_state` (narrow allowed pairs), `admin.force_clear_assignee`, `admin.force_unmark_ready`, etc. No wildcard. |
| Lifecycle of `discarded` reciters | New 8th state value with schema bump | **`visibility = 'discarded'` orthogonal to lifecycle** (no schema bump; round-trip preserves position) |
| `ready_for_merge` | Separate state | **`marked_ready: bool` column on `under_review`** (one column, two flips, three transitions removed) |
| Bucket WIP layout | `wip/<slug>/data/recitation_segments/<slug>/...` | **Flat `wip/<slug>/...`** (data_dir.resolve handles indirection) |
| Completed reciter URL | `inspector/segments/<slug>/<file>.gz` | **Versioned: `inspector/segments/<slug>/v<n>/<file>.gz`** + `CURRENT` pointer (re-edit forward-compat) |
| Per-reciter PR branches | `reciter/<slug>` | None |
| Per-edit GitHub commit attribution | `<id>+<login>@users.noreply.github.com` author + bot committer | None — attribution is in audit log |
| Per-reciter merge gate | Maintainer clicks Squash & Merge on github.com | Maintainer clicks Publish in Inspector admin dashboard |
| Snapshot to HF dataset | `segments-pr-merged.yml` → `--build-inspector-segments` | Publish HF Job |
| Maintainer team identity | GitHub team `<org>/inspector-maintainers` (App team-API call) | `data/inspector_roles.json` (single consolidated file) |
| Reciter request intake | Reciter Requests Space → `repository_dispatch` → `update-reciter-state.yml` | Same Space → `repository_dispatch` → `forward-to-inspector.yml` → POST to Inspector → state transition |
| Cache-invalidate webhook | Required (`segments-pr-merged.yml` POSTs to Inspector) | Not needed (no cache; bucket serves live state) |
| GitHub App permissions | Contents/Pull-requests/Issues/Members write | None (App removed) |
| GitHub PAT used by Inspector | None | `INSPECTOR_GITHUB_DISPATCH_TOKEN` (small, only fires `repository_dispatch`) |
| Code in `services/github_*.py` (deleted in v2) | ~450 LoC | 0 |
| New code in `services/state.py + catalog.py + hf_bucket.py + auth.py + role.py + publish.py + hf_jobs.py + github_dispatch.py + data_dir.py` | n/a | ~700 LoC |

## 10. Reference docs and schema doc generation — deferred

**Not in v2 scope.** See [`../../schema-docs.md`](../../schema-docs.md) for the post-v2 plan covering:

- Tier model for schema placement (`scripts/lib/schemas/` for cross-component, `inspector/schemas/` for inspector-internal, etc.)
- `scripts/gen_schemas.py` generator for JSON Schema, rendered MD, TS types
- CI drift gate
- VS Code JSON-schema association
- Trigger conditions to start (v2 stable + actual contributor/frontend pain)

What v2 ships at the schema layer:

- **Pydantic models** for `state`, `catalog`, `audit`, `edit_history` shapes — used by `services/*.py` for runtime validation. Lives at `inspector/schemas/`. ~150 LoC total for Phase 0.
- Nothing else. No generator, no rendered MD per schema, no TS types, no `.vscode` config, no audit script, no per-phase doc landing gate.

What's already at `docs/reference/inspector/`:

- `README.md`, `state-machine.md`, `schemas/README.md` exist as **pre-v2 sketches**. They are reference-quality but not authoritative — code is the contract while v2 is in flight. The schema-docs plan revisits them when it lands; until then they're best-effort design exploration.

**Why deferred:** v2 is on the critical path. Pydantic models used directly by services is enough until a second contributor or the frontend feels actual drift pain. Solving "the next person needs nice rendered docs" before that person exists is premature optimization.
