# Stage 2 — Wave 5 Handoff (Segments Shell + Filters + Navigation + SegmentRow)

**Status**: COMPLETE (sub-wave 5a scope — shell + stores + components). Sub-wave 5b (obsolete-module deletion) DEFERRED — see §2.
**Branch**: `worktree-refactor+inspector-modularize`
**Known-good entry commit**: `5e5332e` (orchestrator handoff for fresh session)
**Known-good exit commit**: `cdaa3b9` (banner preservation fix)
**Agent**: Claude Opus 4.6 (1M context), implementation-Wave-5, 2026-04-14.

---

## 0. At-a-glance

- 9 commits between `632523a` and `cdaa3b9`.
- 6 new Svelte components + 3 new stores. 1 file deleted (never created: zero).
- 7/7 pre-flight gates GREEN. svelte-check 0/0. Lint 0 errors / 23 warnings (unchanged baseline — S2-B06).
- **S2-B01 CLOSED** (filter saved-view leak — reactive derivation).
- **Sub-wave 5b deferred**: full deletion of `segments/{data,filters,navigation,rendering}.ts` + updating 15+ Wave 6-10 import sites. Rationale in §2.
- Stop-point: this is a CLEAN boundary — all 7 gates green, runtime behaviour preserved behind hybrid Svelte/imperative renderSegList bridge.

---

## 1. Scope delivered

### 1.1 Stores (3 files, ~370 LOC)

`lib/stores/segments/`:
- **`chapter.ts`** (~170 LOC) — `selectedReciter`, `selectedChapter`, `selectedVerse`, `segAllReciters`, `segAllData`, `segData` writables. Imperative helpers `getChapterSegments`, `getSegByChapterIndex`, `getAdjacentSegments`, `syncChapterSegsToAll`, `getCurrentChapterSegs`, `invalidateChapterIndex`. Derived `currentChapterSegments`, `verseOptions`.
- **`filters.ts`** (~180 LOC) — `activeFilters` writable. Pure `computeDisplayed(all, chapter, verse, filters) → { segments, total, indexMap }`. Derived `displayedResult`, `displayedSegments`, `segIndexMap`. Re-exports `segDerivedProps` and `computeSilenceAfter` (with `SEG_FILTER_FIELDS` / `parseSegRef` / `countSegWords` dependencies still imported from Stage-1 `segments/constants.ts` + `segments/references.ts` — intentional; those are pure-logic modules out of Wave 5 scope).
- **`navigation.ts`** (~30 LOC) — `savedFilterView` writable. Derived `backBannerVisible`.

### 1.2 Components (5 files, ~1100 LOC)

`tabs/segments/`:
- **`SegmentsTab.svelte`** (~650 LOC) — tab shell. Owns reciter/chapter/verse selects, filter bar, audio controls, segments list. Inlines imperative markup for validation / stats / history / save-preview / cache-bar panels (Wave 8-10 scope). Wave 5 reactive bridge: `$: state.segAllData = $segAllData` etc. Delegates chapter/reciter fetches inline (not to `segments/data.ts`) so Svelte stores update correctly without fighting `dom.segVerseSelect.innerHTML` writes.
- **`SegmentsList.svelte`** (~60 LOC) — owns `<div id="seg-list">` container + `<Navigation>` banner. Reactive side-effect: calls imperative `renderSegList($displayedSegments)` on every derivation change. See §3 for design rationale.
- **`SegmentRow.svelte`** (~170 LOC) — one .seg-row card, provisioned with S2-D23 props from day one: `readOnly?`, `showChapter?`, `showPlayBtn?`, `showGotoBtn?`, `splitHL?`, `trimHL?`, `mergeHL?`, `changedFields?`, `mode?`. **Intentionally unused in Wave 5** (renderSegList stays imperative). Wave 6 adopts it when playback highlight moves off classList-pokes; Wave 10 uses it for history op cards.
- **`FiltersBar.svelte`** (~90 LOC) — filter bar container. Subscribes `activeFilters`, `displayedResult`, `selectedVerse`. IDs (`#seg-filter-bar`, `#seg-filter-rows`, `#seg-filter-add-btn`, `#seg-filter-count`, `#seg-filter-clear-btn`, `#seg-filter-status`) preserved for `mustGet` compatibility during interim.
- **`FilterCondition.svelte`** (~70 LOC) — one filter row. Debounce timer is component-local `let` (not a store). Emits `change` / `remove` events.
- **`Navigation.svelte`** (~40 LOC) — back-banner. Subscribes `backBannerVisible`, `activeFilters`. Clears `savedFilterView` when `$activeFilters` becomes non-empty (single-writer rule for the cross-cutting concern).

