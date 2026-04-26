# Phase 7 Cleanup — Sonnet Quality Review Brief

This file is **pre-committed** before Phase 7 implementation begins. The orchestrator wrote this brief specifying what Phase 7 should accomplish, then implemented Phase 7 itself, and now hands this exact brief to a Sonnet reviewer. The pre-commitment prevents the orchestrator from softening verification criteria after the fact.

You are the Sonnet quality reviewer. Read-only. **DO NOT modify files. DO NOT commit. DO NOT spawn agents.** Be skeptical — the implementer (the orchestrator itself) may have cut corners or missed consumers.

## Working environment

- **Working dir**: `C:\Users\ahmed\Documents\Work\my-projects\quranic-universal-audio\.claude\worktrees\inspiring-ramanujan-2d4e7e`
- **HEAD**: the new Phase 7 commit (read with `git log --oneline -3`)
- **Baseline**: `29512f0` (Phase 6)
- **Diff to review**: `git diff 29512f0..HEAD`

## Required reading

1. `.refactor/plan.md` — §Invariants (MUST-1..11, IS-7 specifically), §Success Criteria.
2. `.refactor/bug-log.md` — B-4 entry should be moved from Section 2 (Active) to Section 3 (Resolved) post-Phase 7.
3. `.refactor/phase-7-handoff.md` — full file.
4. `.refactor/phase-4-handoff.md` — the "Deferred to Phase 5" / Phase 4b appendix that listed `_byChapter` consumer migration as a follow-up.
5. `.refactor/phase-6-handoff.md` — the 3 minor Opus findings (stale ValidationPanel comment, empty-string uid drop, mid-load race).

## What Phase 7 was supposed to do (committed up front)

The orchestrator presented these items as the Phase 7 scope, before implementing:

1. **B-4 resolution**: Backend SAVE route rejects (HTTP 400) malformed `command` envelopes; SAVE handler writes `ignored_categories` based on the registry rather than trusting the payload. **4 pytest phase-3 markers cleared.**

2. **`_byChapter` consumer migration (IS-7 full enactment)**: ~50 consumer sites migrated from `stores/chapter.ts` legacy selectors to `stores/segments.ts` derived selectors. The `_byChapter` and `_byChapterIndex` module-level cache vars in `chapter.ts` **deleted** (not hidden, not renamed). Invalidation functions deleted or stripped to no-op shims. Compat re-exports for `$segData`/`$segAllData` subscribers preserved.

3. **`SegmentsList.svelte` → `$derivedTimings` migration**: Component reads `silence_after_ms` from `$derivedTimings`, not from `seg.silence_after_ms` directly. The in-place mutation functions `computeSilenceAfter` / `recomputeSilenceForRange` deleted (or made private inside `filters.ts`) once no consumers remain.

4. **Stale comment in `ValidationPanel.svelte`** (~line 336) referencing deleted `fixups.ts` removed.

5. **Stale `SegAllDataState` interface in `types/segments.ts`** deleted (Phase 4b deferred item).

6. **2 inline notes / bug-log entries** documenting the truly zero-impact items:
   - Empty-string `segment_uid` drop in `filterStaleIssues` (unreachable — backend canonicalizes `""→None`)
   - Mid-load race (not exercised today; would only matter if lazy chapter loading is added)

## Verification protocol — be skeptical

The implementer is the orchestrator itself. Possible footguns:
- "Migrated" some consumers but missed a long tail
- "Deleted" the cache at one site but left dead references elsewhere
- Marked B-4 cleared but the new validation is loose (rejects only the exact test inputs, not all malformed shapes)
- Slipped a refactor-trace breadcrumb into the diff
- Introduced a new dual path while removing an old one

### A. B-4 resolution

- Run: `grep -rn "phase-3" inspector/tests --include="*.py" | grep -v __pycache__`. Expected: ZERO `@pytest.mark.xfail(reason="phase-3"` matches.
- Read `inspector/services/save.py` validation logic. Verify HTTP 400 on:
  - missing `command` envelope
  - `command.type != op.type` mismatch
  - unknown `command.type` values
- Read save handler. Verify `ignored_categories` write reads from `inspector/services/validation/registry.py:apply_auto_suppress` or equivalent registry-driven helper, NOT from raw payload.
- **MUST-1 check**: only additive rejection. Read the diff: any previously-accepted field now rejected? Any previously-emitted response field removed?
- Run the 4 originally-deferred tests by name: `test_history_record_reflects_command_result_metadata`, `test_edit_from_card_records_suppression_per_registry`, `test_command_save_round_trip`, `test_save_payload_is_correctly_built_from_command_results`. All should pass.

### B. `_byChapter` consumer migration

