# Stage 3 — Interview Summary

**Date**: 2026-04-16
**Branch**: `inspector-refactor` (worktree `refactor+inspector-modularize`)
**Seed doc**: `.refactor/stage3-draft.md` (pre-plan survey by Opus, 2026-04-15) + orchestrator review 2026-04-16 appended ~15 items.

---

## 0a Orientation

**Agents dispatched**: 0 (skipped).
**Rationale**: Codebase already deeply understood — Stage 3 draft covers the structural gaps, pre-plan survey already ran, orchestrator just completed a friction review adding ~15 additional items. Prompt specificity: high. Per `interview.md` skip condition "prompt is dense and specific enough, interview questions obvious from context" → 0a skipped, 0b ran directly.

Preparatory greps done by orchestrator before 0b:
- `src/segments/` = 29 `.ts` files, 6358 LOC (biggest: state.ts 616, data.ts 408, split.ts 404, trim.ts 351)
- `src/shared/` = 3 files (accordion.ts, dom.ts, searchable-select.ts); callers: only `segments/index.ts` + `segments/state.ts`
- `src/types/` = 2 files (api.ts, domain.ts); ~18 import sites across `lib/stores/*` + `lib/utils/*` + `src/segments/*`
- Big shells: `TimestampsTab.svelte` 806, `SegmentsTab.svelte` 603, `ErrorCard.svelte` 458
- Large stores: `lib/stores/segments/history.ts` 550, `filters.ts` 225, `chapter.ts` 189
- Python: `services/validation.py` 567, `services/undo.py` 420, `services/cache.py` 348, `services/data_loader.py` 316
- Imperative DOM usage: 136 `classList` / `querySelector` calls (styles-migration unblocker metric)
- `as unknown as` casts: ~15 (most disappear with `src/segments/` removal)
- Refactor-noise surface: **72 files** reference `Wave N` / `Stage N` / `S2-D` / `bridge for` / `(Wave N)` / `legacy` / `refactored in` across .ts, .svelte, .py (excluding node_modules)

---

## 0b Questions asked

1. **Q**: Comment/docstring cleanup scope — 72 files touch refactor-noise. How wide?
   **A**: **Frontend + backend** — strip across all `inspector/` code (ts, svelte, py). Keep `.refactor/` workflow artifacts + `CLAUDE.md` stage/wave terminology intact.

2. **Q**: Python backend cleanup in scope?
   **A**: **Yes — include deferred god-funcs + cache factory** — `validation.py::validate_reciter_segments` (393 LOC), `undo.py::apply_reverse_op` (105 LOC), `cache.py` 12-silo factory, `data_loader.py` (316 LOC) cleanup. Addresses Stage-2 deferrals S2-D28 + S2-D29.

3. **Q**: Big Svelte shells — split in this refactor?
   **A**: **All three** — `TimestampsTab` → `Controls/Audio/Keyboard` subcomponents; `SegmentsTab` shell split once `src/segments/` dies; `ErrorCard` → per-category subcomponents.

4. **Q**: Destiny of `src/segments/*` .ts code — pure Svelte-ify or utility extraction?
   **A**: **Decide per-file during planning** — Stage 2 planning agents classify each of the 29 files individually. No global rule. Pragmatic per-case judgment: pure logic → `lib/utils/`, UI behavior → Svelte components + stores, bridge-only → delete.

---

## Derived intent

- **Motivation**: Close Stage 2's 4 structural carry-forwards (legacy dirs) + strip refactor-process residue (comments, NOTEs, wave refs) + tackle backend god-funcs + split remaining big files. End state = no visible trace of the wave/stage process in code.
- **Subtype (primary)**: Dead-code / legacy elimination (kill `src/segments|shared|styles`, merge `src/types`).
- **Subtype (secondary, composed)**: Big-file decomposition (3 shells + 3 stores + backend god-funcs + cache factory).
- **Subtype (tertiary)**: Comment/docstring normalization (72-file sweep).

---

## Seed for §2a Invariants

### MUST stay true
- All existing frontend behavior preserved (no UX regression): every tab loads, dropdowns populate, segment edit/save/undo all green, timestamps waveform draws, audio playback works, validation accordions render every category, stats charts render, history panel loads.
- All `/api/*` endpoints return same shapes (no route signature break).
- Build: `cd inspector/frontend && npm run build` passes with zero TS errors.
- Lint: `npm run lint` passes (strictness: `strict: true`, `noUncheckedIndexedAccess: true`, `allowJs: false`).
- Python: `python3 -c "from inspector.app import create_app; create_app()"` succeeds.
- Comments explain WHY not WHAT. Remaining comments are load-bearing (subtle invariants, hidden constraints, workarounds) — not process residue.
- Production build does not ship `.map` source-maps.

### MAY change
- Any file path under `inspector/frontend/src/{segments,shared,styles,types}/` (these are deletion targets).
- Any comment referencing "Wave N", "Stage N", "S2-D", "bridge", "(Wave N)", "refactored in", "legacy compatibility" in code files.
- `lib/stores/segments/*.ts` NOTE comments documenting bridge state.
- Internal imports, module boundaries, component granularity within `tabs/`.
- `vite.config.ts` (manual chunks, sourcemap gate), `eslint.config.js` (enable .svelte rules).
- `inspector/services/*.py` internal decomposition (god-func splits).
- `inspector/CLAUDE.md` — update obsoleted sections (State object pattern, Registration pattern, file structure, `shared/constants.ts` wrong path).