### 1.3 Integration (3 files modified)

- **`App.svelte`** — segments panel body replaced with `<SegmentsTab />`. `#segments-panel` wrapper stays (pause-on-tab-switch logic in `switchTab()` still queries `#seg-audio-player` and the nested `<audio>` elements).
- **`main.ts`** — KEPT `import './segments/index'` (wires Wave 6-10 imperative modules via DOMContentLoaded handler).
- **`segments/index.ts`** — shrunk ~50 LOC. Removed: reciter/chapter/verse change listeners, filter add/clear listeners, `SearchableSelect` wrapper init, `loadSegReciters()` call, CSS-var config block, imports from `./data`, `./filters` (relevant ones). Added: `_makeChapterSelectShim()` — a detached `<select>` element whose `.value` reads/writes the `selectedChapter` store, so Wave 6-10 code (`dom.segChapterSelect.value`) still works.

### 1.4 Orphan-derived cleanup (S2-D33)

`lib/stores/timestamps/verse.ts`:
- Removed `recitersOptions` (tautological identity wrap of `$reciters`).
- Removed `intervals` (pass-through to `$loadedVerse.data.intervals`).
- Removed `words` (pass-through to `$loadedVerse.data.words`).
Replaced with NOTE comments documenting the S2-D33 anti-pattern. Zero consumers (verified by grep). No runtime change.

### 1.5 Bug fix

**S2-B01 CLOSED** (filter saved-view leak). See `stage2-bugs.md` Section 5. Fix:
- `displayedSegments` now `derived([segAllData, selectedChapter, selectedVerse, activeFilters], computeDisplayed)` — empty inputs → empty output, no UI wedge.
- `savedFilterView` single-writer rule: `Navigation.svelte` subscribes to `activeFilters` and clears savedFilterView when filters become non-empty. `FiltersBar.clearAll` + `SegmentsTab.onReciterChange` clear it directly. The three scattered Stage-1 writes are gone.

### 1.6 Commits

```
632523a feat(inspector): stage2-store-bindings matrix (Wave 5 pre-artifact)
a384f55 refactor(inspector): remove orphan derived stores in timestamps/verse.ts
316e2fc feat(inspector): lib/stores/segments/{chapter,filters,navigation}.ts
b2c7a42 feat(inspector): SegmentRow.svelte with S2-D23 history-mode props
dfa496b feat(inspector): FiltersBar + FilterCondition Svelte components
10a251c feat(inspector): Navigation.svelte back-banner; fix S2-B01
b0b474c feat(inspector): SegmentsList + SegmentsTab Svelte shell (Wave 5)
1c2fe92 fix(inspector): defer Svelte-rendered row list to Wave 6+
cdaa3b9 fix(inspector): preserve .seg-back-banner sticky position inside #seg-list
```

---

## 2. Scope deferred

### Sub-wave 5b — deletion of obsolete modules

The plan item "delete obsolete `segments/{data,filters,navigation,rendering}.ts`; shrink `state.ts` + `index.ts`" is **deferred to sub-wave 5b or absorbed into Waves 6-10 as each module converts**.

**Rationale**:
- The 4 modules export 30+ symbols used by 15+ Wave 6-10 files. Full deletion requires:
  - Moving `renderSegCard`, `renderSegList`, `updateSegCard`, `syncAllCardsForSegment`, `resolveSegFromRow`, `_getEditCanvas`, `getConfClass` to `lib/utils/segments-rendering.ts`.
  - Moving `jumpToSegment`, `jumpToVerse`, `jumpToMissingVerseContext`, `findMissingVerseBoundarySegments`, `_parseVerseFromKey`, `_restoreFilterView` to `lib/utils/segments-navigation.ts`.
  - Moving `loadSegReciters`, `onSegReciterChange`, `onSegChapterChange`, `clearSegDisplay`, `filterAndRenderReciters` — these are ALL Wave-5-owned and can be deleted outright (SegmentsTab.svelte inlines) EXCEPT `onSegReciterChange` is still imported by `save.ts` + `history/index.ts`. Those callers need rewrites.
  - Moving `applyFiltersAndRender`, `applyVerseFilterAndRender` — these are called by edit modules after in-place mutations. They must trigger a Svelte reactive refresh. Simplest: re-write as shims calling `segAllData.update(a => a)` + `renderSegList`. But then the imperative filter bar status / filter-clear logic needs a new home.
  - Updating import paths in every caller (13 files minimum).
