# Stage 2 — Wave 8b Handoff (stats + chart + fullscreen)

**Status**: COMPLETE — Wave 8b scope fully delivered.
**Branch**: `worktree-refactor+inspector-modularize`
**Known-good entry commit**: `970fa29` (B1 fix — Wave 8a.2 review follow-up)
**Known-good exit commit**: `413b2d1` (cycle ceiling tighten)
**Agent**: Claude Sonnet 4.6 (implementation-Wave-8b), 2026-04-14.

---

## 0. At-a-glance

- 5 source commits + this handoff = 6 commits.
- 4 new files (stats.ts store, stats-types.ts, StatsChart.svelte, ChartFullscreen.svelte, StatsPanel.svelte = 5 files), 4 modified, 1 deleted (segments/stats.ts).
- 7/7 pre-flight gates GREEN. svelte-check 0/0. Lint 0 errors / **14 warnings** (cycle count
  unchanged at 14; ceiling decremented 18 → 16).
- Bundle: 135 modules (+3 from prior 132), ~520 kB.
- All Wave 8b scope delivered: segStats store, write-site migration, StatsPanel.svelte,
  StatsChart.svelte, ChartFullscreen.svelte, SegmentsTab integration, segments/stats.ts
  DELETED, cycle ceiling tightened to 16.

---

## 1. Scope delivered

### 1.1 `lib/stores/segments/stats.ts` — new store (commit `cc23618`)

Path: `inspector/frontend/src/lib/stores/segments/stats.ts`

Mirrors the validation store pattern exactly:

```ts
export const segStats = writable<SegStatsResponse | null>(null);
export function setStats(data: SegStatsResponse): void { segStats.set(data); }
export function clearStats(): void { segStats.set(null); }
```

~36 LOC. Single `SegStatsResponse | null` field (provisional per S2-D11).

### 1.2 Write-site migration + B1 DOM-clobber removal (commit `1c745c7`)

**`segments/data.ts`** — 3 write sites:
- Added `clearStats`, `setStats` imports from `lib/stores/segments/stats`.
- Removed `renderStatsPanel` import (was pulling in the entire Chart.js renderer).
- `onSegReciterChange` clear path: `dom.segStatsPanel.hidden = true; dom.segStatsPanel.removeAttribute('open'); state.segStatsData = null;` → `clearStats()`.
- `onSegReciterChange` load path: `state.segStatsData = statsResult.value; renderStatsPanel(...)` → `if (!statsResult.value.error) setStats(statsResult.value)`.
- `clearSegDisplay`: `state.segStatsData = null; if (dom.segStatsPanel) { dom.segStatsPanel.hidden = true; dom.segStatsCharts.innerHTML = ''; }` → `clearStats()`.

**`SegmentsTab.svelte`** — 2 write sites:
- Added `clearStats`, `segStats`, `setStats` imports. Removed `renderStatsPanel` import.
- `onReciterChange` load: same → `if (!statsResult.value.error) setStats(statsResult.value)`.
- `clearPerReciterState`: removed `getElementById('seg-stats-panel')` / `.hidden` / `.innerHTML` clobbers → `clearStats()`.
- Bridge added: `$: state.segStatsData = $segStats;` (keeps imperative consumers working).

### 1.3 Component tree (commit `7ae82a6`)

**`tabs/segments/stats-types.ts`** — shared pure types file.
- `Distribution { bins, counts, percentiles? }`
- `ChartCfg { key, title, refLine?, refLabel?, barColor, formatBin?, showAllLabels? }`

**`tabs/segments/StatsChart.svelte`** — single histogram card.
- Props: `title`, `dist: Distribution`, `cfg: ChartCfg`, `reciter`, `onOpenFullscreen?`.
- `bind:this={canvasEl}` on canvas; `onMount` + `$: if (canvasEl && dist)` triggers `buildChart()`.
- `buildChart()` calls `drawBarChart()` with full destroy+rebuild (matches Stage-1 pattern).
- `onDestroy` destroys Chart instance.
- Chart ref held as `let chartInstance: Chart | null` (not augmenting HTMLCanvasElement).
- Save-PNG button calls `/api/seg/stats/:reciter/save-chart` via `fetchJson`.
- Fullscreen button calls `onOpenFullscreen(dist, cfg)` callback if provided.

