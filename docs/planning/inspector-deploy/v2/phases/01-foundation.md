# Phase 1 — Foundation

> All non-deploy groundwork lands. Nothing is shipped to a public Space yet, but every refactor v2 needs is in code and the JSON state store + bucket helpers work end-to-end against the dev bucket.

**Status:** done (with deferred items — see Outcomes log)
**Depends on:** dev bucket already created (done)
**Blocks:** Phase 2

## Goal

Build the migration scaffolding so subsequent phases can move fast: per-mode data path resolver, JSON state/catalog/audit primitives, pydantic schemas, consolidated roles file, slim repo `data/`. After this phase, Inspector still runs locally as before — but the deployed-mode plumbing is in place.

## Deliverables

- [ ] `inspector/services/data_dir.py::resolve(slug)` + `list_slugs()` — per-mode data dir resolver
- [ ] Sibling-path cleanup in `inspector/services/data_loader.py` (drop the `RECITATION_SEGMENTS_PATH.parent / "surah_info.json"` walk)
- [ ] `inspector/services/segments_data.py::seg_reciters` route migrated off `RECITATION_SEGMENTS_PATH.iterdir()`
- [ ] `scripts/lib/schemas/` pydantic models for state row, catalog row, audit record, edit-history batch — **cross-consumer location** (read by Inspector, dataset builder, GH Actions, training pipeline; see [`../inspector-cleanup-registry.md`](../inspector-cleanup-registry.md) §10)
- [ ] State row schema mirrors [`../inspector-state-management.md`](../inspector-state-management.md) §2: 7 lifecycle states (`catalogued | awaiting_alignment | awaiting_review | under_review | awaiting_timestamps | released | completed`), `marked_ready: bool`, `visibility: 'public' | 'discarded'`, `assignee_hf_id`, `assignee_login`, `assignee_since`, `last_save_at`, `timestamps_job_ids: list[str]` (append-on-refresh), `revision_in_progress: RevisionContext | None` (sub-struct set on `admin.unlocked_for_revision`, cleared on re-publish; carries `unlocked_from_state`, `unlocked_at`, `unlocked_by_hf_id`, `original_assignee_hf_id`). **No `force_assignee_*`** (force-claim deferred). **No `archived` visibility** (deferred).
- [ ] Audit event schema mirrors [`../inspector-state-management.md`](../inspector-state-management.md) §4 "Shipping in v2" event list, including the access/lifecycle/admin events added with the bucket-resident roles file
- [ ] `inspector/services/state.py` — JSON file at `<bucket>/state/reciter_state.json`, per-slug `threading.Lock`, atomic-write-then-rename + `huggingface_hub.upload_file()` per write
- [ ] `inspector/services/catalog.py` — same write pattern for `<bucket>/catalog/reciter_catalog.json`; schema is authoritative in [`../../../reference/reciter-catalog.md`](../../../reference/reciter-catalog.md) (vocab + reciters + deliveries + sidecars + derived + aliases)
- [ ] `inspector/services/hf_bucket.py` — mount path resolver + direct-upload helpers
- [ ] `inspector/services/audit.py` — append to `<bucket>/audit/<YYYY>-<MM>.jsonl` via `upload_file()`
- [ ] `inspector/services/access.py` — sole-writer for `<bucket>/access/inspector_roles.json`; in-memory cache hydrated at startup + replaced on every write; bootstrap path documented in [`../inspector-state-management.md`](../inspector-state-management.md) §9
- [ ] `validators/{validate_segments,validate_audio,validate_edit_history,validate_timestamps}.py` refactored as libraries with thin CLI wrappers
- [ ] Test fixtures updated (`inspector/tests/conftest.py`, `parity/snapshot_route_baselines.py`) to monkey-patch the resolver instead of `RECITATION_SEGMENTS_PATH`
- [ ] `data/reciters_index.json` consumer audit complete; file deleted from repo
- [ ] `data/{riwayat,sources,styles}.json`, `data/audio/<cat>/<src>/<slug>.json`, `data/.audio_meta.json`, `data/.audio_durations.json` deleted from repo (data migrated into `<bucket>/catalog/...`)