- Run: `grep -rn "_byChapter\b\|_byChapterIndex\b" inspector/frontend/src --include="*.ts" --include="*.svelte"`. Expected: ZERO production matches. Test files asserting "the cache is gone" are OK; classify each match.
- Read `inspector/frontend/src/tabs/segments/stores/chapter.ts`: `_byChapter` and `_byChapterIndex` module-level vars must be GONE (not commented out, not renamed to `_byChapterLegacy`, just gone). Their invalidation functions (`invalidateChapterIndex`, `invalidateChapterIndexFor`) either deleted entirely OR converted to no-op shims with explicit "kept for API compat" justification.
- Spot-check 5 random consumer files. Pick a mix:
  - `inspector/frontend/src/tabs/segments/utils/edit/split.ts`
  - `inspector/frontend/src/tabs/segments/utils/edit/merge.ts`
  - `inspector/frontend/src/tabs/segments/utils/edit/delete.ts`
  - 2 random `.svelte` components from `components/`
  - Verify each imports `getChapterSegments`/`getSegByChapterIndex`/`getAdjacentSegments` from `stores/segments.ts` (NOT `stores/chapter.ts`), or reads via a unified compat re-export.
- Subscriber preservation: `$segData` and `$segAllData` exports from `chapter.ts` still work — existing components subscribing to them don't break. Run `grep -rn "\\$segData\\|\\$segAllData" inspector/frontend/src/tabs/segments/components/`. List subscribers. Spot-check that one of them still functions (is it imported correctly? are its types unchanged?).

### C. `SegmentsList.svelte` migration

- Read `inspector/frontend/src/tabs/segments/components/SegmentsList.svelte` (or its current location — find it via grep if moved). Find every `silence_after_ms` reference. Each must read from `$derivedTimings`, not from `seg.silence_after_ms`.
- Run: `grep -n "seg\.silence_after_ms\|\\.silence_after_ms\\b" inspector/frontend/src/tabs/segments/components/SegmentsList.svelte`. Each result must be a derived-store access pattern, not direct field read.
- Run: `grep -rn "computeSilenceAfter\|recomputeSilenceForRange" inspector/frontend/src`. Each match must be EITHER inside `stores/filters.ts` (private/internal) OR zero matches if fully deleted. Report exact count + locations.
- Run: `grep -n "\\.silence_after_ms\\s*=" inspector/frontend/src/tabs/segments/stores/filters.ts`. Expected: ZERO in-place mutation assignments.

### D. Stale comment + interface deletion

- Run: `grep -n "fixups" inspector/frontend/src/tabs/segments/components/validation/ValidationPanel.svelte`. Expected: ZERO matches.
- Run: `grep -rn "SegAllDataState\b" inspector/frontend/src`. Expected: ZERO matches (interface gone, no references).

### E. Ignored-item documentation

- Inline comments in `inspector/frontend/src/tabs/segments/utils/validation/stale.ts` (or wherever `filterStaleIssues` lives) explaining the empty-string defensive case and why it's unreachable.
- Documented (inline OR in bug log as e.g. B-5/B-6) note about the mid-load race — what it is, why it's not exercised today, when it would matter.
- If documented in bug log: the entries should be in Section 2 (Active) with status OPEN-LOW-PRIORITY or similar, NOT silently swept under the rug.

### F. MUST invariants (verify NOTHING regressed)

- **MUST-1 routes additive**: `git diff 29512f0..HEAD -- inspector/routes/ inspector/services/save.py | head -200`. Verify no field removal/rename.
- **MUST-2** detailed.json schema unchanged.
- **MUST-3** segments.json format unchanged.
- **MUST-4** segment_uid stability preserved (Phase 4 work intact).
- **MUST-7** empty `ignored_categories` clears persisted. With Phase 7 making the SAVE handler registry-driven, verify the test `test_save_clears_ignores.py` (or equivalent) still passes for the explicit `[]` clear case.
- **MUST-8** patch-based undo (Phase 5 intact).
- **MUST-9** validation issues by uid (Phase 6 intact).
- **MUST-11**: NO breadcrumb phrases. Run:
  ```
  git diff 29512f0..HEAD --no-color -- ':!.refactor/' ':!inspector/tests/fixtures/' ':!docs/inspector-segments-refactor-plan.md' | grep -E '^\+' | grep -inE '(// refactored|// removed|# refactored|# removed|previously this|previously did|now uses the new|now dispatches via|migrated from|replaced by|superseded by Phase|before this refactor|as of Phase|legacy [A-Z][a-z]+ handling)'
  ```
  Expected: ZERO matches. List any.
- **IS-7 enactment status**: pre-Phase-7 was "half enacted" (cache hidden, not retired). Post-Phase-7: must be "fully enacted" (cache deleted, all consumers on new path). Provide evidence.

