# Wave 11b — Implementation Handoff

**Date**: 2026-04-14
**Branch**: `worktree-refactor+inspector-modularize` (WSL worktree)
**Wave HEAD**: `e48a091`
**Agent model**: claude-sonnet-4-6

---

## 1. Wave scope and completion status

Wave 11b covered 2 priorities.

| Priority | Scope | Status | Key commit |
|----------|-------|--------|------------|
| P5 | Audio tab Svelte conversion (S2-D06) | COMPLETE | `e48a091` |
| P6 | CSS migration global → scoped | PARTIAL — audio-tab.css done; 8 files deferred (see §4) | `e48a091` |
| NB-3 | Delete dead `void _findCoveringPeaks` in waveform/index.ts | COMPLETE (folded into P5 commit) | `e48a091` |
| NB-1 | Collapse `_applyHistoryData` / `renderEditHistoryPanel` | DEFERRED (Wave 12) | — |
| NB-2 | `undo.ts:227` self-round-trip cleanup | DEFERRED (Wave 12) | — |

---

## 2. P5 — Audio tab conversion (S2-D06)

### Component created

`inspector/frontend/src/tabs/audio/AudioTab.svelte` — 310 LOC self-contained Svelte component replacing `audio/index.ts` (341 LOC imperative).

### Key transformations

| Imperative (audio/index.ts) | Svelte (AudioTab.svelte) |
|-----------------------------|--------------------------|
| `document.createElement('optgroup'/'option')` + `innerHTML` | `SelectOption[]` arrays → `<SearchableSelect>` |
| `initAudioTabDom()` + `DOMContentLoaded` handler | `onMount` + `bind:this={playerEl}` |
| `mustGet<T>(id)` for 8 DOM refs | Component-local `let` variables + reactive |
| `classList.toggle('active', ...)` on category buttons | `class:active={selectedCategory === 'by_surah'}` |
| `ayahLabel.hidden = (selectedCategory !== 'by_ayah')` | `{#if selectedCategory === 'by_ayah'}` |
| `SearchableSelect` class (legacy imperative) | `<SearchableSelect>` Svelte component |
| Imperative `player.src = url; player.load()` | Same (player ref via `bind:this={playerEl}`) |

### State model

All state is component-local `let` — no store needed. No cross-tab sharing. Pattern notes #1-#8 from Wave 4 apply.

```ts
let selectedCategory: 'by_surah' | 'by_ayah' = 'by_surah';
let currentCategory: string | null = null;
let audioSources: AudioSourcesResponse = {};
const urlCache: Record<string, Record<string, string>> = {};
let ayahBySurah: Record<number, number[]> = {};
let allSurahNums: number[] = [];
let reciterOptions: SelectOption[] = [];
let surahOptions: SelectOption[] = [];
let ayahOptions: SelectOption[] = [];
let selectedReciter = '';
let selectedSurah = '';
let selectedAyah = '';
let playerEl: HTMLAudioElement;
let prevDisabled = true;
let nextDisabled = true;
```

### IDs preserved for App.svelte compatibility

- `id="aud-player"` on `<audio>` — `App.svelte:switchTab()` queries it to pause audio on tab switch.
- `id="audio-panel"` on the wrapper `<div>` — preserved in App.svelte for any CSS/JS that may reference it.

### Files changed in P5

| File | Change |
|------|--------|
| `frontend/src/tabs/audio/AudioTab.svelte` | NEW — 310 LOC |
| `frontend/src/App.svelte` | Import AudioTab; replace HTML block with `<AudioTab />` |
| `frontend/src/main.ts` | Remove `import './audio/index'` side-effect; remove `import './styles/audio-tab.css'` |
| `frontend/src/audio/index.ts` | DELETED (superseded) |
| `frontend/src/styles/audio-tab.css` | DELETED (ported to scoped `<style>`) |
| `frontend/src/segments/waveform/index.ts` | NB-3: Remove dead `void _findCoveringPeaks` + stale comment (line 16-17); keep `_findCoveringPeaks` import (still has live caller at line 246) |

---

## 3. P6 — CSS migration