**Already complete (in `.local/dedup/`, will be promoted but not in scope here):**
- Catalog seed (`reciter_catalog.json` + 864 `audio_manifest/<slug>.json` sidecars) — produced by `.local/dedup/build_catalog.py`.
- State seed — produced from corrected clusters; will be uploaded to `<bucket>/state/reciter_state.json` during cutover.
- Naming consistency pass + dedup decisions captured in `.local/dedup/naming_consistency_report.md` (with override notice) and `.local/dedup/catalog_design_critique.md`.

## Out of scope

- Anything that runs on the deployed Space (Phase 2+).
- HF OAuth, role-based gating (Phase 3).
- Frontend dual-mode for segments tab (Phase 2).
- Save flow rewiring (Phase 4).

## Acceptance criteria

- [ ] `services/state.py::transition(slug, event, actor)` round-trips against the dev bucket: every transition in the §4 matrix validates correctly; invalid transitions raise `InvalidTransition`.
- [ ] `services/catalog.py::add()` / `edit()` rejects mutations to `slug` and `reciter_id`; vocab additions append correctly.
- [ ] Concurrent writes against the same slug serialize via the per-slug `Lock`; concurrent writes across slugs run independently.
- [ ] Manual seed script run against dev bucket produces a `reciter_state.json` and `reciter_catalog.json` that round-trip through the pydantic schemas without errors.
- [ ] All four validators run as `python -m validators.validate_<name>` against either repo `data/` (local mode) or `<bucket>/...` (`--bucket` flag, downloads via `huggingface_hub`).
- [ ] `data/reciters_index.json` no longer present anywhere in the working tree, and no script under `.github/scripts/` or `scripts/` reads it (grep confirms).
- [ ] Existing local-mode Inspector still runs (`python3 inspector/app.py`) end-to-end — no regressions.

## Verification

```bash
# Schema round-trip
python -m scripts.lib.schemas.smoke    # dummy state row + catalog row + audit + edit-history batch

# Bucket round-trip (against dev bucket)
INSPECTOR_BUCKET_REPO=hetchyy/quranic-inspector-bucket-dev \
INSPECTOR_HF_TOKEN=$HF_TOKEN \
python -m inspector.services.state.smoke   # transition seed-row -> awaiting_review -> under_review -> awaiting_review

# Access bootstrap (one-shot per env; first owner only)
python -m inspector.services.access.bootstrap --hf-user-id <id> --login <login>

# Concurrency
python -m inspector.tests.parity.test_per_slug_lock

# Validators-as-libs
python -m validators.validate_segments --bucket --slug saad_al_ghamdi

# Repo discipline
test ! -f data/inspector_roles.json         # moved to bucket
test ! -f data/reciters_index.json
test ! -f data/riwayat.json
test ! -d data/audio
grep -r "reciters_index" .github/ scripts/ inspector/ validators/ && exit 1 || true
```

## Risks

- **Existing on-disk `edit_history.jsonl` files** carry old schema (genesis + `file_hash_after`). Phase 1 doesn't migrate them; readers tolerate both schemas. See `inspector-data-storage.md` §8.
- **External consumers of `reciters_index.json`** outside this repo — covered by the pre-drop audit in `cleanup-registry.md` §7 Phase 1.

## Reference

- [`inspector-data-storage.md`](../inspector-data-storage.md) §1, §2, §3 — file IO model, bucket layout, mount semantics
- [`inspector-state-management.md`](../inspector-state-management.md) §1–§5 — JSON schema, state machine, write semantics
- [`inspector-state-management.md`](../inspector-state-management.md) §3 — consolidated catalog schema
- [`inspector-cleanup-registry.md`](../inspector-cleanup-registry.md) §2, §3, §4 — deletions, modifications, new code

