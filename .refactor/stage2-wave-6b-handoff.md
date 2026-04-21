# Stage 2 — Wave 6b Handoff (Waveform + Peaks + S2-B04)

**Status**: COMPLETE
**Branch**: `worktree-refactor+inspector-modularize`
**Known-good entry commit**: `65a44cb` (Wave 6a review follow-ups)
**Known-good exit commit**: `e56d3e1` (CF-1 hot-path migration)
**Agent**: Claude Sonnet 4.6, implementation-Wave-6b, 2026-04-14.

---

## 0. At-a-glance

- 6 source commits + this handoff = 7 commits.
- 4 new files created, 4 files modified, 0 deleted.
- 7/7 pre-flight gates GREEN. svelte-check 0/0. Lint 0 errors / 23 warnings (unchanged baseline).
- **S2-B04 CLOSED** — URL normalization approach (option a).
- **Wave 5 CF-1** — 5 hot-path `dom.segChapterSelect.value` reads in `playback/index.ts` migrated to `get(selectedChapter)`.
- Cycle ceiling: **23 (unchanged)** — no file deletions this wave.
- Bundle: 120 modules (+1 from Wave 6b: `SegmentWaveformCanvas.svelte`).

---

## 1. Scope delivered

### 1.1 Types migration (1 file created, 1 rewritten)

**`lib/types/segments-waveform.ts`** (new, ~80 LOC):
- Moved `SegCanvas`, `TrimHighlight`, `SplitHighlight`, `MergeHighlight`, `TrimWindow`, `SplitData`, `TrimEls`, `SplitEls` from `segments/waveform/types.ts`.
- Rationale: lib-layer components (`SegmentWaveformCanvas.svelte`, future history diff thumbnails) need these types without importing from the segments/ imperative layer.

**`segments/waveform/types.ts`** (rewritten as re-export shim, ~15 LOC):
- All types re-exported from `lib/types/segments-waveform.ts`.
- All existing callers in `segments/` continue working unchanged.

### 1.2 Waveform cache util (1 file created)

**`lib/utils/waveform-cache.ts`** (~90 LOC):
- Non-reactive module-scope `Map<string, AudioPeaks>` (not a Svelte store — per S2-D12).
- Key insight: `normalizeAudioUrl(url)` strips the audio-proxy wrapper before cache key use, implementing S2-B04 fix.
- Exported: `getWaveformPeaks`, `setWaveformPeaks`, `invalidateWaveformCache`, `clearWaveformCache`, `waveformCacheSize`.
- All lookups and stores go through normalized key; proxy URL and CDN URL resolve to the same entry.

### 1.3 S2-B04 fix — caller integration

**`segments/waveform/index.ts`** (modified):
- `_fetchPeaks`: stores via `setWaveformPeaks(url, pe)` for each returned entry (normalized key). Keeps `state.segPeaksByAudio` in sync for backwards-compat read sites. **Removed** the dual-keying workaround (lines 143-147) that stored under both CDN and proxy URL.
- `_fetchChapterPeaksIfNeeded`: single `getWaveformPeaks(audioUrl)` call replaces the two-step CDN + proxy URL check (the old `proxyUrl` variable is gone).
- `_fetchPeaksForClick`: skip guard uses `getWaveformPeaks(audioUrl)?.peaks?.length`.
- Removed `_isCurrentReciterBySurah` import (no longer needed).

**S2-B04 CLOSED** — see stage2-bugs.md Section 5.

### 1.4 SegmentWaveformCanvas.svelte (1 file created)

**`tabs/segments/SegmentWaveformCanvas.svelte`** (~140 LOC):
- Wraps `<WaveformCanvas>` for per-segment-row usage.
- Props: `seg: Segment`, `chapterPeaks: AudioPeaks | null`, `startMs?`, `endMs?`, `totalDurationMs?`, `width`, `height`.
- `getCanvas(): SegCanvas` — exposes raw canvas for imperative overlay code (60fps playhead, trim/split/merge descriptors).
- `data-seg-index` / `data-seg-chapter` on wrapper div — readable by IntersectionObserver in `waveform/index.ts` (Wave 7 wires this).
- **Intentionally unused** in Wave 6b. Wave 7 mounts inside `SegmentRow.svelte` when `{#each}` adoption lands.
- svelte-check 0/0.