### G. Test surface (counts + regressions)

- Run `python -m pytest inspector/tests/ -q 2>&1 | tail -5`. Compare to baseline: pytest 123 passed / 14 xfailed / 2 xpassed. Expected post-Phase-7: passed ≥ 127 (4 B-4 markers cleared → 4 new passes, possibly more from parametrization expansion); xfailed dropped by 4 (the 4 phase-3 parametrizations) plus possibly more if implementer cleared other markers.
- Run `cd inspector/frontend && npx vitest run --reporter=default 2>&1 | tail -10`. Compare: 204 passed / 15 todo. Expected: passed ≥ 204; no NEW failures (timestamps tab errors are pre-existing, allowed).
- Run `bash .refactor/checks.sh` step 5: report all phase markers. Expected: phase-3 = 0 (cleared by B-4 work), phase-4/5/6 unchanged at 0.

### H. Anti-corner-cutting checks

The orchestrator-as-implementer may have:
- **Removed cache reads but left the cache writes**: verify by reading `chapter.ts` for any leftover `_byChapter[ch] = ...` assignment. Should be zero.
- **Deleted `computeSilenceAfter` from exports but left it as a private function**: verify with `grep -n "function computeSilenceAfter\|const computeSilenceAfter" inspector/frontend/src/tabs/segments/stores/filters.ts`. If found, check if it's still called from anywhere internal to filters.ts; if not, delete it.
- **Migrated 30 of 50 consumers and called it good**: spot-checked the 5 above; if any still imports from old path, this is a partial migration. Estimate by `grep -rn "from.*['\"].*stores/chapter['\"]" inspector/frontend/src/tabs/segments/ | wc -l`. Compare to consumers importing from `stores/segments`.
- **Fixed the stale comment by replacing it with another stale comment**: read the surrounding 5 lines of any change.
- **Marked B-4 cleared by deleting the tests rather than fixing the code**: verify the 4 named tests in section A still EXIST and ASSERT meaningful behavior.

### I. Bug log update

- B-4 entry moved from Section 2 (Active) to Section 3 (Resolved). Status updated to RESOLVED-fix-<SHA>.
- Phase 7 SHA substituted (no `_(this c<!---->ommit's SHA)_` placeholder leftover).
- New entries B-5/B-6 if any of the documented zero-impact items got formal entries (optional; inline comments are also acceptable).

### J. Handoff doc

- `.refactor/phase-7-handoff.md` exists with sections matching prior phases (What was done / Decisions that differ from plan / Patterns / Invariant check / Phase metrics / Risks for next phase OR "no next phase" if this closes the refactor).

## Output format

```
# Phase 7 Cleanup Review

## Verdict
ACCEPT | ACCEPT-WITH-WARNINGS | REVISE

## Findings

### CRITICAL
- (any item that fails a MUST or leaves a Phase-7-claimed deliverable unresolved without rationale)

### WARNING
- (any partial-migration / dead-code / softened-claim items)

### INFO
- (notable non-blocking observations)

## Per-deliverable verdicts (the central table)
| Item | Pass | Partial | Fail | Evidence |
|---|---|---|---|---|
| B-4: 4 pytest phase-3 markers cleared | | | | |
| B-4: HTTP 400 on malformed command envelope | | | | |
| B-4: registry-driven ignored_categories write | | | | |
| _byChapter cache actually deleted | | | | |
| _byChapter consumers fully migrated | | | (N still on old path) | |
| computeSilenceAfter status | (deleted) | (private only) | (still exported) | |
| SegmentsList → derivedTimings | | | | |
| Stale ValidationPanel comment removed | | | | |
| SegAllDataState interface deleted | | | | |
| Empty-string uid drop documented | | | | |
| Mid-load race documented | | | | |
| B-4 entry moved to bug-log Section 3 | | | | |
| phase-7-handoff.md present and complete | | | | |

## MUST invariants final state
- MUST-1 .. MUST-11: pass | fail per — evidence

## IS-7 enactment status
- Pre-Phase-7: half-enacted (cache hidden, parallel paths)
- Post-Phase-7: __ (provide evidence with greps)

## Test surface
- pytest: 123/14/2 → __
- vitest: 204/15 → __
- xfail count: phase-3 = __

## Anti-corner-cutting verdict
- Cache writes left after read removal: yes | no | n/a
- computeSilenceAfter dead code: yes | no
- Partial-migration consumers: __ files still on old path
- Tests deleted instead of fixed: yes | no
- Comment swapped, not removed: yes | no

## Recommendation
- Accept Phase 7 | Phase 7b corrections needed (list specific items) | Revert
```

Cap at 1000 words. Be specific: file paths, line numbers, exact grep counts. The orchestrator will not ship without your sign-off; do not soften.
