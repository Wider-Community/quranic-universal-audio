# Stage 2 — Wave 8a Handoff (segValidation store promotion)

**Status**: COMPLETE at stopping point 8a.1 (store + memo cleanup).
**Branch**: `worktree-refactor+inspector-modularize`
**Known-good entry commit**: `f8333c6` (Wave 7b review follow-ups)
**Known-good exit commit**: `048d604` (bridge-lag correctness fix)
**Agent**: Claude Sonnet 4.6 (implementation-Wave-8a), 2026-04-14.

---

## 0. At-a-glance

- 2 source commits + 1 fix + this handoff = 4 commits.
- 1 new file (`lib/stores/segments/validation.ts`), 3 modified, 0 deleted.
- 7/7 pre-flight gates GREEN. svelte-check 0/0. Lint 0 errors / 19 warnings
  (ceiling unchanged).
- Cycle ceiling: **19 (unchanged)** — no new cycles introduced.
- Bundle: 129 modules (+1 from 7b's 128), ~507 kB (unchanged).
- Stop-point: 8a.1 (store + D1 memo cleanup). ValidationPanel/ErrorCard
  migration deferred to Wave 8b (see §2.1).

---

## 1. Scope delivered

### 1.1 `lib/stores/segments/validation.ts` — new store (commit `dbeacf9`)

Created `inspector/frontend/src/lib/stores/segments/validation.ts`:

```ts
export const segValidation = writable<SegValidateResponse | null>(null);
export function setValidation(data: SegValidateResponse): void { segValidation.set(data); }
export function clearValidation(): void { segValidation.set(null); }
```

Follows the existing `lib/stores/segments/` pattern (chapter.ts, edit.ts, etc.).
Single `SegValidateResponse | null` field (provisional per S2-D11).

### 1.2 Write sites updated (commit `dbeacf9`)

**`SegmentsTab.svelte`** — 2 write sites:
- `onReciterChange` (was line 249): `state.segValidation = valResult.value` →
  `setValidation(valResult.value)`
- `clearPerReciterState` (was line 296): `state.segValidation = null` →
  `clearValidation()`

Bridge added to store→state sync block:
```svelte
$: state.segValidation = $segValidation; // Wave 8a: store → state bridge
```

**`validation/index.ts::refreshValidation`** (line 436):
```ts
// Before:
state.segValidation = await fetchJson<SegValidateResponse>(...);
// After:
const valData = await fetchJson<SegValidateResponse>(...);
segValidation.set(valData);
state.segValidation = valData; // direct assignment (not through bridge — correct)
```

The explicit `state.segValidation = valData` is intentional: `refreshValidation`
is a plain `.ts` module (not Svelte), so the bridge `$:` doesn't run here.
The direct assignment keeps `state.segValidation` in sync for the
`renderValidationPanel(state.segValidation, ...)` calls that immediately follow.

### 1.3 Fixup helpers: `segValidation.update(v => v)` (commit `dbeacf9`)

All three fixup helpers in `validation/index.ts` now notify store subscribers
after in-place mutation:

```ts
export function _fixupValIndicesForSplit(...): void {
    _forEachValItem(...);
    segValidation.update(v => v); // notify subscribers of in-place mutation
}
// Same pattern for _fixupValIndicesForMerge + _fixupValIndicesForDelete
```

### 1.4 `SegmentsList.svelte` D1 memoization simplification (commit `dbeacf9`)

The `missingWordSegIndices` derivation now keys on `$segValidation` (a real
store) instead of `state.segValidation` (plain field). The `void
$displayedSegments` dep trigger workaround is removed:

```ts
// Before (Wave 7a.2 workaround):
$: missingWordSegIndices = (() => {
    void $displayedSegments; // re-trigger on list refresh (covers save→revalidate)
    if (state.segValidation === _missingCacheValRef && ...) return _missingCache;
    ...
})();

// After (Wave 8a):
$: missingWordSegIndices = (() => {
    // $segValidation is a real store — reactive firing happens automatically
    if ($segValidation === _missingCacheValRef && ...) return _missingCache;
    ...
})();
```

Removed import of `state` from `../../segments/state` (no longer needed).
Added import of `segValidation` from `../../lib/stores/segments/validation`.

### 1.5 Bridge-lag correctness fix (commit `048d604`)

**Bug found post-commit by advisor:** `SegmentsTab.svelte` was passing
`state.segValidation` to `renderValidationPanel()` immediately after
`setValidation(valResult.value)`. Svelte `$:` reactive statements are
batched — they don't fire synchronously within an async function. The
`state.segValidation` field would still be `null` at that point on first
reciter load, causing an empty validation panel.

**Fix:** Pass `valResult.value` directly to `renderValidationPanel`:
```ts
// Before (broken):
setValidation(valResult.value);
renderValidationPanel(state.segValidation); // stale null!

// After (fixed):
setValidation(valResult.value);
renderValidationPanel(valResult.value); // pass directly
```

This is the correct pattern when an imperative call must use store data
immediately after writing to a store inside a Svelte component's async
function. The `$:` bridge is for long-lived reactivity; synchronous
read-after-write must use the value directly.

---

## 2. Scope deferred

### 2.1 ValidationPanel.svelte + ErrorCard.svelte — deferred to Wave 8b

**Decision: defer.** The advisor confirmed this during pre-work orientation.

`renderValidationPanel` in `validation/index.ts` is 420+ LOC of imperative
DOM building with stateful closures (lcThreshold, activeQalqalaLetter,
qalqalaEndOfVerse, batch RAF rendering, context toggle state). The
`renderCategoryCards` function in `error-cards.ts` renders into DOM
containers created by `renderValidationPanel`. `_rebuildAccordionAfterSplit/Merge`
reaches into those imperative containers.

These three modules must be co-migrated — ValidationPanel + ErrorCard + the
accordion lifecycle together. That's a full wave, not a remaining-budget task.
Wave 8b should scope exactly: migrate `renderValidationPanel` → Svelte
`ValidationPanel.svelte`, `renderCategoryCards` → `ErrorCard.svelte`, and
`error-cards.ts` accordion rebuild helpers → reactive store-driven updates.

### 2.2 Stats panel Svelte migration — deferred to Wave 8b or 9

`renderStatsPanel` in `segments/stats.ts` is also imperative. Wave 8b can
optionally include it (simpler than validation — no rebuild helpers).

### 2.3 ReferenceEditor autocomplete — deferred (unchanged from Wave 7b)

### 2.4 All other Wave 7b deferred items (unchanged)

`_addEditOverlay` / `_removeEditOverlay` no-op stubs (Wave 11),
`deleteSegment` confirm() → Svelte UI (Wave 11 or optional Wave 8b),
full Svelte-native drag (Wave 11).

---

## 3. Deviations from plan

### 3.1 Stopping at 8a.1 (store + memo) rather than 8a.3 (ValidationPanel)

**Plan/brief**: Optional progression to ErrorCard.svelte (commit 3),
ValidationPanel.svelte (commit 4), SegmentsTab integration (commit 5).

**Actual**: Stopped at commit 2. The advisor confirmed the ErrorCard/
ValidationPanel migration requires co-migration of the full accordion
container — a full wave, not incremental commits on top of the store work.
The briefed acceptable stopping point "after 8a.1" was taken.

### 3.2 Bridge-lag fix required an additional commit

Not anticipated in the brief. The `$:` batching behavior of Svelte means
store writes in async functions don't synchronously update `state.*` before
the next line runs. This is a general pattern to be watched for in future
waves: any Svelte component that writes a store and immediately passes
`state.field` (the bridge target) to an imperative function must pass the
value directly instead.

---

## 4. Verification results

### 4.1 Pre-flight gates (final run, commit `048d604`)

| Gate | Result | Detail |
|------|--------|--------|
| [1/7] tsc typecheck | PASS | 0 errors |
| [2/7] eslint | PASS | 0 errors, 19 warnings (ceiling unchanged) |
| [3/7] vite build | PASS | 129 modules (+1 from 7b's 128), 507 kB |
| [4/7] no-global-keyword | PASS | Backend unchanged |
| [5/7] no-orphan-cache-vars | PASS | Backend unchanged |
| [6/7] no-cycle-NOTEs | PASS | Zero |
| [7/7] cycle-ceiling | PASS | 19/19 |
| `npm run check` (svelte-check) | PASS | 0 errors, 0 warnings |

### 4.2 D1 memoization: `void $displayedSegments` removed

`SegmentsList.svelte` no longer has the `void $displayedSegments` dep trigger.
The `missingWordSegIndices` derivation fires when either `$segValidation` or
`$selectedChapter` changes — both are real Svelte stores. The `update(v => v)`
calls in the fixup helpers ensure the store notifies on in-place mutation.

### 4.3 Write site audit (all 3 found + fixed)

| Location | Before | After |
|----------|--------|-------|
| `SegmentsTab.svelte` reciter load | `state.segValidation = valResult.value` | `setValidation(valResult.value)` |
| `SegmentsTab.svelte` clearPerReciterState | `state.segValidation = null` | `clearValidation()` |
| `validation/index.ts` refreshValidation | `state.segValidation = await fetchJson(...)` | `const valData = await fetchJson(...); segValidation.set(valData); state.segValidation = valData;` |

### 4.4 Fixup helpers: in-place mutation notification

All 3 fixup functions now call `segValidation.update(v => v)` after
modifying arrays in-place. This ensures `$segValidation` subscribers
(SegmentsList.svelte `missingWordSegIndices`) re-derive after split/merge/delete.

### 4.5 S2-B07 (no module-top-level DOM access)

New `validation.ts` store has no DOM access. SegmentsList changes have no
DOM access. All clean.

---

## 5. Bug-log delta

### New: BL-8a-B1 — $: bridge-lag on renderValidationPanel (FIXED this wave)

**Symptom**: Validation panel would render as empty on first reciter load
because `state.segValidation` was still `null` when passed to
`renderValidationPanel()` immediately after `setValidation()`.

**Root cause**: Svelte `$:` reactive statements are batched and do not fire
synchronously within an async function. The bridge `$: state.segValidation =
$segValidation` had not run yet.

**Fix**: Pass `valResult.value` directly to `renderValidationPanel`.

**General pattern**: When a Svelte component writes a store and immediately
needs the value in an imperative call, pass the value directly — not via
the `state.*` bridge field. The bridge is for long-lived reactive consumption.

---

## 6. Review findings + disposition

**Advisor (pre-work / mid-work):** 2 actionable items.

1. **Stop at 8a.1** — ValidationPanel/ErrorCard require co-migration of the
   full accordion container. Confirmed. Stopped at acceptable point.
2. **Bridge-lag bug** — identified post-commit-1, fixed in commit-2.
   Explicitly: `state.segValidation` is stale at `renderValidationPanel`
   call site in SegmentsTab async handler.

---

## 7. Surprises / lessons

1. **$: bridge-lag is a recurring trap.** When a Svelte component does:
   ```ts
   storeWriteFn(value);
   imperativeCall(state.mirroredField); // WRONG — $: bridge hasn't run
   ```
   The imperative call sees stale state. Fix: pass `value` directly.
   This will recur for `state.segStatsData` (stats panel, Wave 8b) and
   `state.segHistoryData` (history view, Wave 10).

2. **`segValidation.update(v => v)` is needed for in-place mutation.**
   All three `_fixupValIndicesFor*` helpers mutate arrays inside the store
   value without replacing the top-level reference. Without an explicit
   `update(v => v)`, Svelte store subscribers would not re-fire, and
   `missingWordSegIndices` would go stale after split/merge/delete. The fix
   is necessary and correct.

3. **ValidationPanel migration is a full-wave scope item.** The imperative
   accordion in `renderValidationPanel` (stateful lcThreshold/qalqalaLetter
   closures, batch RAF, 420 LOC) and the error-card rebuild helpers
   (`_rebuildAccordionAfterSplit/Merge`) are tightly coupled and must be
   co-migrated. Any attempt to Svelte-ify one without the other produces a
   shell that delegates to nothing useful.

---

## 8. Handoff to Wave 8b

### Prerequisites the next agent must respect

1. **All Wave 7b prerequisites still apply** (audioElRef prop pattern,
   imperative drag modules retained, backdrop scoped to trim/split).
2. **segValidation store** is now the source of truth. All write sites go
   through the store. The `state.segValidation` bridge field is read-only
   from the perspective of the next wave — write to the store, not to state.
3. **Bridge-lag pattern**: When writing to a store in a Svelte component's
   async function and immediately calling an imperative function that needs
   the value, pass the value directly — not `state.mirroredField`.
4. **In-place mutation**: If any new code mutates arrays inside `segValidation`
   in-place, it must call `segValidation.update(v => v)` afterwards.
5. **Cycle ceiling at 19.** Wave 8b work should not increase cycles.

### Queued tasks (Wave 8b)

- [ ] **ValidationPanel.svelte** — Svelte migration of `renderValidationPanel`
  (all 11 categories, lc-slider, qalqala filter, batch RAF rendering, context
  toggle, accordion open-state persistence). Must co-migrate with ErrorCard.svelte.
- [ ] **ErrorCard.svelte** — Svelte migration of `renderCategoryCards` /
  `renderOneItem` / `addContextToggle`. `_rebuildAccordionAfterSplit/Merge`
  become reactive store-driven updates once the list is a `{#each}`.
- [ ] **Stats panel Svelte migration** (optional Wave 8b or Wave 9) —
  `renderStatsPanel` in `segments/stats.ts`.
- [ ] **SegmentsTab integration** — once ValidationPanel/ErrorCard landed,
  remove the `captureValPanelState`/`renderValidationPanel`/`restoreValPanelState`
  calls from SegmentsTab and shrink `validation/index.ts`.
- [ ] **`error-cards.ts` deletion** — after ErrorCard.svelte fully replaces it.
- [ ] **Cycle ceiling decrement** — ValidationPanel migration should dissolve
  the `validation/index.ts → error-cards.ts → state` cycle (currently 1 of
  the 19 warnings).

### Open questions for orchestrator

1. **Wave 8b scope**: Should Wave 8b include both ValidationPanel + Stats, or
   just ValidationPanel? Stats is simpler (no rebuild helpers, no context
   toggles). Including both in 8b may be optimal (same integration commit to
   SegmentsTab).
2. **`_rebuildAccordionAfterSplit/Merge` migration strategy**: Once the card
   list is a Svelte `{#each}`, these imperative DOM rebuilds become store
   mutations + `segValidation.update(v => v)`. The Svelte runtime handles
   the DOM reconciliation. Confirm this approach is sufficient or if a
   `tick()` is needed post-mutation.

---

## 9. Commits (exit-point detail)

```
dbeacf9 feat(inspector): promote state.segValidation to writable store (Wave 8a prerequisite)
048d604 fix(inspector): pass valResult.value directly to renderValidationPanel (bridge-lag fix)
```

2 source commits + this handoff = 3 commits.

---

## 10. Time / token budget (self-reported)

- Tool calls: ~28 (Read/Edit/Write/Bash/Grep/advisor)
- New source files: 1 (validation.ts store)
- Modified source files: 3 (validation/index.ts, SegmentsTab.svelte, SegmentsList.svelte)
- Deletes: none
- Bash: ~8 (typecheck/check/build/lint/git)
- Advisor calls: 2 (pre-work orientation, mid-work wave scope check)
- Model: Claude Sonnet 4.6
- Commits: 2 source + 1 handoff = 3

---

**END WAVE 8a HANDOFF.**
