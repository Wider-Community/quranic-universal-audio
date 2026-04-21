# Ph13 — Final polish sprint: bugs + LOC targets + type hygiene + dedupe

Baseline HEAD: `cf52c1c`. Branch: `inspector-refactor`.

All three review reports (Opus design / Sonnet general / Haiku criteria) agreed the main refactor goals are met. Ph13 closes the remaining findings.

## Ph13a — Runtime bugs + dead code + micro-polish (Sonnet)

### HIGH bugs

**A1. `lib/utils/segments/save-execute.ts:~155`** — the `.catch(() => refreshValidation())` on the `trigger-validation` POST call is wrong: if the endpoint is unreachable, refreshing the validation panel reloads the stale pre-save snapshot. Fix: remove `refreshValidation()` from the `.catch` branch; log via `console.warn('trigger-validation failed:', err)` and stop. Callers already handle stale-data via the post-save reload path.

**A2. `lib/utils/segments/play-range.ts:~139`** — when `_playRange` is called while `audioEl.src` is being changed, a second `once: true` `canplay` listener gets registered before the first one fires. The old `doPlay` closure stays alive with stale `startMs/endMs`, causing a double-seek. Fix: hoist the `canplay` handler to module-level `let _previewCanplayHandler: (() => void) | null`, `removeEventListener('canplay', h)` the old one before registering a new one (mirror the existing `_previewStopHandler` pattern).

### MEDIUM bugs

**A3. `inspector/services/undo.py:~337 and ~414`** — in both `undo_batch` and `undo_ops`, the `except ValueError` block calls `invalidate_seg_caches(reciter)` before any write. Remove that call from both except blocks; cache only becomes stale after a successful write.

**A4. `lib/utils/segments/waveform-utils.ts:~148-155`** — `parseInt(row.dataset.segIndex ?? '')` can produce `NaN` during fast chapter switches when the observer fires before dataset is fully populated. Add `if (isNaN(idx) || isNaN(chapter)) return;` before calling `getSegByChapterIndex`.

**A5. `tabs/segments/StatsChart.svelte::handleSave`** — `fetchJson(...).then(...)` has no `.catch`; network failure = silent no-tip. Add `.catch((err) => console.warn('Stats save failed:', err))`.

**A6. Magic color `#f72585`** — hardcoded in two places: `lib/utils/segments/play-range.ts:~115` and `lib/utils/segments/waveform-draw-seg.ts:~85`. Move to `lib/utils/constants.ts` as `export const PREVIEW_PLAYHEAD_COLOR = '#f72585';` and import in both callers.

### Dead exports (delete all 5)

**A7.** `lib/utils/ls.ts::lsRestore` — zero importers (every `localStorage.getItem` reads directly).
**A8.** `lib/utils/webaudio-peaks.ts::_clearAudioBufferCache` — "testing hook" never called.
**A9.** `lib/utils/waveform-cache.ts::waveformCacheSize` — zero importers.
**A10.** `lib/utils/segments/playback.ts::animateSeg` — "legacy caller passthrough" with no importers.
**A11.** `lib/utils/segments/playback.ts::isSegAnimRunning` — zero importers.

Verify with `rg "lsRestore|_clearAudioBufferCache|waveformCacheSize|animateSeg|isSegAnimRunning" inspector/frontend/src` after deleting — should return only the definition site or zero.

### Micro-polish

**A12.** `lib/stores/segments/dirty.ts:~8-11` — docstring references "bug B01". Reword to plain "Map keys are always `number` (never string-cast)." No `B01`/`S2-B01`/bug-number references.

**A13.** `lib/utils/segments/edit-common.ts` — add one-line comment noting `enterEditWithBuffer` lives separately in `edit-enter.ts` to break a cycle.

**A14.** `tabs/segments/FiltersBar.svelte:~36` — replace `rowsEl?.querySelectorAll<HTMLInputElement>('input.filter-input')` + `.last().focus()` pattern with: pass `autoFocus={i === activeFilters.length - 1 && justAdded}` prop into `FilterCondition.svelte` where the input does `use:autofocus` or on `onMount()` calls `inputEl.focus()` when `autoFocus` is true. Drop the `justAdded` flag after 1 tick.

**A15.** Rename `trimStatusText` → `editStatusText` across the codebase (`lib/stores/segments/edit.ts` + callers in `edit-trim.ts`, `edit-split.ts`, anywhere else). Use `rg -l 'trimStatusText' src` first to get the full list; update all in one pass.

