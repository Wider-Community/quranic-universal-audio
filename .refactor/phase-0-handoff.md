# Phase 0 Handoff: Test Infrastructure + Fixtures

**Commits:** `4be27a3` (initial), `6223ba8` (review fixes)
**Branch:** `inspiring-ramanujan-2d4e7e`

---

## What was done

- Created the upfront test suite gating the rest of the refactor: 73 files at initial commit, 18 modified/new at fixup commit.
- Pytest test suite at `inspector/tests/` — registry, classifier, routes, persistence, command, undo, identity, parity (~36 test files / ~3000 LOC).
- Vitest test suite at `inspector/frontend/src/tabs/segments/__tests__/` — registry, command, normalized-state, save, identity, parity (~17 test files).
- Shared JSON fixtures at `inspector/tests/fixtures/segments/`:
  - `112-ikhlas.detailed.json` — real Minshawi slice + one synthetic confidence drop (low_confidence trigger).
  - `113-falaq.detailed.json` — real Minshawi slice + 3 synthetic injections (audio_bleeding, cross_verse, boundary_adj).
  - `synthetic-classifier.detailed.json` — one segment per per-segment category.
  - `synthetic-structural.detailed.json` — covers missing_verses, missing_words, structural_errors.
  - Each fixture carries `_fixture_meta` documenting per-segment intended classifications.
- Expected-output baselines at `inspector/tests/fixtures/segments/expected/`:
  - `<fixture>.classify.json` — post-Phase-2 unified classifier expected output (4 files).
  - `<fixture>.routes.json` — MUST-1 baseline for HTTP route response field-key sets (4 files; added in fixup commit).