### IS being intentionally changed
- `src/segments/` directory deleted in full (scoped across multiple phases).
- `src/shared/` directory deleted (after callers gone).
- `src/types/` → merged into `src/lib/types/`; `src/types/` deleted.
- `src/styles/{components,timestamps,segments,filters,validation,history,stats}.css` → scoped `<style>` blocks per component; only `base.css` remains.
- All 136 imperative `classList.*` + `querySelector` calls in frontend removed (phase-by-phase as Svelte migration progresses).
- `services/validation.py::validate_reciter_segments` + `_print_verbose` decomposed.
- `services/undo.py::apply_reverse_op` decomposed.
- `services/cache.py` 12 silos → `make_cache(name)` factory.
- `services/data_loader.py` loader shape factoring.
- `TimestampsTab.svelte` → `TimestampsTab` + `TimestampsControls` + `TimestampsAudio` + `TimestampsKeyboard`.
- `SegmentsTab.svelte` → shell + subcomponents (scope TBD during planning, after imperative dies).
- `ErrorCard.svelte` → per-category subcomponents.
- `lib/stores/segments/history.ts` → split into `history-data.ts` + `history-chains.ts` (+ maybe `history-filters.ts`).
- `lib/stores/segments/filters.ts` (225) + `chapter.ts` (189) split if natural seams emerge.
- `AudioElement.svelte` consolidated — `TimestampsTab` + `SegmentsAudioControls` both adopt it (instead of each wiring `<audio>` independently).
- `lib/utils/waveform-draw.ts` duplicate path (segments vs Svelte) collapsed once `src/segments/waveform/draw.ts` is gone.
- Registration pattern (`registerHandler`/`registerEditModes`/`registerWaveformHandlers`) removed — obsolete once imperative callers die.
- `vite.config.ts`: add `manualChunks` for Chart.js (~200 KB deferred to Segments tab only); gate sourcemap on dev mode only.
- `eslint.config.js`: remove `**/*.svelte` ignore; enable `eslint-plugin-svelte`.
- Refactor-process noise comments stripped from all 72 files. Remaining comments are clean WHY-not-WHAT notes.
- `main.ts`: delete dead ghost comment about `timestamps/index` not being imported.
- `inspector/CLAUDE.md`: remove obsoleted "State object pattern" + "Registration pattern" sections; correct `shared/constants.ts` → `lib/utils/constants.ts`; remove `src/{segments,shared,styles,types}/` from file tree.

---

## Seed for §2f Review allocation

Expected profile by phase type:
- **Legacy dir deletion phases** (segments/shared/types sweeps): Sonnet quality + Haiku coverage (mechanical coverage valuable given file count).
- **Shell split phases** (TimestampsTab/SegmentsTab/ErrorCard): Sonnet quality + Opus verification (logic preservation risk).
- **Style migration phases** (7 CSS files → scoped): Sonnet quality + Haiku coverage (mechanical, large file count).
- **Python backend phases**: Sonnet quality + Opus verification (god-func decomposition has logic-preservation risk).
- **Comment sweep phase** (72 files): Sonnet quality + Haiku coverage (mechanical high-volume).
- **Tooling phases** (vite/eslint/CLAUDE.md): Sonnet only.

---

## Seed for §2i Stop-points

- **Autonomous between phases** (per `feedback_autonomous_pipeline` memory).
- Systemic stop-points active by default: S2 (context-window ≥ 75%), S3 (review disagreement), S4 (plan deviation), S7 (pre-merge).
- User-declared pauses: **none**. Pipeline runs phases sequentially, handoffs only, orchestrator continues without prompting.

---

## Seed for §2g Shared-doc choice

- **Decision log** (`.refactor/stage3-decisions.md`): per-case classification of each `src/segments/` file (Q4: "decide per-file"). Captures for each .ts file: destination (lib/utils/ vs Svelte vs delete), rationale, and phase it lands in. Grows across phases.
- **Bug log** (`.refactor/stage3-bugs.md`): any latent bug surfaced during decomposition (the `history/undo.ts:210,212` Map-key cast already flagged as a "real bug, worth a look"). Standard bug-log protocol.
- **No drift ledger / budget / perf ledger** — not applicable.

---

## Explicit exclusions from refactor scope

- **Tests**: user confirmed no testing layer to be added. Build-pass + structural diff + smoke via S7 are the only verification. No test floor added.
- **Untracked data reciters** (`data/recitation_segments/{maher_al_meaqli,mohammed_alghazali,raad_al_kurdi,saad_al_ghamdi}/`): outside scope; not .gitignored, not tracked, not this refactor's concern.
- **`inspector/CLAUDE.md` wave/stage terminology normalization** (Q1 option 3 rejected): historical context preserved; only **obsoleted sections** are updated (State object pattern, Registration pattern, wrong path).
- **`.refactor/` directory**: workflow artifacts preserved untouched (stage3-draft.md, stage2-*.md, phase-N-handoff.md, etc.).
- **External validators package** (now out-of-tree per commit 86b9fec): not scope.