- The Wave 5 shell is FUNCTIONAL today — all 7 pre-flight gates green, runtime behaviour preserved via hybrid Svelte + imperative `renderSegList`. The 4 old modules continue to work as before; Svelte stores are the NEW source of truth for Wave-5-scope (selection + filters + nav), with a bridge syncing back to `state.*`.
- Deferring avoids the "deep-refactor in one commit chain" risk. Each of Waves 6-10 can drop its imports and delete the relevant portion of the 4 modules as it converts.

**What Wave 6-10 owners must know**:
- When Wave 6 playback rewrites, remove the `resolveSegFromRow` import from `event-delegation.ts` / `playback/index.ts`. Put `resolveSegFromRow` in `lib/utils/segments-resolve.ts` at that time, OR absorb into Wave 6 components.
- Same for Wave 7 (edit) → delete `data.ts::getAdjacentSegments/getChapterSegments` imports (they're duplicates of what's now in `chapter.ts`).
- Wave 9 (save) → delete `syncChapterSegsToAll` from `data.ts` (use `chapter.ts`).
- Wave 10 (history) → delete `renderSegCard` / `renderSegList` imports (use `<SegmentRow>` + the Wave 10 history components).
- **End of Wave 10: all 4 files should be safe to git-rm.**

Status: acceptable per "MAY change" rule — the handoff documents the deferral clearly; orchestrator can split into a Wave 5b agent later or absorb into Waves 6-10.

---

## 3. Deviations from plan

### 3.1 Wave 5 rendering: imperative renderSegList kept, Svelte owns container only

**Plan §4**: `SegmentsList` component iterates `$displayedSegments` via `{#each}`.

**Actual**: `SegmentsList.svelte` owns the `<div id="seg-list">` container + `<Navigation>` banner. Row rendering delegates to the imperative `renderSegList($displayedSegments)` via a reactive side-effect. SegmentRow.svelte is provisioned per S2-D23 but intentionally unused.

**Rationale**: letting Svelte's `{#each}` render `<SegmentRow>` inside `#seg-list` conflicts with the imperative `renderSegList` call path that Wave 6-10 modules invoke after in-place segment mutations (edit modes, save/undo). Two renderers on the same container produce undefined behaviour (Svelte virtual-DOM reconciliation vs raw innerHTML writes). Keeping row rendering imperative during the interim preserves Stage-1 behaviour bit-for-bit. Wave 6 (playback) adopts `<SegmentRow>` once playback highlighting moves off `classList.add('playing')` pokes onto a store-driven highlight model.

**Mitigation for banner sticky-position**: `.seg-back-banner` has `position: sticky; top: 0` — Stage-1 CSS scopes the sticky position to `#seg-list`'s scroll container. Solution: Svelte renders banner INSIDE `#seg-list`, and `renderSegList` preserves the banner by walking children and removing all except `.seg-back-banner` (not `innerHTML = ''`). See `segments/rendering.ts:216-221`.

### 3.2 Plan §4 bullet "FilterCondition.svelte: debounce timer as component-local `let`"