### Completed

| CSS File | Disposition | Where |
|----------|-------------|-------|
| `styles/audio-tab.css` | PORTED | Scoped `<style>` in `AudioTab.svelte` (one rule: `#aud-player { width: 500px; ... }`) |

### Deferred

| CSS File | Reason for deferral | Suggested wave |
|----------|---------------------|----------------|
| `styles/base.css` | STAYS GLOBAL — resets, fonts, `:root` vars, scrollbars (per CSS migration map §4) | Never / permanent |
| `styles/components.css` | `.btn`/`.btn-nav`/`.info-bar`/`.audio-controls` used across ALL tabs + imperative `.ts` files via DOM queries; `.ss-*` classes already scoped in `SearchableSelect.svelte` (but global file must stay for legacy imperative callers) | Wave 12 |
| `styles/timestamps.css` | Imperative `classList.add/remove` for `.anim-word.active`, `.anim-word.reached`, `.mega-block.active` etc. in `AnimationDisplay.svelte` + `UnifiedDisplay.svelte`; needs `:global()` wrappers per pattern note #8 — non-trivial | Wave 12 |
| `styles/segments.css` | Many imperative `.ts` files use class names as query selectors (`.seg-row`, `.seg-edit-overlay`, `.seg-edit-target`, etc.) | Wave 12 |
| `styles/filters.css` | `.seg-filter-bar` and related classes rendered by imperative `rendering.ts` DOM manipulation | Wave 12 |
| `styles/validation.css` | `.val-card-wrapper`, `.val-action-btn`, `.val-card-issue-label` queried imperatively in `event-delegation.ts`, `error-cards.ts`, `rendering.ts` | Wave 12 |
| `styles/history.css` | Classes rendered inside Svelte history components (`HistoryBatch.svelte`, `HistoryOp.svelte`) but still need global scope for imperative `segments/history/index.ts` rendering | Wave 12 |
| `styles/stats.css` | `#seg-stats-fullscreen` queried by ID in `stats.ts`; stats panel rendered imperatively | Wave 12 |

**Decision**: All remaining CSS files deferred to Wave 12 per S2-D34 softening. The blocking issue is pattern note #8 (60fps imperative `classList` manipulation requires `:global()` in scoped styles, and many class names are also DOM query selectors in imperative `.ts` files). Full CSS migration requires those imperative modules to either be Svelte-ified or refactored to use data attributes / refs instead of class-selector queries.

---

## 4. NB absorption status

