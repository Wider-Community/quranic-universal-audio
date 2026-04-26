# Phase 4 Handoff: Normalize Segment State + UID Backfill

**Commit:** (see `git log --oneline -1` after final commit)
**Branch:** `inspiring-ramanujan-2d4e7e`

---

## What was done

- **`inspector/domain/identity.py`** (new): `NAMESPACE_INSPECTOR = uuid.UUID("00000000-0000-0000-0000-000000000001")`, `derive_uid(chapter, original_index, start_ms)`, `backfill_entry_uids`, `backfill_entries_uids`. UUID v5 derivation from `f"{chapter}:{original_index}:{start_ms}"`.
- **`inspector/domain/segment.py`** (new): Frozen `Segment` dataclass with all canonical fields. Unused in runtime paths this phase but establishes the domain model for Phase 5+.
- **`inspector/adapters/detailed_json.py`** (new): `load_entries(path)` — loads a `detailed.json` file and calls `backfill_entries_uids` before returning entries. Extracted from `data_loader.py` load path.
- **`inspector/adapters/segments_json.py`** (new): `rebuild(reciter_dir, entries)` — extracted `rebuild_segments_json` logic. Receives a `Path` instead of a reciter string.
- **`inspector/adapters/save_payload.py`** (new): `make_seg` and `build_seg_lookups` extracted from `services/save.py`. `make_seg` accepts `word_counts` parameter. Preserves MUST-7 semantics for `ignored_categories`.
- **`inspector/services/data_loader.py`** (modified): Added `from domain.identity import backfill_entries_uids` and a `backfill_entries_uids(entries)` call after loading entries from disk. This makes UID backfill automatic on every `load_detailed` call — including the call at the top of `save_seg_data` — so UIDs persist on the next save without any save-path changes.
- **`inspector/tests/persistence/test_uid_backfill.py`** (modified): Removed 4 `@pytest.mark.xfail(reason="phase-4", strict=False)` decorators. Fixed Windows path bug in `test_uid_deterministic_across_processes`: replaced `str(__file__).replace(...)` with `str(_Path(__file__).parent.parent.parent)`.
- **`inspector/frontend/src/tabs/segments/domain/identity.ts`** (new): Pure synchronous JS SHA-1 uuid5 implementation (no `crypto.subtle` — async-incompatible with Svelte store initializers and vitest sync tests). Exports `deriveUid({chapter, originalIndex, startMs})` and `backfillSegmentUids(segs, chapter)`. Verified bit-exact match with Python: `deriveUid({chapter:1, originalIndex:0, startMs:0})` → `418dc3a4-5e80-5d8e-9a3f-209a6403206e`.
- **`inspector/frontend/src/tabs/segments/stores/segments.ts`** (new): `SegmentState{byId: Record<string, Segment>, idsByChapter: Record<number, string[]>, selectedChapter: number | null}` normalized store. Exports pure selectors: `getChapterSegments`, `getSegByChapterIndex` (with positional fallback for legacy fixtures), `getAdjacentSegments` (with positional fallback), `findByUid`. Exports `applyNextState(current, nextState)` reducer.
- **`inspector/frontend/src/tabs/segments/stores/chapter.ts`** (modified): Retired `_byChapter` / `_byChapterIndex` from the store value object (`SegAllDataState` is now `= SegAllResponse` — no internal cache fields). Both moved to module-level variables (`_cachedRef`, `_byChapter`, `_byChapterIndex`) with identity-based cache invalidation. All 50+ subscriber-facing public selectors (`getChapterSegments`, `getSegByChapterIndex`, `getAdjacentSegments`, `invalidateChapterIndex`, `invalidateChapterIndexFor`, `refreshSegInStore`, `syncChapterSegsToAll`, `getCurrentChapterSegs`) preserved with identical signatures and semantics.
- **`inspector/frontend/src/tabs/segments/stores/filters.ts`** (modified): Added `derivedTimings` derived store that computes `silence_after_ms` and `silence_after_raw_ms` per segment UID from `segAllData` — replacing in-place mutation. Keyed by `segment_uid` for O(1) lookup in render paths.
- **`inspector/frontend/src/tabs/segments/domain/apply-command.ts`** (modified): Added import of `SegmentState` from `stores/segments`. The reducer already accepted the `{byId, idsByChapter, selectedChapter}` duck-typed view from Phase 3; now it has a formal type alias covering the normalized store shape too.
- **`inspector/frontend/src/tabs/segments/utils/edit/common.ts`** (modified): Added `segSlice(seg, chapter): SegmentState` helper — builds the minimal single-segment state view that all dispatchers pass to `applyCommand`. Centralizes the repeated `{ byId: {[uid]: seg}, idsByChapter: {[chapter]: [uid]}, selectedChapter: chapter }` boilerplate.
- **Vitest normalized-state tests** (modified): Removed all `xfail('phase-4', () => { ... })` wrappers from `selectors.test.ts`, `compat.test.ts`, `uid-backfill.test.ts`. Added concrete Python-cross-check value assertion.

## Decisions that differ from plan