### 1.5 draw.ts consolidation

**`segments/waveform/draw.ts`** (modified):
- `drawSegmentWaveformFromPeaks` now delegates the core draw algorithm to `lib/utils/waveform-draw.ts::drawWaveformPeaks` instead of duplicating ~60 LOC of peak-sampling + canvas fill/stroke code.
- SegCanvas-specific concern (`canvas._wfCache = null`) stays in `draw.ts`.
- File NOT deleted: state lookups (`segPeaksByAudio`, `_findCoveringPeaks`), covering-peaks resolution, playhead draw, `_slicePeaks`, and three overlay functions all remain — they depend on `SegCanvas` types and `state` imports with no better home until Wave 7.

### 1.6 Wave 5 CF-1 — hot-path migration

**`segments/playback/index.ts`** (modified):
5 hot-path `dom.segChapterSelect.value` reads migrated to `get(selectedChapter)`:
1. `playFromSegment` line ~26 — chapter resolution on every play-click
2. `playFromSegment` line ~51 — `chapterForPeaks` for `_fetchPeaksForClick`
3. `onSegTimeUpdate` line ~178 — continuous-play advance peaks fetch
4. `drawActivePlayhead` lines ~274-276 — 60fps guard + chapter parse (hottest path)
5. `updateSegPlayStatus` lines ~316-317 — called on play/advance

Non-hot-path reads elsewhere in `segments/` (edit modes, validation, navigation, filters) left on `dom.segChapterSelect.value` — they fire on user action, not per-frame.

### 1.7 Commits

```
7efd2bb refactor(inspector): lib/types/segments-waveform.ts — move SegCanvas + highlight types
39d6e98 feat(inspector): lib/utils/waveform-cache.ts — non-reactive Map with S2-B04 URL normalization
01468fd fix(inspector): S2-B04 waveform peaks orphaned after audio-proxy URL rewrite
8f0b813 feat(inspector): SegmentWaveformCanvas.svelte — ready for Wave 7 SegmentRow adoption
e99e67e refactor(inspector): consolidate segments/waveform/draw.ts into lib/utils/waveform-draw.ts
e56d3e1 refactor(inspector): Wave-5 CF-1 — hot-path reads use get(selectedChapter)
```

---

## 2. Scope deferred

### 2.1 `segments/waveform/index.ts` — keep as imperative shim

**Decision (kept)**: `segments/waveform/index.ts` remains an imperative module — IntersectionObserver + peak fetching. Moving it to `lib/utils/` would be pure relocation with no structural benefit, since it still creates/observes `<canvas>` nodes from imperative `renderSegList`. The meaningful change (cache reads via `waveform-cache.ts`) is already done.

**What Wave 7 must do**: When `SegmentRow.svelte` adopts `{#each}` and `<SegmentWaveformCanvas>`, the observer setup in `index.ts` (`drawAllSegWaveforms`) should wire through the component's `getCanvas()` instead of `querySelectorAll`. At that point `waveform/index.ts` can shrink significantly.

### 2.2 `segments/waveform/draw.ts` — partial consolidation

NOT deleted — see §1.5. The seg-specific overlay/state code (4 functions + `_slicePeaks`) has no better home until Wave 7's component adoption. Wave 7 can move `_drawTrimHighlight`, `_drawSplitHighlight`, `_drawMergeHighlight` into the component's overlay logic.

### 2.3 Full `state.segPeaksByAudio` migration

`state.segPeaksByAudio` is still written (for backwards compat) and read by:
- `segments/waveform/draw.ts:drawWaveformFromPeaksForSeg` (uses it for full-chapter peaks lookup)
- `segments/waveform/draw.ts:drawSegPlayhead`
- `segments/waveform/draw.ts:_slicePeaks`