### Acceptance

- `npm run lint && npm run build` green.
- `python3 -c "from inspector.app import create_app; create_app()"` green.
- `rg "lsRestore|_clearAudioBufferCache|waveformCacheSize|animateSeg|isSegAnimRunning|trimStatusText|#f72585" inspector/frontend/src` → 0 hits except `constants.ts::PREVIEW_PLAYHEAD_COLOR`.
- `rg "B01|bug-B01|S2-B01" inspector/` → 0 hits.
- Save preview + undo + trigger-validation path manually exercised (trace through, can't test).

Commit: `refactor(inspector): Ph13a runtime bugs + dead exports + micro-polish`. ONE commit.

---

## Ph13b — LOC target splits (Sonnet)

### B1. `lib/stores/segments/history.ts` (541 LOC) — split into 3 files

- **Keep in `lib/stores/segments/history.ts`** (~130 LOC): writables (`historyVisible`, `historyData`, `historyDataStale`, `historyFilters`, `sortMode`, `editHistory`), actions (`setHistoryData`, `setHistoryVisible`, `setSortMode`, `clearFilters`, `toggleHistoryFilter`), derived `flatItems` store (imports helpers from the new files).
- **Move to `lib/utils/segments/history-chains.ts`** (~130 LOC): `buildSplitLineage`, `buildSplitChains`, `computeChainLeafSnaps`, `getChainBatchIds`, `snapToSeg`, related chain helpers + the `SplitChain` type re-exported from here.
- **Move to `lib/utils/segments/history-items.ts`** (~200 LOC): `flattenBatchesToItems`, `groupRelatedOps`, `buildDisplayItems`, `computeFilteredItemSummary`, verse counters, sort helpers, `OpFlatItem` / `HistorySnapshot` type re-exports.
- Update all importers of `stores/segments/history` for the types and helpers that moved. `rg "from.*stores/segments/history" src` returns the list.

### B2. `tabs/segments/SegmentsTab.svelte` (506 LOC) — extract 2 chunks

- **`lib/utils/segments/keyboard.ts`**: lift the 110-line `handleSegKeydown` switch. Export `handleSegmentsKey(e: KeyboardEvent): boolean` returning `true` if handled (so SegmentsTab can `e.preventDefault()` only then). Uses existing stores + action functions; no new state.
- **`tabs/segments/ShortcutsGuide.svelte`**: extract the Shortcuts & Guide `<details>` block (~45 LOC of template + zero logic). Mirror the existing `tabs/timestamps/TimestampsShortcutsGuide.svelte` structure.
- SegmentsTab becomes a 3-line `on:keydown` wrapper: `if (handleSegmentsKey(e)) e.preventDefault();` and `<ShortcutsGuide />` in the template.
- Verify SegmentsTab ≤ 250 LOC after.

### B3. Optional (ask user first)

- `cache.py` (328 → ≤250): possible extraction of the `_build_segment_index` cluster or surah-info section into `services/cache_surah.py` / `services/cache_segments.py`. Invasive — skip unless user asks.
- `TimestampsTab.svelte` (390 → ≤300): lift keyboard handler to `lib/utils/timestamps/keyboard.ts` mirroring B2. Skip unless user asks.

**SKIP B3 for this phase unless user explicitly requested.**

### Acceptance

- Build + lint + py-smoke green.
- `wc -l src/lib/stores/segments/history.ts` ≤ 150 OR three files each ≤ 280.
- `wc -l src/tabs/segments/SegmentsTab.svelte` ≤ 250.
- `wc -l src/tabs/segments/ShortcutsGuide.svelte` exists.
- `wc -l src/lib/utils/segments/keyboard.ts` exists.
- No behavior change. Manual trace: history flat items still sort correctly; segments keyboard shortcuts still work (↑/↓/Space/Enter/etc. — whatever the current handler covers).

Commit: `refactor(inspector): Ph13b split history.ts + SegmentsTab to hit LOC targets`. ONE commit.

---

## Ph13c — Type hygiene (Sonnet)

### C1. Four bogus `as unknown as` casts — convert to real typing

- `tabs/segments/history/SplitChainRow.svelte:~92, ~96` — casts `HistorySnapshot as unknown as Segment` to call `_classifySnapIssues`. But `_classifySnapIssues` already accepts `SnapForIssues` (or verify its signature). **Fix**: drop both casts; if `SnapForIssues` is broader than `HistorySnapshot`, pass directly. Otherwise change `_classifySnapIssues` param to accept `HistorySnapshot | Segment`.
- `lib/utils/segments/waveform-utils.ts:~130, ~257` — casts exist because `indexSegPeaksBulk` types param as `Partial<SegmentPeaks>` but API returns `SegmentPeaks`. **Fix**: change `indexSegPeaksBulk` signature to `Record<string, SegmentPeaks>` and narrow internally via existing null-check. Delete both casts.
- `tabs/timestamps/TimestampsTab.svelte:~129` — casts `TsValidateResponse as unknown as { error?: string }`. **Fix**: add optional `error?: string` field to `TsValidateResponse` in `lib/types/api.ts`; drop the cast.

### C2. Relocate `SegVal*Item` types

- `lib/types/domain.ts` lines ~258-361 contain ~100 LOC of `SegValFailedItem`, `SegValMissingVerseItem`, `SegValMissingWordsItem`, `SegValBoundaryAdjItem`, `SegValCrossVerseItem`, `SegValAudioBleedingItem`, `SegValRepetitionItem`, `SegValMuqattaatItem`, `SegValQalqalaItem`, `SegValLowConfidenceItem`, `SegValAnyItem` union. These are response-shape types — move to `lib/types/api.ts` next to `SegValidateResponse`.
- Update all importers of these types. `rg "SegVal(Failed|MissingVerse|MissingWords|BoundaryAdj|CrossVerse|AudioBleeding|Repetition|Muqattaat|Qalqala|LowConfidence|AnyItem)Item" src` returns the list.
- Confirm `domain.ts` afterwards: ≤ 280 LOC.

### Acceptance

- Build + lint green. **Strict TS** catches any broken cast chain.
- `rg "as unknown as" inspector/frontend/src` returns ≤ 5 hits, all in: `webaudio-peaks.ts` (webkit AudioContext), `stats-chart-draw.ts` (Chart.js annotation), `dirty.ts` (comment only — exempt).
- `rg "SegVal.*Item" inspector/frontend/src/lib/types/domain.ts` → 0 hits.
- `rg "SegVal.*Item" inspector/frontend/src/lib/types/api.ts` → 11 type definitions + 1 union.

Commit: `refactor(inspector): Ph13c type hygiene — drop bogus casts + relocate SegVal types`. ONE commit.

---

## Ph13d — Design dedupe (Opus, most invasive)

### D1. Extract `finalizeEdit` helper

Current state: every `edit-*.ts` file (trim/split/merge/delete/reference) repeats the same post-mutation scaffolding, roughly:

```ts
op.applied_at_utc = new Date().toISOString();
op.targets_after = [snapshotSeg(seg)];
markDirty(chapter);
finalizeOp(chapter, op);
computeSilenceAfter(chapter);  // sometimes
applyVerseFilterAndRender();
refreshOpenAccordionCards();
clearEdit();
playStatusText.set(msg);
setPendingOp(null);
```

Extract into `lib/utils/segments/edit-common.ts`:

```ts
export function finalizeEdit(
  op: EditOp,
  chapter: number,
  targets: Segment[],
  statusMsg: string,
  opts?: { computeSilence?: boolean }
): void {
  op.applied_at_utc = new Date().toISOString();
  op.targets_after = targets.map(snapshotSeg);
  markDirty(chapter);
  finalizeOp(chapter, op);
  if (opts?.computeSilence !== false) computeSilenceAfter(chapter);
  applyVerseFilterAndRender();
  refreshOpenAccordionCards();
  clearEdit();
  playStatusText.set(statusMsg);
  setPendingOp(null);
}
```

Update all 5 edit files to call it. Each should lose ~10-15 LOC.

**⚠️ Preserve behavior exactly** — if any edit site does the scaffolding in a different order, or skips a step (e.g. `edit-delete.ts` may not need `computeSilenceAfter`), reflect that via `opts` or leave it inline.

### D2. `edit-reference.ts::commitRefEdit` internal dedupe

Lines ~71-99 (no-op ref path where user confirmed without changes) duplicates 80% of the logic in lines ~102-145 (actual change). Extract local helper `_applyRefChange(seg, op, newRefText?)` that encapsulates "set matched_ref (or not), set confidence, push ignored-category when needed, finalize via `finalizeEdit`".

### D3. Shared `drawEditPeakBase` helper

`lib/utils/segments/trim-draw.ts:~18-54` (`_ensureTrimBaseCache`) and `split-draw.ts:~13-62` (`_ensureSplitBaseCache`) draw the same blue peak-fill base from a time range. Extract `drawEditPeakBase(canvas, audioUrl, startMs, endMs): ImageData | null` into `lib/utils/segments/waveform-draw-seg.ts` (or new `edit-draw-shared.ts` if that file is already bloated). Both callers collapse to ~10 LOC each.

### D4. Registered-container Set replaces hardcoded DOM IDs

- Current: `lib/utils/segments/waveform-utils.ts::redrawPeaksWaveforms:~75` hardcodes `['seg-list', 'seg-validation', 'seg-validation-global', 'seg-history-view', 'seg-save-preview']` — a pure util knows 5 components' DOM layout.
- **Fix**: add `export const registeredWaveformContainers = writable<Set<HTMLElement>>(new Set());` in `lib/stores/segments/playback.ts`.
- Each consuming component (`SegmentsList`, `ValidationPanel`, `HistoryPanel`, `SavePreview`) registers via `onMount(() => { registeredWaveformContainers.update(s => { s.add(rootEl); return s; }); return () => { registeredWaveformContainers.update(s => { s.delete(rootEl); return s; }); }; });`
- `redrawPeaksWaveforms` iterates `get(registeredWaveformContainers)` instead of `document.querySelector` by ID.
- Delete the ID array; delete any `id=` attribute that existed only for this loop.

### D5. `isSegmentDirty` / `getChapterOpsSnapshot` — replace `getDirtyMap()` leak

- Current: `lib/stores/segments/dirty.ts::getDirtyMap()` returns the raw `Map<number, {indices: Set<number>, ops: EditOp[]}>`. Consumers: `tabs/segments/validation/GenericIssueCard.svelte:~60`, `MissingWordsCard.svelte:~81, ~116`.
- **Fix**: add `export function isSegmentDirty(chapter: number, index: number): boolean` and `export function getChapterOpsSnapshot(chapter: number): readonly EditOp[]` to `dirty.ts`.
- Update 3 card consumers to use the new API + subscribe to `dirtyTick` so the reactive derivation fires correctly: `$: dirty = ($dirtyTick, isSegmentDirty(ch, idx))`.
- Keep `getDirtyMap()` only if internal callers within `dirty.ts` / `save-execute.ts` still need it; otherwise make it module-private.

### D6. `_vwc()` → `references.ts::getVerseWordCounts()`

`edit-split.ts`, `edit-delete.ts`, `edit-reference.ts` each define an identical 3-line `_vwc()` wrapper accessing the verse-word-counts cache. Move the function to `lib/utils/segments/references.ts` as `getVerseWordCounts()`, import in the 3 callers, delete the local copies.

### D7. `SegmentsTab.svelte::groupedReciters` → use shared util

Lines ~78-96 in SegmentsTab replicate the shape of `lib/utils/grouped-reciters.ts::buildGroupedReciters`. Replace with `$: groupedReciters = buildGroupedReciters($segAllReciters)`. Delete the local version.

### Acceptance

- Build + lint green.
- Each `edit-*.ts` uses `finalizeEdit`; each loses 10-15 LOC.
- `rg "document.querySelector.*seg-" inspector/frontend/src` → 0 hits in `waveform-utils.ts`.
- `rg "getDirtyMap" inspector/frontend/src/tabs` → 0 hits.
- `rg "_vwc" inspector/frontend/src/lib/utils/segments/edit-" → 0 hits (all 3 deleted).
- SegmentsTab `groupedReciters` local definition gone; import `buildGroupedReciters`.
- Manual trace: trim/split/merge/delete/reference all finalize correctly; validation cards still flag dirty segments; waveforms still redraw across panels on chapter change.

Commit: `refactor(inspector): Ph13d cross-cutting dedupe — finalizeEdit + container registry + dirty API`. ONE commit.

---

## Global constraints (all sub-phases)

- Svelte 4 only. Strict TS. No `@ts-ignore`.
- No shim files, no re-export facades, no comment noise ("Wave N", "Stage N", "S2-D*", etc.).
- ONE commit per sub-phase. Do not push. Do not amend prior commits.
- If you discover a finding that is OUT of scope for your sub-phase but urgent, STOP and escalate rather than absorb it.
- Report at end: files modified (count), LOC delta, gate results, commit SHA, any surprises.
