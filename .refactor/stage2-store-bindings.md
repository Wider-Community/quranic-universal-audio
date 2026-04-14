# Stage-2 Store Bindings Matrix (Wave 5 pre-artifact)

> Generated pre-wave artifact for Wave 5. Source files read: `state.ts`, `data.ts`, `filters.ts`, `navigation.ts`, `rendering.ts`, `index.ts`.

---

## 1. Store: `chapter`

**Proposed shape**
```ts
{
  reciter: string;               // dom.segReciterSelect.value
  chapterId: string;             // dom.segChapterSelect.value (string "1"-"114" or "")
  verseFilter: string;           // dom.segVerseSelect.value
  segData: SegDataState | null;  // state.segData (chapter-specific per-file meta + segments)
  segAllData: SegAllDataState | null; // state.segAllData (full reciter corpus)
  segAllReciters: SegReciter[];  // state.segAllReciters
}
```

**Components that READ it**

| Component | Fields used | Rationale |
|---|---|---|
| `SegmentsTab` | `reciter`, `chapterId` | Drives chapter/reciter selects, passes to children |
| `FiltersBar` | `chapterId`, `segAllData` | `applyFiltersAndRender` reads both to decide whether to show segments |
| `SegmentsList` | `chapterId`, `segAllData`, `verseFilter` | List computation scopes to chapter + verse |
| `SegmentRow` | `chapterId` | Used in `renderSegCard` for dirty-class and `data-seg-chapter` attr |
| `Navigation` | `chapterId`, `segAllData` | `jumpToSegment` / `jumpToVerse` read chapter to decide if re-load needed |

**Components that WRITE it**

| Component | Action |
|---|---|
| `SegmentsTab` | Reciter change clears and reloads chapter; chapter select change sets `chapterId` |
| `Navigation` | `jumpToSegment` / `jumpToMissingVerseContext` programmatically change `chapterId` and trigger re-load |

**Derived values**

- `chapterSegments` — `derived(chapter, $c => getChapterSegments($c.chapterId))` — the per-chapter slice of `segAllData`. Currently computed lazily in `getChapterSegments` using mutable `_byChapter` / `_byChapterIndex` caches on the `segAllData` object itself; Wave 5 should move these to a `derived`.
- `verseOptions` — `derived(chapter, $c => computeVerseSet($c))` — currently built imperatively inside `onSegChapterChange` by iterating `segAllData.segments`.

**Cross-cutting warnings**

- `Navigation` reads `chapter.chapterId` AND `filters.activeFilters` together in `jumpToMissingVerseContext` to decide whether to save the current filter view before navigating away. This is the main cross-cutting surprise: the Navigation component (or the function it calls) must see both stores simultaneously.
- `renderSegList` (→ `SegmentsList`) reads `state.segValidation.missing_words` filtered by chapter to tag rows — this means `SegmentsList` also has an implicit read on the `chapter` store AND the `segValidation` field, which is Wave-6 scope (`validation/index`). Do not bake `segValidation` into `chapter` store shape; pass it as a separate prop or defer to Wave 6.

---

## 2. Store: `filters`

**Proposed shape**
```ts
{
  activeFilters: SegActiveFilter[];  // state.segActiveFilters
  displayedSegments: Segment[] | null; // state.segDisplayedSegments (derived output)
  _segIndexMap: Map<string, Segment> | null; // state._segIndexMap (derived index)
}
```

**Components that READ it**

| Component | Fields used | Rationale |
|---|---|---|
| `FiltersBar` | `activeFilters` | Renders filter rows from this list |
| `SegmentsList` | `displayedSegments` | Iterates the filtered result to render rows |
| `Navigation` | `activeFilters` (+ `chapter.verseFilter`) | `jumpToMissingVerseContext` checks `segActiveFilters.some(f => f.value !== null)` to decide save-view path |
| `rendering` (resolveSegFromRow) | `_segIndexMap` | Used to resolve a `Segment` from a clicked `.seg-row` element |

**Components that WRITE it**

| Component | Action |
|---|---|
| `FiltersBar` / `FilterCondition` | Add, remove, mutate individual filter rows; calls `applyFiltersAndRender` after each change |
| `Navigation` | `_restoreFilterView` writes `activeFilters` back from saved snapshot; `jumpToMissingVerseContext` clears filters before navigating |
| `SegmentsTab` | `clearSegDisplay` zeros out `segActiveFilters` on reciter change |

**Derived values**

- `displayedSegments` — `derived([chapter, filters], fn)` — the result of `applyFiltersAndRender`. Currently written back into `state.segDisplayedSegments` as a side-effect. In Svelte this should be a `derived` off both `chapter` and `filters` stores; do NOT make it `writable`.
- `_segIndexMap` — `derived(filters, $f => new Map($f.displayedSegments.map(...)))` — purely a lookup index of the derived output; never needs to be writable.
- Filter count / status text shown in `FiltersBar` (`segFilterCountEl`, `segFilterStatusEl`) — reactive label strings, ideal as inline `$derived` in the component.

**Cross-cutting warnings**

- `displayedSegments` is derived from BOTH `chapter` (for `segAllData`, `chapterId`, `verseFilter`) and `filters` (`activeFilters`). The derived store must take both as inputs. The impl agent should model this as `derived([chapterStore, filtersStore], fn)`, not as a standalone `filters`-only derived.
- `_segFilterDebounceTimer` (state field) is a transient implementation detail of the value-input's `oninput` handler. In Svelte this becomes a local `let timer` inside `FilterCondition.svelte` — do NOT put it in the store.
- `_segSavedFilterView` (state field) is navigation-owned state (save/restore for go-to). It should live in the `navigation` store, not in `filters`.