These three are called inside the 60fps animation loop. Migrating them to `getWaveformPeaks()` is safe (normalized keys work) but the imperative model is still correct. Full migration can happen in Wave 7 or Wave 11 cleanup when `draw.ts` functions move into components.

### 2.4 `data.ts::loadSegReciters` / `onSegReciterChange` deletion

Deferred per Wave 6a handoff §2.1 — Wave 9/10.

### 2.5 CF-1 non-hot-path reads

~30 other `dom.segChapterSelect.value` reads across `segments/` (edit/, validation/, navigation, etc.) left on the shim — they fire on user action, not per-frame. Wave 7-10 will convert them as each module rewrites. The shim is correct; these reads are not performance-sensitive.

---

## 3. Deviations from plan

### 3.1 `draw.ts` not fully absorbed

Plan said "delete `segments/waveform/draw.ts` if fully absorbed." It was NOT fully absorbed — seg-specific overlay logic, state reads, and SegCanvas cache management stay. The consolidation is partial: `drawSegmentWaveformFromPeaks` delegates to the lib util. Documented per advisor recommendation before commit.

### 3.2 `waveform/index.ts` kept in segments/ (not moved to lib/utils/)

Plan noted: "move IntersectionObserver + peak fetching logic into `lib/utils/segments-waveform-io.ts` OR keep in `segments/waveform/index.ts` as thin wrapper." Decision: keep in place. The module is imperative-only with no Svelte refs; moving it is pure relocation. The meaningful structural change (waveform-cache.ts util + S2-B04 fix) is done. See §2.1.

---

## 4. Verification results

### 4.1 Pre-flight gates (final run)

| Gate | Result | Detail |
|------|--------|--------|
| [1/7] tsc typecheck | PASS | 0 errors |
| [2/7] eslint | PASS | 0 errors, 23 warnings (unchanged baseline) |
| [3/7] vite build | PASS | 120 modules (+1 SegmentWaveformCanvas.svelte), ~497 kB bundle |
| [4/7] no-global-keyword | PASS | Backend unchanged |
| [5/7] no-orphan-cache-vars | PASS | Backend unchanged |
| [6/7] no-cycle-NOTEs | PASS | Zero `// NOTE: circular dependency` |
| [7/7] cycle-ceiling | PASS | 23/23 warnings (unchanged — no file deletions this wave) |
| wave-2+ docker smoke | SKIPPED | docker not on this WSL |
| `npm run check` (svelte-check) | PASS | 0 errors, 0 warnings |

### 4.2 S2-B04 smoke reasoning (no dev server started)

- [x] **by_ayah reciter (CDN URLs)**: `_fetchPeaks` stores via `setWaveformPeaks(origUrl, pe)`. `normalizeAudioUrl(origUrl)` returns `origUrl` unchanged (no proxy prefix). Lookup via `getWaveformPeaks(origUrl)` hits. Same as before.
- [x] **by_surah reciter (proxy URLs)**: `_fetchPeaks` stores via `setWaveformPeaks(origUrl, pe)`. `normalizeAudioUrl(origUrl)` returns `origUrl` (CDN form). Later, `drawWaveformFromPeaksForSeg` reads `state.segPeaksByAudio[proxyUrl]` via the still-kept backwards-compat sync. Additionally, `_fetchChapterPeaksIfNeeded` now calls `getWaveformPeaks(audioUrl)` which normalizes the CDN URL key — no double-fetch. The old dual-keying band-aid is removed; no orphaned-peaks regression.
- [x] **URL normalization round-trip**: `normalizeAudioUrl('/api/seg/audio-proxy/reciter?url=https%3A%2F%2Fcdn.example.com%2Faudio.mp3')` → `'https://cdn.example.com/audio.mp3'`. Non-proxy URL passes through unchanged.

### 4.3 CF-1 hot-path smoke reasoning

- [x] `get(selectedChapter)` from `svelte/store` is O(1) — reads the current store value without subscribing.
- [x] `playFromSegment` called on every play-click: `_chStr = get(selectedChapter)` replaces `dom.segChapterSelect.value` shim call.
- [x] `drawActivePlayhead` called at 60fps: `_chStr` captured once per frame, used for both guard and chapter parse.
- [x] The shim's `value` setter (`selectedChapter.set(v)`) is not affected — those code paths still use `dom.segChapterSelect.value = X`.