- **`segSlice` helper in `common.ts`** — plan mentioned "consolidate `applyResultToStores`". On inspection, the dispatchers' live-store glue (splice+reindex+syncChapterSegsToAll) is already heterogeneous enough that a single helper wouldn't reduce duplication meaningfully. What IS uniform is the `applyCommand` state-slice construction — so `segSlice` targets that instead.
- **`SegmentState` not wired as primary live store** — the Phase 4 plan (IS-7) introduced the store type but intentionally deferred full wiring. `$segAllData` / `$segData` remain primary. `segmentsStore` is initialized but not populated at load time. Phase 5 or 6 completes the wiring. Compat selectors in `chapter.ts` remain authoritative.
- **`domain/segment.py` is a stub** — frozen dataclass defined but no production paths use it yet. Phase 5 adapters will adopt it.
- **B-4 not resolved in Phase 4** — the phase-3 pytest markers (backend route validation / registry-driven `ignored_categories` write at save handler) remained deferred. The new adapter modules in `inspector/adapters/` provide the right hook, but the HTTP route changes needed for B-4 are out of scope.

## Current codebase state

- **Production code**: normalized `SegmentState` store type active; identity backfill wired on `load_detailed`; `_byChapter`/`_byChapterIndex` retired from store value; `derivedTimings` available; `segSlice` helper available to dispatchers.
- **Test surface**:
  - pytest: 103 passed, 33 xfailed, 2 xpassed (up from 99/36/3 before Phase 4; 4 phase-4 markers cleared).
  - vitest: 197 passed, 3 skipped, 16 todo (up from 189/11/16 before Phase 4; 11 phase-4 wrappers removed → 8 net new passing tests).
  - No phase-4 xfail markers remain anywhere.

## Patterns established

- **UID derivation**: `uuid5(NAMESPACE_INSPECTOR="00000000-0000-0000-0000-000000000001", f"{chapter}:{original_index}:{start_ms}")`. Same on Python and TypeScript — verified cross-platform via test vector.
- **Backfill on load, persist on save**: `data_loader.load_detailed` calls `backfill_entries_uids`; `save_seg_data` calls `load_detailed` first, so backfilled UIDs are present when `_make_seg` builds the time-key lookup. No explicit save-path changes needed.
- **Module-level identity-cached index**: `chapter.ts` uses `_cachedRef === all` identity check for fast-path; `invalidateChapterIndexFor` does surgical per-chapter eviction without full rebuild.
- **Positional fallback in `getSegByChapterIndex`**: `segs.find(s => s.index === index)` first; `segs[index]` fallback for legacy test fixtures that omit the `index` field.

## Invariant check

- **MUST-1**: Routes additive only. No `routes/` or `services/` route handler changes.
- **MUST-2**: `detailed.json` schema unchanged. `backfill_entries_uids` adds `segment_uid` fields to legacy docs but the schema is additive.
- **MUST-3**: `segments.json` format unchanged. `adapters/segments_json.py` extracted from existing logic.
- **MUST-4**: UID stability ✓ — `derive_uid` is deterministic from `(chapter, original_index, start_ms)`. Existing UIDs are never regenerated (`if seg.get("segment_uid"): continue`). Cross-process reproducibility tested.
- **MUST-5**: Issue visibility from registry — no regression.
- **MUST-6**: Classifier parity — no regression.
- **MUST-7**: `ignored_categories` clears persisted ignores — adapters preserve the `filter_persistent_ignores` semantics.
- **MUST-8**: Undo (Phase 5) — `applyNextState` in `segments.ts` is ready to receive `CommandNextState` slices.
- **MUST-9**: Validation issue identity (Phase 6) — no regression.
- **MUST-10**: Registry-driven extensibility — no regression.
- **MUST-11**: No refactor-trace breadcrumbs — verified via checks.sh [8].
- **IS-7**: `SegmentState{byId, idsByChapter, selectedChapter}` introduced ✓; compat selectors preserved ✓.
- **IS-8**: Deterministic uid backfill on load ✓; uid persists on next save ✓; Python ↔ TypeScript cross-platform parity ✓.

## Risks/concerns for next phase (Phase 5 — Patch-based undo)

- **`SegmentState` not yet live**: Phase 5 dispatchers will receive `result.nextState` and apply it. Currently the dispatchers still drive `segAllData`/`segData` mutations manually. Phase 5 could complete the wiring or leave it for Phase 6.
- **`segSlice` covers single-seg calls only**: `merge.ts` passes both merged segments; `split.ts` is single-seg (second half uid is brand new). Any Phase 5 batch-undo path needs to build its own slice or extend `segSlice` to accept a map.
- **B-4 remains open**: 4 pytest phase-3 markers still xfailed. Route-level `ignored_categories` write validation not yet implemented.
- **`domain/segment.py` unused**: frozen dataclass introduced but not yet plumbed into `data_loader` or `save.py` return types. Phase 5 can adopt it if it simplifies the patch payload builder.
- **`adapters/` modules not yet integrated into routes**: `detailed_json.py`, `segments_json.py`, `save_payload.py` exist but `services/` still has its own copies of the logic. Phase 5 can consolidate.

## Phase metrics

- **Files modified**: 9 production + 7 new + 3 test + 2 doc (orchestration-log, this handoff)
- **LOC added/removed**: ~700 net added
- **Wall-clock**: ~35–40 min (single agent, context-window split into two sessions)
- **Token budget**: not captured (agent exceeded context limit mid-session)