## Outcomes (running log)

Most of the schema, catalog, and naming work usually slotted in Phase 1 was front-loaded as **pre-execution prep** to unblock subsequent phases. Artifacts live in `.local/dedup/` (gitignored — scratch) and the v2 docs. Execution of the actual code deliverables (pydantic models, services, validator refactor) is still pending.

### Pre-execution: catalog & schema groundwork — done

**Reciter dedup + cluster reconciliation:**
- 870 source manifests audited and inventoried with channel inference per delivery
- Dual-agent dedup pass: programmatic (467 clusters via 5-pass normalization) + manual (426 clusters with Quran-reciter domain knowledge)
- 374 fully-agreed clusters; 48 membership disagreements reconciled (44 manual-merged-more, 4 over-merges split); 275 same-cluster name-choice disagreements resolved with maintainer override
- Same-channel duplicate probe via ffprobe: 14 pairs analyzed → 2 byte-identical + 1 broken qul manifest + 11 distinct-master pairs kept
- Follow-up re-probe on 2 suspicious pairs (Abdulbasit murattal, Minshawi murattal) confirmed same-recording → dropped one side each
- **Final: 864 deliveries, 422 reciter clusters, 0 slug collisions**

**Naming style guide + corrections:**
- Style guide locked in 14 axes (Al-/El-/sun-letter/Abdul-/Abdel-/honorifics/bin-lowercase/etc.) with explicit override-trail
- **41** manual cross-cluster corrections (Alfoo → Al-Foo + slug, bin lowercase, glued Abdul-/Abdel-)
- **62** Mohammed/Ahmed/Yusuf/Mahmoud universal normalizations (including surname-position appearances)
- **11** extra normalizations (Khaled→Khalid, Mansoor→Mansour, Mishari→Mishary, Adil→Adel, Khaleel→Khalil, Yassir→Yasser, Mostafa→Mustafa, Hesham→Hisham, Sayeed→Saeed, Tawfeeq→Tawfiq)
- **114 total naming corrections** applied; reciter_id + display name + member slugs rebuilt; zero collisions

**Catalog schema (v2):**
- Three-layer model: Reciter / Recording (computed group-by, not stored) / Delivery
- `source` × `channel` orthogonality (M:N at the vocab level; materialized in `derived.source_channels[]`)
- Slug convention `<reciter_id>[_<riwayah_short>][_<style_short>][_<year>]_<channel_short>[_<disambiguator>]` with `_<bitrate>k` / `_v2` / `_byayah` rules
- `vocab.recording_contexts[]` orthogonal to `vocab.styles[]` (studio/broadcast/prayer/taraweeh/mixed; null when unidentified)
- `hadr` style added; legacy `taraweeh` style migrated to `style: murattal + recording_context: taraweeh`
- Null convention adopted (`null` not `""` / `"unknown"`) across `name_ar`, `country`, `recording_context`, audio metadata
- Audio metadata split: row uniform fields (`codec`, `container`, `sample_rate_hz`, `channels`, `bitrate_mode`, `bitrate_kbps_nominal`, `total_duration_sec`, `chapter_count`) + per-chapter sidecar (`url`, `size_bytes`, `duration_sec`, `bitrate_kbps`)
- `bitrate_mode`: 4-value rollup (cbr/vbr/mixed/unknown); `bitrate_kbps_nominal: null` when mixed
- `audio_manifest_checksum` lives only in sidecar `_meta.checksum`; URL normalization (lowercase host, strip trailing slash) before hashing
- Sidecar layout: flat at `<bucket>/catalog/audio_manifest/<slug>.json` (864 sidecars)
- 6 channels inventoried (mp3quran, everyayah, quranicaudio, tarteel, tvquran, archive_org) from manifest URL host inference