- Snapshot regenerator scripts:
  - `inspector/tests/parity/snapshot_expected_outputs.py` — regenerates `*.classify.json` (rerun after Phase 2's classifier consolidation).
  - `inspector/tests/parity/snapshot_route_baselines.py` — regenerates `*.routes.json` (rerun if MUST-1 baseline ever needs re-anchoring; intentionally a manual operation).
- Test infrastructure:
  - `inspector/tests/conftest.py` extended with `load_fixture`, `load_expected`, `flask_client`, `fresh_registry`, `tmp_reciter_dir`, `assert_keys_superset` helpers.
  - `inspector/frontend/src/tabs/segments/__tests__/helpers/` — `fixtures.ts`, `make-segment.ts`, `optional.ts`, `xfail.ts`, `categories.ts`.
  - `inspector/frontend/vitest.config.ts` — added `@fixtures` Vite alias resolving to `inspector/tests/fixtures/segments/` so frontend imports the same JSON files as pytest.
- `.refactor/` artifacts committed as part of Phase 0: `plan.md`, `plan.yaml`, `test-inventory.md`, `bug-log.md`, `orchestration-log.md`, `checks.sh`.

## Decisions that differ from plan

- Vitest config alias is a clean single-line addition; no `vite.config.ts` changes needed.
- xfail strategy combines `pytest.importorskip` (file-level for missing future modules) with `@pytest.mark.xfail(strict=False)` per-test, and `loadOptional()` + `describe.skipIf(!mod)` + `xfail("phase-N", ...)` helper on the vitest side. Cleanly handles both "module doesn't exist yet" and "module exists but wrong shape" cases.
- 5 expected XPASSes documented in agent report — current behavior happens to match the target in those specific cases (e.g. legacy ignored boolean migration, basic schema additivity probes). Per user directive (`strict=False`), these are acknowledged, not fixed.
- `_fixture_meta` field added as a top-level key on each fixture detailed.json. Backend loader reads only `_meta` and `entries`, so this addition is invisible to production code (additive-only consistent with MUST-2).
- Conftest's `tmp_reciter_dir` monkeypatches `RECITATION_SEGMENTS_PATH` on six modules (`config`, `routes.segments_data`, `routes.segments_edit`, `routes.segments_validation`, `services.data_loader`, `services.history_query`, `services.save`, `services.undo`) and invalidates seg-related caches. Without this, route tests would read from the real data directory.
- The fixup commit (`6223ba8`) added `routes.segments_validation` to the patched-modules list (Sonnet quality reviewer caught the omission).

## Current codebase state

- Production source: untouched. `git diff 8e535bc..6223ba8 -- inspector/services inspector/routes inspector/frontend/src/tabs/segments/components inspector/frontend/src/tabs/segments/utils inspector/frontend/src/tabs/segments/stores validators` returns no changes.
- Test surface went from 9 tests to 90 collected (pytest) + 216 collected (vitest, including 16 todo and 120 skipped).
- Suite final state at `6223ba8`: pytest 46 passed / 11 skipped / 34 xfailed / 5 xpassed; vitest 80 passed / 120 skipped / 16 todo / 0 unexpected failures (2 pre-existing fetch errors in unrelated timestamps tests).
- xfail bucket counts: Phase 1 = 19 (pytest) + 7 (vitest); Phase 2 = 14 + 3; Phase 3 = 5 + 57; Phase 4 = 4 + 11; Phase 5 = 7 + 2; Phase 6 = 7 + 6. Total 135 xfails. (Inventory projected ~121; the Phase 3 expansion comes from per-command parametrization that the inventory abstracted as fewer test functions.)

## Patterns established

- **Fixture import (cross-stack):** pytest reads via `load_fixture("name")` from `conftest.py`; vitest imports via `import data from '@fixtures/<name>.detailed.json'`. Same file, same JSON.
- **Deferred modules:** for Phase-N tests asserting symbols not yet present, use `pytest.importorskip` (Python) or `loadOptional()` + `describe.skipIf(!mod)` (TS).
- **xfail markers:** every Phase-N test carries an explicit `reason="phase-N"` (pytest) or `xfail("phase-N", body)` (vitest). Sonnet quality reviewer of each subsequent phase verifies that phase-N markers are removed when the phase commits.
- **Registry parametrization placeholder:** until Phase 1 lands the registry, tests reference `ALL_CATEGORIES`, `PER_SEGMENT_CATEGORIES`, `CAN_IGNORE_CATEGORIES`, `AUTO_SUPPRESS_CATEGORIES` constants in `conftest.py` and `helpers/categories.ts`. Phase 1 replaces these with `from inspector.services.validation.registry import IssueRegistry; ALL_CATEGORIES = list(IssueRegistry.keys())`.
- **Route baseline:** `expected/<fixture>.routes.json` records top-level field-key sets per route; route tests assert `keys(response) ⊇ baseline_keys` (additive-only, MUST-1).
- **Fixture meta self-doc:** `_fixture_meta.segments[i].expected_categories` enumerates the categories each segment should classify as, post-Phase-2.

## Invariant check

- **MUST-1**: route response shapes captured in `expected/*.routes.json`. Route tests now assert key-superset against these baselines. Verified: 4 baselines generated.
- **MUST-2**: `_fixture_meta` is a new top-level key on detailed.json fixtures only; backend production loaders read only `_meta` and `entries`, so the new key is invisible to them. No removal or rename of existing fields.
- **MUST-3**: segments.json format unchanged; Phase 0 doesn't write segments.json.
- **MUST-4..MUST-10**: no production code changed; these are tested by Phase-1+ work.
- **MUST-11**: zero refactor-trace breadcrumbs in test code introduced by Phase 0. Sonnet quality reviewer scanned all 73 files and confirmed clean. Fixup commit additionally rewrote 5 transitional docstrings ("Pre-Phase-3", "post-Phase-3" wording) into phase-neutral assertion descriptions.
- **IS-changing items**: none scoped to Phase 0; this is pure additions.

## Review findings addressed

- **Sonnet C-1 (CRITICAL)**: `_modules_holding_seg_path()` missing `routes.segments_validation` — fixed in `6223ba8`.
- **Sonnet C-2 (CRITICAL)**: `113-falaq.detailed.json` `_fixture_meta` had `expected_categories: ["qalqala"]` for segments expected to classify as `[]` (suppression via `ignored_categories`) — fixed; consistency between `_fixture_meta` and `expected/*.classify.json` re-asserted.
- **Sonnet W-3/4/5 (WARNING)**:
  - `<T = any>` defaults in `loadFixture`/`loadExpectedClassify` replaced with `RawDetailedFixture`/`RawClassifyExpected` interfaces.
  - `<T = any>` default in `loadOptional` changed to `<T = unknown>` so callers must narrow.
  - Transitional docstrings rewritten to phase-neutral language across 6 test files.
- **Haiku ✗17 (CRITICAL)**: missing `expected/*.routes.json` baselines — generated for all 4 fixtures in fixup commit; route tests upgraded from stub assertions to baseline-anchored `assert_keys_superset` calls.
- **Haiku ✗15 (xfail balance)**: not a real defect; parametrized expansion accounts for the apparent surplus in Phase 3. No action.
- **Haiku ✗16 (bug-log placeholders)**: by design for OPEN bugs B-1/2/3. No action.

## Phase metrics

- **Files modified**: 73 (initial) + 18 (fixup) = 91 distinct file touches across two commits.
- **LOC added/removed**: 6465 / 3 (initial) + 578 / 98 (fixup) = ~7050 added / ~100 removed.
- **Wall-clock for implementation agent**: 32m 43s (Opus, initial) + 9m (Sonnet, fixup) = ~42 minutes total.
- **Build / typecheck / lint final state**: pytest collects clean; vitest collects clean; no production code touched, so typecheck on production unaffected.
- **Token budget**: 320,713 (Opus impl) + ~94,000 (Sonnet fixup) + ~30k each for Sonnet/Haiku reviewers ≈ 470k tokens for Phase 0.

## Review-allocation retrospective

- Sonnet quality + Haiku coverage was correct allocation.
- Sonnet caught two critical defects (conftest module gap, fixture meta inconsistency) and three good-housekeeping warnings — earned its keep.
- Haiku caught the missing `expected/*.routes.json` baselines (genuine completeness gap from inventory). Earned its keep.
- For Phase 1: stay with default Sonnet-only allocation per plan; the registry phase is mechanical-ish.

## Automations to add for future phases

- `.refactor/checks.sh` step 1 (path validity) now correctly skips Phase 0 (pure additions). For Phase 1+, the heuristic walks ancestor dirs to find a real existing root — works as expected.
- Step 8 (MUST-11 breadcrumb scan) currently shows pre-existing references in `inspector/frontend/src/lib/types/api.ts` (an unrelated comment about drift findings) and `package-lock.json`. These predate this refactor; the diff-based filter (`git diff main...HEAD`) was added in the script and excludes pre-existing matches. Verify the diff filter is producing zero hits at every phase boundary.
- Suggest adding step 9 to checks.sh: count the xfail markers per phase and assert they decrease monotonically. Useful starting Phase 2.

## Shared-doc delta (bug log)

- No new entries added in Phase 0.
- B-1, B-2, B-3 remain OPEN with `_(this commit's SHA)_` placeholders awaiting Phase 2 resolution.

## Sidecar amendments

- None required for Phase 1.

## Risks/concerns for next phase

- **Phase 1 must export `IssueRegistry` matching plan §Appendix A exactly.** Required fields (Python keys): `kind`, `card_type`, `severity`, `accordion_order`, `can_ignore`, `auto_suppress`, `persists_ignore`, `scope`, `display_title`, `description`. TS twin uses camelCase: `canIgnore`, `autoSuppress`, `persistsIgnore`, `cardType`, `accordionOrder`. The Phase 1 implementation prompt should explicitly list both naming conventions.
- **Auto-suppress helper**: `test_registry_behavior.py::test_auto_suppress_*` calls a helper `apply_auto_suppress(seg, category, edit_origin)` which Phase 1 must export. Decide its location: probably alongside the registry, or in `inspector/services/validation/registry.py` itself.
- **Categories list source-of-truth migration**: Phase 1 should migrate `inspector/constants.py:VALIDATION_CATEGORIES` (and the associated `MUQATTAAT_VERSES`, `QALQALA_LETTERS`, `STANDALONE_*` sets) into the registry. Tests reference both today; both must keep working through the phase or via re-exports.
- **Frontend registry mirror discipline**: hand-written from Python registry. If drift surfaces in Phase 2 parity tests, Phase 1's handoff should suggest codegen as a follow-up.
- **No production-code touched yet**: all Phase 1+ work writes to production. Pre-phase check now becomes load-bearing for catching scope violations (S4).