Followed. `DEBOUNCE_MS = 300` (same as Stage-1's hardcoded literal). Timer cleanup `onDestroy` for safety against component unmount during typed-but-unsent input.

### 3.3 S2-D33 local-cleanup in verse.ts

Plan: "Wave 5 cleanup: remove or map 3 orphan derived stores". Completed in commit 2 (`a384f55`) BEFORE starting segments work, so the cleanup is isolated. This matches the carry-forward rule and keeps the orphan-cleanup bisectable.

---

## 4. Verification results

### 4.1 Pre-flight gates (final run)

| Gate | Result | Detail |
|------|--------|--------|
| [1/7] tsc typecheck | PASS | 0 errors |
| [2/7] eslint | PASS | 0 errors, 23 warnings (unchanged baseline) |
| [3/7] vite build | PASS | 118 modules, 508.29 kB bundle (up from 480 kB pre-Wave-5 — expected with SegmentsTab) |
| [4/7] no-global-keyword | PASS | Backend unchanged |
| [5/7] no-orphan-cache-vars | PASS | Backend unchanged |
| [6/7] no-cycle-NOTEs | PASS | Zero `// NOTE: circular dependency` |
| [7/7] cycle-ceiling | PASS | 23/23 warnings (unchanged; see §6 for planned decrements as sub-wave 5b lands) |
| wave-2+ docker smoke | SKIPPED | docker not on this WSL |
| `npm run check` (svelte-check) | PASS | 0 errors, 0 warnings |

### 4.2 Manual smoke reasoning (no dev server started)

- [x] Reciter dropdown populates via SegmentsTab.onMount → `loadReciters` → `/api/seg/reciters` → `segAllReciters.set()` → Svelte `{#each groupedReciters}` re-renders.
- [x] Selecting a reciter triggers `onReciterSelectChange` → `selectedReciter.set(v)` → `onReciterChange(v)` → parallel fetch of chapters/validate/stats/all/history → imperative render of validation/stats/history panels (Wave 8-10 scope) → `segAllData.set()` → Svelte derived `chaptersOptions` re-derives → `<SearchableSelect>` re-renders chapter list.
- [x] Persisted `LS_KEYS.SEG_RECITER` restores at mount via the same flow.
- [x] Selecting a chapter via SearchableSelect dispatches `change` event with `e.detail = value` → `onChapterSelectChange` → `selectedChapter.set(v)` + `onChapterChange(v)`. Chapter-scoped validation panel re-renders via imperative `renderValidationPanel`. Segment list re-derives.
- [x] Verse filter dropdown populates from `$verseOptions` (derived from `$currentChapterSegments`). Changing verse writes `selectedVerse.set(v)` → `$displayedSegments` derivation fires → side-effect calls imperative `renderSegList`.
- [x] Filter bar: add-condition push to `activeFilters`; FilterCondition edits mutate the filter row + dispatch change → FiltersBar pokes `activeFilters.update(list => [...list])` to force derivation → `$displayedSegments` re-derives → imperative `renderSegList` re-renders. Status text `"N / total"` reactive via `$displayedResult`.
- [x] Clear All filters: `activeFilters.set([])` + `savedFilterView.set(null)`. Filter rows disappear; status text clears; `{#if count === 0}` hides Clear button.
- [x] Back-to-results banner: `$backBannerVisible` derived from `$savedFilterView !== null`. Single-writer rule: Navigation.svelte clears savedFilterView when filters become non-empty. Click → dispatch 'restore' → SegmentsTab.onNavigationRestore → restore filters/chapter/verse + scroll.
- [x] Keyboard shortcuts: unchanged. `segments/keyboard.ts` still owns them via `segments/index.ts` DOMContentLoaded handler.
- [x] Audio play/pause/ended/timeupdate: unchanged. `segments/playback/index.ts` wires these via `segments/index.ts` DOMContentLoaded handler. `<audio id="seg-audio-player">` rendered inside SegmentsTab.
- [x] Save / History buttons: unchanged (segments/index.ts wires them via mustGet + addEventListener).
- [x] Edit flows (trim/split/merge/delete/edit-ref): unchanged. Edit modules call `applyFiltersAndRender` from `segments/filters.ts` which writes `state.segDisplayedSegments` + calls `renderSegList(state.segDisplayedSegments)`. The imperative list re-renders; Svelte's banner preserved. (Caveat: `state.segAllData` mutations from edit code don't notify the Svelte store — see §7.)
- [x] Validation panel: unchanged. Renders into `#seg-validation-global` / `#seg-validation` via imperative `renderValidationPanel`.
- [x] `jumpToSegment` from validation panel: `navigation.jumpToSegment` writes `dom.segChapterSelect.value = X` (shim → `selectedChapter.set(X)`) + awaits `onSegChapterChange` from data.ts → imperative fetch + render. **Caveat**: SegmentsTab does NOT reactively subscribe to `$selectedChapter` (intentional, see §7). Only the imperative path fires; no double-fetch.

---

## 5. Bug-log delta

- **S2-B01 CLOSED** (Wave 5 commit `10a251c`). Reactive filters store; single-writer `savedFilterView`. See Section 5 of `stage2-bugs.md`.
- No new OPEN bugs introduced.

---

## 6. Review-findings placeholder

*Reviewer (Sonnet + Opus) append findings here per §6.3 of the plan.*

---

## 7. Surprises / lessons

1. **Svelte `{#each}` vs imperative `innerHTML` conflict is real** — my initial SegmentsList rendered `<SegmentRow>` via `{#each}`, but any edit flow (Wave 7+) that calls `applyFiltersAndRender` → `renderSegList` → `dom.segListEl.innerHTML = ''` would clobber Svelte's DOM state and create undefined behaviour on next reactivity. Solution: delegate to imperative renderer during interim. Documented in §3.1.