**`tabs/segments/ChartFullscreen.svelte`** — fullscreen overlay.
- Props: `dist: Distribution | null`, `cfg: ChartCfg | null`, `reciter`, `onClose`.
- `dist == null` → overlay not rendered (conditional `{#if dist && cfg}`).
- `<svelte:window on:keydown>` — Escape key calls `onClose`.
- Backdrop click (`e.target === e.currentTarget`) calls `onClose`.
- Separate Chart.js instance per overlay open. `requestAnimationFrame` deferred rebuild
  (gives canvas layout time to stabilize).
- Chart destroyed in `$: if (!dist || !cfg)` reactive block + `onDestroy`.
- Scoped `<style>` for `.seg-stats-fullscreen` / `.seg-stats-fs-inner` / `.seg-stats-fs-bar`.

**`tabs/segments/StatsPanel.svelte`** — shell component.
- Subscribes `$segStats`. Renders nothing when null.
- `$: data = $segStats` — reactive re-render on store change.
- `$: reciter = $selectedReciter` — passed to StatsChart + ChartFullscreen for save-chart.
- `buildCharts(vad)` pure function returns 5 `ChartCfg[]` (same keys/colors as Stage-1).
- `<details class="seg-stats-panel">` element with `{#each charts as cfg (cfg.key)}` keyed loop.
- `{@const dist = ...}` inside `{#if}` block for type narrowing (avoids `undefined` prop error).
- Fullscreen state: `let fullscreenDist / fullscreenCfg` component-local. `openFullscreen` /
  `closeFullscreen` callbacks passed to StatsChart + ChartFullscreen.
- `<ChartFullscreen>` mounted unconditionally (renders null when `dist === null`).

### 1.4 SegmentsTab integration (commit `0a27fd1`)

- Added `import StatsPanel from './StatsPanel.svelte'`.
- Replaced `<details id="seg-stats-panel" class="seg-stats-panel" hidden>` with `<StatsPanel />`.
- IDs `seg-stats-panel` / `seg-stats-charts` removed (no imperative consumers remain).

### 1.5 Dead code deletion (commit `0a27fd1`)

**Deleted: `inspector/frontend/src/segments/stats.ts`** (~216 LOC)
- `renderStatsPanel` — imperative DOM builder, all callers migrated.
- `_openChartFullscreen` — replaced by ChartFullscreen.svelte.
- `_saveChart` — replicated in StatsChart.svelte + ChartFullscreen.svelte.
- `_findBinIndex` — replicated inline in each component (pure utility, <10 LOC).
- `drawBarChart` — replicated as component-local function in each component.
- All imports: `Chart`, `fetchJson`, `dom`, `state`.

Also removed from `segments/index.ts`:
- `import './stats'` side-effect import (no longer needed).
- `dom.segStatsPanel = mustGet(...)` and `dom.segStatsCharts = mustGet(...)` calls.

Also removed from `segments/state.ts` DomRefs:
- `segStatsPanel: HTMLDivElement`
- `segStatsCharts: HTMLDivElement`
- Corresponding `dom` object slots.

### 1.6 Cycle ceiling decrement (commit `413b2d1`)

`stage2-checks.sh` `CYCLE_CEILING` decremented from `18` to `16`.

Actual cycle count: **14** (unchanged — no new cycles introduced or dissolved this wave).
14 actual + 2 defensive buffer = ceiling 16, per Opus recommendation from Wave 8a.

---

## 2. Scope deferred

### 2.1 `drawBarChart` duplication in StatsChart + ChartFullscreen

Both components contain a local `drawBarChart` function that is ~95% identical. This is
intentional — the alternative was a shared utility file that both import, but given the
Chart.js lifecycle is tightly coupled to the component, having it inline avoids complexity.
Future cleanup (Wave 11) can extract to `lib/utils/stats-chart-draw.ts` if desired.

