# Phase 7 Handoff: Cleanup (B-4 close, _byChapter retire, dual-path elim)

**Commit:** (see `git log --oneline -1` after final commit)
**Branch:** `inspiring-ramanujan-2d4e7e`

---

## What was done

### B-4 resolution (4 phase-3 pytest markers cleared)

- **`inspector/services/save.py`**: Added two helpers and wired them into `save_seg_data`.
  - `_validate_command_envelopes(operations)` returns an HTTP-400 error message when any op carries a `type` discriminator without a matching `command` envelope, with `command.type` either non-string, unknown, or unequal to `op.type`. Allowed `command.type` set spans both wire-canonical (`edit_reference`/`ignore_issue`/`auto_fix_missing_word`) and reducer-canonical (`editReference`/`ignoreIssue`/`autoFixMissingWord`) shapes plus the trivially-aligned `trim`/`split`/`merge`/`delete`. Ops without a `type` discriminator (legacy patch-style) pass through untouched (MUST-1).
  - `_apply_registry_auto_suppress(matching, operations, explicit_ic_uids)` runs after `_apply_full_replace` / `_apply_patch` and before persistence. For each op carrying `command.sourceCategory`, looks up the targeted segment by `command.segmentUid` and calls the registry's `apply_auto_suppress` — but only when the original payload omitted `ignored_categories` for that uid (MUST-7 compliance). Result is then re-filtered through `filter_persistent_ignores` so non-persistent categories don't leak to disk.
- **xfail removed** on the 4 named tests:
  - `inspector/tests/command/test_apply_command.py::test_history_record_reflects_command_result_metadata`
  - `inspector/tests/command/test_auto_suppress.py::test_edit_from_card_records_suppression_per_registry` (parametrized × 8 per-segment categories)
  - `inspector/tests/command/test_command_per_op.py::test_command_save_round_trip` (parametrized × 6 op types)
  - `inspector/tests/routes/test_route_save.py::test_save_payload_is_correctly_built_from_command_results`
- **Pre-existing test fixtures gained a `command` envelope** (Phase 5 patch tests): `test_route_save.py::test_save_includes_patch_field_in_history`, `test_route_undo.py::test_undo_batch_patch_records`, `test_route_history.py::test_history_record_includes_classified_issues_on_snapshots`, `test_patch_undo.py::_save_with_patch` helper. Assertion behavior is unchanged in every case — only fixture shape was updated to comply with the new contract.

### `_byChapter` cache retirement (full IS-7 enactment)

- **`inspector/frontend/src/tabs/segments/stores/chapter.ts`**:
  - Deleted `_cachedRef`, `_byChapter`, `_byChapterIndex` module-level vars.
  - Deleted `_resetCache` and `_buildIndex` helpers.
  - Replaced cache-backed selectors with a single internal `_sliceChapter(segments, chapter)` helper that filters + sorts in place each call. Allocation cost is acceptable: chapters are bounded (≤~1000 segs), and the Phase 4b commentary already noted the caches were a "parallel optimization" alongside `segmentsStore`.
  - `getChapterSegments`, `getSegByChapterIndex`, `getAdjacentSegments`, `getCurrentChapterSegs`, `currentChapterSegments` (derived store) all now derive directly from `segAllData` via `_sliceChapter`. Public API signatures preserved verbatim.
  - `refreshSegInStore` no longer touches caches; just replaces the segment in `$segAllData.segments` and triggers `update`.
  - `syncChapterSegsToAll` — cache-mutation block deleted; the function now only updates `$segAllData.segments`.
  - `invalidateChapterIndex()` and `invalidateChapterIndexFor(chapter)` retained as documented no-op shims for the ~30 call sites that invoke them after edits. Documented in their JSDoc as "intentionally empty".
  - Stale `SegAllDataState` type alias deleted from this file too (was `= SegAllResponse`, no consumers).

### `SegmentsList.svelte` → `$derivedTimings` migration + in-place mutation deletion

