# Stage-2 Bug Log

Shared append-only document maintained by the orchestrator and every refactor agent during the Svelte 4 migration (Stage 2).

All rows have a stable ID (`S2-B01`..`S2-B99`). **Append** new rows to the appropriate section; **never delete** a row. Status transitions move a row to the Closed section at the bottom with the fixing commit SHA and wave.

## Legend

- **STATUS**: `OPEN` | `LINT-CAUGHT` | `BUILD-CAUGHT` | `SMOKE-CAUGHT` | `REVIEW-CAUGHT` | `CLOSED` | `DEFERRED`
- **ORIGIN**: `STAGE1-CARRY` (open at end of Stage 1, brought forward) | `LINT` | `BUILD` | `SMOKE` (manual smoke detected) | `REVIEW` (reviewer agent surfaced) | `INTRODUCED` (regression from Stage 2 work)
- Cite code as `relative/path/from/repo/root.ts:LINE`

## Append protocol

- Orchestrator seeds Section 1 before Wave 0.5 starts (done — see below).
- Implementation agents append to Sections 2–4 the moment a finding surfaces — **before** any fix.
- Review agents append to Section 4 if regressions appear in the per-wave gate.
- Fixes go in **separate commits** for bisect-ability (one bug = one commit), unless the fix is trivial and lands alongside its enabling change.

---

## Section 1 — Stage-1 carry-overs (seeded 2026-04-13)

| ID | Title | File:Line | Origin | Wave-target | Status | Fix-SHA | Notes |
|----|-------|-----------|--------|-------------|--------|---------|-------|
| S2-B01 | Filter state saved-view leak | inspector/frontend/src/segments/filters.ts:166-168, :255-258 | STAGE1-CARRY | Wave 5 | CLOSED | (Wave-5 Navigation commit) | Fixed by reactive derivation. `displayedSegments` is now a `derived([segAllData, selectedChapter, selectedVerse, activeFilters], computeDisplayed)` — when all four inputs settle to empty/null, no segments render (no wedge). Single-writer rule enforced for `savedFilterView`: Navigation.svelte clears it when `$activeFilters` becomes non-empty; FiltersBar.clearAll + SegmentsTab.onReciterChange clear it directly. See Section 5. |
| S2-B02 | segData / segAllData chapter-index desync on delete | inspector/frontend/src/segments/edit/delete.ts:30-43 | STAGE1-CARRY | Wave 1 | CLOSED | 2d06251 | Two branches diverge on re-indexing; save can persist mismatched indices. Carry-over from Stage 1 B02. Medium-high priority. Fixed in Wave 1 by unifying on `segAllData.segments` as single source of truth. See Section 5. |
| S2-B04 | Waveform peaks orphaned after audio-proxy URL rewrite | inspector/frontend/src/segments/playback/audio-cache.ts:27-40 | STAGE1-CARRY | Wave 6 | CLOSED | (see Section 5) | Closed Wave 6b. Root cause: `state.segPeaksByAudio` keyed by original CDN URL; proxy URL lookups (by_surah reciters) always missed. Fix: `lib/utils/waveform-cache.ts::normalizeAudioUrl()` strips the proxy wrapper before cache key use. `_fetchChapterPeaksIfNeeded` single lookup replaces the dual CDN+proxy check. `_fetchPeaksForClick` skip guard uses normalized lookup. The old dual-keying band-aid in `_fetchPeaks` (lines 143-147) removed. Approach: option (a) URL normalization. |
| S2-B05 | Split chain UID lost on undo | inspector/frontend/src/segments/state.ts (`_splitChainUid`) | STAGE1-CARRY | Wave 9 | CLOSED | 02e116f | Null `_splitChainUid`/`_splitChainWrapper`/`_splitChainCategory` in `_afterUndoSuccess`, `onPendingBatchDiscard` (undo.ts), and `clearSegDisplay` (data.ts). See Section 5. |

## Section 2 — Lint/build-caught

_Empty at start. Implementation agents append rows here when typecheck/lint surfaces an issue mid-wave._

| ID | Title | File:Line | Caught by | Wave | Status | Fix-SHA | Notes |
|----|-------|-----------|-----------|------|--------|---------|-------|
| S2-B06 | 23 pre-existing segments-tab import cycles surfaced when TS resolver enabled | inspector/frontend/src/segments/{data,edit/reference,filters,history/{filters,index,rendering,undo},navigation,playback/index,rendering,save,validation/index,waveform/index}.ts | LINT | 1 | CLOSED | 71a1dc7 | `import/no-cycle` was silently no-op (see S2-D24) because `eslint-plugin-import` had no TS resolver. Wave 1 installed `eslint-import-resolver-typescript` + `import/parsers` mapping; **23** warnings surfaced in the segments tab. These were runtime-safe cycles the `register*` pattern was built to handle. Dissolved progressively across Waves 5-10 as state-store rewiring broke bidirectional edges (23 → 19 → 16 → 14 → 12). The final 8 cycles dissolved in **Wave 11a P4** via 5 register* wirings (`registerStopSegAnimation`, `registerOnSegReciterChange`, `registerGetEditCanvas`, `registerFetchChapterPeaks`, `registerDataLookups`). Rule re-promoted to `error` (S2-D24); CYCLE_CEILING=0. See Section 5. |

## Section 3 — Manual-smoke-caught

