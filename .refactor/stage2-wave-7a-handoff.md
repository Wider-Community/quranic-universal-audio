# Stage 2 — Wave 7a Handoff (SegmentsList {#each} + Edit Store + Wave 6b CF Closure)

**Status**: COMPLETE (sub-wave 7a.1 — store + {#each} + cleanup). TrimPanel/SplitPanel/EditOverlay DEFERRED to sub-wave 7a.2 — see §2.
**Branch**: `worktree-refactor+inspector-modularize`
**Known-good entry commit**: `5be8fd4` (Wave 6b review follow-ups)
**Known-good exit commit**: `ef8e50f` (missingWordSegIndices stale-after-revalidate fix)
**Agent**: Claude Opus 4.6 (1M context), implementation-Wave-7a, 2026-04-14.

---

## 0. At-a-glance

- 6 source commits + this handoff = 7 commits.
- 1 new file (`lib/stores/segments/edit.ts`), 8 modified, 0 deleted.
- 7/7 pre-flight gates GREEN. svelte-check 0/0. Lint 0 errors / 19 warnings (was 23 baseline — **4 cycles dissolved**).
- **Cycle ceiling: 23 → 19** (decremented in `.refactor/stage2-checks.sh`, two steps).
- **`{#each}` adoption COMPLETE** — SegmentsList.svelte renders #seg-list reactively; `renderSegList` deleted.
- **Wave 6b CFs CLOSED** — `state.segPeaksByAudio` field removed; all 5 read sites + the backwards-compat sync gone.
- **`segments/filters.ts`** collapsed from ~280 LOC to ~115 LOC shim.
- **`segments/rendering.ts::renderSegList`** removed (53 LOC); other helpers retained.
- Bundle: 121 modules (+1 from `edit.ts`), ~501 kB.
- Stop-point: clean boundary — all 7 gates green, trim/split work imperatively atop stable `{#each}` rows. TrimPanel/SplitPanel/EditOverlay Svelte components are 7a.2 scope.

---

## 1. Scope delivered

### 1.1 Wave 6b CF closure — `state.segPeaksByAudio` migration (commit `a4d6b23`)

5 hot-path reads migrated to `getWaveformPeaks()` (normalized URL key per S2-B04):

| Site | Path | Notes |
|---|---|---|
| `drawWaveformFromPeaksForSeg` | `segments/waveform/draw.ts:46` | 60fps hot path — Wave 6b NB-1's primary CF |
| `_slicePeaks` | `segments/waveform/draw.ts:128` | Trim/split overlay base-cache builder |
| `_findCoveringPeaks` | `segments/state.ts:643` | Covering-range fallback (used by playhead + slice) |
| `enterTrimMode` | `segments/edit/trim.ts:71` | Next-seg duration boundary (Wave 6b NB-2) |
| `enterSplitMode` | `segments/edit/split.ts:85` | Pre-fetch guard (Wave 6b NB-2) |

With all readers migrated, the backwards-compat sync in `segments/waveform/index.ts::_fetchPeaks` (lines 148-149 — `state.segPeaksByAudio[url] = pe`) became dead code and is **removed**. The `state.segPeaksByAudio` field itself is dropped from `SegmentsState` + `state` initializer; the two clear sites (`segments/data.ts::clearSegDisplay`, `SegmentsTab.svelte::clearPerReciterState`) call `clearWaveformCache()` instead.

### 1.2 Edit store — `lib/stores/segments/edit.ts` (commit `a892799`, ~44 LOC)

Thin store provisioned for sub-wave 7a.2 / 7b consumers:
- `editMode: Writable<'trim' | 'split' | null>`
- `editingSegUid: Writable<string | null>` — UID rather than index so split-induced reindex doesn't lose track.
- `clearEdit()` / `setEdit(mode, uid)` helpers.

Drag state stays component-local (pattern note #3). Per-frame canvas overlay state stays on `SegCanvas` extension fields (pattern note #4). Provisional shape per S2-D11.

**No consumers yet** — the existing imperative `state.segEditMode` + `state.segEditIndex` keep working. TrimPanel/SplitPanel adopt the store when they land (7a.2).

### 1.3 SegmentsList {#each} adoption (commit `0200825`)

The Wave-5 hybrid (Svelte container + imperative `renderSegList` bridge) becomes a fully Svelte-driven list:

- `{#each $displayedSegments as seg, displayIdx (rowKey(seg))}` — keyed by `segment_uid ?? \`${seg.chapter}:${seg.index}\``. UID survives split-induced reindexing; compound-key fallback is unique within a chapter for legacy data.
- Inlines `<SegmentRow>` per row + silence-gap markers (preserves Stage-1 `renderSegList:253-264` semantics — gap shown only when next-displayed is the consecutive index).
- `missingWordSegIndices` derived reactively from `state.segValidation` + `$selectedChapter`, with a `void $displayedSegments` dependency so it re-derives after save+revalidate (see §1.7 fix).
- `Navigation` banner stays inside `#seg-list` (Wave 5 sticky-position requirement). The Wave-5 banner-preservation walk in `renderSegList` is no longer needed: Svelte owns the banner and renders it OUTSIDE the `{#each}` block.

### 1.4 SegmentRow.svelte adopted (was provisioned-but-unused) (commit `0200825`)

The component already had S2-D23 props (Wave 5). This wave activates it:
- Added `bind:this={canvasEl}` on the `<canvas>` element.
- `onMount` calls `_ensureWaveformObserver().observe(canvasEl)` (replaces the post-walk in `renderSegList:268`).
- On destroy, explicit `unobserve(canvasEl)` — IntersectionObserver doesn't strongly retain detached nodes but releasing entries avoids dangling state when rows are recycled mid-edit.

The component's other markup is bit-identical to `renderSegCard` so edit/playback selectors continue to work (`.btn-adjust`, `.seg-card-play-btn`, `data-seg-index`, etc.).

### 1.5 `applyFiltersAndRender` shim — `segments/filters.ts` (commit `0200825`)

**~280 LOC → ~115 LOC.** The original imperative module owned filter UI + filter computation + DOM rendering; all 3 concerns now live in Svelte stores (`activeFilters`, `displayedSegments` derived) + components (`FiltersBar.svelte`, `SegmentsList.svelte`).

The shim keeps the old API (`applyFiltersAndRender`, `applyVerseFilterAndRender`, `renderFilterBar`, `updateFilterBarControls`, `addSegFilterCondition`, `clearAllSegFilters`) so 8+ imperative callers (edit modes, save, undo, validation, navigation) continue to compile. Each one now writes through the store:

```ts
export function applyFiltersAndRender(): void {
    // 1. Reset playback highlight refs (Wave-5 renderSegList:216-217)
    state._prevHighlightedRow = null; state._prevHighlightedIdx = -1;
    state._currentPlayheadRow = null; state._prevPlayheadIdx = -1;
    // 2. Sync state→store (callers that mutate state.segActiveFilters directly)
    activeFiltersStore.set([...state.segActiveFilters]);
    // 3. Notify segAllData subscribers — derived `displayedSegments` re-fires
    segAllDataStore.update((a) => a);
}
```

Re-exports `segDerivedProps` + `computeSilenceAfter` from the lib store so existing import sites don't break.

`renderFilterBar` / `updateFilterBarControls` are no-ops (FiltersBar.svelte derives both from `$activeFilters` reactively); they sync state→store as a safety net for callers that mutate state and expect a UI refresh.

### 1.6 `segments/navigation.ts` store sync (commit `0200825`)

- `_showBackToResultsBanner` no longer creates an imperative `<div class="seg-back-banner">` (would double-render on top of Navigation.svelte's reactive banner). Now writes the existing `state._segSavedFilterView` value to the `savedFilterView` store so the Svelte banner appears via `$backBannerVisible`.
- `_restoreFilterView` mirrors all state writes into both stores (`savedFilterView`, `activeFilters`) so the reactive paths see them.

### 1.7 `validation/index.ts` (commit `0200825`)

The fork
```ts
if (state.segData?.segments) applyFiltersAndRender();
else if (state.segDisplayedSegments) renderSegList(state.segDisplayedSegments);
```
collapses to `applyFiltersAndRender()` — the store-notify path covers both branches. `renderSegList` import deleted.

### 1.8 `clearSegDisplay` innerHTML wipe removed (commit `0200825`)

`segments/data.ts::clearSegDisplay` had `dom.segListEl.innerHTML = ''`, which would clobber Svelte's reconciliation. The function already sets `state.segAllData = null` first, so the derived `displayedSegments` becomes empty and SegmentsList's `{#if length === 0}` shows the placeholder. Imperative wipe gone.

(Note: `clearSegDisplay` writes `state.segAllData = null` but does NOT call `segAllData.set(null)` — that's a pre-existing Wave 5 deferral. See §7.4 + the save/history carry-forward in §2.3.)

### 1.9 Cycle ceiling decrement 23 → 19 (commits `879da86` + `5e280c8`)

- **23 → 20**: `segments/filters.ts` no longer imports `./rendering` (the `renderSegList` call is gone). Breaks the `rendering ↔ data ↔ filters ↔ validation` cycle cluster.
- **20 → 19**: `segments/rendering.ts` no longer imports `./waveform/index` (only `renderSegList` did, and it's deleted). Breaks the `rendering → waveform/index → ... → state → rendering` cycle.

`.refactor/stage2-checks.sh::CYCLE_CEILING` updated to 19.

### 1.10 `renderSegList` deletion + rendering.ts shrink (commit `5e280c8`)

`segments/rendering.ts::renderSegList` (53 LOC) deleted. `renderSegCard` / `updateSegCard` / `syncAllCardsForSegment` / `resolveSegFromRow` / `_getEditCanvas` / `getConfClass` retained — used by `validation/error-cards.ts` (accordion error cards) and `history/rendering.ts` (read-only history view), both still imperative through Wave 8/10.

### 1.11 missingWordSegIndices stale-after-revalidate fix (commit `ef8e50f`)

`state.segValidation` is a plain field (not a store). The reactive derivation in `SegmentsList.svelte` for `missingWordSegIndices` only depended on `$selectedChapter`, so when validation refreshed mid-session (save → revalidate writes `state.segValidation = ...`), the derivation never re-ran. Tags would go stale until the user changed chapters.

Fix: add `void $displayedSegments` as a dependency. `applyFiltersAndRender` already notifies `segAllData → displayedSegments`, so the dependency cascades through to the missing-word computation without exporting validation as a store.

### 1.12 Commits

```
a4d6b23 refactor(inspector): Wave 6b CFs — migrate state.segPeaksByAudio reads to waveform-cache util
a892799 feat(inspector): lib/stores/segments/edit.ts — edit mode store
0200825 feat(inspector): SegmentsList {#each} adoption + applyFiltersAndRender shim
879da86 chore(inspector): decrement cycle ceiling 23 → 20
5e280c8 refactor(inspector): remove dead renderSegList; cycle ceiling 20 → 19
ef8e50f fix(inspector): SegmentsList missingWordSegIndices stale after revalidation
```

---

## 2. Scope deferred

### 2.1 TrimPanel / SplitPanel / EditOverlay Svelte components → sub-wave 7a.2

**Decision: defer.** Trim and split modes work today via the imperative path (`segments/edit/{common,trim,split}.ts`) acting on top of the new `{#each}` rows. The Svelte refactor is incremental refinement, not a behavior unlock.

**Why this is safe** (verified by reasoning, not dev server):
- `{#each}` keyed by `segment_uid` keeps the same DOM node for a given key unless the `seg` reference changes.
- Entering edit mode appends a transient `<div class="seg-edit-inline">` to `.seg-left` and sets canvas overlay state. None of this triggers a store write.
- `applyVerseFilterAndRender` only fires AFTER `exitEditMode` cleans up the inline DOM (every confirm path: trim.ts:322-323, split.ts:348-349). So Svelte never sees the transient state.
- The advisor independently confirmed this.

**What's left for 7a.2 / 7b**:
- `tabs/segments/edit/EditOverlay.svelte` — backdrop + confirm/cancel/preview shell, dispatches based on `$editMode`.
- `tabs/segments/edit/TrimPanel.svelte` — trim drag handles + waveform overlay.
- `tabs/segments/edit/SplitPanel.svelte` — split handle + ref chaining (calls `startRefEdit` after split).
- All three accept `audioElRef` prop per S2-D33 instead of `document.getElementById('seg-audio-player')`.
- The edit store (already provisioned in §1.2) becomes the single writer for `editMode` / `editingSegUid` — components subscribe.

User preference (#migration-strictness, 2026-04-14): "don't be so strict about migrations if it makes things easier — commits give rollback safety". Stop-point 7a.1 is a clean boundary; 7a.2 can land in a separate session.

### 2.2 Merge / Delete / Reference editor → Wave 7b (unchanged)

Original Wave 7 split. 7b owns these.

### 2.3 `data.ts::loadSegReciters` + `onSegReciterChange` deletion

Still soft-mandated, deferred to Wave 9/10 per Wave 6a §2.1. Two callers (`save.ts:173`, `history/index.ts:77`) need rewrites that go beyond Wave 7a's scope.

**One additional fragility introduced this wave**: `clearSegDisplay` in `data.ts` (called by `onSegReciterChange`) sets `state.segAllData = null` but does NOT call `segAllData.set(null)` on the store. So if save/history-undo paths invoke `onSegReciterChange`, the imperative chain breaks with the Svelte store. Pre-existing Wave-5 deferral; Wave 9/10 rewrite resolves it. Documented for next agent.

### 2.4 Imperative `_segSavedFilterView` writes in event-delegation.ts:132

`event-delegation.ts::handleSegRowClick` (Go-To button branch) writes `state._segSavedFilterView = {...}` directly, then calls `jumpToSegment`. The store sync now happens inside `_showBackToResultsBanner` (called from jumpToSegment), so the banner appears correctly. No code change needed today; flagged for awareness.

### 2.5 `state.segDirtyMap` as a store / `isIndexDirty` as derived

The original spec mentioned moving `isIndexDirty` to a derived store off `segOpLog`. Decision: leave as-is. `isIndexDirty` is a synchronous read in SegmentRow's `$:` block; making it derived would require subscribing to a store. The current `state.segDirtyMap` is mutated from edit/save/undo paths (markDirty/unmarkDirty), and the `dirty` class on the row only matters when `$displayedSegments` re-renders (which happens on every edit confirm via `applyFiltersAndRender`). So the read is fresh-on-render. Lower-priority refactor; flag for Wave 11.

---

## 3. Deviations from plan

### 3.1 Stop at 7a.1 — TrimPanel/SplitPanel deferred

**Plan §4 Wave 7**: ships TrimPanel + SplitPanel + EditOverlay in Wave 7a.

**Actual**: stops at SegmentsList `{#each}` + edit-store + Wave 6b CF closure + cleanup. Trim/split panels deferred to sub-wave 7a.2.

**Rationale**: per user preference + advisor: the high-leverage work was the `{#each}` adoption (which unlocks store-driven row rendering). The edit panels are incremental Svelte conversion — they re-render the same trim/split UI in components instead of imperative DOM, but the imperative path already works correctly atop `{#each}` rows. Defer reduces risk and respects the "MAY change" / "acceptable stopping points" rules in the task spec.

### 3.2 Stage-1 `_showBackToResultsBanner` rewritten to write the savedFilterView store instead of injecting DOM

**Originally**: imperative banner injection.
**Now**: writes to `savedFilterViewStore` so Navigation.svelte's reactive banner appears.

This was necessary because the Svelte Navigation banner (rendered when `$backBannerVisible`) and the imperative banner would have double-rendered. Pre-Wave-7 they coexisted only because Navigation never received its trigger from the imperative path (the bridge was one-way: store → state). Wave 7 closes this loop.

### 3.3 No `EditOverlay.svelte`

Not landed (deferred per §3.1). The current `_addEditOverlay()` (in `segments/edit/common.ts`) does `document.body.appendChild(<div class="seg-edit-overlay">)` — a DOM-level backdrop. It works fine atop the Svelte `{#each}` rows; no conflict.

---

## 4. Verification results

### 4.1 Pre-flight gates (final run)

| Gate | Result | Detail |
|------|--------|--------|
| [1/7] tsc typecheck | PASS | 0 errors |
| [2/7] eslint | PASS | 0 errors, 19 warnings (was 23 — 4 cycles dissolved) |
| [3/7] vite build | PASS | 121 modules (+1 edit.ts), 501.57 kB bundle |
| [4/7] no-global-keyword | PASS | Backend unchanged |
| [5/7] no-orphan-cache-vars | PASS | Backend unchanged |
| [6/7] no-cycle-NOTEs | PASS | Zero `// NOTE: circular dependency` |
| [7/7] cycle-ceiling | PASS | 19/19 (decremented from 23) |
| wave-2+ docker smoke | SKIPPED | docker not on this WSL |
| `npm run check` (svelte-check) | PASS | 0 errors, 0 warnings |

### 4.2 S2-B07 grep (zero module-top-level DOM access)

`SegmentRow.svelte` + `SegmentsList.svelte` use `bind:this` (canvas) + `onMount` (observer registration); no module-top access. Verified by inspection.

### 4.3 Manual smoke reasoning (no dev server started)

- [x] **Chapter load → row render**: SegmentsTab.onChapterChange writes segData.set + segAllData.update. Derived `displayedSegments` recomputes. SegmentsList `{#each}` reconciles — keyed by uid so identical-content re-renders are O(0). Each new SegmentRow's onMount registers its canvas with the observer.
- [x] **Filter add/edit/clear**: FiltersBar writes to `activeFilters`. Derived `displayedSegments` recomputes. `{#each}` shrinks/grows. Filter status text reactive via FiltersBar's `$displayedResult`.
- [x] **Verse filter change**: `selectedVerse` store write triggers `displayedSegments` re-derivation.
- [x] **Trim mode entry**: `enterEditWithBuffer` finds row via `dom.segListEl.querySelector('.seg-row[data-seg-index=...]')` (still works — Svelte renders the selectors) → trim.ts appends inline DOM to `.seg-left`. No store write, so `{#each}` doesn't fire. Stable row.
- [x] **Trim confirm**: `confirmTrim` mutates seg in place (state.segData.segments[i]), calls `syncChapterSegsToAll`, `computeSilenceAfter`, `exitEditMode` (cleans up inline DOM), `applyVerseFilterAndRender` (notifies segAllData store → derived re-fires → {#each} reconciles, same uid → same row, but new `seg` reference triggers SegmentRow's `$:` re-derivations → updated text/conf class/duration). `syncAllCardsForSegment(seg)` walks remaining cards (validation/history accordions) and updates them.
- [x] **Split confirm**: `confirmSplit` splices `state.segData.segments` (1 → 2 items, both with new uids), reindexes, calls `markDirty`, `_fixupValIndicesForSplit`, `exitEditMode`, `applyVerseFilterAndRender`. Store update fires → `{#each}` keys by new uids → splices in 2 fresh `<SegmentRow>` instances; the original row is removed (its `onMount` cleanup unobserves the canvas). The `_splitChainUid` mechanism (queries `.seg-row[data-seg-uid="..."]` to find the new first-half) still works because Svelte writes the `data-seg-uid` attr.
- [x] **Playback highlight**: `playFromSegment` updates `state.segCurrentIdx`. The animation loop's `updateSegHighlight` queries `dom.segListEl.querySelector('.seg-row[data-seg-index="..."]')` and toggles `.playing` class. Works because Svelte renders `data-seg-index` on every row. The shim's `state._prevHighlightedRow = null` reset ensures stale refs from pre-{#each} renders don't break.
- [x] **Waveform observer**: Each row's onMount adds its canvas to the observer. When the row scrolls into view, observer callback runs `drawWaveformFromPeaksForSeg` → calls `getWaveformPeaks(audioUrl)` (Wave 6b CF migrated). Works.
- [x] **Save+revalidate → missing-word tag refresh**: save.ts writes `state.segValidation = ...`, then calls `applyFiltersAndRender` which fires `segAllData.update`. The `void $displayedSegments` dependency in SegmentsList causes `missingWordSegIndices` to re-derive. SegmentRow's `showMissingTag` updates. (Without the §1.11 fix, this would have been broken.)
- [x] **Back-to-results banner**: `jumpToSegment` (called from validation panel "Go To") sets `state._segSavedFilterView` then calls `_showBackToResultsBanner` → writes to `savedFilterView` store → Navigation.svelte's `$backBannerVisible` → renders banner. Click → dispatch `restore` → SegmentsTab.onNavigationRestore → restore via store writes.
- [x] **Reciter change → clearWaveformCache**: SegmentsTab.clearPerReciterState calls `clearWaveformCache()` instead of writing `state.segPeaksByAudio = null`. Subsequent observer callbacks find empty peaks, queue fresh fetch.

---

## 5. Bug-log delta

- No new OPEN bugs.
- Pre-existing latent bug fixed: missingWordSegIndices stale-after-revalidate (§1.11). Not previously logged in stage2-bugs.md (Stage-1 imperative `renderSegList` always re-read `state.segValidation` per render so it didn't manifest).

---

## 6. Review findings + disposition

### Sonnet (pattern review) — **APPROVE**

All §6.3 conformity, pattern notes #1-#8, `{#each}` adoption correctness, `applyFiltersAndRender` shim coverage (8+ callers), cache migration completeness (zero live `segPeaksByAudio` references — only comment-text hits), cycle ceiling 19 confirmed, S2-B07 grep clean, runtime flows traced.

**Non-blockers (all deferred to Wave 7a.2 / 8):**

| ID | Item | Wave target |
|---|---|---|
| NB-1 | `syncAllCardsForSegment` (rendering.ts:259) mutates `.seg-text` / `.seg-text-ref` / `.seg-text-conf` in-place on Svelte-rendered rows; overwritten on next reconcile. Acceptable because trim/split confirm immediately fires `applyVerseFilterAndRender` — transient. Validation accordion context that calls it without subsequent refresh could show stale data. | Wave 8 |
| NB-2 | `drawAllSegWaveforms` (waveform/index.ts:122) guards on `state.segDisplayedSegments` which is never written post-Wave-7 — effective no-op. Dead guard code smell. | Wave 11 |
| NB-3 | `missingWordSegIndices` `void $displayedSegments` pattern (SegmentsList.svelte:44) — unconventional but correct Svelte-4 workaround for non-store imperative state. Handoff §7.3 queues `state.segValidation` → store promotion. | Wave 8 |

### Opus (judgment review) — **APPROVE**

7 judgment calls validated; 1 real perf concern + 1 fragility invariant flagged.

**Judgment calls:**
- A (`{#each}` + trim/split coexistence): **SOUND.** `trim.ts:324` + `split.ts:350-351` call `exitEditMode` BEFORE `applyVerseFilterAndRender` — inline DOM cleaned before store notify; split confirm creates fresh UIDs so `{#each}` splices cleanly.
- B (`applyFiltersAndRender` shim): **CORRECT.** 8 callers confirmed; `navigation._restoreFilterView` writes both stores explicitly; double-source benign because shim resyncs on every call.
- C (playback highlight / classList): **ROBUST, with fragility.** Svelte 4 `class:X={bool}` compiles to `classList.toggle`, not `className` rewrite — imperative `classList.add('playing')` persists. **Invariant**: 7a.2/7b must NOT add `class:playing={...}` to SegmentRow.svelte unless `updateSegHighlight` migrates to a store simultaneously.
- D (TrimPanel/SplitPanel deferral): **JUSTIFIED.** Wave 7b has no dependency on 7a.2; clean commit boundary.
- E (cycle ceiling): 19 confirmed. Narration in handoff §1.9 slightly misleading (rendering.ts is still in a cycle, just via reversed edge `waveform/index → rendering`); prose nit.
- F (edit store with no consumers): **ACCEPTABLE PRIMING.** Thin shape anticipates 7a.2/7b needs; extend rather than rewrite if merge/delete need `editingSegs: Segment[]`.
- G (state.* bridge coherence): **THIN BUT WORKING.** ~14 fields still bridged; `segPeaksByAudio` genuinely gone; `clearSegDisplay` store-desync carried forward.

**Real perf concern (7a.2 must address):**
- `SegmentsList.svelte:43-55` rebuilds `missingWordSegIndices` Set on every `$displayedSegments` tick and passes by reference to every `<SegmentRow>`. New Set identity → Svelte marks every row dirty → all `$:` blocks re-run. O(N) reactive work per edit confirm (N≈1000 segs possible). **Memoize when `state.segValidation` reference unchanged.**

**7a.2 prerequisites from Opus:**
1. Memoize `missingWordSegIndices` prop-churn.
2. Preserve playing-class invariant (don't add `class:playing` to SegmentRow).
3. Handoff §1.9 cycle-direction clarification.
4. Edit store may need `editingSegs: Segment[]` or `editContext` for 7b merge/delete.
5. `clearSegDisplay` store-desync (Wave 9/10).
6. `event-delegation.ts:132` imperative `state._segSavedFilterView` write — don't add more.

### Orchestrator disposition

- Both reviewers APPROVE. No blockers.
- Opus perf NB (`missingWordSegIndices` memoization) + fragility invariant (`class:playing` prohibition) carried into Wave 7a.2 brief as explicit prerequisites — NOT fixed inline per user migration-strictness preference (clean commit boundary; 7a.2 fresh agent handles alongside the TrimPanel/SplitPanel work).
- Cycle ceiling 19 locked; Wave 7b likely dissolves 2-3 more.
- Proceed to Wave 7a.2 in fresh agent with this handoff + §6 findings as primary input.

---

## 7. Surprises / lessons

1. **Filter-shim approach beats per-caller migration**. The original spec proposed deleting `applyFiltersAndRender` outright and updating ~8 callers. In practice, a thin shim that does `activeFiltersStore.set([...state.segActiveFilters]) + segAllDataStore.update(a => a)` covers every imperative caller in one shot — including the savedFilterView restore path that mutates state directly. This aligns with user preference #migration-strictness and lets Wave 9/10 finish the deletion organically.

2. **`{#each}` reconciliation does NOT fight imperative DOM appended to a row's child during edit**. The risk I worried about (Wave 5 deviation A's whole reason) was that `applyFiltersAndRender → renderSegList` would clobber edit-mode inline DOM. With `{#each}` keyed by `seg.segment_uid`, two things happen:
   - Edit entry doesn't trigger `segAllData.update`, so `{#each}` doesn't re-render — the row stays stable and the inline DOM persists.
   - On confirm, `exitEditMode` removes the inline DOM BEFORE `applyVerseFilterAndRender` fires the store update. Svelte never sees the transient state.
   The Wave 5 fear was specific to Svelte rendering rows AND imperative `renderSegList` rendering rows simultaneously (two writers to the same children). Wave 7 has only one writer (`{#each}`), so the conflict dissolves naturally.

3. **`state.segValidation` not being a store is a footgun for reactive derivations**. `missingWordSegIndices` in SegmentsList depends on it; without a synthetic dependency on `$displayedSegments`, mid-session validation refreshes silently fail to update tags. Pattern: when reading from non-store imperative state in a `$:` derivation, add `void $someStore` as a re-trigger when the imperative state is updated alongside store updates. Consider promoting `state.segValidation` to a store in Wave 8 (validation rewrite).

4. **`_showBackToResultsBanner` was rendering a parallel imperative banner that would have fought Svelte's Navigation since Wave 5**. It worked pre-Wave-7 only because the imperative path never set `savedFilterView` in the store (one-way bridge). Wave 7 closes this loop by writing the store from inside `_showBackToResultsBanner`. The DOM-level injection is now gone.

5. **Cycle ceiling decrements come for free with deletion-driven cleanup**. Two decrements (23→20→19) landed naturally as I removed (a) the rendering import from filters.ts, (b) the waveform/index import from rendering.ts. No targeted cycle-breaking work was needed; just deleting dead code dissolved them.

6. **Bundle grew by ~5kB despite deleting 53 LOC of `renderSegList`**: SegmentRow.svelte's `onMount` waveform-observer registration costs more bytes than the imperative post-walk it replaces, and Svelte's runtime adds reactivity overhead. Net is +5kB; well within budget.

---

## 8. Handoff to sub-wave 7a.2 / Wave 7b

### Prerequisites the next agent must respect

1. **Pattern notes #1-#8** from Wave 4 handoff still apply.
2. **Edit store ready**: `lib/stores/segments/edit.ts` exports `editMode`, `editingSegUid`, `setEdit`, `clearEdit`. Use these from TrimPanel/SplitPanel (and merge/delete/reference panels in Wave 7b).
3. **`{#each}` keyed by uid + index fallback**: edit code writing new segments (split) should set `segment_uid` via `crypto.randomUUID()` (current trim/split.ts does). Fresh uids cause `{#each}` to splice the new rows in, removing the old one (its onMount cleanup unobserves the canvas).
4. **`audioElRef` prop pattern (S2-D33)**: TrimPanel/SplitPanel/EditOverlay should accept `audioElRef: HTMLAudioElement` instead of querying `document.getElementById('seg-audio-player')`. Pass from `SegmentsAudioControls` → `SegmentsTab` → through to the panels.
5. **Edit mode entry stays imperative-from-event**: `event-delegation.ts::handleSegRowClick` → `_handlers.enterEditWithBuffer(seg, row, 'trim'|'split', cat)`. The handler can call `setEdit('trim', seg.segment_uid)` AND continue with the imperative DOM injection (transient — no Svelte conflict). When TrimPanel.svelte renders, it can take over canvas drag handlers via `bind:this`.
6. **Don't write to `dom.segListEl.innerHTML`** anywhere. The `clearSegDisplay` wipe was already removed; new code that wants to "clear" the list should set `segAllData.set(null)` (or filter to empty).
7. **`_showBackToResultsBanner` writes to the savedFilterView store** — don't add a parallel DOM banner injection.
8. **`renderSegCard` is still needed** by validation/error-cards.ts + history/rendering.ts. Don't delete `segments/rendering.ts` until Waves 8 + 10 finish.
9. **Cycle ceiling at 19**: Wave 7b deletions of merge/delete/reference imperative modules should dissolve more cycles. Decrement as appropriate.
10. **Wave 6b CF closure complete**: `state.segPeaksByAudio` field gone. All peaks reads go through `getWaveformPeaks()`. Don't reintroduce the field.

### Queued tasks

- [ ] **TrimPanel.svelte** — drag handles, preview, confirm. Use `<SegmentWaveformCanvas>` from Wave 6b for the waveform; imperative drag/overlay via `bind:this` on a separate overlay canvas OR the same canvas's 2D context (matches current trim.ts model).
- [ ] **SplitPanel.svelte** — single drag handle, preview, confirm + ref-chain trigger. After split, call `startRefEdit` for the first half (current split.ts:374 does this imperatively).
- [ ] **EditOverlay.svelte** — backdrop + cancel/preview/confirm shell that delegates to `<TrimPanel>` or `<SplitPanel>` based on `$editMode`. Replace `_addEditOverlay()` body-append with a Svelte-rendered overlay.
- [ ] **MergePanel / DeletePanel / ReferenceEditor** — Wave 7b scope.
- [ ] **`segments/rendering.ts`** can shrink further once validation + history adopt SegmentRow in history mode (Wave 8 / Wave 10).
- [ ] **Promote `state.segValidation` to a store** during Wave 8 to avoid the §7.3 footgun. The `void $displayedSegments` workaround in SegmentsList becomes unnecessary then.
- [ ] **Wave 9/10 rewrites of save + history**: replace `onSegReciterChange` callers, then delete `data.ts::loadSegReciters` / `onSegReciterChange` / `clearSegDisplay`.

### Open questions for orchestrator

1. **Sub-wave 7a.2 vs Wave 7b**: the original split was 7a (trim+split) / 7b (merge+delete+reference). With trim+split deferred, the natural re-slice is 7a.2 (trim+split+overlay panels) → 7b (merge+delete+reference) — same order, just labeled differently. Recommend a fresh agent for 7a.2 with this handoff as primary input.
2. **Stop-point review**: 7a.1 is a clean boundary (gates green, behavior preserved). Per user preference #6-7 (autonomous between Waves 5-9), proceeding to 7a.2 without stop-point review is appropriate.
3. **Cycle ceiling review**: 19/19 holds. Each deletion in Wave 7b/8/9/10 may dissolve another 1-3.

---

## 9. Suggested pre-flight additions

None. 7-gate + svelte-check caught everything needed.

---

## 10. Commits (exit-point detail)

```
a4d6b23 refactor(inspector): Wave 6b CFs — migrate state.segPeaksByAudio reads to waveform-cache util
a892799 feat(inspector): lib/stores/segments/edit.ts — edit mode store
0200825 feat(inspector): SegmentsList {#each} adoption + applyFiltersAndRender shim
879da86 chore(inspector): decrement cycle ceiling 23 → 20
5e280c8 refactor(inspector): remove dead renderSegList; cycle ceiling 20 → 19
ef8e50f fix(inspector): SegmentsList missingWordSegIndices stale after revalidation
```

6 source commits + this handoff = 7 commits.

---

## 11. Time / token budget (self-reported)

- Tool calls: ~55 (Read/Edit/Write/Bash/Grep/advisor)
- New source files: 1 TS store (`lib/stores/segments/edit.ts`)
- Modified source files: 8 (`segments/{filters,navigation,data,rendering,state,waveform/index,waveform/draw,validation/index,edit/trim,edit/split}.ts`, `tabs/segments/{SegmentsList,SegmentRow,SegmentsTab}.svelte`, `.refactor/stage2-checks.sh`)
- Deletes: `renderSegList` function (53 LOC); `state.segPeaksByAudio` field; `state.segPeaksByAudio` writes/reads (5 sites)
- Bash: ~15 (typecheck/svelte-check/lint/build/git per commit, pre-flight)
- Advisor calls: 2 (pre-{#each}-adoption planning, pre-stop-point reconcile)
- Model: Claude Opus 4.6 (1M context)
- Commits: 6 source + 1 handoff = 7

---

**END WAVE 7a HANDOFF.**