**Audio probing infrastructure:**
- Reuse + extend `scripts/probe_audio_meta.py` (mutagen + frame-scan)
- `.local/dedup/bulk_probe.py` extends with `size_bytes` (Content-Range), `channels` (mutagen), Xing-aware per-chapter `duration_sec`
- Probe cache `.local/dedup/probe_cache.json` (URL→result, restart-safe)
- Per-host concurrency throttle (20 global, 10 for archive.org)
- `by_ayah` deliveries deferred per real-cost estimate (~3–6 h on one prober; trigger to revisit documented)

**State + lifecycle (reconciled with 07-admin-dashboard.md):**
- Lifecycle expanded **6 → 7 states** (`released` inserted between `awaiting_timestamps` and `completed`)
- `revision_in_progress: RevisionContext | None` sub-struct replaces flat `previous_*` fields (atomic invariant; self-documenting)
- `timestamps_job_ids: list[str]` (append-on-refresh)
- New events: `reciter.dataset_published`, `reciter.removed_from_dataset`, `reciter.unpublished`, `admin.unlocked_for_revision`, `published.edited`, `admin.batch_timestamps_refresh`, `access.role_granted/revoked/updated`
- Force-claim entirely deferred (no `force_assignee_*` columns); `archived` visibility deferred
- `admin.force_set_state` allowed-pairs extended: `awaiting_timestamps ↔ released`, `released ↔ completed`

**Roles & access:**
- `inspector_roles.json` **moved from GitHub raw to `<bucket>/access/inspector_roles.json`** (private; Inspector sole writer; bootstrap via hand-seed at Phase 0)
- New admin endpoints: `POST /api/admin/access/{grant,revoke,update}` (§5.7)
- `access.*` audit events; soft-delete via `removed_at`
- `data/inspector_roles.json` + CODEOWNERS path eliminated entirely

**Reference + planning docs:**
- New canonical reference: [`docs/reference/reciter-catalog.md`](../../../reference/reciter-catalog.md) — 12 sections, 380 lines (layers, slug, schema tables, audio metadata, naming guide, 12-step seed pipeline, workflows, probing, host migration, deletion, maintenance)
- New phase doc: [`07-dataset-packaging-refactor.md`](07-dataset-packaging-refactor.md) — post-refactor FLAC migration (decouples lossy 128k MP3 re-encode from source quality)
- Reconciled across: `state-machine.md`, `inspector-state-management.md`, `inspector-admin-perms.md`, `inspector-data-storage.md`, `inspector-cleanup-registry.md`, `inspector-deployment-plan.md`, `inspector-deploy-runbook.md`, `inspector-publish-pipeline.md`, `phases/03-auth-and-claims.md`, `phases/07-admin-dashboard.md`, `schemas/README.md`
- Override trail captured in [`naming_consistency_report.md`](../../../../.local/dedup/naming_consistency_report.md) header
- Design critique [`catalog_design_critique.md`](../../../../.local/dedup/catalog_design_critique.md) — 31 findings, all critical/high addressed

**Audit artifacts (preserved in `.local/dedup/`, gitignored):**
- `inventory.json` (870 raw manifests + channel inference)
- `programmatic_clusters.json`, `manual_clusters.json`, `reconciliation_report.{json,md}`
- `final_clusters.json` → `final_clusters_corrected.json` → `final_clusters_v3.json` (864 deliveries)
- `naming_consistency_{report.md,corrections.json}`, `name_normalize_proposed.json`, `name_normalize_extra_{proposed.json,report.md}`
- `qul_duplicate_probe.json`, `probe_followup.json`, `probe_cache.json`
- `bulk_probe.py` (with by_ayah-skip + Xing-aware extensions)
- `build_catalog.py` + `finalize.py` + `apply_corrections.py` (catalog assembly pipeline)
- `catalog_design_critique.md`

### Execution: code + cutover — landed

8 commits on `dev` (sharp-curie worktree); ~5,000 LoC of new code with smoke tests against the dev bucket green throughout.

