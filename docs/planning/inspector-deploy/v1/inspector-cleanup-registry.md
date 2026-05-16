# Inspector Cleanup Registry

Running ledger for the inspector deployment migration. Each item has a phase tag and a status. Edit as you go — strike out completed items with a commit reference.

This is **not** a design doc. For *why* something is being done, see [`inspector-deployment-plan.md`](inspector-deployment-plan.md), [`inspector-data-storage.md`](inspector-data-storage.md), [`inspector-state-management.md`](inspector-state-management.md). This doc tracks *what's actually done* vs *what should not exist anymore*.

Status legend: `open` / `wip` / `done` (with commit short SHA in `[brackets]` once landed).

## 1. Mode policy

The Inspector supports **two modes**, not three. Speculative third-mode hybrids are an explicit "do not add."

| Mode | Filesystem access | Audio proxy | TS source | Validation panel | Audio manifests | Invocation |
|---|---|---|---|---|---|---|
| `local` | Yes (repo `data/`) | On | Local files | On | Individual `data/audio/<cat>/<src>/<slug>.json` | `python3 inspector/app.py` OR `docker compose up` (bind-mounts data) |
| `deployed` | No (HF / github-fetch / scratch) | Off | HF CDN | Off | Consolidated `audio_catalog.json.gz` from `/app/data` | HF Space build |

`local Python` and `local Docker` are two ways to invoke the same `local` mode — the Dockerfile is single-image-two-profile via env vars (`INSPECTOR_TS_SOURCE`, `INSPECTOR_AUDIO_PROXY_ENABLED`, `INSPECTOR_DATA_DIR`, `INSPECTOR_QUA_DATA_PATH`). Code should branch only on these env vars, never on "is this Docker?".

**Forbidden combinations** (do not add code paths to support):
- Docker without bind-mount (no longer reachable; deploy mode covers it)
- `INSPECTOR_TS_SOURCE=huggingface` with `INSPECTOR_AUDIO_PROXY_ENABLED=1` (incoherent — deployed mode skips audio proxy)
- Any third "staging" tier between local and deployed — staging is a separate Space tracking `dev` branch, same code, different secrets

## 2. Code deletions

| File / symbol | Reason | Phase | Status |
|---|---|---|---|
| `inspector/app.py:180` `app.run()` → gunicorn-gthread CMD in Dockerfile | werkzeug dev server is not production-grade; mandatory before public deploy | 1 | open |
| `.github/scripts/find_segments_pr.py` | Replaced by `gh pr list --head reciter/<slug>` after slug-first identity convention | 6 | open |
| `.github/workflows/pr-assignee-sync.yml` | State workflow mirrors assignment to issue + PR in one shot | 0 | open |
| `routes/timestamps.py::ts_validate` (excluded from deployed image only — kept for local) | No validation panel surface in deployed mode | 1 | open |
| `routes/audio_proxy.py` (excluded from deployed image only — kept for local) | Audio plays browser→origin direct in deployed mode | 1 | open |
| `app.py::serve_audio` (excluded from deployed image only — kept for local) | Same as audio proxy | 1 | open |
| `validators/validate_edit_history.py::check_file_hash` | File-hash chain dropped (data-storage §7) | 5b | open |
| `validators/validate_edit_history.py::check_genesis_record` | Genesis record dropped (no longer anchors anything) | 5b | open |
| `inspector/utils/io.py::file_sha256` | Last caller is the file-hash chain | 5b | open |
| `inspector/config.py::METADATA_PEEK_BYTES` | Audio-source 512-byte peek replaced by state file | 1 | open |
| `inspector/services/save.py::backup_file()` calls in deployed save path | Git history is recovery; .bak files clutter PR branches | 5b | open |
| `inspector/services/save.py::_persist_and_record` `file_hash_after` write | Field dropped | 5b | open |
| `inspector/services/save.py::_append_revert_record` `file_hash_after` write | Field dropped | 5b | open |
| `inspector/services/data_loader.py::discover_ts_reciters` 512-byte audio_source peek | Audio-source carried in state file | 1 | open |
| `seg_save_chart` route + `analysis/*.png` writes | Debug-only, no UI surface | 5a | open |
| `inspector/app.py` ThreadPoolExecutor startup preload of timestamps | Lazy-load via TS HF static; no eager preload (verify already removed in current code per app.py:171 comment) | 1 | open |
| `data/audio/<cat>/<src>/<slug>.json` from Docker image (kept in repo, excluded from image via `.dockerignore`) | Replaced by `audio_catalog.json.gz` | 1 | open |