### 2.2 ReferenceEditor autocomplete — unchanged from Wave 7b (Wave 11)

### 2.3 All Wave 7b / 8a.2 deferred items — unchanged

---

## 3. Key decisions / lessons

### 3.1 Chart lifecycle: full destroy+rebuild, not `chart.update()`

Stage-1 always destroyed and rebuilt (the `canvas._chartInstance.destroy()` pattern).
StatsChart mirrors this: `buildChart()` → `if (chartInstance) { chartInstance.destroy(); }` →
`new Chart(canvas, config)`. This is correct because the data shape changes entirely between
reciters (different bins, counts, vad_params). `chart.update()` is only appropriate when
updating to a different view of the same dataset.

### 3.2 `requestAnimationFrame` deferred rebuild in ChartFullscreen

The overlay canvas doesn't have layout dimensions until after the DOM renders. Wrapping the
`new Chart(...)` call in `requestAnimationFrame` in `rebuildChart()` ensures the canvas has
its computed width/height before Chart.js reads them for responsive sizing.

### 3.3 `{@const dist = ...}` for type narrowing inside `{#each}`

Svelte templates don't carry TypeScript narrowing from `{#if dist != null}` into the
child `dist={dist}` prop. Using `{@const dist = data.distributions?.[cfg.key]}` before the
`{#if dist != null}` block makes the narrowed type (`Distribution`, not `Distribution | undefined`)
visible in the template's inner scope.

### 3.4 Error-guard at `setStats()` call site, not in StatsPanel

If `statsResult.value.error` is truthy, we don't call `setStats()`. The component thus never
sees error data — it renders nothing when `$segStats` is null. This is cleaner than checking
inside StatsPanel (avoids error-branch rendering code in the component).

### 3.5 Stats `<details>` open state — component-local (intentional change from Stage-1)

Stage-1 imperative code preserved `<details>` open state across reciter changes by keeping it
in the DOM (`hidden` toggled, not removed). The Svelte component unmounts entirely when
`$segStats === null` (reciter change), so the open state resets. This is **intentional** — the
stats panel is reciter-specific, so resetting on reciter change is correct behavior. Document
as acceptable difference from Stage-1.

---

## 4. Verification results

### 4.1 Pre-flight gates (final run, commit `413b2d1`)

| Gate | Result | Detail |
|------|--------|--------|
| [1/7] tsc typecheck | PASS | 0 errors |
| [2/7] eslint | PASS | 0 errors, **14 warnings** (unchanged) |
| [3/7] vite build | PASS | 135 modules (+3), 520 kB |
| [4/7] no-global-keyword | PASS | Backend unchanged |
| [5/7] no-orphan-cache-vars | PASS | Backend unchanged |
| [6/7] no-cycle-NOTEs | PASS | Zero |
| [7/7] cycle-ceiling | PASS | 14/16 |
| `npx svelte-check` | PASS | 0 errors, 0 warnings |

---

## 5. Manual QA smoke items

The following items should be tested manually after next deploy:

1. **Stats panel renders after reciter load**: Select a reciter → stats panel appears with
   5 histogram charts. Verify colors match: pause (grey/blue threshold), confidence (red/orange/green).
2. **Fullscreen toggle**: Click ⛶ on any chart → fullscreen overlay opens. Press Escape or click
   backdrop → closes. Click × button → closes.
3. **Save PNG**: Click ↳ on any chart or in fullscreen → "Saved" tooltip appears briefly.
4. **Reciter change resets stats**: Switch to another reciter → stats panel disappears then
   re-appears with new data.