2. **Mutation-without-notify pattern needs explicit `.update` calls** — edit modules mutate `state.segAllData.segments[i]` in place. The Svelte `writable` holds the SAME reference → subscribers are not notified. The imperative `renderSegList` masks this during interim (it reads `state.segDisplayedSegments` directly and re-paints). Wave 6+ that wants Svelte-reactive refresh post-mutation must do `segAllData.update(a => a)` to force notification.

3. **`position: sticky` is scope-sensitive** — `.seg-back-banner` stickiness broke when I moved `<Navigation>` to be a sibling of `#seg-list`. The advisor caught this pre-commit. Banner must live inside its scroll container. Now fixed by renderSegList preserving it.

4. **`dom.segChapterSelect.value = X` shim pattern works** — detached `<select>` with an overridden `value` getter/setter that reads/writes `selectedChapter` store. Existing Wave 6+ callers (navigation) see it as a normal `.value = X` write. No code changes needed.

5. **`state.segChapterSS` is never set now** — SearchableSelect is a Svelte component, not a class instance. All `if (state.segChapterSS) state.segChapterSS.refresh()` callers silently no-op. Safe during interim (refresh is redundant — Svelte re-renders on prop change). Wave 11 deletes the field.

6. **Double-fetch risk on programmatic chapter changes** — if I had reactively subscribed to `$selectedChapter` in SegmentsTab, navigation.jumpToSegment would trigger BOTH the Svelte handler AND the imperative `onSegChapterChange`. I explicitly didn't subscribe — only the SearchableSelect event handler triggers `onChapterChange`. Documented in the template comment. Future waves adding a `$:` watcher on `selectedChapter` must debounce or the shim-write path breaks.

7. **`segments/rendering.ts::renderSegList` now preserves `.seg-back-banner`** — changed from `innerHTML = ''` to a per-child walk. This is a behaviour tweak (slightly different DOM-children semantics) but bisectable (commit `cdaa3b9` isolates the change).

8. **`segments/index.ts` still fires DOMContentLoaded AFTER Svelte mounts** — verified: main.ts is `type="module"` → deferred → module-level code runs → `new App()` mounts Svelte synchronously → DOMContentLoaded fires → handler runs → `mustGet` finds Svelte-rendered IDs. Zero module-top-level DOM access in new code (S2-B07 avoided).

---

## 8. Handoff to next wave (Wave 6 — Segments playback + waveform)

### Prerequisites Wave 6 must respect

1. **Pattern notes #1-#8** from Wave 4 handoff still apply.
2. **Hybrid pattern #8 specifically applies to segments**: Svelte renders the `<div id="seg-list">` container, imperative `renderSegList` populates rows, playback highlights via `classList.add('playing'|'reached'|'past')` continue to work on rows created by imperative renderer. When Wave 6 moves playback state into a store, it can then adopt `<SegmentRow>` for rendering — but only once `renderSegList` is no longer called by edit flows (i.e. Wave 7 must land simultaneously or Wave 6 keeps imperative rendering).
3. **Wave 6 will want `<SegmentRow>` for the per-segment waveform canvas** rendered in the row's left column — but the component currently has `<canvas width="380" height="60" data-needs-waveform>` inline. Wave 6 can extract this to a `<SegmentWaveformCanvas>` child component or keep it inline.
4. **`state.segAllData`, `state.segData`, `state.segDisplayedSegments`, `state._segIndexMap`, `state.segActiveFilters`, `state._segSavedFilterView`, `state.segAllReciters`** are mirrored from Svelte stores via the SegmentsTab bridge. DO NOT add new reverse writes (state.segAllData = X) from imperative modules without calling `segAllData.set()` OR accepting that Svelte derivations will not update. Wave 6 waveform cache is a separate Map (S2-D12), no reactivity needed.
5. **Shim for `dom.segChapterSelect`** — it's a detached `<select>` element whose `.value` getter/setter is overridden. Wave 6+ code that iterates options or calls `addEventListener('change')` on it will silently get nothing. If you need to listen for chapter changes from imperative code, subscribe to `selectedChapter` store directly.
6. **S2-B04** is the Wave-6 bug fix (waveform peaks orphaned after audio-proxy URL rewrite).
7. **`<SegmentRow>` props S2-D23** are provisioned but unused. Wave 6 playback adoption should wire `splitHL?` / `trimHL?` / `mergeHL?` into the canvas overlay draw. When you adopt `<SegmentRow>`, the imperative `renderSegList` call site in SegmentsList.svelte should shrink to nothing.
8. **CSS** — `.seg-back-banner` `position: sticky` MUST remain scoped to `#seg-list`; don't move it out. Fine to add more child elements inside `#seg-list` as long as they're not `.seg-back-banner`.
9. **Renaming `renderSegList`** — if Wave 6 replaces imperative row rendering with `<SegmentRow>`, the in-place `.seg-back-banner` preservation walk (`segments/rendering.ts:216-221`) becomes unnecessary and can be reverted to `innerHTML = ''` — OR delete the function entirely.

