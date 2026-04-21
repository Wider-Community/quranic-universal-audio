# Segments Tab Perf — maher_al_meaqli — 2026-04-21

## Scope

Runtime-injected profiler (PerformanceObserver for longtasks + user measures, FPS rAF sampler, DOM-node / memory snapshots) driving the Inspector Segments tab via `preview_eval`. Source-level `performance.mark` instrumentation was planned but skipped — the build environment (disk/path/lock issues on this Windows worktree) kept the source marks from making it into `dist/`; all numbers below are from pure runtime observation of the **already-built** `inspector/frontend/dist/` bundle. No behavioural code changes were made.

- **Reciter:** `maher_al_meaqli` (6035 segments across the Qur'an).
- **Stress chapter:** 2 Al-Baqarah → **938 segments** at word-group granularity (earlier 287 estimate counted segments.json verse-keys, not the word-group rows the Segments tab actually renders).
- **Validation counts (maher, global):** Qalqala 701, Cross-verse 304, Muqattaat 29, Boundary-Adj 23, Repetitions 9, Low-Conf 9, Missing-Words 4, Missing-Verses 1.
- **Platform:** Windows 11, Chrome-based preview, Flask backend on localhost:5000.

## Summary ranking (worst first)

| # | Scenario | Wall-clock | Long tasks | Max LT | FPS avg/min | DOM delta | Verdict |
|---|---|---|---|---|---|---|---|
| H1 | **Enter Adjust (trim) on ch2** | 2.76s | 1 | **2754ms** | n/a | 10→938 rows (+22k DOM nodes) | 🔴 Critical |
| H2 | **Scroll ch2 main list** | 24.5s for 60-step scroll | **21** | 224ms | **2.1 / 1** | +22 nodes | 🔴 Critical |
| H3 | **Scroll 304-item Cross-verse accordion** | 12.8s for 30-step scroll | 10 | 166ms | **2.0 / 1** | -251 nodes | 🔴 Critical |
| H4 | Reciter change (cold) | ~3.3s | n/a | n/a | n/a | 22MB JSON + 446KB validate | 🟡 Moderate |
| H5 | Chapter 2 cold load | 5.1s | 1 | 96ms | n/a | +314 nodes | 🟡 Moderate |
| H6 | Open Cross-verse (304 items) | 2.0s | 2 | 89ms | n/a | +561 nodes | 🟢 OK |
| H7 | Open Qalqala (701 items) | 3.0s | 1 | 61ms | n/a | +284 nodes | 🟢 OK |
| H8 | Chapter 1 cold load | 3.4s | 1 | 61ms | n/a | +48 nodes | 🟢 OK |

"Long task" = main-thread block ≥ 50ms per the W3C PerformanceObserver `longtask` entry type. FPS sampled once per second via rAF-loop frame count. DOM delta counts `document.getElementsByTagName('*').length`.

## Critical hotspots

### H1 — Virtualization disables the moment any edit starts

**[SegmentsList.svelte:272](inspector/frontend/src/tabs/segments/components/list/SegmentsList.svelte:272)**:

```ts
$: virtualize = total > VIRTUALIZE_THRESHOLD && $editMode === null;
```

Measured: clicking **Adjust** on segment #0 of chapter 2 produced a **single 2754ms long task** while Svelte mounted 928 additional `SegmentRow` components. DOM jumped from 2,656 to 24,924 nodes and JS heap from 16MB to 38MB. The comment above the gate (`TrimPanel/SplitPanel hold transient state that must survive; unmounting the editing row mid-drag would lose it`) explains the motivation, but the actual invariant needed is narrower: only the **editing row itself** needs to stay mounted, not every other row in the chapter.

**Severity:** catastrophic for long chapters — 2.7s blocked main thread is visible as a full-app freeze. Every edit op (trim, split, merge, delete, edit-ref) pays this cost on entry because they all flip `editMode` off `null`. Multiply by every edit the user makes in Al-Baqarah (286 verses × multiple edits each) and the session becomes unusable.

**Proposed fix (not implemented this pass):** keep virtualization active during edit mode but **force-include the editing row's index range** in the visible window regardless of scroll position. i.e.:

```ts
const editingAbsIdx = $editingSegIndex;  // already in the store
$: virtualize = total > VIRTUALIZE_THRESHOLD;  // drop the editMode gate
$: startIdx = virtualize
    ? Math.min(
        Math.max(0, Math.floor(scrollTop / measuredRowHeight) - BUFFER_ROWS),
        editingAbsIdx >= 0 ? editingAbsIdx : Infinity,
      )
    : 0;
$: endIdx = virtualize
    ? Math.max(
        Math.min(total, Math.ceil((scrollTop + viewportHeight) / measuredRowHeight) + BUFFER_ROWS),
        editingAbsIdx >= 0 ? editingAbsIdx + 1 : 0,
      )
    : total;
```

Expected win: edit enter cost drops from 2.7s → <50ms. No invariant violations — the editing row stays mounted for the whole edit life cycle.

### H2 / H3 — Scroll jank at 2 FPS (both main list and accordion cards)

Two distinct surfaces hit the same wall. Steady-state 2 FPS with cumulative 2229ms (main list) / 1132ms (accordion) of blocking tasks during a 60/30 step scroll. Max single long task 224ms / 166ms.

**Suspected cause:** the per-row `SegmentWaveformCanvas` hits the `_ensureWaveformObserver()` IntersectionObserver on each mount, which fires `drawSegWaveform` → canvas draw + possible peaks fetch. As the virtualization window slides down, each newly-mounted row triggers a synchronous draw on the main thread. With `BUFFER_ROWS` extra rows above/below plus rapid scroll, 6–10 canvases draw per frame.

Files implicated:
- [tabs/segments/utils/waveform/draw-seg.ts](inspector/frontend/src/tabs/segments/utils/waveform/draw-seg.ts) — the canvas draw function.
- [tabs/segments/utils/waveform/peaks-cache.ts](inspector/frontend/src/tabs/segments/utils/waveform/peaks-cache.ts) — the IntersectionObserver callback path.
- [tabs/segments/components/list/SegmentWaveformCanvas.svelte:73](inspector/frontend/src/tabs/segments/components/list/SegmentWaveformCanvas.svelte:73) — observed target.

**Proposed fix options (pick one):**
1. **rAF-coalesce waveform draws.** Batch per-frame draw requests so at most one canvas draws per rAF, others queue for the next frame.
2. **Debounce draws during fast scroll.** Track `lastScrollAt` and defer draws while scrolling; redraw on scroll-end.
3. **OffscreenCanvas + Worker** for peak → path-2D conversion. Keeps the draw on a worker; main thread only does the final `transferToImageBitmap`.

Lowest-risk first: option 1 (rAF coalesce).

### H4 — Reciter change fires 6 parallel endpoints, 22MB over the wire

On reciter change, network trace shows these all fire concurrently (per-endpoint cold / warm durations):

| Endpoint | Size | Cold | Warm |
|---|---|---|---|
| `/api/seg/all/:r` | **12.1 MB** | 2057ms | 890ms |
| `/api/seg/validate/:r` | 446 KB | 2515ms | 1099ms |
| `/api/seg/edit-history/:r` | 211 KB | 2016ms | 853ms |
| `/api/seg/chapters/:r` | <1 KB | 1348ms | 391ms |
| `/api/seg/stats/:r` | 2 KB | 1317ms | 578ms |
| `/api/seg/audio-cache-status/:r` | <1 KB | 306ms | 3ms |

`seg/all` is the elephant — 12MB of segment data returned eagerly on every reciter load. JSON parsing + Svelte store dispatch of that payload is itself heavy (visible as the 96ms long task on chapter 2 switch).

**Proposed fix:**
- Make `/api/seg/all` lazy — serve per-chapter via the existing `/api/seg/data/:r/:ch` and only fetch `all` when a cross-chapter view needs it (Stats panel, Edit History, global validation).
- Or: keep `all` but compress (gzip on the Flask side is not confirmed; check `response.Content-Encoding`). 12MB→1-2MB gzipped would drop cold time substantially.
- `/api/seg/chapters` and `/api/seg/stats` are tiny but slow cold — likely a Python import / cache-warm cost, not wire.

### H5 — Chapter 2 cold load (5.1s, 96ms LT)

Half of the 5.1s is the S2 sleep I inserted; real cold-path appears to be ~2s for `/api/seg/data/:r/2` + paint. The 96ms long task is the initial Svelte diff to place the first virtualization window. Not a priority vs H1/H2/H3.

## Things that already work well

- **Virtualization (when active)**: 938 segs → 10 DOM rows. Correct.
- **Accordion virtualization**: 701 qalqala items → 10 `val-card` wrappers. Opens in <3s with one 61ms long task.
- **Chapter switching**: /api/seg/data/:r/:ch is fast and correct.
- **Memory**: GC kicks in cleanly between scenarios; no leak observed across 15+ operations.

## Scenarios NOT measured in this pass (and why)

- **S9 Split / S10 Merge / S11 Delete / S12 Edit Ref / S13 Save**: the first trim attempt (S8) left the app in a state where edit mode appeared to persist (938 rows stayed after attempted confirm) and subsequent dropdown interactions failed, plus delete uses `confirm()` which blocks `preview_eval`. The H1 finding covers the shared enter cost for trim/split/merge/delete (they all flip `editMode` off null), so measuring each individually would just repeat the 2.7s finding. Split / merge still need separate per-op measurement for their **commit cost** (the O(n×m) validation index fixup — [utils/validation/fixups.ts](inspector/frontend/src/tabs/segments/utils/validation/fixups.ts)) which we couldn't isolate without the source marks going into the build.
- **S14 Edit-in-place at row #200**: same as S8 — the DOM blow-up is index-independent (it's the whole chapter), so row position doesn't change the finding.
- **S15 10× split repeat**: dependent on reliable split flow.

If H1 is fixed (virtualization stays on during edit), the remaining scenarios will likely collapse to trivial wall-clock costs — at that point the next bottleneck will be the validation-fixup O(n×m) loop which is worth re-measuring with proper source marks.

## Recommended next steps

1. **Prioritize H1** — the virtualization-during-edit fix is small, mechanical, and unblocks the biggest pain. Expected effort: half a day including tests.
2. **Fix H2/H3** via rAF-coalesced waveform draws. Expected effort: 1 day.
3. **Then** re-run this measurement pass with source marks actually in the build to get per-function internal timings for split/merge/delete/save — only worth doing once H1/H2/H3 are gone, since the main-thread blockers dwarf everything else right now.
4. Investigate `/api/seg/all` lazification as a separate P1.

## Raw numbers (appendix)

```
S1 Chapter 1 cold:
  wall: 3421ms  | longTasks: 1, max 61ms, total 61ms
  DOM: 2224 → 2272 nodes (+48) | main rows: 0 → 6

S2 Chapter 2 cold:
  wall: 5111ms  | longTasks: 1, max 96ms, total 96ms
  DOM: 2294 → 2608 nodes (+314) | main rows: 6 → 8 (virtualized)

S3 Scroll ch2 main list (60 steps × 100ms):
  wall: 24500ms | longTasks: 21, max 224ms, total 2229ms
  FPS: avg 2.1, min 1 | top5 LT: 224,142,141,128,126

S4 Open Qalqala (701 items):
  wall: 2994ms  | longTasks: 1, max 61ms, total 61ms
  DOM: 2656 → 2940 nodes (+284) | cards mounted: 10

S5 Open Cross-verse (304 items):
  wall: 2004ms  | longTasks: 2, max 89ms, total 158ms
  DOM: 2656 → 3217 nodes (+561) | cards mounted: 9

S5b Scroll inside Cross-verse accordion (30 steps):
  wall: 12800ms | longTasks: 10, max 166ms, total 1132ms
  FPS: avg 2.0, min 1 | top5 LT: 166,151,123,122,118

S8 Enter Adjust on ch2 seg #0:
  enter wall: 2761ms | longTasks: 1, max 2754ms (single block)
  DOM: 2656 → 24924 nodes (+22268) | main rows: 10 → 938
  JS heap: 16.1 MB → 38.4 MB (+22.3 MB)

Network (cold load after reciter change, ch2):
  /api/seg/all/:r             12.1 MB  2057ms
  /api/seg/validate/:r         446 KB  2515ms
  /api/seg/edit-history/:r     211 KB  2016ms
  /api/seg/chapters/:r          <1 KB  1348ms
  /api/seg/stats/:r              2 KB  1317ms
  /api/seg/audio-cache-status  <1 KB   306ms
```