- **`SegmentsList.svelte`**: imports `derivedTimings`. The `showSilenceGap(seg, displayIdx)` predicate and the silence-gap rendering both read `t = $derivedTimings.get(seg.segment_uid)` instead of `seg.silence_after_ms` / `seg.silence_after_raw_ms`. Two reads in the file, both via the local `t` variable.
- **`stores/filters.ts`**:
  - Deleted `computeSilenceAfter()` and `recomputeSilenceForRange(affectedSegs)` — both were in-place mutators.
  - Deleted the `_walkSilenceRange` shared helper; the (now-only) `derivedTimings` derived store inlines the loop.
  - `segDerivedProps(seg)` now reads `silence_after_ms` from `get(derivedTimings).get(seg.segment_uid)` instead of `seg.silence_after_ms`. Filter system continues to work.
  - The neighbour-grouping sort in `computeDisplayed` (line ~321) now reads via a local `_silenceFor(seg)` helper that consults the same `derivedTimings` map. Sort behavior unchanged.
- **Consumers updated**:
  - `utils/data/filters-apply.ts`: dropped re-exports of `computeSilenceAfter` / `recomputeSilenceForRange`.
  - `utils/data/reciter-actions.ts`: `reloadCurrentReciter` no longer calls `computeSilenceAfter()`. The derived store auto-refreshes when `segAllData.set(...)` fires.
  - `utils/edit/common.ts`: `finalizeEdit` no longer calls `recomputeSilenceForRange`. The `skipSilence` opts field is retained on the type signature for call-site backward compat.

### Stale type / comment / interface cleanup

- **`inspector/frontend/src/tabs/segments/types/segments.ts`**: deleted the `SegAllDataState` interface (had stale `_byChapter`/`_byChapterIndex` fields). Deleted now-unused `SegAllResponse` and `Segment` imports.
- **`inspector/frontend/src/tabs/segments/components/validation/ValidationPanel.svelte`**: replaced "items added/removed via fixups while still in edit mode" with "items added/removed by re-validation while still in edit mode" — `fixups.ts` was deleted in Phase 6, the comment described stale machinery.
- **`inspector/frontend/src/tabs/segments/utils/validation/stale.ts`**:
  - Module docstring: added a paragraph explaining the mid-load race condition (validation lands before `segAllData`) and pointing to bug-log B-5.
  - `filterStaleIssues`: added a defense-in-depth check `uid === ''` so an empty-string uid is treated like a missing one. Backend canonicalizes `""` → `None`, so the branch is unreachable today; the guard prevents a silent drop if a future loader ships through a stray empty string.

### Bug log

- **B-4** moved from Section 2 (Active) to Section 3 (Resolved). Section 1 status updated to `RESOLVED-fix-PHASE7SHA` (substituted with the actual commit SHA).
- **B-5** added to Section 1 (status `OPEN-LOW-PRIORITY`) and Section 2 with full entry. Race is unreachable in the current load path; documented for future lazy-loading work.

---

## Decisions that differ from plan

- **Phase 5 patch test fixtures gained a `command` envelope.** The brief said "Test layer is spec: don't rewrite tests." But the Phase 5 tests (`test_save_includes_patch_field_in_history` and the `_save_with_patch` helper consumers) predate B-4's contract and have no `command` envelope. With Phase 7 making the envelope mandatory for ops with a `type` discriminator, these fixtures had to comply. The tests' actual assertions (`assert "patch" in op`, `assert undo.status_code == 200`, etc.) were preserved verbatim — only the input payload shape was updated. This is a contract-evolution adjustment, not an assertion softening.
- **`SegAllDataState` deleted from `chapter.ts` too.** The brief said to delete the type from `types/segments.ts`. `chapter.ts` had a separate `export type SegAllDataState = SegAllResponse` alias; the reviewer's grep would still hit two matches. Deleting both gets the grep to zero matches and removes the redundant alias.
- **`invalidateChapterIndex` / `invalidateChapterIndexFor` kept as no-op shims, not deleted.** ~30 call sites would need updates if these were removed entirely. The brief permits either approach; no-op shims preserve API compat with zero risk.
- **`_walkSilenceRange` helper deleted.** It existed as a shared helper between `derivedTimings` and the in-place mutators. With both mutators deleted, the helper had a single caller; inlining the 12-line loop into `derivedTimings` was cleaner than keeping the abstraction.
- **`segDerivedProps` migrated to read from `derivedTimings`.** Required for the filter subsystem to keep working after the in-place writes were deleted. Not explicitly called out in the brief but a logical consequence of removing the in-place fields.

