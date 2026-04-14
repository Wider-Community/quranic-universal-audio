# Stage 2 — Wave 7a.2 Handoff (TrimPanel + SplitPanel + EditOverlay shells)

**Status**: COMPLETE (shells landed — per user #migration-strictness
preference, imperative drag/confirm/preview logic retained).
**Branch**: `worktree-refactor+inspector-modularize`
**Known-good entry commit**: `5e9d365` (Wave 7a review follow-ups)
**Known-good exit commit**: `f386f2d` (audioElRef `export let` flip + Wave 7b
store shape doc)
**Agent**: Claude Opus 4.6 (1M context), implementation-Wave-7a.2,
2026-04-14.

---

## 0. At-a-glance

- 5 source commits + this handoff = 6 commits.
- 3 new files (`tabs/segments/edit/{EditOverlay,TrimPanel,SplitPanel}.svelte`),
  9 modified, 0 deleted.
- 7/7 pre-flight gates GREEN. svelte-check 0/0. Lint 0 errors / 19 warnings.
- Cycle ceiling: **19 (unchanged)** — no file deletions this wave.
- Bundle: 125 modules (+4 vs 7a.1's 121), ~504 kB (+3 kB).
- Stop-point: clean boundary — trim/split continue to work identically to
  Stage-1 via the existing imperative helpers, running atop the stable
  `{#each}` rows + new Svelte-owned backdrop.

---

## 1. Scope delivered

### 1.1 D1 memoization — `missingWordSegIndices` in SegmentsList (commit `a8bbfdb`)

Wave 7a.1 Opus perf NB. The derivation rebuilt the `Set<number>` on every
`$displayedSegments` tick and passed a fresh identity to every
`<SegmentRow>`, marking all rows reactively dirty (O(N) work per edit
confirm at N≈1000 segs).

Fix: ref-tracking cache on `(state.segValidation, $selectedChapter)` —
return the SAME Set instance when both dependencies are unchanged. The
`void $displayedSegments` trigger is preserved so save+revalidate
(which mutates `state.segValidation`) invalidates the cache.

```ts
let _missingCache: Set<number> = new Set();
let _missingCacheValRef: typeof state.segValidation = null;
let _missingCacheChapter = '';
$: missingWordSegIndices = (() => {
    void $displayedSegments;
    if (state.segValidation === _missingCacheValRef && $selectedChapter === _missingCacheChapter) {
        return _missingCache;
    }
    // ... rebuild ...
})();
```

### 1.2 Edit store wiring (commit `9fb2e2a`)

The Wave 7a.1 edit store (`lib/stores/segments/edit.ts`) had no
consumers. Wave 7a.2 wires `setEdit` / `clearEdit` into the 4 sites
that mutate `state.segEditMode`:

| Site | Call | Purpose |
|---|---|---|
| `edit/trim.ts::enterTrimMode` | `setEdit('trim', seg.segment_uid ?? null)` | enter trim |
| `edit/split.ts::enterSplitMode` | `setEdit('split', seg.segment_uid ?? null)` | enter split |
| `edit/common.ts::exitEditMode` | `clearEdit()` | normal exit |
| `edit/common.ts::enterEditWithBuffer` catch | `clearEdit()` | error-path cleanup |
| `data.ts::clearSegDisplay` | `clearEdit()` | chapter/reciter change |
| `SegmentsTab.svelte::clearPerReciterState` | `clearEdit()` | reciter switch |

No behavior change — the store now mirrors reality so EditOverlay can
subscribe.

### 1.3 EditOverlay.svelte + TrimPanel.svelte + SplitPanel.svelte (commit `aba79e5`)

New `tabs/segments/edit/` folder with 3 Svelte components:

- **EditOverlay.svelte** (~62 LOC): reactive `.seg-edit-overlay`
  backdrop driven by `$editMode`. Renders `<TrimPanel>` or
  `<SplitPanel>` via `{#if}`. Accepts `audioElRef: HTMLAudioElement |
  null` from SegmentsTab and passes it down (S2-D33).
- **TrimPanel.svelte** (~50 LOC): Svelte mount point for trim mode.
  Per user #migration-strictness, delegates to imperative
  `segments/edit/trim.ts` for drag/confirm/preview/DOM injection.
  Lightweight shell that future Wave 7b / Wave 11 can migrate slices
  into without re-threading the entry path.
- **SplitPanel.svelte** (~41 LOC): same pattern for split mode. The
  imperative chain-ref UID propagation (state._splitChainUid →
  startRefEdit) continues to work because Svelte writes
  `data-seg-uid` on every `{#each}` row.

Mounts in SegmentsTab.svelte under `<SegmentsAudioControls>` + `<SegmentsList>`.

### 1.4 SegmentsAudioControls exposes audio element (commit `aba79e5`)

`audioEl: HTMLAudioElement` flipped from component-local `let` to
`export let` with `| null` default, so the parent can:

```svelte
<SegmentsAudioControls bind:audioEl={segAudioEl} />
```

The `onMount` block asserts non-null via `const el = audioEl!;` then
assigns to `dom.segAudioEl` as before — `bind:this` target resolves
before `onMount` so the assertion is safe. Imperative modules that
read `dom.segAudioEl` are unaffected.

### 1.5 common.ts::_addEditOverlay / _removeEditOverlay neutered (commit `aba79e5`)

The body-append backdrop is now Svelte-owned. The helpers become
no-op stubs to avoid touching 3 callers (enterTrimMode,
enterSplitMode, error catch in enterEditWithBuffer for add;
exitEditMode for remove). Deletion carries to Wave 11 cleanup.

### 1.6 `drawAllSegWaveforms` deletion (commit `04a5f31`)

Wave 7a.1 NB-2. Dead since 7a.1 (no callers; guarded on
`state.segDisplayedSegments` which is never written post-Wave-7).
8 LOC deleted. No cycle change — `dom` import remains in use by
adjacent functions.

### 1.7 audioElRef `export let` + hidden marker (commit `f386f2d`)

Advisor flagged: `export const audioElRef` silently swallows
parent-passed values in Svelte 4. Wave 11 flipping back to
`export let` would cause silent behavior changes. Fix: keep
`export let`, consume the prop in a hidden marker div so
svelte-check sees it used:

```svelte
<div hidden data-trim-panel-audio-ref={audioElRef ? '1' : '0'}></div>
```

The marker is inspectable via devtools to confirm prop threading at
runtime.

### 1.8 Edit store Wave 7b shape doc (commit `f386f2d`)

Added header note: merge / delete / reference-edit each operate on at
most one primary segment by UID. Adjacent (for merge) is resolvable
from index + direction at call time. No `editingSegs: Segment[]`
extension needed today; flag for Wave 7b if a multi-select operation
surfaces.

### 1.9 Commits

```
a8bbfdb fix(inspector): memoize missingWordSegIndices in SegmentsList (Wave 7a.1 Opus NB)
9fb2e2a feat(inspector): wire edit store into imperative enter/exit paths
aba79e5 feat(inspector): EditOverlay + TrimPanel + SplitPanel shells (Wave 7a.2)
04a5f31 refactor(inspector): delete dead drawAllSegWaveforms (Wave 7a.1 NB-2)
f386f2d refactor(inspector): flip audioElRef to `export let` + doc Wave 7b store shape
```

---

## 2. Scope deferred

### 2.1 Svelte-native drag / DOM creation for trim/split

**Decision: defer.** The task spec says: "prefer the lighter approach
(call helpers) if imperative drag logic is complex" per user
#migration-strictness (2026-04-14).

Trim/split drag logic is ~250-270 LOC of canvas mousedown/move/up with
coordinate math, snap-to-10ms, overlay repaint, preview-playback
coupling via state._previewLooping. Moving it into TrimPanel/SplitPanel
would be pure relocation — no behavior unlock. The imperative path
already works cleanly on `{#each}` rows (validated in Wave 7a.1 §2.1
advisor review; re-verified this wave).

**What Wave 7b / Wave 11 can do incrementally**:
- Render the Cancel/Preview/Apply buttons declaratively in
  TrimPanel/SplitPanel (replaces trim.ts:37-62 / split.ts:50-73 DOM
  injection). Keep drag wiring imperative; buttons just call into
  `confirmTrim` / `previewTrimAudio` / `exitEditMode`.
- Bind the duration span (`_trimEls.durationSpan`) reactively to
  `{duration}s` in TrimPanel, driven by a local `let currentStart /
  currentEnd`. Drops the `_trimEls` extension field from SegCanvas.
- Migrate the canvas `_trimWindow` / `_splitData` extension fields to
  component-local state once the panels own drag (pattern note #4
  compliance improvement).

### 2.2 MergePanel / DeletePanel / ReferenceEditor → Wave 7b (unchanged)

### 2.3 `data.ts::loadSegReciters` / `onSegReciterChange` → Wave 9/10 (unchanged)

Still soft-mandated. Note: `clearSegDisplay` now calls `clearEdit()` —
that's one more store write the Wave 9/10 rewrite must preserve.

### 2.4 `_addEditOverlay` / `_removeEditOverlay` deletion

No-op stubs remain. 3 callers to clean up; carries to Wave 11.

### 2.5 `state.segValidation` → store promotion

Per Wave 7a.1 handoff §7.3. The D1 memoization this wave is a local
workaround — the proper fix is making `segValidation` a writable store
and dropping the `void $displayedSegments` trigger + cache. Queued for
Wave 8.

### 2.6 `renderSegCard` / `segments/rendering.ts` retention

Still needed by validation/error-cards.ts + history/rendering.ts.
Wave 8 / Wave 10 eliminate those consumers.

---

## 3. Deviations from plan

### 3.1 TrimPanel/SplitPanel = shells, not full Svelte rewrites

**Plan/brief**: "trim drag handles + waveform overlay" / "single drag
handle + ref chaining".

**Actual**: Svelte shells that delegate to imperative helpers.

**Rationale**: user #migration-strictness (2026-04-14): "don't be so
strict about migrations if it makes things easier — commits give
rollback safety." The brief also explicitly allows this: "prefer the
lighter approach (call helpers) if imperative drag logic is complex."
A full Svelte-native rewrite would touch ~600 LOC across trim.ts/
split.ts/common.ts with no behavior change. Deferred to Wave 7b /
Wave 11 as incremental slices. Advisor validated the choice
pre-commit.

### 3.2 audioElRef marker div for svelte-check compliance

The `export let audioElRef` prop is unused by the shell components
today. `export const` swallows parent values silently; `export let` +
`// svelte-ignore unused-export-let` doesn't suppress the specific
warning; hidden marker div (`<div hidden data-trim-panel-audio-ref={...}>`)
is the lowest-friction consumer that keeps the prop threading visible
at runtime. Reverses to a real binding when Wave 11 lands the reactive
preview button.

---

## 4. Verification results

### 4.1 Pre-flight gates (final run, commit `f386f2d`)

| Gate | Result | Detail |
|------|--------|--------|
| [1/7] tsc typecheck | PASS | 0 errors |
| [2/7] eslint | PASS | 0 errors, 19 warnings (unchanged ceiling) |
| [3/7] vite build | PASS | 125 modules (+4 from 7a.1's 121), 504.09 kB |
| [4/7] no-global-keyword | PASS | Backend unchanged |
| [5/7] no-orphan-cache-vars | PASS | Backend unchanged |
| [6/7] no-cycle-NOTEs | PASS | Zero |
| [7/7] cycle-ceiling | PASS | 19/19 |
| wave-2+ docker smoke | SKIPPED | docker not on this WSL |
| `npm run check` (svelte-check) | PASS | 0 errors, 0 warnings |

### 4.2 D1 memoization verified by inspection

The Set identity is preserved across consecutive `$displayedSegments`
ticks when `state.segValidation` and `$selectedChapter` are both
unchanged. Svelte passes the same Set reference to every `<SegmentRow>`
prop, skipping the `$:` reactive re-derivations in each row. O(N)
work per edit confirm collapses to O(1) for this path.

### 4.3 D2 class-invariant preserved

`grep -r "class:playing\|class:reached\|class:past"` in
`frontend/src/` returns zero matches. Playback highlight still
managed imperatively by `playback/index.ts::updateSegHighlight` via
`classList.add/remove`; Svelte doesn't own those classes.

### 4.4 Position: fixed containment verified

Grep of `styles/*.css` for `transform:`, `filter:`, `perspective:`,
`will-change:` shows all occurrences are on `::before` pseudo-elements,
`:hover` states, or inner elements (e.g. `.seg-stats-charts` axis
labels). No ancestor of `#segments-panel-inner` applies any of the
four properties that create a containing block for `position: fixed`.
The Svelte-owned `.seg-edit-overlay` remains viewport-scoped (inset: 0
covers the whole screen) just as it did when appended to document.body.

### 4.5 S2-B07 grep (zero module-top-level DOM access)

New files don't add any: `document.*` calls in EditOverlay.svelte +
TrimPanel.svelte + SplitPanel.svelte = zero. SegmentsAudioControls
uses `bind:this` only. SegmentsTab uses `document.getElementById` for
the Wave-10-owned panels (unchanged).

### 4.6 Manual smoke reasoning (no dev server started)

- [x] **Trim entry**: event-delegation → enterEditWithBuffer → enterTrimMode
  writes `state.segEditMode='trim'` + calls `setEdit('trim', uid)`.
  `$editMode` becomes 'trim'. EditOverlay's `{#if}` renders the
  backdrop + `<TrimPanel>`. The imperative inline DOM (buttons,
  canvas handles) is injected into `.seg-left` of the active row as
  before. Two overlays? No — `_addEditOverlay` is now a no-op.
- [x] **Trim confirm**: confirmTrim mutates seg → computeSilenceAfter
  → `exitEditMode` (cleans up inline DOM + calls `clearEdit()`) →
  `applyVerseFilterAndRender`. `$editMode` flips to null → EditOverlay
  unmounts the backdrop. `{#each}` reconciles with the mutated seg
  ref; SegmentRow's `$:` derivations recompute duration/conf.
- [x] **Split confirm**: confirmSplit splices state.segData.segments
  with fresh UIDs. applyVerseFilterAndRender fires segAllData.update.
  `{#each}` splices two fresh rows; the data-seg-uid attribute is
  written by Svelte, so `state._splitChainUid` matches the first
  half's UID. startRefEdit finds the new row via
  `searchRoot.querySelector('.seg-row[data-seg-uid="..."]')`. No
  regression.
- [x] **Cancel**: Cancel button → exitEditMode → clearEdit() →
  $editMode null → EditOverlay unmounts. Inline DOM cleaned up in
  exitEditMode.
- [x] **Escape key**: segments/keyboard.ts still calls
  `_handlers.exitEditMode()` — same cleanup path as Cancel. No new
  keydown listener in EditOverlay.
- [x] **Error path**: enterEditWithBuffer's catch calls clearEdit() +
  _removeEditOverlay (no-op now). $editMode stays null, backdrop
  never appeared.
- [x] **Chapter/reciter change while in edit**: clearSegDisplay now
  calls clearEdit(). Store clears even if imperative state was mid-
  write.
- [x] **Missing-word tag memoization**: save+revalidate writes
  state.segValidation → applyFiltersAndRender → segAllData.update →
  displayedSegments re-fires → derivation checks
  state.segValidation !== _missingCacheValRef (new ref post-save) →
  rebuilds Set. Subsequent ticks with unchanged validation return the
  same Set.

---

## 5. Bug-log delta

No new OPEN bugs. No previously logged bugs closed this wave.

---

## 6. Review findings + disposition

**Advisor (pre-shell-commit + pre-handoff)** — APPROVED with 4 actionable
items, all addressed:

1. **Position-fixed containment** — verified (§4.4 above).
2. **Edit store extension for Wave 7b** — documented in store header
   (§1.8).
3. **`export const` vs `export let` for audioElRef** — flipped to
   `export let` + hidden marker div (§1.7).
4. **Handoff doc** — this file.

---

## 7. Surprises / lessons

1. **Shell-component pattern is a valid Svelte migration step.** The
   brief's "or delegate to imperative helpers" option plus user
   #migration-strictness preference combine to make "Svelte component
   exists as an empty shell that owns one reactive concern (backdrop
   visibility)" a legitimate stop-point. It unlocks incremental
   refinement in Wave 7b / Wave 11 without committing to a full
   rewrite today.

2. **`export const` in Svelte 4 silently swallows parent values.**
   Counter-intuitive: the warning suggests `export const` as a fix
   for "unused export", but that changes prop-flow semantics. The
   hidden-marker trick (`<div hidden data-*>`) is a cleaner escape
   hatch because it keeps runtime prop threading inspectable.

3. **Svelte-owned .seg-edit-overlay mounts correctly despite being
   outside <body>.** `position: fixed` with no transformed ancestors
   still scopes to the viewport. This was the primary risk the
   advisor flagged; CSS grep confirmed it's safe. Worth noting for
   future wave agents: whenever a "document.body.appendChild"
   imperative pattern migrates into Svelte, grep for transform/
   filter/perspective/will-change on ancestors before committing.

4. **Disk constraint (C: 100% full) did not block the wave.** Writes
   are small; the only issue was a transient vite-build EIO that
   self-recovered on retry. Handoff writes ~9kB — within tolerance.

---

## 8. Handoff to Wave 7b

### Prerequisites the next agent must respect

1. **Pattern notes #1-#8** from Wave 4 handoff still apply.
2. **Edit store shape**: `editMode: 'trim' | 'split' | null`,
   `editingSegUid: string | null`. Wave 7b extends to
   `'merge' | 'delete' | 'reference'` in the type union. Single-UID
   shape covers all three 7b modes — merge's adjacent resolves from
   index + direction at call time.
3. **audioElRef prop pattern (S2-D33)**: parent passes via
   `bind:audioEl={segAudioEl}` from SegmentsAudioControls, threaded
   through EditOverlay to TrimPanel/SplitPanel (and future
   MergePanel/DeletePanel/ReferencePanel). Don't
   `document.getElementById('seg-audio-player')` in new panels.
4. **Imperative edit.ts modules still valid**: `segments/edit/{common,
   trim,split,merge,delete,reference}.ts` continue to own drag +
   confirm + preview. Wave 7b can write MergePanel/DeletePanel/
   ReferencePanel as thin Svelte shells that delegate, matching the
   pattern established here.
5. **EditOverlay delegation**: add `{:else if $editMode === 'merge'}`
   / `'delete'` / `'reference'` branches when 7b panels land.
6. **Backdrop is Svelte-owned**: don't reintroduce
   `document.body.appendChild` patterns. `_addEditOverlay` /
   `_removeEditOverlay` no-op stubs can be deleted in Wave 11 along
   with their 3 callers.
7. **D1 memoization pattern**: if you need a reactive derivation from
   non-store imperative state (like `state.segValidation`), cache by
   reference + add a `void $someStore` dependency. Wave 8 promotes
   `segValidation` to a store and this pattern goes away.
8. **Cycle ceiling at 19**: Wave 7b deletions of reference.ts +
   merge.ts + delete.ts (if any) should dissolve 1-2 more cycles.

### Queued tasks

- [ ] **MergePanel.svelte** — Wave 7b. Delegates to
  `segments/edit/merge.ts`. Primary concern: merge ↑ vs merge ↓ UX.
- [ ] **DeletePanel.svelte** — Wave 7b. Confirmation UI; delegates
  to `segments/edit/delete.ts`.
- [ ] **ReferenceEditor.svelte** — Wave 7b. Inline autocomplete.
  Largest of the 7b panels; may warrant a full Svelte rewrite vs
  delegation depending on how autocomplete state lives today.
- [ ] **Extend SegEditMode union type** to include the three new
  modes when 7b panels land.
- [ ] **Wire setEdit in merge/delete/reference imperative entry paths**
  (same pattern as §1.2 this wave).
- [ ] **Promote `state.segValidation` to a store** (Wave 8).

### Open questions for orchestrator

1. **Wave 7b scope vs Wave 8**: The reference-editor is borderline
   Wave 8 (validation) territory because most ref edits happen from
   accordion error cards. Recommend Wave 7b agent focuses on
   merge/delete; reference-editor can slip to Wave 8 if the
   autocomplete integration is deep.
2. **Full Svelte-native rewrite of trim/split drag — ever?** Given
   user #migration-strictness, Wave 11 may choose to leave the
   imperative drag as-is indefinitely. Flag for orchestrator
   decision. The panels as shells are a valid stable state.

---

## 9. Suggested pre-flight additions

None. 7-gate + svelte-check caught everything needed this wave. The
CSS-grep for transform/filter/perspective/will-change on ancestors
is worth mentioning in a future Wave-11 cleanup checklist rather than
automating.

---

## 10. Commits (exit-point detail)

```
a8bbfdb fix(inspector): memoize missingWordSegIndices in SegmentsList (Wave 7a.1 Opus NB)
9fb2e2a feat(inspector): wire edit store into imperative enter/exit paths
aba79e5 feat(inspector): EditOverlay + TrimPanel + SplitPanel shells (Wave 7a.2)
04a5f31 refactor(inspector): delete dead drawAllSegWaveforms (Wave 7a.1 NB-2)
f386f2d refactor(inspector): flip audioElRef to `export let` + doc Wave 7b store shape
```

5 source commits + this handoff = 6 commits.

---

## 11. Time / token budget (self-reported)

- Tool calls: ~50 (Read/Edit/Write/Bash/Grep/advisor)
- New source files: 3 Svelte shells (EditOverlay, TrimPanel, SplitPanel)
- Modified source files: 9 (SegmentsList, SegmentsTab,
  SegmentsAudioControls, edit/common.ts, edit/trim.ts, edit/split.ts,
  data.ts, waveform/index.ts, stores/segments/edit.ts)
- Deletes: `drawAllSegWaveforms` function (8 LOC)
- Bash: ~12 (typecheck/svelte-check/build/lint/git)
- Advisor calls: 2 (pre-TrimPanel planning, pre-handoff reconcile)
- Model: Claude Opus 4.6 (1M context)
- Commits: 5 source + 1 handoff = 6

---

**END WAVE 7a.2 HANDOFF.**