**Schemas — `scripts/lib/schemas/`** (cross-consumer):
- `state.py`, `catalog.py`, `audit.py`, `access.py`, `edit_history.py` + smoke
- Slug regex validation, per-state invariants (e.g. `assignee_*` forbidden outside `under_review`, `marked_ready` requires `under_review`+assignee), FK validation in `ReciterCatalog`, soft-delete in `RolesFile`, v1-tolerant `parse_edit_history_line`

**Storage abstraction — `inspector/services/`**:
- `hf_bucket.py`: `StorageBackend` protocol + `BucketBackend` (HF buckets API: `batch_bucket_files`, `list_bucket_tree`, `hffs.cat_file`, `get_bucket_file_metadata`) + `FilesystemBackend` (POSIX, tests + opt-in offline). Singleton via `get_backend()`/`set_backend()`/`reset_backend()`
- `BucketBackend.__init__` calls `huggingface_hub.login(token)` once so Xet uploads work (per-call `token=` alone leaves Xet writes 401)
- `hffs.invalidate_cache()` after every write so read-after-write within a process is fresh
- `storage_paths.py`: pure path-string helpers for the v2 layout
- `data_dir.py`: `kind_for(slug)`, `list_slugs(kind)`, high-level helpers (`read_segments_doc`, `read_detailed_bytes`, `write_detailed_doc`, `append_edit_history`, `iter_peaks_history`, …)

**Stateful services — full state machine + audit + catalog + access**:
- `state.py`: dispatcher implementing the full §4 transition matrix (21 slug-bound events) per-slug `threading.Lock`; `_replace()` validates via pydantic on every mutation; `has_other_active_claim()` predicate for one-claim-per-user
- `catalog.py`: hydrate/snapshot/add_reciter/edit_reciter/add_delivery/add_audio_source with maintainer-only authorization
- `audit.py`: append-only monthly partitions via direct upload (bypasses mount flush); `ensure_meta_initialized()` writes `audit/_meta.json` once
- `access.py`: roles file with owner/maintainer gates (maintainers cannot grant/revoke owners); soft-delete via `removed_at`; `bootstrap()` CLI for the first owner
- `app.py`: hydrates state/catalog/access stores at module import; degrades to empty in-memory model + warning on bucket-unreachable

**Cutover seeds — `scripts/inspector_v2_seed/`** (ran end-to-end against `hetchyy/quranic-inspector-bucket-dev`):
- `bootstrap_access`: first OWNER seeded (`hetchyy`, hf_user_id `684abe5b6327ae8863d106d2`)
- `seed_catalog_stub`: vocab-only stub from on-disk `data/{riwayat,sources,styles}.json` + canonical 6 channels + 5 recording_contexts; legacy `taraweeh` style dropped (migrated to `style=murattal + recording_context=taraweeh`)
- `seed_state`: 14 rows from filesystem signals (6 completed via `reciter_eligibility`, 8 `awaiting_review`)
- `seed_reciter_data`: 70 per-reciter files uploaded under `wip/<slug>/` (8 reciters) and `published/<slug>/` (6 reciters); timestamps intentionally not uploaded (live on public HF dataset until Phase 6 HF Job)

**Call-site migration — every per-reciter IO now flows through the backend**:
- `services/data_loader.py`, `services/save.py`, `services/undo.py`, `services/history_query.py`, `services/peaks_history.py`, `services/audio_meta.py`, `routes/segments_data.py`, `routes/segments_validation.py`, `routes/segments_edit.py`, `routes/audio_metadata.py` all migrated
- `adapters/detailed_json.py` + `adapters/segments_json.py` split into pure-data + filesystem-wrapper variants (`load_entries_from_bytes`, `build_segments_doc`)
- Save flow drops `backup_file()`, `file_sha256()`, `file_hash_after`, genesis records — file-hash chain entirely gone in v2 writes
- `LocalWritesDisabled` exception + `@_gate_local_writes` route decorator: local mode reads the shared dev bucket but refuses to write by default (`INSPECTOR_LOCAL_WRITES=1` to opt in); deployed mode (Phase 3+) is OAuth-gated separately
- `seg_reciters` route returns 14 reciters from `state_service.all_rows()` with `state` + `visibility`
- `seg_trigger_validation` returns 410 (deprecated; validators-as-libraries in Phase 5); `seg_save_chart` removed entirely (debug-only)