---

## 3. Store: `navigation`

**Proposed shape**
```ts
{
  savedFilterView: SegSavedFilterView | null; // state._segSavedFilterView
  backBannerVisible: boolean;                  // whether banner is injected
}
```

**Components that READ it**

| Component | Fields used | Rationale |
|---|---|---|
| `Navigation` | `savedFilterView`, `backBannerVisible` | Drives banner render and back-button click handler |
| `FiltersBar` | `savedFilterView` | `applyFiltersAndRender` clears `_segSavedFilterView` when active filters exist — cross-cut |
| `SegmentsList` | (indirect) | Banner is prepended to `segListEl`; in Svelte should be a slot or sibling component |

**Components that WRITE it**

| Component | Action |
|---|---|
| `Navigation` | `jumpToMissingVerseContext` writes `savedFilterView`; `_restoreFilterView` clears it |
| `FiltersBar` | `applyFiltersAndRender` sets `_segSavedFilterView = null` when active filters are non-empty — this is a cross-cutting write |
| `SegmentsTab` | `clearAllSegFilters` sets `_segSavedFilterView = null` |

**Derived values**

- `backBannerVisible` can be `derived(navigation, $n => $n.savedFilterView !== null)` — controls whether the `Navigation` component renders the back-banner at all.

**Cross-cutting warnings**

- `FiltersBar` writes `navigation.savedFilterView = null` (via `applyFiltersAndRender`). This is the most important cross-cut: the filter application logic currently destroys the saved navigation state as a side effect. In Svelte the cleanest fix is to have `FiltersBar` dispatch an event or call a shared action, rather than importing and writing the navigation store directly. Alternatively: move the "clear saved view on filter change" rule into a `derived` or `subscribe` side-effect in `Navigation.svelte`.

---

## Notable Patterns for the Impl Agent

1. **No DOM-in-store.** `dom.*` fields (`segListEl`, `segFilterRowsEl`, etc.) are all element refs that must NOT be carried into any Svelte store. Replace with `bind:this` in the component that owns each element. The `DomRefs` interface is fully redundant once components own their own refs.

2. **`_segSavedPreviewState` is out of Wave 5 scope.** It is only used by `save.ts` (Wave 7+). Do not model it in Wave 5 stores at all; it should remain in `state` until Wave 7.

3. **Debounce timer is local state.** `state._segFilterDebounceTimer` is only ever set and cleared inside `filters.ts` filter-value `input` handler. Make it a component-local `let` in `FilterCondition.svelte`.

4. **`segChapterSS` (SearchableSelect) is a component-local concern.** The `SearchableSelect` wrapper lives on the `segChapterSelect` element. In Svelte the chapter select will be a `<select bind:value>` in `SegmentsTab`; the SS enhancement can be handled via `onMount` in that component. Do not put `segChapterSS` in any store.

5. **Playback highlight fields are out of Wave 5 scope.** `_prevHighlightedRow`, `_prevHighlightedIdx`, `_prevPlayheadIdx`, `_currentPlayheadRow` are all used by `playback/index.ts` (Wave 8). Flag them — Wave 5 `SegmentsList` must NOT encode these in its store shape.

6. **`segDisplayedSegments` must be derived, not writable.** The current code writes it as a side-effect of `applyFiltersAndRender`. Making it a `writable` store in Wave 5 would be a tautological pass-through (the S2-D33 anti-pattern). Use `derived([chapterStore, filtersStore], computeDisplayed)` instead.

7. **`SegmentRow` history-mode props are additive, not a different mode.** The existing `renderSegCard` `RenderSegCardOptions` already has `readOnly`, `showChapter`, `showPlayBtn`. Wave 5 must declare the full prop interface from day one per S2-D23: `readOnly?`, `showChapter?`, `showPlayBtn?`, `splitHL?`, `trimHL?`, `mergeHL?`, `changedFields?`, `mode?`. The `changedFields` and highlight props are Wave-6+ concerns but the interface slot must exist so `SegmentRow` is not broken when history/waveform waves land.

8. **`segOpLog` and `segDirtyMap` are shared with Wave 6+.** `isIndexDirty(chapter, index)` is called inside `renderSegCard` to apply the `dirty` CSS class per row. If `segDirtyMap` is moved into a store in Wave 5 (`chapter` store is the natural home), Wave 6 edit operations will need to write to it. Do not freeze its store placement — mark it provisional under S2-D11.

9. **`_segIndexMap` races with navigation.** `resolveSegFromRow` reads `state._segIndexMap` to look up a segment from a clicked row. This map is rebuilt by `applyFiltersAndRender` synchronously. In Svelte, if `displayedSegments` is derived, `_segIndexMap` should be derived from it as well to avoid a stale-map window.

10. **`computeSilenceAfter` mutates `segAllData.segments` in-place.** Called once after `segAllData` loads. In Svelte this should run as a side effect when the `chapter` store's `segAllData` field is first set (e.g. in a `$effect` or `derived` initializer), not as a standalone imperative call. The mutation pattern (`seg.silence_after_ms = ...`) is safe only if `segAllData` is owned by a single store; document this ownership clearly so Wave 6 edit ops that also mutate segments know the write protocol.