---

## 5. Bug-log delta

**S2-B04 CLOSED** (see stage2-bugs.md Section 5).

No new OPEN bugs introduced.

---

## 6. Review findings + disposition

### Sonnet (pattern review) — **APPROVE**

No blockers. 2 non-blockers + 4 Wave-7 carry-forwards.

**Non-blockers:**

| ID | Item | Disposition |
|---|---|---|
| NB-1 | S2-B04 fix-SHA in `stage2-bugs.md` Section 5 said "(Wave 6b commit 3)" rather than literal `01468fd`. (Same gap on S2-B01 row, legacy "(commit below)" placeholder.) | **Fixed** by orchestrator — both rows now carry literal SHAs (`10a251c` for S2-B01, `01468fd` for S2-B04). |
| NB-2 | `segments/edit/trim.ts:71` + `segments/edit/split.ts:85` read `state.segPeaksByAudio?.[audioUrl]?.duration_ms` directly (raw URL, not normalized). Backwards-compat sync in `_fetchPeaks` keeps the dict populated so no functional regression today, but Wave 7 must audit these call sites when it adopts edit-mode Svelte conversion. | Carry-forward to Wave 7. |

**Wave 7 carry-forwards:**

1. `segments/waveform/draw.ts::drawWaveformFromPeaksForSeg` (line 47, 60fps hot path) still reads `state.segPeaksByAudio` directly. Prioritize migration in Wave 7 since it's the most-called function.
2. 2 `edit/` call sites (trim.ts:71, split.ts:85) read `state.segPeaksByAudio` raw — migrate during Wave 7a edit-store rewrite.
3. `SegmentWaveformCanvas.svelte` `getCanvas()` exposed + `data-seg-index`/`data-seg-chapter` on wrapper `<div>` — Wave 7 must look up the canvas from within the `<div>` (observer observes `canvas[data-needs-waveform]`).
4. `state.segPeaksByAudio` dual-write coexists (raw + normalized both populated for by_surah); safe but will sunset when Wave 7 fully migrates.

**Validated:** §6.3 conformity, pattern #1/#5/#8 (waveform-cache = plain `Map` not `writable(new Map())`, 60fps hybrid preserved), S2-B04 fix correctness (normalize regex idempotent, handles missing `?url=` edge case), Wave 5 CF-1 migration (5 hot-path reads migrated in `playback/index.ts`; grep confirms zero remaining; ~30 non-hot-path reads intentionally on shim), S2-B07 grep (zero module-top DOM access), gates 7/7 + svelte-check 0/0.

### Orchestrator disposition