5. **Stats panel after save + re-hydrate**: Make a dirty edit → save → confirm. Verify stats
   panel still shows (the reciter doesn't change on save; store is untouched by save flow).
   This is the parallel of the ValidationPanel B1 regression test from Wave 8a Opus review.
6. **Empty stats response**: If a reciter returns `{error: "..."}` from `/api/seg/stats`,
   the stats panel should remain hidden (store not set with error data).

---

## 6. Commits (exit-point detail)

```
cc23618 feat(inspector): lib/stores/segments/stats.ts — promote state.segStatsData to writable
1c745c7 refactor(inspector): segments/data.ts + SegmentsTab use setStats/clearStats; remove dom.segStatsPanel clobbers (B1 parallel)
7ae82a6 feat(inspector): StatsChart.svelte + ChartFullscreen.svelte + StatsPanel.svelte (Wave 8b)
0a27fd1 refactor(inspector): mount StatsPanel in SegmentsTab; delete segments/stats.ts; remove dead dom.segStatsPanel refs
413b2d1 chore(inspector): tighten import/no-cycle ceiling 18 → 16 (14 actual + 2 buffer, Wave 8b)
```

5 source commits + this handoff = 6 commits.

---

## 7. Wave 9 prerequisites

Wave 9 owns: save preview + undo panels.

Prerequisites Wave 9 must respect:

1. **All Wave 8a.1 + 8a.2 prerequisites still apply** (store patterns, bridge-lag, {#each} keys).
2. **Stats panel open-state resets on reciter change** — this is intentional (§3.5). Wave 9
   should document it in CLAUDE.md if user needs a different behavior.
3. **Cycle ceiling at 16**. Wave 9 should target further reduction if segments cycles dissolve.
4. **`_rebuildAccordionAfterSplit/Merge`** — NB from Wave 8a still deferred to Wave 11.
5. **`segStatsData` in `state.ts`**: The field is still present in `SegmentsState` interface and
   gets synced via `$: state.segStatsData = $segStats`. This bridge is safe to keep until
   Wave 11 removes the state object entirely.
6. **Manual-QA smoke item (Opus rec from Wave 8a)**: After save + undo, confirm ValidationPanel
   re-populates correctly (B1 regression test). Also test that StatsPanel still shows after save
   (item 5 in §5 above).

---

## 8. Open questions for Wave 9

- [ ] Should `segStatsData` be removed from `SegmentsState` now that the store is source of
      truth? Currently kept for any imperative consumer that might read it. Grep confirms no
      current imperative reads of `state.segStatsData` outside the bridge and SegmentsTab.
      Could be cleaned up in Wave 9 without risk.
- [ ] Save panel + undo panel have similar imperative DOM patterns to stats. Wave 9 should
      follow the same store-promotion + B1-audit approach.

---

## 9. Stats store usage in save/undo flow

The stats store is NOT invalidated by save/undo operations currently. Stage-1 didn't
invalidate either — `renderStatsPanel` was only called on reciter load. This is acceptable:
stats reflect the pre-save distribution; refreshing would require another `/api/seg/stats`
call. Wave 9 can decide whether to add a `refreshStats()` call after save succeeds (similar
to `refreshValidation()`).

---

## 10. File delta

New files:
- `inspector/frontend/src/lib/stores/segments/stats.ts` (36 LOC)
- `inspector/frontend/src/tabs/segments/stats-types.ts` (24 LOC)
- `inspector/frontend/src/tabs/segments/StatsChart.svelte` (~200 LOC)
- `inspector/frontend/src/tabs/segments/ChartFullscreen.svelte` (~200 LOC)
- `inspector/frontend/src/tabs/segments/StatsPanel.svelte` (~80 LOC)

Modified:
- `inspector/frontend/src/segments/data.ts` (import swaps, call site replacements)
- `inspector/frontend/src/segments/index.ts` (removed './stats' + 2 mustGet lines)
- `inspector/frontend/src/segments/state.ts` (removed 2 DomRefs fields + slots)
- `inspector/frontend/src/tabs/segments/SegmentsTab.svelte` (import swap, StatsPanel mount, clearStats bridge)

Deleted:
- `inspector/frontend/src/segments/stats.ts` (216 LOC — fully absorbed)

---

## 11. Token / tool-call self-report

- Orientation reads: 8 files (handoff docs, source files, store pattern).
- 1 advisor call (before first component commit — Chart.js lifecycle guidance).
- ~25 tool calls total (reads + edits + bash runs).
- No dev server started. No new circular dependencies introduced.

---

**END WAVE 8b HANDOFF.**
