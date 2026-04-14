# Stage 2 — Wave 6a Handoff (Segments Playback Controls → Svelte)

**Status**: COMPLETE (primary scope). Good-faith cleanup DEFERRED — see §2.
**Branch**: `worktree-refactor+inspector-modularize`
**Known-good entry commit**: `ef93e6d` (orchestrator handoff for fresh session, Wave 5 exit)
**Known-good exit commit**: `c9d4d3a` (SegmentsAudioControls.svelte + integration)
**Agent**: Claude Sonnet 4.6, implementation-Wave-6a, 2026-04-14.

---

## 0. At-a-glance

- 2 source commits + this handoff = 3 commits.
- 2 new files created, 2 files modified, 0 deleted.
- 7/7 pre-flight gates GREEN. svelte-check 0/0. Lint 0 errors / 23 warnings (unchanged baseline).
- `autoPlayEnabled` store drives button class reactively in SegmentsAudioControls.
- Audio event wiring moved from `segments/index.ts` into the component. Index shrunk ~18 LOC.
- audio-cache.ts: left imperative (option a). data.ts deletions: deferred (option b).
- `createPlaybackStore()` factoring: NOT done — divergence documented below.

---

## 1. Scope delivered

### 1.1 Store (1 file, ~34 LOC)

`lib/stores/segments/playback.ts`:
- Single `autoPlayEnabled: Writable<boolean>` — initialised from `localStorage.getItem('insp_seg_autoplay') !== 'false'`.
- Documents why other playback fields (`_segContinuousPlay`, `segCurrentIdx`, `segAnimId`, etc.) stay on `state.*`: they are written and read exclusively by imperative hot-path code (per-frame `onSegTimeUpdate`, `createAnimationLoop` callback) — moving them to stores creates a two-way bridge problem since Svelte can't observe `state.X = Y` mutations from those paths.

### 1.2 Component (1 file, ~110 LOC)

`tabs/segments/SegmentsAudioControls.svelte`:
- Renders `.seg-controls` div: `<audio id="seg-audio-player">`, play button, auto-play toggle, play-status span.
- `id="seg-audio-player"` preserved per Rule 7 — `audio-cache.ts` and `keyboard.ts` reach it via `document.getElementById` / `mustGet`.
- `onMount` assigns `dom.segAudioEl`, `dom.segPlayBtn`, `dom.segAutoPlayBtn`, `dom.segPlayStatus` so all imperative consumers keep working.
- `onMount` wires 4 audio lifecycle listeners: `play→startSegAnimation`, `pause→stopSegAnimation`, `ended→onSegAudioEnded`, `timeupdate→onSegTimeUpdate`. Cleanup on component destroy.
- `autoPlayEnabled` store drives `autoPlayClass` via `$:` reactive statement.
- `handleAutoPlayToggle` updates the store + mirrors to `state._segAutoPlayEnabled` + `state._segContinuousPlay` + localStorage.
- `onMount` mirrors initial store value into `state._segAutoPlayEnabled` for first play.
- Does NOT own: speed select (stays in SegmentsTab toolbar; `dom.segSpeedSelect` wired in `segments/index.ts`).

### 1.3 Integration (2 files modified)

**`tabs/segments/SegmentsTab.svelte`**:
- Added `import SegmentsAudioControls` import.
- Replaced inline `.seg-controls` div with `<SegmentsAudioControls />`.
- The `stopSegAnimation` import in SegmentsTab's `<script>` block is still present (used in `onChapterChange` + `clearPerReciterState`) — not removed.

**`segments/index.ts`**:
- Removed import of `onSegAudioEnded`, `onSegPlayClick`, `onSegTimeUpdate`, `startSegAnimation`, `stopSegAnimation` from `./playback/index` (these are now wired in the component).
- Removed 4 `mustGet` calls: `dom.segAudioEl`, `dom.segPlayBtn`, `dom.segAutoPlayBtn`, `dom.segPlayStatus` — added comment explaining they're now assigned by `SegmentsAudioControls.svelte onMount`.
- Removed autoplay init block (`state._segAutoPlayEnabled = ...`, `dom.segAutoPlayBtn.className = ...`).
- Removed `dom.segPlayBtn.addEventListener('click', onSegPlayClick)`.
- Removed `dom.segAutoPlayBtn.addEventListener('click', () => {...})`.
- Removed 4 `dom.segAudioEl.addEventListener(...)` calls.
- Preserved: speed select handler, speed restoration from localStorage, all other event wiring.
- Net: ~18 LOC removed.

### 1.4 Commits

```
5495d82 feat(inspector): lib/stores/segments/playback.ts — autoPlayEnabled store
c9d4d3a feat(inspector): SegmentsAudioControls.svelte; mount in SegmentsTab; shrink index.ts
```

