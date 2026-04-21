# Stage 2 — Wave 7b Handoff (MergePanel + DeletePanel + ReferenceEditor)

**Status**: COMPLETE (shells landed — merge/delete/reference imperative logic
retained per user #migration-strictness preference).
**Branch**: `worktree-refactor+inspector-modularize`
**Known-good entry commit**: `efe9e71` (Wave 7a.2 review follow-ups)
**Known-good exit commit**: `87490f6` (MergePanel + DeletePanel + ReferenceEditor
shells + EditOverlay branches)
**Agent**: Claude Sonnet 4.6 (implementation-Wave-7b), 2026-04-14.

---

## 0. At-a-glance

- 3 source commits + this handoff = 4 commits.
- 3 new files (`tabs/segments/edit/{MergePanel,DeletePanel,ReferenceEditor}.svelte`),
  5 modified, 0 deleted.
- 7/7 pre-flight gates GREEN. svelte-check 0/0. Lint 0 errors / 19 warnings
  (ceiling unchanged).
- Cycle ceiling: **19 (unchanged)** — no file deletions this wave.
- Bundle: 128 modules (+3 from 7a.2's 125), ~507 kB (+3 kB).
- Stop-point: clean boundary — merge/delete/reference all work identically
  to Stage-1 via existing imperative helpers, now also reflected in the
  edit store so EditOverlay mounts the correct panel shell.

---

## 1. Scope delivered

### 1.1 SegEditMode union extension (commit `b6e5941`)

Extended `lib/stores/segments/edit.ts`:

```ts
// Before:
export type SegEditMode = 'trim' | 'split' | null;

// After:
export type SegEditMode = 'trim' | 'split' | 'merge' | 'delete' | 'reference' | null;
```

Updated header comment to document Wave 7b status, the backdrop-scoping
rationale (merge/delete one-shot, reference inline — no backdrop for these
modes), and confirmation that `setEdit` signature accepts new modes without
change (the `Exclude<SegEditMode, null>` type widens automatically).

### 1.2 setEdit/clearEdit wiring (commit `c47ba3b`)

Three imperative modules instrumented:

**`segments/edit/merge.ts::mergeAdjacent`**:
- `setEdit('merge', seg.uid)` placed AFTER all guard checks (lines 33-40)
  but BEFORE `createOp`, per advisor recommendation. This way the store only
  reflects merge mode when we're committed to executing.
- `clearEdit()` on the one post-setEdit early return (`firstAudio !== secondAudio`).
- `clearEdit()` at normal completion (before `dom.segPlayStatus` update).

**`segments/edit/delete.ts::deleteSegment`**:
- `setEdit('delete', seg.uid)` placed AFTER `confirm()` passes — cancelled
  confirms don't touch the store.
- `clearEdit()` on the `!state.segAllData` guard-fail early return.
- `clearEdit()` at normal completion.

**`segments/edit/reference.ts`**:
- `setEdit('reference', seg.uid)` in `startRefEdit` after initial
  setup (audio pause, `_segContinuousPlay = false`).
- `clearEdit()` in the Escape keydown handler (after `committed = true`).
- `clearEdit()` at both `commitRefEdit` exit paths — AFTER
  `_chainSplitRefEdit(chapter)` so the split-chain's 100ms setTimeout
  fires after clearEdit, then the chained `startRefEdit` calls
  `setEdit('reference', ...)` again correctly.

### 1.3 MergePanel + DeletePanel + ReferenceEditor shells (commit `87490f6`)

Three new files in `tabs/segments/edit/`:

- **MergePanel.svelte** (~32 LOC): shell for merge mode. Invisible marker
  div consuming `audioElRef`. Documents that merge is one-shot async.
- **DeletePanel.svelte** (~29 LOC): shell for delete mode. Notes that
  `setEdit('delete')` only fires after `confirm()` passes — the shell
  may mount and immediately unmount in the same tick.
- **ReferenceEditor.svelte** (~33 LOC): shell for reference-edit mode.
  Documents the `startRefEdit` → `commitRefEdit` → `_chainSplitRefEdit`
  imperative flow. Notes autocomplete deferred to Wave 8.

All three follow the TrimPanel/SplitPanel `export let audioElRef` + hidden
marker pattern from Wave 7a.2 §1.7.

### 1.4 EditOverlay.svelte extensions (commit `87490f6`)

Two changes:

**Backdrop scoping**: The `.seg-edit-overlay` div is now conditionally
rendered only for trim/split:

```svelte
{#if $editMode === 'trim' || $editMode === 'split'}
    <div class="seg-edit-overlay"></div>
{/if}
```

Previously it appeared for any non-null `$editMode`. Showing the
viewport-covering overlay for merge/delete/reference would be a UX
regression — those modes are either one-shot (instant) or inline (ref
editing on the card row).

**New branches**: Four new `{:else if}` branches:

```svelte
{:else if $editMode === 'merge'}
    <MergePanel {audioElRef} />
{:else if $editMode === 'delete'}
    <DeletePanel {audioElRef} />
{:else if $editMode === 'reference'}
    <ReferenceEditor {audioElRef} />
```

---

## 2. Scope deferred

### 2.1 ReferenceEditor autocomplete Svelte-ification

**Decision: defer to Wave 8.** The imperative autocomplete in `reference.ts`
is DOM-building and tightly coupled to the `startRefEdit` input lifecycle.
Svelte-ifying it would be pure relocation with no behaviour unlock.

The `ReferenceEditor.svelte` shell exists as the mount point; Wave 8 can
migrate the autocomplete list into a reactive `{#each}` without re-threading
the entry path.

### 2.2 `_addEditOverlay` / `_removeEditOverlay` no-op stub removal

Still 3 callers (`trim.ts:30`, `split.ts:38`, `common.ts:87`). Carries to
Wave 11 cleanup (unchanged from 7a.2).

### 2.3 `deleteSegment` native `confirm()` → Svelte-native confirmation UI

`DeletePanel.svelte` is the future home for a Svelte-native confirmation
banner replacing `confirm()`. Not done this wave — no behaviour unlock
needed today and `confirm()` works fine.

### 2.4 All other deferred items from Wave 7a.2

`state.segValidation` → store (Wave 8), `clearSegDisplay` store-desync
(Wave 9/10), `renderSegCard` retention (Wave 8/10), full Svelte-native
drag rewrite (Wave 11). Unchanged.

---

## 3. Deviations from plan

### 3.1 MergePanel/DeletePanel/ReferenceEditor = shells, not full rewrites

**Plan/brief**: "MergePanel", "DeletePanel", "ReferenceEditor" with
delegating to imperative helpers.

**Actual**: Exactly shells per Wave 7a.2 precedent. The brief
simultaneously says "delegates to existing imperative helpers" and
"user #migration-strictness (2026-04-14): shell delegation is the
established pattern."

### 3.2 Backdrop scoping change

Not in the original brief. Advisor identified this UX regression risk
pre-work. The fix (scope backdrop to `trim | split`) is the correct
behaviour and doesn't require additional tests — it's a pure narrowing
of the existing condition.

### 3.3 setEdit placement in mergeAdjacent

Brief said "add `setEdit` before imperative work". Advisor recommended
placing it after guard checks to avoid needing `clearEdit()` on each
guard return. Advisor's recommendation followed — cleaner code.

---

## 4. Verification results

### 4.1 Pre-flight gates (final run, commit `87490f6`)

| Gate | Result | Detail |
|------|--------|--------|
| [1/7] tsc typecheck | PASS | 0 errors |
| [2/7] eslint | PASS | 0 errors, 19 warnings (ceiling unchanged) |
| [3/7] vite build | PASS | 128 modules (+3 from 7a.2's 125), 507.00 kB |
| [4/7] no-global-keyword | PASS | Backend unchanged |
| [5/7] no-orphan-cache-vars | PASS | Backend unchanged |
| [6/7] no-cycle-NOTEs | PASS | Zero |
| [7/7] cycle-ceiling | PASS | 19/19 |
| `npm run check` (svelte-check) | PASS | 0 errors, 0 warnings |

### 4.2 S2-B07 grep (zero module-top-level DOM access)

New shell files have no `document.*` calls. All three panels use only
the `audioElRef` prop (passed from parent) + a hidden marker div.

### 4.3 D2 class-invariant preserved

No `class:playing` / `class:reached` / `class:past` added. Verified
by grep — zero matches in `tabs/` for these class directives.

### 4.4 S2-D33 audio-el via props preserved

All three new panels accept `audioElRef: HTMLAudioElement | null` via
`export let` and receive it from EditOverlay via `{audioElRef}`. No
`document.getElementById` in `tabs/segments/edit/*.svelte`.

### 4.5 Merge/delete/reference flows unchanged

**Merge**: `mergeAdjacent` → `setEdit('merge', uid)` → async resolve ref
→ mutate segments → `applyVerseFilterAndRender` → `clearEdit()`. Store
transitions: null → 'merge' → null. EditOverlay mounts MergePanel shell
(no backdrop) then immediately unmounts.

**Delete**: confirm() → `setEdit('delete', uid)` → splice + reindex →
`applyVerseFilterAndRender` → `clearEdit()`. Store: null → 'delete' →
null. MergePanel shell (no backdrop) mounts/unmounts in same tick.

**Reference**: `startRefEdit` → `setEdit('reference', uid)` → input
injected inline. Escape: `clearEdit()`. Enter/blur: `commitRefEdit` →
resolve ref → `_chainSplitRefEdit` → `clearEdit()`. Split-chain: 100ms
later `startRefEdit` → `setEdit('reference', ...)` for second half.

**Undo/redo**: unchanged — `finalizeOp` / `mergeOp` / `deleteOp` still
called via the same imperative paths. Confidence → 1.0 for merge and
ref-edit confirmed present in the code.

---

## 5. Bug-log delta

No new OPEN bugs. No previously logged bugs closed this wave.

---

## 6. Review findings + disposition

**Advisor (pre-work)**: 6 actionable items, all addressed:

1. **merge/delete are one-shot, not persistent modes** — handled (setEdit
   placed after guards; clearEdit at every exit path).
2. **Backdrop scoping** — implemented (trim/split only).
3. **Reference lifecycle is self-contained** — clearEdit wired at both
   commitRefEdit paths and the Escape handler.
4. **setEdit signature widening automatic** — confirmed, no change needed.
5. **Combine union extension + setEdit wiring** — followed; 3 commits
   total (union, wiring, shells+overlay).
6. **setEdit placement in mergeAdjacent** — placed after guards per advice.

### Sonnet (pattern review) — **APPROVE-WITH-CHANGES**

1 blocker (fixed) + 1 non-blocker (deferred).

| ID | Item | Disposition |
|---|---|---|
| B1 | `segments/edit/delete.ts:47` — `if (globalIdx === -1) return;` missing `clearEdit()`. After `setEdit('delete', uid)` at line 39, this guard-fail path would leave the store frozen in `'delete'` mode with no escape. Practically unreachable (UID was just looked up from `segAllData`) but pattern invariant broken. | **Fixed** by orchestrator: `if (globalIdx === -1) { clearEdit(); return; }` |
| NB-1 | `EditOverlay.svelte:57` outer `{#if $editMode !== null}` is redundant — inner branch cascade already handles null. | Wave 11 cleanup |

**Validated:** §6.3 conformity, Wave 7a.2 prerequisite satisfied (`SegEditMode` union extended at `edit.ts:46`), shell pattern conformity (3 panels all ~34-41 LOC matching TrimPanel/SplitPanel precedent with `export let audioElRef` + hidden marker div), setEdit/clearEdit placement correct in merge + reference (merge.ts:48+56+147; reference.ts:31+66+141+190), **backdrop correctly scoped to trim/split only** (`EditOverlay.svelte:61`), D2 class-invariant grep clean (zero hits in `tabs/`), S2-D33 audio-el plumbing clean (zero `document.getElementById` in `edit/*.svelte` outside comments), S2-B07 grep clean, single-UID edit store shape sufficient (merge resolves adjacent at call time from index+direction), pattern notes #1-#8.

### Orchestrator disposition

- Blocker B1 fixed inline (1 line in `delete.ts:47`) — single-Edit, trip-wire budget preserved.
- NB-1 deferred to Wave 11 cleanup.
- **Wave 7 CLOSED** (7a.1 + 7a.2 + 7b all APPROVED).
- Proceed to Wave 8 (validation + stats) autonomously per user pref #7.

---

## 7. Surprises / lessons

1. **Merge/delete are NOT persistent edit modes.** The brief's framing of
   "MergePanel" implies a persistent UI like TrimPanel. In reality both are
   instant one-shot operations — the edit store transitions from null → mode
   → null in the same async tick. The shell pattern still makes sense (it's
   the future home for progress UI or confirmation UI), but the backdrop
   concern doesn't apply.

2. **Backdrop scoping is a correctness concern, not just polish.** If the
   backdrop appeared for merge/delete, it would block the segment list click
   targets during the brief 'merge' or 'delete' store state, potentially
   causing a frozen-UI percept. The advisor caught this before any code was
   written.

3. **clearEdit ordering with _chainSplitRefEdit.** The split-chain flow
   calls setTimeout(100ms) from inside `_chainSplitRefEdit`. If `clearEdit()`
   ran BEFORE `_chainSplitRefEdit`, the chain would still set the store
   correctly 100ms later. But calling `clearEdit()` AFTER `_chainSplitRefEdit`
   returns (before the timeout fires) is the correct semantic — "this reference
   edit is done; the chained one is a new edit."

---

## 8. Handoff to Wave 8

### Prerequisites the next agent must respect

1. **All Wave 7a.2 prerequisites still apply** (pattern notes #1-#8,
   audioElRef prop pattern, imperative drag modules retained).
2. **Edit store shape**: `editMode: 'trim' | 'split' | 'merge' | 'delete' |
   'reference' | null`, `editingSegUid: string | null`. Single-UID shape
   sufficient for all current modes.
3. **ReferenceEditor.svelte** is a shell waiting for Wave 8 autocomplete
   Svelte-ification. The `startRefEdit` / `commitRefEdit` imperative flow is
   intact; the shell is the future mount point.
4. **DeletePanel.svelte** is a shell waiting for a Svelte-native confirmation
   UI to replace `confirm()`. Not blocking.
5. **Backdrop is scoped to trim/split only.** Don't change this when adding
   Wave 8 validation/stats panels — those are outside the edit overlay.
6. **Cycle ceiling at 19.** Wave 8 work (validation panel Svelte migration)
   should not increase cycles; it may decrease them if validation/index.ts
   consumers of renderValidationPanel are removed.

### Queued tasks

- [ ] **`state.segValidation` → writable store** — Wave 8. The D1 memoization
  workaround (ref-tracking cache + `void $displayedSegments`) goes away once
  this is a proper store.
- [ ] **Validation panel Svelte migration** — Wave 8.
- [ ] **Stats panel Svelte migration** — Wave 8.
- [ ] **ReferenceEditor autocomplete Svelte rewrite** — Wave 8 (was deferred
  from Wave 7b per plan §8.2 option).
- [ ] **DeletePanel → Svelte-native confirm UI** — Wave 8 optional, Wave 11
  cleanup at latest.
- [ ] **`_addEditOverlay` / `_removeEditOverlay` no-op stubs deletion** — Wave 11.
- [ ] **Full Svelte-native drag rewrite of trim/split** — Wave 11 decision.

### Open questions for orchestrator

1. **ReferenceEditor autocomplete: Wave 8 or Wave 11?** The autocomplete is
   DOM-building but lightweight. If Wave 8 touches `reference.ts` for other
   reasons (e.g. validation error-card ref-edit integration), consider doing
   the autocomplete Svelte rewrite at the same time to avoid a third touch.
2. **DeletePanel confirm() replacement**: A Svelte-native confirmation banner
   would be a UX improvement (consistent with the dark theme, no browser
   dialog flash). Low priority unless Wave 8 touches delete flows.

---

## 9. Suggested pre-flight additions

None. 7-gate + svelte-check caught everything needed this wave.

---

## 10. Commits (exit-point detail)

```
b6e5941 feat(inspector): extend SegEditMode union for Wave 7b modes
c47ba3b feat(inspector): wire setEdit/clearEdit into merge/delete/reference entry paths
87490f6 feat(inspector): MergePanel + DeletePanel + ReferenceEditor shells + EditOverlay branches
```

3 source commits + this handoff = 4 commits.

---

## 11. Time / token budget (self-reported)

- Tool calls: ~28 (Read/Edit/Write/Bash/Grep/advisor)
- New source files: 3 Svelte shells (MergePanel, DeletePanel, ReferenceEditor)
- Modified source files: 5 (edit.ts, merge.ts, delete.ts, reference.ts,
  EditOverlay.svelte)
- Deletes: none
- Bash: ~8 (typecheck/svelte-check/build/lint/git)
- Advisor calls: 1 (pre-work orientation)
- Model: Claude Sonnet 4.6
- Commits: 3 source + 1 handoff = 4

---

**END WAVE 7b HANDOFF.**