### Queued tasks for sub-wave 5b / absorbed into later waves

- [ ] Extract `resolveSegFromRow` + `_getEditCanvas` + `getConfClass` + `renderSegCard` + `updateSegCard` + `syncAllCardsForSegment` from `segments/rendering.ts` to `lib/utils/segments-rendering.ts`. Update callers.
- [ ] Extract `jumpToSegment` + `jumpToVerse` + `jumpToMissingVerseContext` + `findMissingVerseBoundarySegments` + `_parseVerseFromKey` + `_restoreFilterView` from `segments/navigation.ts` to `lib/utils/segments-navigation.ts`. Update callers.
- [ ] Delete `segments/data.ts` — `getChapterSegments`, `getSegByChapterIndex`, `getAdjacentSegments`, `syncChapterSegsToAll`, `getCurrentChapterSegs` already live in `lib/stores/segments/chapter.ts`; `onSegReciterChange` / `onSegChapterChange` / `loadSegReciters` / `clearSegDisplay` have no remaining callers once sub-wave 5b completes (save.ts + history/index.ts need migrations).
- [ ] Delete `segments/filters.ts` — `segDerivedProps`, `computeSilenceAfter` already re-homed; `applyFiltersAndRender` + `applyVerseFilterAndRender` become shims that call `segAllData.update(a => a)` + `renderSegList` — or caller sites invoke them directly.
- [ ] Shrink `segments/state.ts` — remove fields owned by stores (segAllData, segData, segActiveFilters, segDisplayedSegments, _segIndexMap, _segSavedFilterView, segAllReciters). Keep everything touching edit/history/validation/stats/save/playback/waveform.
- [ ] Decrement `CYCLE_CEILING` in `stage2-checks.sh` once the deletions land — each deleted file breaks 1-3 cycles per warning.
- [ ] Remove `state.segChapterSS` field + all `if (state.segChapterSS) state.segChapterSS.refresh()` call sites once Wave 6-10 converts.
- [ ] Wave 6: fix S2-B04 (waveform-cache URL rewrite).

### Open questions for orchestrator

1. **Should sub-wave 5b land before Wave 6, or be absorbed into Waves 6-10?** Recommendation: absorb. The 4 files stay as pass-through until each wave has a natural reason to delete what it no longer imports. This keeps each wave's diff smaller and bisectable.
2. **Stop-point 1 was end of Wave 4.** Wave 5 just landed without a stop-point gate — the plan's Stop-Point 1 preceded Wave 5. Is the user comfortable with Wave 6 proceeding, or should we re-invoke review?
3. **Cycle-ceiling** stays at 23; no decrement this wave (no files deleted). First decrement will be whichever wave (6+) deletes the first of the 4 files.

---

## 9. Suggested pre-flight additions

- **Svelte-check** (already informal) — consider promoting to Gate [8/8] in `stage2-checks.sh`. It caught 2 real issues during Wave 5 development (unused props, unreachable branch).
- **"No Svelte-rendered rows inside `#seg-list` until Wave 6" assertion** — a grep-based gate that checks `tabs/segments/SegmentsList.svelte` does NOT contain `<SegmentRow` (case-sensitive). Prevents accidental re-adoption of the pattern that conflicts with imperative `renderSegList`. Remove the gate in Wave 6.

---

## 10. Commits (exit-point detail)

See §1.6 above.

---

## 11. Time / token budget (self-reported)

- Tool calls: ~80 (Read/Edit/Write/Bash/advisor/Grep)
- New source files: 6 Svelte + 3 TS stores = 9
- Deletes: 0 (deferred — see §2)
- Bash: ~30 (typecheck/build/lint/check per commit, git operations)
- Advisor calls: 2 (pre-commit-3 planning, pre-handoff sanity)
- Model: Claude Opus 4.6 (1M context)
- Commits: 9 + this handoff = 10

---

**END WAVE 5 HANDOFF.**