## 3. Code modifications

| File / area | Change | Phase | Status |
|---|---|---|---|
| `inspector/Dockerfile` ENV defaults | Flip to `INSPECTOR_DATA_DIR=/app/data`, `INSPECTOR_QUA_DATA_PATH=/app/data` (was `/data`); add `INSPECTOR_AUDIO_PROXY_ENABLED=0`, `INSPECTOR_CACHE_DIR`, `INSPECTOR_SCRATCH_DIR`. Local `docker-compose.yml` overrides back to `/data` + bind mount | 1 | open |
| `inspector/Dockerfile` COPY list | Extend from current 3 static files to all 10 static reference files + `audio_catalog.json.gz` | 1 | open |
| `inspector/Dockerfile` CMD | `app.run()` → `gunicorn -k gthread -w 2 --threads 8 --max-requests 5000 --max-requests-jitter 500 --timeout 60 --graceful-timeout 30` | 1 | open |
| Root `.dockerignore` | Create at repo root (current `inspector/.dockerignore` is dead weight when build context is repo root) with the exclusion list from data-storage §7 | 1 | open |
| `inspector/services/cache.py` `_seg` dict | Replace with parsed-cache layer keyed `(slug, file, ref)`, sized by `INSPECTOR_PARSED_CACHE_BYTES` | 1 | open |
| `inspector/services/data_loader.py::load_timestamps` | Gate behind `INSPECTOR_TS_SOURCE=local`; deployed mode browser-fetches HF CDN direct | 1 | open |
| `inspector/services/data_loader.py::load_audio_urls` | Gate behind `INSPECTOR_TS_SOURCE=local`; deployed mode reads from `audio_catalog.json.gz` (or kills the loader entirely if browser does the lookup) | 1 | open |
| `inspector/routes/timestamps.py::config` (`/api/ts/config`) | Extend response with `inspector_shard_url_template`, `globals_url_template` (same-origin in deployed mode, HF in local) | 1 | open |
| `.github/scripts/build_reciter.py` | Add `--build-inspector-segments <slug>` build target; mirror `--build-timestamps` and `--build-segments` patterns; hash-diff against `manifest.reciters.<slug>._build.inspector_shard_hashes` | 1 | open |
| `.github/workflows/sync-dataset.yml` | Add `build_reciter.py --build-inspector-segments <slug>` step + `inspector_only` workflow_dispatch input | 1 | open |
| `.github/workflows/segments-pr-merged.yml` | POST `/api/internal/cache-invalidate?slug=<slug>` after merge | 6 | open |
| `.github/workflows/validate-segments-pr.yml` | Skip on commits whose subject contains `[wip]` | 6 | open |
| `.github/workflows/update-reciters.yml` | Cadence reduction (every 30 min instead of every push); regenerate from state file rather than computing from labels | 6 | open |
| `inspector/services/peaks.py` | Add `Cache-Control: public, max-age=31536000, immutable; ETag: <hash>` headers to `/api/seg/segment-peaks` and `/api/seg/peaks` responses | 1 | open |
| `inspector/services/peaks.py` cache dir | Use `INSPECTOR_CACHE_DIR/<slug>/peaks/` (not the existing `inspector/.cache/...` repo-relative path); ephemeral on `/tmp` in deployed | 1 | open |
| `scripts/lib/segments_shards.py` | Verify the slim shard schema is documented somewhere — cross-link from data-storage §2 | 1 | open |

## 4. New code