- NB-1 fixed inline (2 bug rows' fix-SHAs now literal).
- NB-2 + 4 Wave-7 carry-forwards logged.
- No blockers; Wave 6 (6a + 6b) is **CLOSED**. Proceed to Wave 7 autonomously.

---

## 7. Surprises / lessons

1. **Dual-keying band-aid was in the wrong place**: The S2-B04 workaround in `_fetchPeaks` stored under both CDN and proxy URL, but the real fix is normalizing at the cache key boundary. The advisor's recommendation to extract `normalizeAudioUrl()` into the cache util was exactly right — it makes the fix automatic and invisible to all call sites.

2. **`waveform-cache.ts` stays clean even with backwards-compat sync**: The decision to keep `state.segPeaksByAudio` sync'd (for the many `draw.ts` read sites) means the cache util is authoritative for key lookups but `state.segPeaksByAudio` remains a secondary cache. This is a deliberate temporary duplication until Wave 7 moves the draw functions into components that use the lib util directly.

3. **Import sort rule (`simple-import-sort`) is strict about blank lines**: Adding `svelte/store` as an external import requires a blank line separator before the `../../` internal group. The autofix handles this in one pass.

4. **Cycle ceiling stays 23**: No file deletions this wave means no cycle dissolution. The first decrement will happen when `segments/waveform/{index,draw,types}.ts` get absorbed into components in Wave 7.

---

## 8. Handoff to Wave 7 (SegmentRow {#each} adoption + edit modes)

### Prerequisites Wave 7 must respect

1. **Pattern notes #1-#8** from Wave 4 handoff still apply.
2. **`SegmentWaveformCanvas.svelte` is ready** — mount inside `SegmentRow.svelte`. Wire `onMount` to call `_ensureWaveformObserver().observe(getCanvas())` and add `data-needs-waveform` attribute.
3. **`waveform-cache.ts`** is the authoritative peaks store. Wave 7 should migrate `draw.ts` functions that still read `state.segPeaksByAudio` to use `getWaveformPeaks()` instead. After that migration, remove the backwards-compat sync in `_fetchPeaks`.
4. **Cycle ceiling 23**: first decrement happens when `segments/waveform/*.ts` files are fully absorbed or deleted. Decrement `CYCLE_CEILING` in `stage2-checks.sh`.
5. **`dom.segChapterSelect.value` non-hot reads**: ~30 remaining reads in edit/, validation/, navigation can be migrated to `get(selectedChapter)` opportunistically; not blocking.
6. **`draw.ts` overlay functions** (`_drawTrimHighlight`, `_drawSplitHighlight`, `_drawMergeHighlight`) are good candidates to move into `SegmentWaveformCanvas.svelte` overlay layer during Wave 7.

### Queued tasks for Wave 7+

- [ ] `SegmentRow.svelte` `{#each}` adoption — primary Wave 7 scope.
- [ ] Wire `SegmentWaveformCanvas.svelte` into SegmentRow (set `data-needs-waveform` + observe via `_ensureWaveformObserver`).
- [ ] Migrate `draw.ts` state reads to `getWaveformPeaks()` + remove backwards-compat sync in `_fetchPeaks`.
- [ ] Consider moving overlay draw functions (`_drawTrimHighlight` etc.) into the component.
- [ ] Edit modes (trim/split/merge/delete/reference) — Wave 7 primary scope.
- [ ] Decrement `CYCLE_CEILING` when any waveform/segments file gets deleted.
- [ ] Carry-forward: `state._segContinuousPlay = next` in `handleAutoPlayToggle` NB-2 (Wave 6a) — surface in Wave 7 handoff §7 if found wrong while tracing flows.

---

## 9. Suggested pre-flight additions

None. 7-gate + svelte-check caught everything needed.

---

## 10. Commits (exit-point detail)

```
7efd2bb refactor(inspector): lib/types/segments-waveform.ts — move SegCanvas + highlight types
39d6e98 feat(inspector): lib/utils/waveform-cache.ts — non-reactive Map with S2-B04 URL normalization
01468fd fix(inspector): S2-B04 waveform peaks orphaned after audio-proxy URL rewrite
8f0b813 feat(inspector): SegmentWaveformCanvas.svelte — ready for Wave 7 SegmentRow adoption
e99e67e refactor(inspector): consolidate segments/waveform/draw.ts into lib/utils/waveform-draw.ts
e56d3e1 refactor(inspector): Wave-5 CF-1 — hot-path reads use get(selectedChapter)
```

---

## 11. Time / token budget (self-reported)

- Tool calls: ~55 (Read/Edit/Write/Bash/Grep/advisor/Glob)
- New source files: 1 Svelte + 2 TS utils + 1 TS type file = 4
- Modified source files: 4 (`waveform/index.ts`, `waveform/types.ts`, `waveform/draw.ts`, `playback/index.ts`)
- Deletes: 0 (deferred — see §2)
- Bash: ~15 (typecheck/svelte-check/lint/build/git per commit, pre-flight)
- Advisor calls: 1 (pre-implementation — validated S2-B04 URL-normalization strategy + draw.ts consolidation scope)
- Model: Claude Sonnet 4.6
- Commits: 6 source + 1 handoff = 7

---

**END WAVE 6b HANDOFF.**
