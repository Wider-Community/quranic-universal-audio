# Phase 6 Handoff: Stable Validation Issue Identity (segment_uid)

**Commit:** (see `git log --oneline -1` after final commit)
**Branch:** `inspiring-ramanujan-2d4e7e`

---

## What was done

- **`inspector/services/validation/detail.py`** (modified): Every issue item appended by `_build_detail_lists` now carries a `segment_uid` field (the segment's uid, or `None` if missing). Added three public helpers at module level: `resolve_segment_by_uid(reciter, uid)`, `resolve_segment_for_issue(reciter, issue)` (uid-first, falls back to seg_index for legacy), and `filter_stale_issues(issues, live_uids)` (drops items whose uid is not in the live set; keeps items without a uid).

- **`inspector/services/validation/_structural.py`** (modified): `errors` (structural errors), `missing_verses`, and their builder now emit `"segment_uid": None` on each item. Chapter-level issues have no associated segment; the `None` value satisfies the "segment_uid present on all items" invariant while keeping the semantics accurate.

- **`inspector/services/validation/_missing.py`** (modified): `missing_words` items now carry `"segment_uid": None` (chapter-level, no associated segment).

- **`inspector/services/save.py`** (modified): Added docstring to `_ensure_patch_on_ops` explaining the forward-only tradeoff (Entry-1).

- **`inspector/services/undo.py`** (modified): `_reverse_via_patch` now validates that `affectedChapterIds` from the patch is a subset of the batch's `chapter_set`. Raises `ValueError` (logged as warning first) if a malformed patch claims chapters outside batch scope (Entry-2).

- **`inspector/frontend/src/lib/types/api.ts`** (modified): `SegValItemBase` gains `segment_uid?: string | null` (additive optional field, IS-10). Updated stale comments on `SegValAutoFix` and `SegValItemBase.seg_index`.

- **`inspector/frontend/src/tabs/segments/utils/validation/resolve-issue.ts`** (modified): Added `resolveByUidStrict(uid, chapter)` export. `resolveIssueSeg` now checks `item.segment_uid` (when present and non-null) before falling back to seg_index. A uid miss returns null (stale) and does NOT fall back to seg_index to avoid re-pointing to a wrong segment.

- **`inspector/frontend/src/tabs/segments/utils/validation/stale.ts`** (new): Exports `filterStaleIssues(issues, liveUids)`. Drops items whose `segment_uid` is not in `liveUids`. Keeps items with `segment_uid: null` or no uid (legacy seg_index path).

- **`inspector/frontend/src/tabs/segments/components/validation/ValidationPanel.svelte`** (modified): Imports `filterStaleIssues`. In `buildCategories`, builds a `liveUids` set from `$segAllData.segments` and applies `filterStaleIssues` to each category's raw items before building the descriptor.

- **`inspector/frontend/src/tabs/segments/utils/edit/split.ts`** (modified): Removed `_fixupValIndicesForSplit` import and call.

- **`inspector/frontend/src/tabs/segments/utils/edit/merge.ts`** (modified): Removed `_fixupValIndicesForMerge` import and call.

- **`inspector/frontend/src/tabs/segments/utils/edit/delete.ts`** (modified): Removed `_fixupValIndicesForDelete` import and call.

- **`inspector/frontend/src/tabs/segments/utils/edit/common.ts`** (modified): Removed `refreshOpenAccordionCards` import from `fixups.ts` and its call in `finalizeEdit`. The `skipAccordion` option remains in the type signature for call-site compatibility (it was already a no-op).

- **`inspector/frontend/src/tabs/segments/utils/validation/fixups.ts`** (deleted): All `_fixupValIndicesFor*` functions and `refreshOpenAccordionCards` removed. Index fixups are no longer needed since uid-based identity is stable through structural edits.

- **`inspector/frontend/src/tabs/segments/stores/validation.ts`** (modified): Updated module docstring to describe the uid-based identity pattern.

- **Phase 6 pytest markers cleared** (7): `test_validation_response_carries_segment_uid`, `test_resolve_issue_uses_uid_first`, `test_resolve_issue_falls_back_to_seg_index_for_legacy_issues`, `test_stale_issue_filtered_after_split`, `test_stale_issue_filtered_after_delete`, `test_no_index_fixups_after_phase_6`, `test_validate_issue_carries_segment_uid`.

- **Phase 6 vitest markers cleared** (6): `stale-filter.test.ts` 3 xfail wrappers removed + 1 it.todo now in skipped describe; `resolve-issue.test.ts` 3 xfail wrappers removed + 1 it.todo now in skipped describe.

- **Phase 5 entry items resolved**: E1 (docstring), E2 (chapter_set guard), E3 (test deleted — option 2).

---

## Decisions that differ from plan

- **`segment_uid: None` on chapter-level items**: Plan said "null for chapter-level" without specifying where to add it. Added `"segment_uid": None` in `_structural.py` (errors + missing_verses) and `_missing.py` (missing_words) so all items in the validate response carry the field. The route itself (`segments_validation.py`) needed no changes — items pass through from builder functions.

- **`resolve-issue.test.ts` test setup**: The plan said "remove xfail wrappers, replace with plain test bodies". The test bodies for uid-first/stale-uid resolution require a populated store. Added `beforeAll`/`afterAll` around the describe block to populate `segAllData` with a synthetic segment. This is necessary for the tests to be meaningful rather than always failing due to empty store. The test bodies themselves are unchanged from the original spec.

- **`common.ts` modified (not in scope_files)**: `common.ts` imported `refreshOpenAccordionCards` from `fixups.ts`. Since `fixups.ts` was deleted, the import had to be removed. Also removed the `skipAccordion: refreshOpenAccordionCards()` call (already a no-op). The `skipAccordion` option remains in the type signature for call-site backward compat.

- **`_structural.py` and `_missing.py` modified (not in scope_files)**: Chapter-level items (structural errors, missing verses, missing words) needed `"segment_uid": None` to satisfy the route test that checks ALL items in the validate response carry the field. Adding it in the builder functions was cleaner than post-processing in `validate_reciter_segments`.

- **Entry-1 docstring style**: Added as a comment block inside the docstring (Python `# ...` inside `"""..."""`). This is slightly unusual but matches the intent of documenting the forward-only tradeoff without changing the function's docstring appearance in `help()`.

---

## Patterns established

- **Uid-first resolution**: When a validation item carries `segment_uid`, all resolution goes through uid lookup. A miss (stale uid) returns null and does NOT fall back to seg_index. This prevents silent re-pointing to a structurally-different segment after a split or merge.
- **Stale filter at render time**: `filterStaleIssues` runs in `buildCategories` every time the validation data or segment data changes. O(1) set membership per item. Chapter-level items (null uid) pass through unconditionally.
- **`segment_uid: None` convention**: Chapter-level validation items (structural errors, missing verses, missing words) carry `segment_uid: None` to distinguish "no associated segment" from "uid not yet known". Both resolve to "no uid-based lookup" in `filterStaleIssues` (kept) and `resolveIssueSeg` (falls through to verse-key or missing path).

---

## Invariant check

- **MUST-1**: No route changes. `segment_uid` rides along as additive field on validation items. No existing fields removed or renamed.
- **MUST-2**: `detailed.json` format unchanged. No Phase 6 changes to persistence.
- **MUST-3**: `segments.json` format unchanged.
- **MUST-4**: UIDs consumed from backfilled segments (Phase 4). Not regenerated.
- **MUST-9**: Validation issues reference segments by `segment_uid` (uid-first resolution). `seg_index` retained as fallback for legacy issues. Stale items hidden via `filterStaleIssues`. Enacted.
- **MUST-11**: No refactor-trace breadcrumbs in new lines. Verified via `checks.sh [8]`.
- **IS-10**: Validation DTO gains `segment_uid` on every issue. Frontend resolution uses uid first; falls back to seg_index for legacy. Stale issues filtered. Enacted.
- **IS-11**: `_fixupValIndicesForSplit/Merge/Delete` removed. All call sites in split/merge/delete/common cleaned up. `fixups.ts` deleted. Enacted.

---

## Phase metrics

- **Files modified**: 13 production + 5 test (2 identity vitest + 3 backend) + 1 new file (stale.ts) + 1 deleted (fixups.ts)
- **LOC added**: ~220 net added
- **Wall-clock**: ~30 min
- **Markers cleared**: 7 pytest (6 identity + 1 route) + 6 vitest (3+3 xfail wrappers removed; 2 it.todo in now-skipped fallback describes)

---

## Phase 5 entry items resolved

- **E1 (docstring on `_ensure_patch_on_ops`)**: Added a 4-line comment block inside the function's docstring explaining the forward-only tradeoff (W-1 risk). No behavior change.
- **E2 (chapter_set guard in `_reverse_via_patch`)**: Added validation that the patch's `affectedChapterIds` is a subset of the batch's `chapter_set`. Logs a warning and raises `ValueError` (matching existing error-handling style in `undo.py`) if a malformed patch claims out-of-scope chapters.
- **E3 (test_inverse_patch_restores_state_exactly)**: Deleted (option 2). The `_save_with_patch` helper sends `full_replace=True, segments=[]` which clears all segments. After undo, only the one segment in the patch's `before` list is restored; `post == pre` is impossible since other segments are gone and `_meta` is not patch-managed. The intent is covered by `test_inverse_patch_handles_inserted_and_removed_ids` and `test_undo_batch_patch_records`.

---

## Final test surface

**pytest (123 passed / 14 xfailed / 2 xpassed)**
- 14 xfailed: all phase-3 (B-4 deferred — route-level command envelope validation)
- 2 xpassed: phase-3 `test_edit_from_card_records_suppression_per_registry[failed]` and `[muqattaat]` (negative assertions that pass; same as Phase 5)
- 0 phase-5 markers: E3 cleared the last one
- 0 phase-6 markers

**vitest (204 passed / 15 todo / 2 unhandled errors)**
- 15 todo: pre-existing from other phases (not increased by Phase 6)
- 2 unhandled errors: pre-existing network errors from timestamps tab tests (fetch to localhost:3000 fails in test environment)
- 0 phase-6 markers

**Only deferred item: B-4** (phase-3 backend route-level command envelope validation, 4 pytest + 2 xpassed). This is intentionally out of scope for all phases up to and including Phase 6.
