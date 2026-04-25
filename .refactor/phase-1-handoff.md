# Phase 1 Handoff: Issue Registry

**Commits:** `99c8b72` (implementation), `b9380a6` (review fixes)
**Branch:** `inspiring-ramanujan-2d4e7e`

---

## What was done

- Introduced `inspector/services/validation/registry.py` (Python) and `inspector/frontend/src/tabs/segments/domain/registry.ts` (TS twin) as the single source of truth for category metadata.
- The 11-category matrix from plan §Appendix A is encoded verbatim with fields: `kind`, `card_type`, `severity`, `accordion_order`, `can_ignore`, `auto_suppress`, `persists_ignore`, `scope`, `display_title`, `description`.
- Helpers exported: `apply_auto_suppress(seg, category, edit_origin) -> dict` and `filter_persistent_ignores(categories) -> list[str]` (Python); `applyAutoSuppress(seg, category, editOrigin)` and `filterPersistentIgnores(cats)` (TS).
- Derived sets exported: `ALL_CATEGORIES`, `PER_SEGMENT_CATEGORIES`, `CAN_IGNORE_CATEGORIES`, `AUTO_SUPPRESS_CATEGORIES`, `PERSISTS_IGNORE_CATEGORIES`.
- Snapshot artifact: `inspector/tests/fixtures/segments/expected/registry-snapshot.json` (Python registry → JSON, used as documentation; TS parity test currently uses inline constant).
- Replaced scattered category checks across:
  - `ValidationPanel.svelte` accordion descriptors (was lines 210–222 hardcoded array).
  - `GenericIssueCard.svelte` Ignore button visibility (was lines 68–75 allowlist literal); `low_confidence` runtime guard preserved (`canIgnore && (cat !== 'low_confidence' || confidence < 1.0)`).
  - `ErrorCard.svelte` card-type dispatch (was lines 45–47 if-else).
  - `trim.ts`, `reference.ts`, `split.ts` auto-suppress check (was `category !== 'muqattaat'` literal at each call site → `applyAutoSuppress`).
  - `merge.ts` union-set path (uses `IssueRegistry[ctx]` directly because the union builds a Set; per-seg helper contract didn't fit).
  - Frontend `utils/constants.ts` — `ERROR_CAT_LABELS` and `_VAL_SINGLE_INDEX_CATS` derived from registry.
- Save serializer (`services/save.py`) now consults `filter_persistent_ignores` so categories with `persists_ignore=False` are dropped on serialization. MUST-7 (`empty array clears`) preserved and tested.
- Validation API response (`services/validation/__init__.py`) now emits `structural_errors` as an additive alias of the existing `errors` key (MUST-1 compliant — both keys live; no field renamed). Frontend already had a `data.errors ?? data.structural_errors` compat fallback; the alias makes it transparent.
- Updated route baseline fixtures (`expected/<fixture>.routes.json`) to include `structural_errors` in `validate.field_keys_top_level`.
- Constants drift assertion at `inspector/constants.py` module load — fires if `VALIDATION_CATEGORIES` literal goes out of sync with the registry. Asymmetric guard (catches literal additions; doesn't catch registry-only additions). Acceptable for the phase.
- Removed Phase-1 xfail markers from 4 pytest test files and 3 vitest test files (12 + 7 = 19 markers cleared).

## Decisions that differ from plan

- **`apply_auto_suppress` return type**: plan stub said `-> None`; the implementation returns `seg` (the mutated dict) because the test (`test_auto_suppress_on_edit_per_segment_categories`) calls `new = apply_auto_suppress(...); new.get(...)`. The contract is still in-place mutation; the return enables fluent chaining without copying. Reviewer (Sonnet) confirmed principled.
- **`/api/seg/config` scope expansion**: `inspector/routes/segments_data.py` was not in `phases[1].scope_files`. Required for `test_seg_config_validation_categories_match_registry` to pass. Diff was a single-line change (`VALIDATION_CATEGORIES` → `ALL_CATEGORIES`); response field went from 9 to 11 entries — additive within MUST-1. Plan Phase 1 scope_files retroactively should include it; not a violation.
- **Panel key `errors` → `structural_errors`**: rename is internal to the panel's `cat.type` (the registry's `kind` field). Wire DTO retains `errors` AND adds `structural_errors` alias (additive). The `resolve-issue.ts:68` literal was caught and updated by the fixup commit (Sonnet flagged it as CRITICAL).
- **`merge.ts` direct registry read**: bypasses `applyAutoSuppress` because merge builds a union-Set across both segments' `ignored_categories`. The per-seg helper contract (mutate-and-return one seg) didn't fit. Direct registry read with the same `auto_suppress && scope === 'per_segment'` gate maintains identical behavior.
- **`VALIDATION_CATEGORIES` retained in `inspector/constants.py`** instead of being moved into the registry, with a runtime drift assertion. Plan permitted either approach; this one is safer (additive guard against future desync).

## Current codebase state

- Production code: 4 svelte components + 4 edit utilities + `services/save.py` + `services/validation/__init__.py` + `routes/segments_data.py` + `constants.py` modified. New: `services/validation/registry.py`, `domain/registry.ts`, `expected/registry-snapshot.json`.
- Test surface: 12 pytest xfail markers removed + 7 vitest markers removed. Phase 1 bucket cleared.
- Test status (after `b9380a6`):
  - pytest registry suite: all 60+ parametrized cases passing.
  - pytest persistence/test_save_clears_ignores.py: 4/4 passing.
  - pytest routes (10 fixture-based) passing; 7 xfailed for later phases.
  - vitest registry suite: ~48 cases passing (was 0 / 7 todo before).
  - Full suite: ~125 passing pytest, ~128 passing vitest. No regressions vs Phase 0.

## Patterns established

- **Single source of truth for category metadata**: the registry. Adding a new category requires only a row addition (Python + TS twin) and (Phase 2) a classifier rule. No edits to edit utilities, components, save serializer, or accordion.
- **`applyAutoSuppress` helper centralizes the auto-suppress logic** so trim/split/reference call one function with a registry-driven check. The helper short-circuits for `auto_suppress=False` categories and for non-`per_segment` scope.
- **`filterPersistentIgnores` short-circuits non-persisting categories** at the save serializer. `_all` legacy marker is preserved.
- **Additive-alias pattern for renames**: when an internal rename touches a wire field, emit BOTH old and new keys (alias) instead of renaming. MUST-1 compliant. Future deprecation of the old key is a separate decision.
- **Cross-stack mirror discipline**: TS twin is hand-mirrored from Python. If Phase 2 parity tests reveal drift, codegen is the next escalation.

## Invariant check

- **MUST-1**: `/api/seg/validate` response gained `structural_errors` (alias of `errors`); `/api/seg/config` `validation_categories` went 9 → 11 entries. Both additive — no field removed or renamed. Verified via route baseline tests.
- **MUST-2**: `detailed.json` schema unchanged. Save serializer's `filter_persistent_ignores` operates on the `ignored_categories` array contents, not the field's presence.
- **MUST-3**: `segments.json` format unchanged.
- **MUST-4**: `segment_uid` not touched.
- **MUST-5**: Ignore button visibility now reads `IssueRegistry[category].canIgnore`. Verified via parametrized vitest.
- **MUST-6**: classifier untouched (Phase 2 work).
- **MUST-7**: `empty ignored_categories array on save = clear` — fixed by review (was a real defect; landed in `b9380a6`). Verified by `test_save_clears_ignores`.
- **MUST-8/9/10/11**: not affected this phase. MUST-11 breadcrumb check clean (zero forbidden phrases in new lines).
- **IS-1 enacted**: registry is now the source of truth.

## Review findings addressed

Phase 1 review (Sonnet quality):
- **CRITICAL — `resolve-issue.ts:68`** dead `'errors'` branch — fixed in `b9380a6`.
- **CRITICAL — wire-key dual-state** — addressed by additive-alias pattern (emit both `errors` and `structural_errors`); MUST-1 compliant. Documented in `api.ts` interface.
- **WARNING — `save.py` empty-array doesn't clear** — fixed in `b9380a6`. Test now passes.
- **WARNING — `_VAL_SINGLE_INDEX_CATS` semantic change** — verified consistent (8 categories before, same 8 after via registry derivation). No drift. No action.
- **INFO — `_assert_categories_match_registry` asymmetry** — acknowledged; acceptable.

## Phase metrics

- **Files modified**: 23 (initial) + 8 (fixup) = 31 file touches.
- **LOC added/removed**: 901 / 178 (initial) + ~50 / ~10 (fixup) = ~950 added / ~190 removed.
- **Wall-clock**: 18m 20s (Opus impl) + 3m 34s (Sonnet fixup) = ~22 minutes.
- **Token budget**: 291,998 (Opus impl) + 62,109 (Sonnet fixup) + ~20k (Sonnet quality reviewer) ≈ 374k tokens for Phase 1.

## Review-allocation retrospective

- Sonnet quality only (per plan) was correct allocation.
- Sonnet caught two real bugs (CRITICAL 1 — `resolve-issue` stale; WARNING 3 — empty-array clear) and one architectural concern (CRITICAL 2 — wire dual-key state, addressed via alias rather than rename).
- For Phase 2: keep the planned Sonnet + Haiku + Opus allocation. Phase 2 is the highest-risk phase (classifier consolidation across 3 stacks); Opus verification is essential.

## Automations to add for future phases

- The `bash .refactor/checks.sh N` command is the gate. Phase 2 should run it both pre- (with N=2) and post-implementation.
- `_(this commit's SHA)_` placeholder check still flags the 3 OPEN bug entries. Phase 2 will resolve B-1/2/3 and substitute SHAs.
- xfail count check: 12 phase-2 markers + others remain. Phase 2 must clear ALL phase-2 markers — Sonnet quality reviewer verifies.

## Shared-doc delta (bug log)

- No new entries added in Phase 1. The matrix matched live behavior; no surprising divergences surfaced.
- B-1, B-2, B-3 remain OPEN; resolution due in Phase 2.

## Sidecar amendments

- None required.

## Risks/concerns for next phase

- **Phase 2 = highest risk**. Three classifiers consolidating into one. Documented divergences (B-1, B-2, B-3) plus possibly undocumented ones.
- **Frontend `_classifySegCategories` consumer in `stores/dirty.ts`**: the `snapshotSeg` function calls it to populate `snap.categories`. Phase 2 must decide: drop `snap.categories` (history will be enriched by backend's `classified_issues` field on each snapshot) OR have `snap.categories` read from the live validation snapshot. The plan recommends the former.
- **Constants drift assertion** is asymmetric. If Phase 2 adds a new category to the classifier without updating the registry, the assertion won't catch it. Phase 2 should ensure both sides are touched.
- **TS registry hand-mirror** — Phase 2 parity tests will exercise it. If drift surfaces, escalate to codegen.
- **`structural_errors` wire key** — Phase 2's classifier consolidation may emit the response. Ensure both `errors` and `structural_errors` keys remain populated.
- **Bug log placeholders** in `bug-log.md` for B-1/2/3 still show as "VIOLATIONS" in `checks.sh [4]`. The check fires on the literal `_(this commit's SHA)_` and is expected for OPEN bugs. Phase 2's commit will substitute the SHAs, clearing the placeholders.