_Empty at start. Implementation agents append rows here when smoke-checklist surfaces an issue mid-wave._

| ID | Title | File:Line | Caught in flow | Wave | Status | Fix-SHA | Notes |
|----|-------|-----------|----------------|------|--------|---------|-------|

## Section 4 — New bugs introduced by refactor

| ID | Title | File:Line | Introduced-in-wave | Detected-in-wave | Status | Fix-SHA | Notes |
|----|-------|-----------|--------------------|-------------------|--------|---------|-------|
| S2-B07 | audio/index.ts module-top-level `mustGet` calls throw before App.svelte mounts | inspector/frontend/src/audio/index.ts:22-29 (pre-fix) | 3 | stop-point-1 (user smoke) | CLOSED | 0d2a4c6 | Wave 3 moved tab markup from index.html into App.svelte. `segments/index.ts` wrapped its `mustGet` calls inside a DOMContentLoaded handler; `audio/index.ts` did not — 8 `const X = mustGet(...)` declarations ran at module import time, BEFORE `new App()` mounted the audio-panel DOM. Bundle evaluation threw, main.ts aborted, App never mounted, blank page. Cascade error from segments/index.ts (its DOMContentLoaded handler fired AFTER the throw, found no App markup). **Missed by Wave-3 Sonnet and Opus reviewers** despite explicit mount-timing focus — reviewers reasoned about DOMContentLoaded handler timing but not module-top-level DOM access. Fix: module-level `let X!: Type` bindings + `initAudioTabDom()` called from DOMContentLoaded handler. See Section 5. |

## Section 5 — Closed

_Empty at start. Move rows here when fixed; record fix-SHA + closing wave + brief fix summary._

| ID | Origin section | Fix summary | Fix-SHA | Wave |
|----|----------------|-------------|---------|------|
| S2-B02 | Section 1 | Unified delete path on `segAllData.segments` as single source of truth: splice + re-index there, null `_byChapter`/`_byChapterIndex`, then refresh `segData.segments` from the re-indexed source via `getChapterSegments(chapter)` when the deletion was in the currently-displayed chapter. Removes the prior divergent re-indexing between the two branches. | 2d06251 | 1 |
| S2-B01 | Section 1 | Reactive filters store: `displayedSegments` derived from `[segAllData, selectedChapter, selectedVerse, activeFilters]` — empty inputs → empty derived output, no UI wedge. Single-writer rule for `savedFilterView`: Navigation.svelte subscribes to `activeFilters` and clears `savedFilterView` when filters become non-empty; explicit clears happen in FiltersBar.clearAll + SegmentsTab.onReciterChange. The scattered Stage-1 writes (filters.ts:166-168 + filters.ts:255-258 + data.clearSegDisplay) are gone. | 10a251c | 5 |
| S2-B07 | Section 4 | Wrapped `audio/index.ts` module-top-level `mustGet` calls + category-toggle click listener into `initAudioTabDom()` called from the existing DOMContentLoaded handler. Module-level `let X!: Type` bindings preserve closure access for the rest of the file. Zero behavior change post-load; fixes the "missing #aud-category-toggle" throw that aborted App.svelte mount. | 0d2a4c6 | stop-point-1 |
| S2-B04 | Section 1 | `lib/utils/waveform-cache.ts` normalizes proxy URLs before cache key use via `normalizeAudioUrl()`. `_fetchChapterPeaksIfNeeded` replaced dual CDN+proxy lookup with single normalized `getWaveformPeaks()` call. `_fetchPeaksForClick` skip guard uses normalized lookup. Removed dual-keying workaround in `_fetchPeaks` (old lines 143-147 that stored under proxy URL as workaround). | 01468fd | 6b |
| S2-B05 | Section 1 | Null `_splitChainUid`/`_splitChainWrapper`/`_splitChainCategory` in `_afterUndoSuccess` and `onPendingBatchDiscard` (`history/undo.ts`) and in `clearSegDisplay` (`data.ts`). These fields are a fire-once intent signal; they are not part of the undo snapshot, so the fix is null-out on cleanup, not snapshot restore. | 02e116f | 9 |
| S2-B06 | Section 2 | All 8 remaining cycles dissolved in Wave 11a P4 via the register* pattern: (1) `data ↔ history/index`: inlined `renderEditHistoryPanel` in data.ts + registered `onSegReciterChange` in history/index.ts; (2) `data ↔ playback/index`: registered `stopSegAnimation` in data.ts; (3) `data ↔ waveform/index`: registered `_fetchChapterPeaksIfNeeded` in data.ts + registered data lookups in waveform/index.ts; (4) `waveform/index ↔ rendering`: registered `_getEditCanvas` in waveform/index.ts. All wired in segments/index.ts. `import/no-cycle` re-promoted to `error`; CYCLE_CEILING updated to 0. | 71a1dc7 | 11a |

---

## Reference: Stage-1 API drift rows (CLOSED — for context only, NOT seeded as OPEN)

The Stage-1 bug log Section 3 has 9 closed API-drift rows (B09-B12, B15-B16, B18-B20). Per Sonnet plan-review fix, these are **not** re-seeded here as OPEN. Reference: `.refactor/stage1-bugs.md` Section 3. They serve as historical context if Wave 2 thin-route extraction or Wave 3 Svelte foundations surfaces similar drift.
