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
- [ ] `inspector/schemas/` pydantic models for state row, catalog row, audit record, edit-history batch
- [ ] State row schema includes the full v2 lifecycle: states `catalogued | awaiting_alignment | awaiting_review | under_review | awaiting_timestamps | released | completed`, `marked_ready: bool`, `visibility: 'public'|'discarded'`, `assignee_hf_id`, `assignee_login`, `timestamps_job_ids: list[str]` (append-on-refresh), `previous_assignee_hf_id` (set on unlock-for-revision), `previous_dataset_state: bool` (set on unlock so re-publish can restore dataset membership)
- [ ] Audit event schema covers the v2 event set: lifecycle (`reciter.published`, `reciter.timestamps_completed`, `reciter.dataset_published`, `alignment.completed`, `catalog.reciter_added`); contributor (`reciter.claimed`, `reciter.released`, `reciter.marked_ready`, `reciter.unmarked_ready`); admin overrides (`claim.force_released`, `claim.reassigned`, `admin.force_set_state`, `reciter.merge_rejected`); admin lifecycle (`admin.unlocked_for_revision`, `published.edited`, `admin.batch_timestamps_refresh`, `reciter.removed_from_dataset`, `reciter.unpublished`, `reciter.discarded`, `reciter.undiscarded`, `catalog.reciter_edited`, `catalog.vocab_added`)
- [ ] `inspector/services/state.py` — JSON file at `<bucket>/state/reciter_state.json`, per-slug `threading.Lock`, atomic-write-then-rename + `huggingface_hub.upload_file()` per write
- [ ] `inspector/services/catalog.py` — same write pattern for `<bucket>/catalog/reciter_catalog.json` (consolidated vocab + reciters + aliases)
- [ ] `inspector/services/hf_bucket.py` — mount path resolver + direct-upload helpers
- [ ] `inspector/services/audit.py` — append to `<bucket>/audit/<YYYY>-<MM>.jsonl` via `upload_file()`
- [ ] `data/inspector_roles.json` — consolidated owners + maintainers; CODEOWNERS entry
- [ ] `validators/{validate_segments,validate_audio,validate_edit_history,validate_timestamps}.py` refactored as libraries with thin CLI wrappers
- [ ] `scripts/seed_state.py` + `scripts/seed_catalog.py` — produce JSON; manual one-shot seeding into the dev bucket
- [ ] Test fixtures updated (`inspector/tests/conftest.py`, `parity/snapshot_route_baselines.py`) to monkey-patch the resolver instead of `RECITATION_SEGMENTS_PATH`
- [ ] `data/reciters_index.json` consumer audit complete; file deleted from repo
- [ ] `data/{riwayat,sources,styles}.json`, `data/audio/<cat>/<src>/<slug>.json`, `data/.audio_meta.json`, `data/.audio_durations.json` deleted from repo (data migrated into `<bucket>/catalog/...`)

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
python -m inspector.schemas.smoke   # dummy state row + catalog row + audit + edit-history batch

# Bucket round-trip (against dev bucket)
INSPECTOR_BUCKET_REPO=hetchyy/quranic-inspector-bucket-dev \
INSPECTOR_HF_TOKEN=$HF_TOKEN \
python -m inspector.services.state.smoke   # transition seed-row -> awaiting_review -> under_review -> awaiting_review

# Concurrency
python -m inspector.tests.parity.test_per_slug_lock

# Validators-as-libs
python -m validators.validate_segments --bucket --slug saad_al_ghamdi

# Repo discipline
test -f data/inspector_roles.json
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
