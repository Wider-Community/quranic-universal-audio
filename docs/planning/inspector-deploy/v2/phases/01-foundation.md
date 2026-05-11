# Phase 1 — Foundation

> All non-deploy groundwork lands. Nothing is shipped to a public Space yet, but every refactor v2 needs is in code and the JSON state store + bucket helpers work end-to-end against the dev bucket.

**Status:** not started
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

### Still pending (Phase 1 execution)

The code-level deliverables in the **Deliverables** list above are not yet started:

- `scripts/lib/schemas/` pydantic models for state, catalog, audit, edit_history (cross-consumer location)
- `inspector/services/{state,catalog,audit,access,hf_bucket,data_dir}.py`
- Validator refactor to libraries with thin CLI wrappers
- Test fixture monkey-patching of the resolver instead of `RECITATION_SEGMENTS_PATH`
- Repo `data/` cleanup (drop `reciters_index.json`, `riwayat/sources/styles.json`, `audio/`, `.audio_meta.json`, `.audio_durations.json`)
- Promotion of `.local/dedup/reciter_catalog.json` + sidecars to `<bucket>/catalog/...` via `huggingface_hub.upload_file()`
- Hand-seed of `<bucket>/access/inspector_roles.json` (first owner)
- `<bucket>/state/reciter_state.json` initial state seed
- Bulk probe completion (~78k chapters; still running) → catalog re-bake with full audio metadata → sidecars filled in

The catalog seed pipeline in `.local/dedup/` is fully exercised and reproducible; promotion is a matter of running `build_catalog.py` once the probe completes and uploading the result.