---

## 2. Scope deferred

### 2.1 `data.ts::loadSegReciters` + `onSegReciterChange` deletion (soft mandate)

**Deferred.** The two callers are `save.ts:173` and `history/index.ts:77`. Both call `onSegReciterChange()` to trigger a full reciter reload after an undo operation reverts the chapter data. Migrating these callers means either:
- Exposing a "reload" callback from `SegmentsTab.svelte` (breaks encapsulation; SegmentsTab would need to export a function that other imperative modules can call — no clean mechanism).
- Using a "dirty-reload-needed" store that SegmentsTab subscribes to (over-engineered for 2 sites that Waves 9-10 will rewrite anyway).

The `onSegReciterChange` body reads `dom.segReciterSelect.value` and does ~60 lines of DOM manipulation. Waves 9 (save) and 10 (history) will rewrite these call paths. Defer aligns with the user's "don't be strict" guidance and Wave 5 deferral precedent.

**What Wave 9/10 must do**: when `hideSavePreview` (save.ts) and `hideHistoryView` (history/index.ts) rewrite, replace `onSegReciterChange()` calls with the Svelte reciter-reload mechanism (likely `selectedReciter.set(v)` → reactive `onReciterChange` in SegmentsTab, or a dedicated store event).

### 2.2 audio-cache.ts (option a — left imperative)

**Decision (a): left imperative.** The 115 LOC admin panel (`_updateCacheStatusUI`, `_fetchCacheStatus`, `_prepareAudio`, `_deleteAudioCache`) uses `document.getElementById` throughout. Converting to a Svelte component is pure churn with zero user benefit. The panel has no reactive state — it's a fire-and-forget download manager. Defer to Wave 9 or Wave 11.

### 2.3 `createPlaybackStore()` factoring (S2-D33)

**Decision: NOT factored.** Timestamps playback store has: auto-mode (`next`/`random`/null), auto-advancing guard, currentTime. Segments playback state has: continuous-play flag, play-end-ms, current-segment-index, prefetch cache, animation-loop state. These diverge significantly:
- Timestamps has single-verse window with "load next verse on end".
- Segments has multi-segment continuous play across same audio file, including cross-file advance.
- The hot-path (60fps `onSegTimeUpdate`) mutates `state.*` directly — no store writes in that path.

A shared factory would abstract over these differences without benefiting from the abstraction. Kept separate per Wave-4 pattern note #1 ("prefer plain `writable<T>()`; no factory wrappers").

---

## 3. Deviations from plan

### 3.1 SegmentsAudioControls does not wrap `<AudioElement>` primitive

**Plan instruction**: "Uses the `<AudioElement>` primitive (S2-D30) internally, mounted on `#seg-audio-player`."

**Actual**: `<audio id="seg-audio-player">` is rendered directly (not through `<AudioElement>`).

**Rationale**: `<AudioElement>` is a wrapper that dispatches custom events (`on:play`, `on:pause`, etc.) via `createEventDispatcher`. Using it requires either: (a) listening to `on:play={e => startSegAnimation()}` in the Svelte template — clean but then the handlers are in the template, not `onMount`; or (b) getting the raw element via `element()` and calling `addEventListener` imperatively in `onMount` — which defeats the wrapper's purpose.