**Validators** — `validate_edit_history` file-hash chain checks dropped (`check_genesis_record` + `check_file_hash` retired from the active pass set per cleanup-registry §2 / D13). Per-reciter check count 7→5. Library/CLI split documented; deeper integration with `services/save.py` is Phase 5 work.

**Tests — partial migration** — `tmp_reciter_dir` fixture now installs a `FilesystemBackend` rooted at `tmp_path`, writes fixtures under `wip/<slug>/` (v2 layout), and seeds a state row so `data_dir.kind_for(slug)` returns `"wip"`. `inspector/pyproject.toml` adds repo root to `pythonpath` so `scripts.lib.schemas` resolves in tests + subprocesses. **138 of 152 tests pass.** 14 legacy-pattern tests deferred — see [`../inspector-deferred.md`](../inspector-deferred.md) D19.

**Verified end-to-end against the dev bucket**:
- Inspector boots clean; state/catalog/access hydrate from bucket
- `GET /api/seg/reciters` → 14 rows with state + visibility
- `GET /api/seg/chapters/saad_al_ghamdi` → 114 chapters
- `GET /api/seg/data/saad_al_ghamdi/1` → full chapter payload
- `GET /api/seg/edit-history/saad_al_ghamdi` → 533 batches with summary
- `POST /api/seg/save/...` → 403 with `LocalWritesDisabled` message

### Deferred (carried forward)

- **Repo `data/` cleanup** (`data/recitation_segments/`, `data/audio/`, `data/{reciters_index,riwayat,sources,styles,.audio_meta,.audio_durations}.json`) — grep audit found 10+ CI consumers (`list_reciters.py`, `build_reciter.py`, `package_release.py`, `update-reciters.yml`, `sync-dataset.yml`, …) that still read these. Deleting now breaks the main-branch CI on next push. **Bundled into Phase 5** alongside the workflow rewrite that points those consumers at the bucket via `huggingface_hub`.
- **Catalog promotion** — bulk audio probe in `.local/dedup/` still running (~78k chapters). When it finishes, extend `scripts/inspector_v2_seed/seed_catalog_stub.py` to write the full `reciters[]` + `deliveries[]` + per-delivery `audio_manifest/<slug>.json` sidecars. The catalog file in the bucket today is vocab-only — sufficient for Phase 1 acceptance.
- **Legacy bucket layout stays — shard builder rewires in Phase 5 (D20).** The `<bucket>/manifest.json.gz` + `<bucket>/segments/<slug>/<chapter>.json.gz` + `<bucket>/timestamps/<slug>/<chapter>.json.gz` layout is **load-bearing**: the universal aligner Space's Preload mode reads it directly (`PRELOAD_BUCKET_ID=hetchyy/quranic-inspector-bucket-dev`, `src/preload/manifest_client.py`), and the Inspector deployed timestamps tab consumes the same format. The shard schema is **not** a slice of v2's `published/<slug>/segments.json` — it's a per-chapter projection with its own `_meta.audio_urls`. Phase 5 rewires `scripts/lib/{segments,timestamps}_shards.py` to read from v2 bucket paths, refresh the shards on every publish, and unblock Phase 11 `data/` deletion. See [D20](../inspector-deferred.md) for the schema diff and migration analysis.
- **14 legacy-pattern test failures** — see D19 in [`../inspector-deferred.md`](../inspector-deferred.md).

The catalog seed pipeline in `.local/dedup/` is fully exercised and reproducible; promotion is a matter of running `build_catalog.py` once the probe completes and uploading the result.