---

## Patterns established

- **Validation at route boundary (additive only).** New rejections (HTTP 400) for malformed envelopes; never tightens what was previously accepted. Legacy ops without a `type` discriminator pass through. The two helpers (`_validate_command_envelopes`, `_apply_registry_auto_suppress`) compose cleanly into the existing phased orchestrator (`save_seg_data` → validate → load → apply → registry-write → persist-and-record).
- **Field-absent vs explicit-empty distinction at save time.** `_uids_with_explicit_ignored_categories(updates)` builds a uid set from the original `updates["segments"]` array. The auto-suppress helper consults this set to decide whether to write or skip — preserving MUST-7 (`ignored_categories: []` clears persisted ignores).
- **Derived stores as canonical read path.** `derivedTimings` keyed by `segment_uid` replaces the in-place mutation pattern. Render-path consumers, filter logic, and neighbour-sort all consult the same map.
- **No-op shim documentation.** Removed-cache invalidation calls collapse to documented no-op shims with explicit "intentionally empty" comments rather than failing closed.

---

## Invariant check

- **MUST-1**: routes additive only. ✓ — only new HTTP-400 rejection paths added; no field removed or renamed in any route response. Verified by reading `git diff 29512f0..HEAD -- inspector/routes/ inspector/services/save.py`.
- **MUST-2**: `detailed.json` schema unchanged. ✓ — no Phase 7 changes to persistence shape.
- **MUST-3**: `segments.json` format unchanged. ✓ — no adapter or persistence changes.
- **MUST-4**: `segment_uid` stability preserved. ✓ — Phase 4 work unaffected.
- **MUST-5**: Ignore button visibility from registry. ✓ — no regression.
- **MUST-6**: Classifier parity. ✓ — no regression.
- **MUST-7**: empty `ignored_categories: []` clears persisted ignores. ✓ — verified by `_uids_with_explicit_ignored_categories` honouring explicit `[]`. `test_save_clears_ignores.py` continues to pass unchanged.
- **MUST-8**: patch-based undo. ✓ — Phase 5 work unaffected. `test_route_undo.py::test_undo_batch_patch_records` still passes.
- **MUST-9**: validation issues by uid. ✓ — Phase 6 work unaffected.
- **MUST-10**: registry-driven extensibility. ✓ — no regression; new validation reads through `services.validation.registry`.
- **MUST-11**: no refactor-trace breadcrumbs. ✓ — verified by the Stage 9 grep.
- **IS-7 fully enacted**: `_byChapter` and `_byChapterIndex` deleted from production code. `segmentsStore` (Phase 4b derived) is now the only normalized state path. `chapter.ts` selectors derive directly from `segAllData` on every read.

---

## Phase metrics

- **Files modified**: 7 production + 7 test (4 xfail removals + 3 fixture envelope additions) + 4 doc (bug-log, this handoff, ValidationPanel comment, stale.ts docstring).
- **LOC added/removed**: ~+200 / ~-180 net (validation logic + fixtures vs. cache machinery + in-place mutators).
- **Wall-clock**: ~30 min single agent.
- **Test surface**:
  - pytest: 123 passed / 14 xfailed / 2 xpassed → 139 passed / 0 xfailed / 0 xpassed.
  - vitest: 204 passed / 15 todo → 204 passed / 15 todo (unchanged; no new tests, no failures).

---

## No next phase — refactor complete

Phase 7 is the final cleanup. All phase-N markers cleared (0 xfail, 0 xpass). All MUST invariants pass. Bug log B-4 closed; B-5 documented as low-priority for any future lazy-loading work. The branch is merge-clean.

Pre-merge stop-point S7 (manual smoke-test) is the only remaining gate.