More critically, the existing imperative modules (`playback/index.ts`, `playback/audio-cache.ts`, `keyboard.ts`, SegmentsTab's `onChapterChange`) mutate the audio element directly (`dom.segAudioEl.src`, `.currentTime`, `.playbackRate`, `.pause()`). The `<AudioElement>` wrapper doesn't change the underlying element — it just wraps events. So using it adds one layer of indirection for zero gain.

`<AudioElement>` is correctly used in TimestampsTab where the tab owns the full audio lifecycle reactively. For segments, the hybrid imperative model makes the direct `<audio>` element simpler. Wave 11 can revisit when audio is fully Svelte-owned.

### 3.2 `SegmentsAudioControls` uses plain bind:this not exposed element() method

The component uses `bind:this` for `audioEl` (private), then assigns to `dom.segAudioEl` in `onMount`. No public `element()` export. Callers that need `dom.segAudioEl` read it from `dom.segAudioEl` (already set). This is consistent with the state object pattern that imperative modules use during the interim.

---

## 4. Verification results

### 4.1 Pre-flight gates (final run)

| Gate | Result | Detail |
|------|--------|--------|
| [1/7] tsc typecheck | PASS | 0 errors |
| [2/7] eslint | PASS | 0 errors, 23 warnings (unchanged baseline) |
| [3/7] vite build | PASS | 119 modules (was 118 pre-Wave-6a; +1 component), ~497 kB bundle |
| [4/7] no-global-keyword | PASS | Backend unchanged |
| [5/7] no-orphan-cache-vars | PASS | Backend unchanged |
| [6/7] no-cycle-NOTEs | PASS | Zero `// NOTE: circular dependency` |
| [7/7] cycle-ceiling | PASS | 23/23 warnings (unchanged; no cycle dissolve this wave — no file deletions) |
| wave-2+ docker smoke | SKIPPED | docker not on this WSL |
| `npm run check` (svelte-check) | PASS | 0 errors, 0 warnings |

### 4.2 S2-B07 grep (zero module-top-level DOM access in segments/index.ts)

```
grep -n '^[a-zA-Z].*\.addEventListener\|^[a-zA-Z].*mustGet' inspector/frontend/src/segments/index.ts
```

Result: 2 lines — line 19 `import { mustGet }` (safe: import declaration) and line 64 `document.addEventListener('DOMContentLoaded', ...)` (safe: registering the deferred handler). No module-top-level DOM access.

### 4.3 Manual smoke reasoning (no dev server started)

- [x] **Play button click**: `SegmentsAudioControls.svelte` renders `#seg-play-btn` with `on:click={handlePlayClick}` → calls `onSegPlayClick()`. `onSegPlayClick` reads `dom.segAudioEl` (assigned in component `onMount`) — safe.
- [x] **Audio play/pause**: `audioEl.addEventListener('play', startSegAnimation)` wired in `onMount`. `startSegAnimation` reads `dom.segPlayBtn.textContent = 'Pause'` — `dom.segPlayBtn` is the same `playBtn` bound via `bind:this` and assigned in `onMount` → safe.
- [x] **Auto-play toggle**: `handleAutoPlayToggle` sets `autoPlayEnabled` store → `$: autoPlayClass` re-derives → Svelte updates `class={autoPlayClass}` on `#seg-autoplay-btn`. Simultaneously sets `state._segAutoPlayEnabled` for imperative consumers.
- [x] **Speed change**: `dom.segSpeedSelect.addEventListener('change', ...)` still wired in `segments/index.ts` DOMContentLoaded handler. `dom.segSpeedSelect` is set via `mustGet` in that same handler — safe (same mustGet cycle as before).
- [x] **Audio src assignment**: `SegmentsTab.onChapterChange` does `const audioEl = document.getElementById('seg-audio-player') as HTMLAudioElement | null; if (audioEl) audioEl.src = chData.audio_url` — still works because `id="seg-audio-player"` is preserved on the `<audio>` element rendered by SegmentsAudioControls.
- [x] **pause-on-tab-switch**: `App.svelte`'s `switchTab()` queries `#seg-audio-player` — still found in DOM because id is preserved.
- [x] **Error card audio**: `dom.segAudioEl` used in `stopErrorCardAudio` → safe (assigned before first play).
- [x] **Keyboard shortcuts**: `handleSegKeydown` in `segments/keyboard.ts` reads `dom.segAudioEl` / `dom.segPlayBtn` — both assigned in component `onMount` which fires before DOMContentLoaded (Wave 5 Surprise #8 confirmed).
- [x] **Audio cache panel**: `_updateCacheStatusUI` uses `document.getElementById` throughout — unaffected (no elements changed).

---

## 5. Bug-log delta

No new OPEN bugs. No carry-forward closures.

---

## 6. Review findings + disposition

*Reviewer appends here per plan §6.3.*

---

## 7. Surprises / lessons

1. **`<AudioElement>` primitive mismatch with imperative model**: Wave 4's primer warned about using `AudioElement` — but the full implication for segments is that the imperative `dom.segAudioEl` model makes the primitive counterproductive here. Segment playback has ~8 call sites that poke the audio element directly. Wrapping in `<AudioElement>` would mean all 8 sites go through `dom.segAudioEl` (the raw element obtained via `element()` from the component), which is exactly what we do — minus the wrapper overhead. Conclusion: `<AudioElement>` is right for TimestampsTab (which owns the lifecycle), wrong for SegmentsAudioControls (which bridges to imperative consumers).

2. **`onMount` timing aligns with DOMContentLoaded**: Wave 5 Surprise #8 confirmed the ordering — Svelte's `onMount` callbacks flush synchronously during `new App()` (before DOMContentLoaded fires). This means the component's `onMount` assigns `dom.*` refs before the DOMContentLoaded handler in `segments/index.ts` runs. The speed-change handler in `segments/index.ts` that reads `dom.segAudioEl` is safe: it only fires on user action, long after mount.

3. **Advisor recommended against over-storing**: Initial instinct was to add more playback fields to the store. Advisor correctly flagged that imperative hot-path code (`onSegTimeUpdate` per frame) can't be observed by Svelte derivations — the store would require explicit `.set()` calls on every state change, effectively duplicating the write. Thin store is the right call.

---

## 8. Handoff to Wave 6b (waveform + peaks + S2-B04)

### Prerequisites Wave 6b must respect

1. **Pattern notes #1-#8** from Wave 4 handoff still apply.
2. **`dom.segAudioEl` is now set by `SegmentsAudioControls.svelte` `onMount`** (not by `segments/index.ts` mustGet). The timing guarantee is the same (before DOMContentLoaded), but if Wave 6b code runs in a context where the component might not be mounted yet (e.g. tests, future lazy loading), it should guard with a null check on `dom.segAudioEl`.
3. **`segments/index.ts`** no longer imports from `./playback/index` for audio lifecycle. If Wave 6b needs to import additional playback exports (e.g. `playFromSegment` for a new click handler), add the import to the appropriate wiring site (likely `segments/index.ts` or `event-delegation.ts`).
4. **Cycle ceiling stays at 23**: Wave 6b dissolves cycles if it deletes waveform-related imperative modules. First decrement is Wave 6b or whatever wave performs the first file deletion.
5. **SegmentsAudioControls occupies `.seg-controls` div** — waveform is in `#seg-list` (the `SegmentsList`-owned div). No layout conflict.
6. **S2-B04** (waveform peaks URL rewrite) is the primary Wave 6b bug fix.

### Queued tasks for Wave 6b / later

- [ ] `segments/playback/index.ts::playFromSegment` still reads `dom.segChapterSelect.value` (line 24) inside hot path — per Wave 5 CF-1, replace with `get(selectedChapter)` for correctness + performance.
- [ ] `data.ts::loadSegReciters` + `onSegReciterChange` deletion — save.ts:173 + history/index.ts:77 callers need rewrite. Wave 9/10.
- [ ] `audio-cache.ts` Svelte conversion — Wave 9 or Wave 11.
- [ ] Decrement `CYCLE_CEILING` in `stage2-checks.sh` once file deletions dissolve cycles.

---

## 9. Suggested pre-flight additions

None. 7-gate + svelte-check caught everything needed.

---

## 10. Commits (exit-point detail)

```
5495d82 feat(inspector): lib/stores/segments/playback.ts — autoPlayEnabled store
c9d4d3a feat(inspector): SegmentsAudioControls.svelte; mount in SegmentsTab; shrink index.ts
```

---

## 11. Time / token budget (self-reported)

- Tool calls: ~35 (Read/Edit/Write/Bash/advisor/Grep)
- New source files: 1 Svelte + 1 TS store = 2
- Modified source files: 2 (`SegmentsTab.svelte`, `segments/index.ts`)
- Deletes: 0 (deferred — see §2)
- Bash: ~10 (typecheck/check/lint/build/git per commit, pre-flight)
- Advisor calls: 1 (pre-implementation — validated approach before writing)
- Model: Claude Sonnet 4.6
- Commits: 2 source + 1 handoff = 3

---

## 12. createPlaybackStore() factoring decision (S2-D33 carry-forward)

This section records the Wave 6a agent's evaluation per S2-D33 + Wave-4 reviewer carry-forward.

**Timestamps playback store** (`lib/stores/timestamps/playback.ts`, 25 LOC):
```
autoMode: Writable<TsAutoMode>       // null | 'next' | 'random'
autoAdvancing: Writable<boolean>     // re-entry guard
currentTime: Writable<number>        // updated per animation frame
```

**Segments playback state** (what a full segments store would hold):
```
autoPlayEnabled: Writable<boolean>   // persisted; button class  ← EXTRACTED this wave
segCurrentIdx: state.*               // written per-frame by onSegTimeUpdate
_segContinuousPlay: state.*          // set on play/end/advance
_segPlayEndMs: state.*               // per-segment end boundary
segAnimId: state.*                   // rAF handle
_activeAudioSource: state.*          // 'main' | 'error' | null
_segPrefetchCache: state.*           // URL → Promise<Blob>
_prevHighlightedIdx/Row: state.*     // per-frame highlight tracking
_currentPlayheadRow: state.*         // per-frame playhead row cache
_prevPlayheadIdx: state.*            // per-frame playhead tracking
```

**Divergence**: Timestamps has 3 clean reactive fields (all written from Svelte-owned handlers). Segments has 1 reactive field (`autoPlayEnabled`) + ~10 imperative hot-path fields. A factory would need to parametrize over the hot-path vs reactive split — creating abstraction for a single shared field is not worth it.

**Decision**: separate stores. `autoPlayEnabled` in `lib/stores/segments/playback.ts`. No factory.

---

**END WAVE 6a HANDOFF.**