| Path | Purpose | Phase | Status |
|---|---|---|---|
| `inspector/services/github_fetch.py` | LRU + parsed cache + ETag + 30s TTL ±10% jitter + single-flight, scoped to `reciter/<slug>` refs only | 1 | open |
| `inspector/services/scratch.py` | Per-active-reviewer scratch dir lifecycle (create, materialise via github-fetch, mark dirty/clean, flush, destroy) | 5a | open |
| `inspector/services/github_commit.py` | Git Data API multi-file commit (blobs → tree → commit → ref update) with author=reviewer, committer=App | 5a | open |
| `inspector/frontend/src/services/segments_hf_client.ts` | Browser fetch from HF CDN for completed-reciter Inspector data | 1 | open |
| `inspector/routes/internal.py` (or extend existing) | `/api/internal/cache-invalidate?slug=<slug>`, `/api/internal/cache-invalidate-all`, `/api/internal/cache-stats` — all gated by `INSPECTOR_INTERNAL_SECRET` | 1 | open |
| `scripts/build_audio_catalog.py` | Walk `data/audio/**/*.json`, drop `_timing`, compact + gzip into `data/audio_catalog.json.gz` (~6 MB) | 1 | open |
| `scripts/test_github_app_auth.py` | Local sanity check that App ID + private key produces a valid installation token + GETs the repo | 1 | open |
| `.github/workflows/pr-uniqueness.yml` | Fail PR if any other open PR already touches `data/recitation_segments/<slug>/` | 6 | open |
| `.github/workflows/inspector-deploy.yml` | On `inspector/**` push to main, trigger HF Space rebuild (or rely on Space's auto-build from its repo push — decide based on the upload pipeline shape) | 6 | open |
| `.github/workflows/update-reciter-state.yml` | Sole writer of `data/reciter_state.json`; handles all `repository_dispatch` event types | 0 | open |
| Upload aliases (`upload-inspector-dev.sh`, `upload-inspector.sh`) | Gitignored from main repo; rsync selective tree into Space repo, build frontend, build audio catalog, commit + push to HF Space | 1 | open |

## 5. Doc amendments triggered by code changes

These are second-order — they need updating *when* the code change lands, not before.

| Doc / file | Trigger | Action | Status |
|---|---|---|---|
| `CLAUDE.md` mention of `find_segments_pr.py` | When `find_segments_pr.py` is deleted (Phase 6) | Drop the reference; update the "ground truth" paragraph | open |
| `.claude/skills/quranic-universal-audio/references/automations.md` | When workflows are consolidated (Phases 0, 6) | Update workflow inventory; remove `pr-assignee-sync.yml`, `find_segments_pr.py`; add `update-reciter-state.yml`, `pr-uniqueness.yml`, `inspector-deploy.yml` | open |
| `.claude/skills/quranic-universal-audio/references/hpc-and-requests.md` | When slug-first identity convention adopted (Phase 0) | Update branch naming, PR title format, marker registry references | open |
| `.claude/skills/quranic-universal-audio/references/validators.md` | When edit-history schema simplified (Phase 5b) | Update `validate_edit_history.py` description (drop file-hash, drop genesis) | open |
| `.claude/skills/segments-extraction/SKILL.md` | When `find_segments_pr.py` is deleted (Phase 6) and slug-first lands (Phase 0) | Update PR-resolution narrative | open |
| `inspector/CLAUDE.md` | When deployed mode lands (Phase 1+) | Add deployed-mode operational notes; clarify two-mode policy from §1 of this registry | open |
| `data/README.md` | When `audio_catalog.json.gz` lands in image (Phase 1) | Note the catalog file alongside other static data files | open |
| `process-requests` skill (if exists in `.claude/skills/`) | When commit attribution exception lands (Phase 5a) | Document the exception: "human edits → user attribution; pipeline artifacts → bot attribution" | open |
| Publish-pipeline doc — new | When `--build-inspector-segments` lands and the build/CI side has real surface area to describe | Create `inspector-publish-pipeline.md` covering `sync-dataset.yml` extension, `build_reciter.py` build targets, HF dataset layout, manifest catalog, cache invalidation contracts. Defer until the work has actually landed (don't shuffle outlines pre-implementation) | open, deferred |

## 6. Open questions consolidated

Pulled from "Open questions" sections across the design docs so the next decision-cycle has a single agenda.

| Question | Source | Decision gate | Status |
|---|---|---|---|
| Anonymous viewing of in-review PRs | [`inspector-deployment-plan.md`](inspector-deployment-plan.md) Open questions | Default yes (transparency); flip later if maintainers prefer | open |
| CDN front for Inspector (Cloudflare free vs HF edge vs none) | [`inspector-deployment-plan.md`](inspector-deployment-plan.md) Open questions | Phase 1 measurement — defer until real cold-start traffic data | open |
| `detailed.json` size cap revisit | [`inspector-data-storage.md`](inspector-data-storage.md) §10 | Monitor; raise to 25 MB if growth observed | open |
| Range-partial shard fetches for pathological chapters | TS tab plan (since superseded — TS tab already implemented) | Almost certainly not worth the complexity; flagged | open, likely no |
| Persistent volume for scratch (vs ephemeral) | [`inspector-data-storage.md`](inspector-data-storage.md) §10 | Defer until restart-loss is actually painful | open, deferred |
| Frontend memory profile on mobile | new (raised this cycle) | Defer until measurement | open, deferred |
| `_meta` block back-compat in inspector shards published to HF | new (raised this cycle) | Verify schema_version + clients-ignore-unknown-fields contract works | open |
| Per-source manifest schema variation (some carry `_timing`, some don't) | new (raised this cycle) | `build_audio_catalog.py` handles by stripping; do not propagate the variation downstream | open |

## 7. Audit checklist

Run before marking each phase complete.

### Phase 0
- [ ] Slug-first identity convention adopted across all referenced workflows
- [ ] `data/reciter_state.json` and `data/reciter_catalog.json` exist with seeded content
- [ ] `update-reciter-state.yml` is sole writer of state file
- [ ] All §2/§3 entries tagged Phase 0 are `done`
- [ ] §5 doc amendments triggered by Phase 0 work are landed

### Phase 1
- [ ] All §2/§3/§4 entries tagged Phase 1 are `done`
- [ ] gunicorn (not werkzeug) running in deployed Space
- [ ] Image discipline check passes (no `data/recitation_segments/`, etc., in `/app/data`)
- [ ] `audio_catalog.json.gz` baked in, ~6 MB
- [ ] HF dataset has `inspector/segments/<slug>/...` for currently-eligible reciters
- [ ] Single-flight verified by burst test (10 cold concurrent → 1 GitHub fetch)
- [ ] Smoke tests in [`inspector-deploy-runbook.md`](inspector-deploy-runbook.md) §6 Phase 1 pass
- [ ] §5 doc amendments triggered by Phase 1 work are landed

### Phase 2
- [ ] Under-review reciter renders via github-fetch
- [ ] Edit affordances hidden globally (`editingDisabled` store wired)
- [ ] Smoke tests Phase 2 pass

### Phase 3
- [ ] OAuth + claim flow live; ≤3 clicks for new contributors, 1 for returning
- [ ] State file updates within ~10s of claim
- [ ] In-memory single-writer lock works
- [ ] Smoke tests Phase 3 pass

### Phase 5a
- [ ] Volunteer round-trips an edit on a `_test_*` reciter
- [ ] Author attribution correct (`<id>+<login>@users.noreply.github.com`)
- [ ] Backend restart mid-session is harmless
- [ ] All §2/§3/§4 entries tagged Phase 5a are `done`

### Phase 5b
- [ ] All §2/§3 entries tagged Phase 5b are `done`
- [ ] New commits land without `file_hash_after`
- [ ] CI `validate_edit_history.py` passes
- [ ] No `.bak` files appear in PR branches

### Phase 6
- [ ] All §2/§3/§4 entries tagged Phase 6 are `done`
- [ ] Skill audit: re-grep `.claude/skills/` for `find_segments_pr`, `pr-assignee-sync`, `file_hash_after`, `bot-only attribution` — should be either gone or documented as exceptions
- [ ] Contributor docs point at the website as primary path
- [ ] Local Docker is documented as the offline / maintainer fallback in `inspector/CLAUDE.md`
- [ ] §5 doc amendments triggered by Phase 6 work are landed

## 8. Post-deploy measurements appendix

To be filled in after Phase 1 has been live ≥ 1 week. Each measurement replaces an estimate in [`inspector-data-storage.md`](inspector-data-storage.md) §11.

| Measurement | Estimated | Measured | Source |
|---|---|---|---|
| Cold p95 — completed reciter end-to-end (browser → HF → render) | < 800 ms | _tbd_ | _tbd_ |
| Validator cold cost on CPU-basic | 300–600 ms | _tbd_ | _tbd_ |
| github-fetch cold latency Space → GitHub raw | 200–400 ms | _tbd_ | _tbd_ |
| Single-flight collapse rate under 10-concurrent burst | 1 upstream | _tbd_ | _tbd_ |
| 24h memory growth (workers w/ `--max-requests` recycling) | flat | _tbd_ | _tbd_ |
| GitHub rate budget consumption / hour at peak | < 5% | _tbd_ | _tbd_ |
| Image size (final) | 300–400 MB | _tbd_ | _tbd_ |
| `audio_catalog.json.gz` size | ~6 MB | _tbd_ | _tbd_ |
| `inspector/segments/<slug>/...` total HF storage at full bootstrap | ~1–2 GB | _tbd_ | _tbd_ |