| NB | Description | Status |
|----|-------------|--------|
| NB-3 | Delete dead `void _findCoveringPeaks` line at waveform/index.ts:17 | DONE — removed stale void + comment in commit `e48a091` |
| NB-1 | Collapse `_applyHistoryData` (data.ts) / `renderEditHistoryPanel` (history/index.ts) | DEFERRED to Wave 12 (cycle-break structure must be kept; NB says "only if cheap", it's not) |
| NB-2 | `undo.ts:228` `setHistoryData(storeGet(historyData))` self-round-trip | DEFERRED to Wave 12 (functional, not blocking) |

---

## 5. Pre-flight gate status at wave exit

```
[1/7] npm run typecheck (tsc --noEmit)        ok
[2/7] npm run lint (ESLint)                   ok: 0 errors, 0 warnings
[3/7] npm run build (Vite production build)   ok: 144 modules
[4/7] Backend: no 'global' outside cache.py   ok
[5/7] Backend: _URL_AUDIO_META and _phonemizer in cache.py only   ok
[6/7] Frontend: zero '// NOTE: circular dependency' comments      ok
[7/7] Frontend: import/no-cycle count ≤ 0     ok: 0 cycle warnings (ceiling: 0)
svelte-check: 0 errors, 0 warnings
```

Build: 144 modules (down from 145 — audio/index.ts removed), 535 kB JS, 31.5 kB CSS.

---

## 6. Files changed this wave

| File | Change |
|------|--------|
| `inspector/frontend/src/tabs/audio/AudioTab.svelte` | NEW (310 LOC) |
| `inspector/frontend/src/App.svelte` | +1 import, −14 lines HTML, +1 `<AudioTab />` |
| `inspector/frontend/src/main.ts` | Remove 2 imports (audio/index, audio-tab.css); alphabetize CSS imports |
| `inspector/frontend/src/audio/index.ts` | DELETED |
| `inspector/frontend/src/styles/audio-tab.css` | DELETED |
| `inspector/frontend/src/segments/waveform/index.ts` | −2 lines (dead void + comment) |

Net LOC delta: approximately −440 (341 imperative TS deleted + 6 CSS deleted, +310 Svelte added, +various edits).

---

## 7. Decisions made this wave

| ID | Decision | Rationale |
|----|----------|-----------|
| W11b-D1 | No separate `AudioPlayer.svelte` — one component covers all | Player is 3 HTML elements; splitting would be over-engineering for this tab size |
| W11b-D2 | No `lib/stores/audio/` — all state is component-local | No cross-tab sharing needed; pattern note #1 |
| W11b-D3 | CSS migration deferred for all files except audio-tab.css | Pattern note #8 imperative classList + DOM query selector conflict; S2-D34 softening |
| W11b-D4 | NB-1 and NB-2 deferred | NB-1 requires careful cycle-break structure evaluation; NB-2 is functional |

---

## 8. Wave 11b exit SHA and commit count

- Entry SHA: `4f2e534` (Wave 11a exit)
- Exit SHA: `e48a091`
- Commits this wave: 1 (P5 + NB-3 + audio-tab.css combined per advisor guidance)

---

## 9. Known concerns / open questions for Wave 11c and beyond

1. **CSS migration (Wave 12)**: All 7 remaining non-base CSS files in `styles/` still global. For `timestamps.css`, the path forward is: (a) add `:global(.anim-word)` etc. in `AnimationDisplay.svelte` scoped style, then remove from `timestamps.css`. For `segments.css`, `validation.css`, `history.css`, `stats.css`, `filters.css`: imperative `.ts` code must be refactored to not use class names as query selectors first (use data attributes or `bind:this` refs instead), then CSS can be scoped.

2. **NB-1 (Wave 12)**: `_applyHistoryData` in `data.ts:53-61` is a private inline duplicate of `renderEditHistoryPanel`. Divergence risk if canonical version evolves. Tracked in Wave 11a handoff §8.

3. **NB-2 (Wave 12)**: `undo.ts:228` self-round-trip `setHistoryData(storeGet(historyData))`. Functional but semantically odd.

4. **`shared/searchable-select.ts` and `shared/dom.ts`**: Still used by `segments/index.ts` and `segments/state.ts`. Cannot delete until segments tab imperative code is fully Svelte-ified.

5. **App.svelte `switchTab()` audio pause**: Queries `#aud-player` by ID. This works because `AudioTab.svelte` preserves `id="aud-player"` on the `<audio>` element even though it's now Svelte-rendered.

---

## 10. Wave 11c prerequisites

Wave 11c (retro + CLAUDE.md + docs) should:

1. Update `CLAUDE.md` file structure section: add `tabs/audio/AudioTab.svelte`; remove `audio/index.ts` and `styles/audio-tab.css`.
2. Write `.refactor/stage2-retro.md` — lessons from the full Stage 2 migration (Waves 0.5–11b).
3. Update `docs/inspector-refactor-notes.md` if it exists.
4. Update `docs/inspector-docker-distribution.md` if it exists.
5. Final review of `.refactor/stage2-decisions.md` to ensure all decision records are current.

---

## 11. Token / tool-call self-report

- Tool calls: ~40 (Read, Bash, Edit, Write, Grep, advisor)
- Files created: 2 (AudioTab.svelte, this handoff)
- Files deleted: 2 (audio/index.ts, audio-tab.css)
- Files modified: 4 (App.svelte, main.ts, waveform/index.ts, advisor call)
- Bash: ~12 (typecheck, check, build, lint, pre-flight, git)
- Advisor calls: 1 (pre-implementation orientation)
- Model: claude-sonnet-4-6

---

**END WAVE 11b HANDOFF.**
