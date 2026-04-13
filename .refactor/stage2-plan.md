# Inspector Stage 2 — Plan (v3 — post 3-model review)

**Status**: Final draft. v1 user-reviewed; v2 advisor + user-reviewed; v3 incorporates Opus + Sonnet 3-model review (Haiku review timed out; mechanical claims spot-checked by Opus and Sonnet inline).
**Author**: Orchestrator (Claude Opus 4.6 via /refactor skill).
**Date**: 2026-04-13.
**Scope**: Frontend Svelte 4 migration + orthogonal backend polish needed for distribution. Testing, Pydantic, and bundle-size tracking all deferred.

---

## Interview Summary

### 0a Orientation
Performed inline. Findings:
- Stage 1 fully committed (15 Phase-0→7 commits + docs-hygiene + path-centralization + post-critique fixes). Clean working tree on `worktree-refactor+inspector-modularize`.
- `docs/inspector-docker-distribution.md` is untracked forward-looking notes — inspector is being prepared for Docker distribution to non-technical reviewers.
- `package.json` has only `chart.js` + `chartjs-plugin-annotation` — no framework experiments started.
- `.refactor/stage1-bugs.md` confirms 4 OPEN bugs (B01 medium, B02 medium-high, B04 low-medium, B05 low).
- Many parallel `feat/add-segments-*` branches — multi-reciter data work ongoing; the refactor must not disturb those.

### 0b Questions asked

**Round 1:**
1. Motivation → *Mixed / general polish* — future-maintainability + distribution prep.
2. Approach → *Commit to full plan.*
3. Svelte 4 vs 5 → *Svelte 4.*
4. Prework → *B02 fix + Timestamps registry cleanup.* (Declined: perf baseline, Playwright.)

**Round 2:**
5. Escalation → *Pause only before highest-risk phases* (Segments tab start + `history/rendering.ts`).
6. Prework sequencing → *Pre-Stage-2 commits on this branch.*
7. Bundle size → *Ignore.*
8. Plan approval gate → *After draft plan, before 3-model review.* User: "those were just notes, not hard requirements."

**Round 3 (during plan review):**
9. Testing → *Out of scope entirely.* No pytest, no Vitest, no Playwright. Manual smoke + reviewers only.
10. Agent allocation → *One implementation agent per wave* (max 3 sub-waves for large ones). Reviewers at wave boundaries.
11. Pydantic → *Skip.*
12. `validators/` → *Vendor* into `inspector/validators/`.
13. `CACHE_DIR` → *Under `DATA_DIR`* (persistent across Docker restarts).
14. `requirements-dev.txt` → *Yes, separate.*
15. Audio tab as warm-up → *Skip.*
16. Wave ordering → *Orchestrator picks + reviewers challenge.* Orchestrator commits to **Option B (Svelte-first)**.
17. History view complexity → *Over-sold in draft.* SVG arrows collapse to a tiny helper + reactive binding.

### Derived intent

- **Primary motivation**: long-term maintainability + distribution readiness + future-contributor cognitive load. No deadline. Non-thesis.
- **Subtype (primary)**: Framework migration (TS imperative DOM → Svelte 4).
- **Subtype (secondary)**: Backend polish focused on distribution-blockers and cheap wins. God-function decomposition DROPPED from scope (too risky without tests; existing behavior works, size isn't a bug).
- **OUT of scope**: testing (any kind), Pydantic, bundle-size tracking, mode B single-writer lock, virtualization.

---

## 1. Context

Stage 1 landed Vite + strict-TS with zero introduced bugs. Explicitly not solved: imperative DOM plumbing, state-DOM sync, shared UI patterns that aren't components, per-domain CSS files not co-located with behavior, untestable UI, registration pattern existing only to break cycles.

Exploration (7 parallel agents, 2026-04-13) surfaced:
- **Frontend**: 55 `.ts` files, 12,265 LOC. Top 10 by size: `history/rendering.ts` (695), `segments/state.ts` (659), `timestamps/index.ts` (569), `validation/index.ts` (532), `validation/error-cards.ts` (456), `data.ts` (418), `edit/split.ts` (399), `types/domain.ts` (376), `timestamps/animation.ts` (362), `timestamps/unified-display.ts` (352). State hubs (659+189 LOC) become stores-per-concern.
- **5 registration slots** (`registerHandler`, `registerKeyboardHandler`, `registerEditModes`, `registerEditDrawFns`, `registerWaveformHandlers`, `setClassifyFn`) all dissolve in a component tree. `segments/registry.ts` is deleted.
- **5 timestamps `// NOTE: circular dependency` comments** still live; ESLint's `import/no-cycle` (already configured) will flag them once lint runs.
- **8 DOM-in-state anti-patterns** + **7 derived-state-stored-independently cases** — Svelte `$derived` / reactive stores handle these by construction.
- **Backend**: `validators/` sibling package is a hidden Docker blocker. `INSPECTOR_DATA_DIR` env var not wired. Two `global` violations in `services/peaks.py` and `services/phonemizer_service.py`. 3 god-handlers (`seg_data` 115, `ts_data` 120, `seg_edit_history` 85 LOC). Zero tests anywhere. `debug=True` in production default.
- **7 API drift rows** live (phantom TS fields, undeclared emitted fields). Cleaned up in Wave 2 via type-layer edits.

---

## 2. Invariants

### MUST stay true

- Runtime behavior per tab — every UI flow (edit/save/undo/validation/history/stats/playback/audio) works identically.
- Data file compatibility — `detailed.json`, `edit_history.jsonl`, backup files, peak cache round-trip unchanged.
- Public API endpoints — all 33 `/api/*` routes keep URL, method, response shape. Drift bugs fixed at the type layer, not by changing server emit.
- Server-side persistence contracts — atomic write + `.bak` + edit-history-append unchanged.
- 16 CLOSED Stage-1 bug rows stay closed.
- ESLint + typecheck + build pass at every wave boundary.

### MAY change

- Folder structure under `inspector/frontend/src/` and inside `inspector/`.
- File names, module boundaries, component granularity.
- CSS file layout — scoped `<style>` per component replaces most of `src/styles/`. `base.css` stays global.
- Store shape — agents refine field allocation based on what components actually bind to.
- Route handler thickness — routes become thin (parse → service → jsonify) where it's behavior-preserving.
- Internal cache ownership — two `global` variables consolidated into `services/cache.py`.
- Any obsolete Stage-1 artifact (e.g. `registry.ts`) can be deleted.
- Magic numbers in Python code move to `config.py`.

### IS-changing (intentional)

- **Framework**: vanilla TS imperative DOM → Svelte 4 component tree + `writable`/`derived` stores.
- **State model**: per-tab state object (60+ fields) + manually-invoked render functions → stores-per-concern with reactivity.
- **DOM reference model**: `dom.*` object with `_UNSET` + `mustGet<T>()` → `bind:this` / direct element authoring.
- **Registration pattern**: 5 register-slot families dissolve. `segments/registry.ts` deleted. Timestamps cycles pre-emptively cleaned in Wave 1.
- **CSS architecture**: 9 files → scoped `<style>` per component + `base.css` global. Fragile selectors (`body.seg-edit-active`, `#animation-display.anim-window`, `:root` vars set by JS) rewritten as props/state.
- **Backend `global` variables**: `_URL_AUDIO_META` (peaks.py) + `_phonemizer` (phonemizer_service.py) → `services/cache.py` API.
- **Routes**: thin handlers. Inline logic extracted where it's a pure move, not a function split.
- **Docker distribution readiness**: `INSPECTOR_DATA_DIR` wired; `CACHE_DIR` under `DATA_DIR`; `validators/` vendored; `debug=False` by default.
- **Import cycles**: all 5 timestamps NOTEs + the 5 register-slots disappear. ESLint `import/no-cycle: 'error'` enforced.

### Explicitly NOT changing

- Backend god-functions `validate_reciter_segments` (393 LOC) and `apply_reverse_op` (105 LOC). Too risky to decompose without tests. Live with size. (`save_seg_data` exception added in Wave 2b — see §4.)
- Error response envelope shape (`{error: str}`), status codes, request body shapes.
- Data-directory layout, audio URL contracts, edit-history JSONL format.

### Deprecated principles (call-out per Sonnet review)

- **State object pattern** — CLAUDE.md lists this as a Code Principle. The plan supersedes it for the frontend: per-tab `state.ts` with a `state` + `dom` object → stores-per-concern (`writable`/`derived`) + Svelte template-bound DOM refs (`bind:this`). Wave 11 updates `inspector/CLAUDE.md` to record the supersession. Implementation agents reading CLAUDE.md mid-refactor should treat the state-object-pattern principle as deprecated for any new code in `frontend/src/`; existing Stage-1 `state.ts` files remain valid until each is replaced by stores in its respective wave.

---

## 3. Success Criteria

(No bundle size. No test coverage.)

### Hard gates at wave boundaries

- Manual smoke pass on every UI flow affected by the wave (checklist generated per wave).
- `npm run build` passes.
- `npm run lint` passes (0 errors; warnings acceptable, logged).
- `.refactor/stage2-bugs.md` has no new OPEN priority-≥-medium rows.

### End-of-refactor exit

- [ ] Every `.ts` module with UI concerns is now `.svelte` OR deleted as obsolete.
- [ ] Pure-logic modules stay `.ts` (`shared/arabic-text.ts`, `shared/api.ts`, `shared/constants.ts`, `shared/animation.ts`, `shared/audio.ts`, `shared/speed-control.ts`, `segments/constants.ts`, `segments/references.ts`, `segments/validation/categories.ts`, all of `types/`).
- [ ] `state.ts` files replaced by stores-per-concern.
- [ ] `segments/registry.ts` and all `register*Handler` / `setClassifyFn` functions deleted.
- [ ] Zero `// NOTE: circular dependency` comments remain.
- [ ] ESLint `import/no-cycle: 'error'` enforced.
- [ ] All 4 OPEN Stage-1 bugs (B01/B02/B04/B05) either CLOSED or have a Stage-2 successor row with explicit deferral rationale.
- [ ] Backend: zero `global` keyword outside `services/cache.py`.
- [ ] Docker: `Dockerfile` + `docker-compose.yml` land; `docker build . && docker compose up` reaches working inspector with mounted `/data`.
- [ ] `validators/` vendored under `inspector/validators/`; no `sys.path` hack.
- [ ] `app.py`: structured logging, central `@app.errorhandler`, `debug=False` unless `FLASK_ENV=development`.
- [ ] `config.py`: `INSPECTOR_DATA_DIR` env override with all 5 data paths derived; `CACHE_DIR` inside `DATA_DIR`.
- [ ] `inspector/CLAUDE.md` architecture section updated to reflect new structure.

---

## 4. Scope

### IN scope

**Wave 1 — Prework (pre-Svelte)**. 4 items, 1 agent, 1 commit-cluster:
- B02 fix (`segments/edit/delete.ts` chapter-index unification).
- Timestamps circular-import cleanup (create `timestamps/registry.ts`, wire 5 NOTE sites).
- ESLint `import/no-cycle` **verified end-to-end** (already set to `error` in `eslint.config.js`; Wave 1 confirms it catches nothing after the timestamps registry cleanup; no config change needed — Sonnet review correction).
- `services/cache.py` absorbs `_URL_AUDIO_META` + `_phonemizer`.

**Wave 2 — Backend polish + Docker distribution**. 1 agent, 2 sub-waves:

*Sub-wave 2a — config + Docker + vendoring*:
- `config.py`: `INSPECTOR_DATA_DIR` env override, wire all 5 data paths, `CACHE_DIR` under `DATA_DIR`.
- Vendor `validators/` into `inspector/validators/`; delete `sys.path` hack in routes/timestamps.py + update services/validation.py import. Record source SHA in `stage2-decisions.md`.
- `Dockerfile` + `docker-compose.yml` + `.dockerignore`.
- Separate `requirements-dev.txt` (empty for now, in place for future use).

*Sub-wave 2b — app cleanup + thin routes + targeted decomposition*:
- `app.py`: stdlib `logging` with JSON formatter, `@app.errorhandler(HTTPException)`, `debug=False` default, `FLASK_ENV=development` branch preserves current dev UX.
- Thin-route extraction for `seg_data`, `ts_data`, `seg_edit_history` (pure move of inline logic into existing services; **behavior-preserving extraction only — no service-function decomposition**).
- **`save_seg_data` mechanical extract-method** (per Opus review): the 140-LOC function decomposes into ~4 named helpers (`_load_and_validate`, `_apply_full_replace`, `_apply_patch`, `_persist_and_record`) along clear sequential phase boundaries. Behavior-preserving by construction (no control flow changes, no field renames). Opus-reviewed diff before merge. `validate_reciter_segments` and `apply_reverse_op` remain out of scope.
- `config.py` magic-number sweep (`0.60` in segments_data, ffmpeg flags, thread counts, port default).

**Wave 3 — Svelte foundations**. 1 agent:
- **Pre-Wave-3 artifact**: enumerate the 9 CSS files' load-bearing global selectors (`body.seg-edit-active`, `#animation-display.anim-window`, `:root` vars set by JS) and assign each to the wave that rewrites its trigger. Output: `.refactor/stage2-css-migration-map.md`. Per Opus review: this is cheap insurance against orphaned selectors at Wave 11.
- Install Svelte 4: `@sveltejs/vite-plugin-svelte`, `svelte@^4`, `svelte-check`. Config files.
- `App.svelte` + tab router; `main.ts` → ~10 LOC mount.
- Shared components: `Button`, `SearchableSelect`, `AccordionPanel`, `SpeedControl`, `ValidationBadge`, `WaveformCanvas` (base canvas primitive).
- **`shared/` migration mapping** (per Sonnet review):

  | Stage-1 file | Stage-2 destination | Rationale |
  |---|---|---|
  | `shared/api.ts` | `lib/api/index.ts` | Pure async utility |
  | `shared/constants.ts` | `lib/utils/constants.ts` | Pure constants |
  | `shared/animation.ts` | `lib/utils/animation.ts` | Framework-agnostic timer primitive |
  | `shared/audio.ts` | `lib/utils/audio.ts` | Pure DOM/audio utility |
  | `shared/arabic-text.ts` | `lib/utils/arabic-text.ts` | Pure string utility |
  | `shared/speed-control.ts` | `lib/utils/speed-control.ts` | Pure control logic |
  | `shared/dom.ts` | DELETED | `mustGet` obsolete in Svelte (`bind:this` replaces it) |
  | `shared/chart.ts` | `lib/utils/chart.ts` | Chart.js bootstrap; one-time registration |
  | `shared/accordion.ts` | DELETED OR `lib/utils/accordion.ts` | If `<AccordionPanel>` absorbs full behavior, delete; else keep |
  | `shared/searchable-select.ts` | DELETED | Replaced by `<SearchableSelect>` component |
  | `shared/surah-info.ts` | `lib/stores/surah-info.ts` (or `lib/utils/surah-info.ts`) | Singleton data cache; reactive store if any UI binds to it, else util |

- No testing-library. No Vitest. Manual smoke + review.

**Wave 4 — Timestamps tab**. 1 agent, possibly 2 sub-waves (4a: stores + tab shell + UnifiedDisplay, 4b: AnimationDisplay + Waveform + Validation):
- Stores: `verse`, `display` (view mode + granularity + show letters/phonemes), `playback`.
- Components: `TimestampsTab`, `UnifiedDisplay`, `AnimationDisplay`, `TimestampsWaveform`, `TimestampsValidationPanel`.

**→ STOP-POINT 1 (user review) ← end of Wave 4**

**Wave 5 — Segments shell + filters + rendering**. 1 agent:
- **Pre-Wave-5 artifact**: produce a component ↔ store binding matrix (which Svelte components subscribe to which stores). Even informal — markdown table at `.refactor/stage2-store-bindings.md`. Per Opus review: prevents "I didn't realize StatsPanel also reads navigation" surprises in later waves.
- Stores: `chapter`, `filters`, `navigation`. **All store-shape decisions provisional through Wave 9; locked in Wave 11.** Per Opus review.
- Components: `SegmentsTab`, `FiltersBar`, `FilterCondition`, `SegmentsList`, `SegmentRow`, `Navigation` (back-to-results banner; per Sonnet review fix).
- **`SegmentRow.svelte` provisioning requirement** (per Wave 0.5 finding S2-D23): the component MUST accept these props from day one — Wave 10's `HistoryOp.svelte` / `SplitChainRow.svelte` depend on them:
  - `readOnly?: boolean`
  - `showChapter?: boolean`
  - `showPlayBtn?: boolean`
  - `splitHL?: SplitHighlight`
  - `trimHL?: TrimHighlight`
  - `mergeHL?: MergeHighlight`
  - `changedFields?: Set<'ref' \| 'duration' \| 'conf' \| 'body'>`
  - `mode?: 'normal' \| 'history'` (history mode = vertical waveform-above-text layout vs default horizontal)

**Wave 6 — Segments playback + waveform**. 1 agent:
- Stores: `playback`, `waveform-cache` (non-reactive Map, not a store).
- Components: `SegmentsAudioControls`, `SegmentWaveformCanvas`.

**Wave 7 — Segments edit modes**. 1 agent, 2 sub-waves (7a: edit store + overlay + trim + split — the hardest; 7b: merge + delete + reference):
- Store: `edit`.
- Components: `EditOverlay`, `TrimPanel`, `SplitPanel`, `MergePanel`, `DeletePanel`, `ReferenceEditor`.

**Wave 8 — Segments validation + stats**. 1 agent:
- Stores: `validation`, `stats`.
- Components: `ValidationPanel`, single `ErrorCard.svelte` with `category` prop and `{#if}`/`{:else if}` branches (split only if a branch > ~100 LOC), `StatsPanel`, `StatsChart`, `ChartFullscreen`.

**Wave 9 — Segments save + undo**. 1 agent:
- Store: `save`.
- Components: `SavePreview`, `SaveConfirm`.
- Undo action hooks into existing history store (rendered in Wave 10).

**→ STOP-POINT 2 (user review + focused exploration on `history/rendering.ts`) ← end of Wave 9**

**Wave 10 — Segments history view**. 1 agent, 2 sub-waves (10a: stores + panel + batch + op + chain; 10b: arrows):
- Pre-wave exploration: focused Opus pass on `history/rendering.ts` to characterize the SVG-arrow geometry and diff-card layout (the initial exploration agent timed out on this file).
- `lib/utils/svg-arrow-geometry.ts`: pure helper, `computeArrowPath(fromRect, toRect) → string`. ~50 LOC. Reactive binding on scroll/resize in the component.
- **Fallback option** if the arrows turn out more complex than expected: drop in `leader-line` library (pure-JS, no Svelte port needed, imperative API used from `onMount`/`onDestroy`). Decide during sub-wave 10b.
- Components: `HistoryPanel`, `HistoryFilters`, `HistoryBatch`, `HistoryOp`, `SplitChainRow`, `HistoryArrows`.

**Wave 11 — Cleanup**. 1 agent:
- **Convert audio tab** (per Sonnet review fix): `src/audio/index.ts` (341 LOC self-contained) → `tabs/audio/AudioTab.svelte` + `tabs/audio/AudioPlayer.svelte` + (if needed) `lib/stores/audio/index.ts`. Small enough to bundle into cleanup; warm-up was skipped per user.
- Delete obsolete `.ts` files (state.ts files, registry.ts, index.ts wiring modules, rendering modules).
- Delete `src/styles/*.css` files fully ported to scoped `<style>` (verify by grep against the CSS migration map from Wave 3).
- Update `inspector/CLAUDE.md` architecture section. **Explicitly note**: the "State object pattern" principle is superseded by stores-per-concern for the Svelte frontend.
- Archive or delete `docs/inspector-refactor-notes.md` (the original Stage-2 notes; superseded by this plan once executed). Per Opus review.
- Update `docs/inspector-docker-distribution.md` to mark pre-reqs done.
- Post-refactor retrospective at `.refactor/stage2-retro.md`.

### OUT of scope

- **All automated testing** (pytest, Vitest, Playwright, component tests). Manual smoke only. Revisit as separate refactor later.
- **Pydantic** — TypedDict can be adopted by individual agents during service-signature work if they want, but no systematic schema layer.
- **Bundle-size tracking**.
- **Backend god-function decomposition** — `validate_reciter_segments`, `save_seg_data`, `apply_reverse_op` stay as-is. Risky to decompose without tests; the existing code works.
- **Mode B single-writer lock** (hosted-deployment-only; not current use case).
- **Virtualization** of segment rows.
- **Svelte 5** — chosen 4.
- **OpenAPI generation / auto-generated TS from Python**.
- **Thesis pipeline code** — inspector-only.

---

## 5. Target structure

```
inspector/
├── app.py                              # thinner; structured logging; production debug flag
├── config.py                           # INSPECTOR_DATA_DIR env; magic-number sweep; CACHE_DIR under DATA_DIR
├── constants.py
├── requirements.txt                    # prod deps unchanged
├── requirements-dev.txt                # NEW — empty for now, placeholder
├── Dockerfile                          # NEW
├── docker-compose.yml                  # NEW
├── .dockerignore                       # NEW
│
├── routes/                             # 7 blueprints; thinner (inline logic extracted)
├── services/                           # unchanged structure; cache.py absorbs 2 globals
├── utils/                              # unchanged
├── validators/                         # NEW — vendored from sibling package
│
└── frontend/
    ├── package.json                    # adds: svelte@^4, @sveltejs/vite-plugin-svelte, svelte-check
    ├── svelte.config.js                # NEW
    ├── vite.config.ts                  # adds svelte plugin
    ├── tsconfig.json                   # svelte-aware
    ├── index.html
    └── src/
        ├── App.svelte                  # tab router
        ├── main.ts                     # ~10 LOC mount
        │
        ├── lib/
        │   ├── api/                    # evolved from shared/api.ts
        │   ├── stores/                # PROVISIONAL — agents may merge/split/derive based on actual binding patterns through Wave 9; locked at Wave 11
        │   │   ├── segments/
        │   │   │   ├── chapter.ts
        │   │   │   ├── filters.ts
        │   │   │   ├── navigation.ts
        │   │   │   ├── edit.ts
        │   │   │   ├── save.ts
        │   │   │   ├── history.ts
        │   │   │   ├── validation.ts   # may be derived() store, not writable
        │   │   │   ├── stats.ts        # may be derived() store, not writable
        │   │   │   └── playback.ts
        │   │   ├── timestamps/
        │   │   │   ├── verse.ts
        │   │   │   ├── display.ts
        │   │   │   └── playback.ts
        │   │   └── audio/
        │   │       └── index.ts        # added in Wave 11 audio-tab conversion
        │   ├── types/                  # migrated from Stage 1 types/
        │   ├── utils/                  # pure TS (arabic-text, references, formatting, peaks math, svg-arrow-geometry, waveform-cache)
        │   └── components/             # shared UI primitives
        │       ├── Button.svelte
        │       ├── SearchableSelect.svelte
        │       ├── SpeedControl.svelte
        │       ├── AccordionPanel.svelte
        │       ├── ValidationBadge.svelte
        │       └── WaveformCanvas.svelte
        │
        ├── tabs/
        │   ├── audio/
        │   │   ├── AudioTab.svelte
        │   │   └── AudioPlayer.svelte
        │   ├── timestamps/
        │   │   ├── TimestampsTab.svelte
        │   │   ├── UnifiedDisplay.svelte
        │   │   ├── AnimationDisplay.svelte
        │   │   ├── TimestampsWaveform.svelte
        │   │   └── TimestampsValidationPanel.svelte
        │   └── segments/
        │       ├── SegmentsTab.svelte
        │       ├── SegmentRow.svelte
        │       ├── SegmentsList.svelte
        │       ├── FiltersBar.svelte
        │       ├── FilterCondition.svelte
        │       ├── Navigation.svelte
        │       ├── SegmentsAudioControls.svelte
        │       ├── SegmentWaveformCanvas.svelte
        │       ├── EditOverlay.svelte
        │       ├── edit/
        │       │   ├── TrimPanel.svelte
        │       │   ├── SplitPanel.svelte
        │       │   ├── MergePanel.svelte
        │       │   ├── DeletePanel.svelte
        │       │   └── ReferenceEditor.svelte
        │       ├── validation/
        │       │   ├── ValidationPanel.svelte
        │       │   └── ErrorCard.svelte    # single component, category-prop branches
        │       ├── stats/
        │       │   ├── StatsPanel.svelte
        │       │   ├── StatsChart.svelte
        │       │   └── ChartFullscreen.svelte
        │       ├── save/
        │       │   ├── SavePreview.svelte
        │       │   └── SaveConfirm.svelte
        │       └── history/
        │           ├── HistoryPanel.svelte
        │           ├── HistoryFilters.svelte
        │           ├── HistoryBatch.svelte
        │           ├── HistoryOp.svelte
        │           ├── SplitChainRow.svelte
        │           └── HistoryArrows.svelte    # uses svg-arrow-geometry.ts helper
        │
        └── styles/
            └── base.css                # resets, fonts, :root vars, scrollbars
```

**Estimated component count**: ~38 `.svelte` files. ~15 pure `.ts` files in `lib/utils/`, `lib/types/`, `lib/stores/`.

---

## 6. Waves (execution plan)

### 6.0 Wave ordering — Hybrid (post 3-model review revision)

**Order**: `Wave 0.5 → Wave 1 → Wave 2 → Wave 3 → Wave 4 → [stop-point 1] → Wave 5 → 6 → 7 → 8 → 9 → [stop-point 2] → Wave 10 → Wave 11`

Draft v2 picked Option B (Svelte-first). Opus review challenged: Wave 2 is non-reversible (Docker distribution gate), orthogonal to Svelte, and mechanical; running it *first* banks distribution-readiness before any frontend churn and removes the context-switch cost of interleaving Python/Docker work inside a Svelte stream. Sonnet review confirmed no dependency blockers either way. Flipped.

**Wave 0.5** (NEW, added per Opus review): focused Opus exploration of `segments/history/rendering.ts` — the 695-LOC file that timed out during initial exploration. Produces a function-by-function breakdown, the SVG-arrow geometry algorithm, DOM-measurement dependencies, and a Wave 10 sizing confirmation. Cheap insurance against mid-Wave-10 sizing surprises. One agent, Opus, read-only, ~1 hour.

### 6.1 Agent allocation

**One implementation agent per wave.** Sub-waves (max 2, absolute max 3) only if a wave is so complex a single agent run risks timeout or coherence loss. Sub-waves run sequentially; each gets its own agent but they share handoff state via the wave's handoff doc.

**Reviewers at wave boundaries**, not per-phase:
- **Sonnet always** — pattern-level review + manual-smoke checklist verification.
- **Opus for heavy waves** — Waves 1 (if cache.py migration gets non-trivial), 4 (Arabic rendering), 5 (store design foundation), 7 (trim+split drag UX), 8 (validation accordion + 11-category conditional rendering), 10 (history, hardest).
- **Haiku for mechanical waves** — Waves 2 (file-exists / dockerfile syntax), 3 (component count), 11 (delete verification).

Escalation: if a wave review surfaces unresolvable issues, fire a second Opus reviewer or pause for user redirect.

### 6.2 Wave summaries (in Hybrid execution order)

| # | Wave | Scope | Sub-waves | Reviewers | Smoke-critical flows |
|---|------|-------|-----------|-----------|----------------------|
| pre | 0.5 | Focused exploration of `history/rendering.ts` (de-risk Wave 10 sizing) | 1 (read-only) | Opus self-review | n/a — read-only |
| 1 | 1 | Prework: B02, timestamps registry, ESLint cycles verified, cache.py absorbs 2 globals | 1 | Sonnet + Opus | Timestamps tab loads; segments delete still saves correctly |
| 2 | 2 | Backend + Docker + config + `save_seg_data` extract-method | up to 2 (2a: config+docker+vendor, 2b: app cleanup+routes+save_seg_data+magic-numbers) | Sonnet + Opus (Wave 2b for save_seg_data diff) + Haiku (file-exists) | `docker build && docker compose up` reaches localhost:5000; existing Flask routes unchanged; save+undo flows unchanged |
| 3 | 3 | Svelte foundations: install, App.svelte, shared components, CSS migration map, `shared/` migration | 1 | Sonnet + Opus + Haiku | Tab switching works; dropdowns replaced cleanly |
| 4 | 4 | Timestamps tab: stores + 5 components | up to 2 (4a: stores+shell+UnifiedDisplay, 4b: animation+waveform+validation) | Sonnet + Opus | Analysis + Animation views, playback, keyboard shortcuts |
| — | **STOP-POINT 1** | User review after Timestamps Svelte conversion | | | |
| 5 | 5 | Segments shell + filters + rendering + Navigation; pre-wave store-binding matrix | 1 | Sonnet + Opus | Filter bar works; segment list renders; row clicks jump |
| 6 | 6 | Segments playback + waveform | 1 | Sonnet | Play/pause/next-seg; waveform draws; IntersectionObserver fires |
| 7 | 7 | Segments edit modes | 2 (7a: edit store+overlay+trim+split, 7b: merge+delete+reference) | Sonnet + Opus | Each of 5 modes end-to-end; undo of pending op |
| 8 | 8 | Segments validation + stats | 1 | Sonnet + Opus | All 11 categories render; auto-fix; ignore; stats panel; fullscreen chart |
| 9 | 9 | Segments save + undo | 1 | Sonnet | Save preview → confirm → post-save refresh; batch undo; op undo |
| — | **STOP-POINT 2** | User review + (if needed) re-confirm Wave 0.5 findings before Wave 10 | | | |
| 10 | 10 | Segments history | 2 (10a: store+components except arrows, 10b: arrows) | Sonnet + Opus | Batches render; diffs show; arrows draw; filters+sort; chain undo |
| 11 | 11 | Cleanup + audio tab conversion + retro | 1 | Sonnet + Haiku | Full tab smoke; no obsolete files remain; CSS fully ported; audio tab works |

Total: 11 waves + 1 pre-wave exploration, ~15 agent invocations (including sub-waves), ~22 reviewer invocations. Compared to v1 draft's 56 phases × per-phase agents: ~80% fewer agent calls.

### 6.3 Per-wave handoff doc

Each wave produces `.refactor/stage2-wave-N-handoff.md` following the Stage-1 convention. Content (revised per Sonnet review to match Stage-1 shape):
- **Known-good commit SHA** for the wave (anchors rebasability).
- **Scope delivered** (the "items" from §4 per wave, with verification evidence).
- **Scope deferred** (anything that slipped from the wave's nominal scope and where it goes).
- **Deviations from plan** (anything that diverged from §4/§5/§6.2; reconcile against the plan).
- **Verification results** (build gates + spot checks + smoke checklist).
- **Bug-log delta** (rows added to `stage2-bugs.md`).
- **Review findings + disposition** (per reviewer model, with action taken).
- **Surprises / lessons** (free-form for downstream-relevance).
- **Handoff to next wave**: prerequisites the next agent must respect, must-not-break invariants surfaced, tasks queued, open questions/decisions for the orchestrator.
- **Suggested pre-flight additions** for future waves (the script in §7 grows as agents propose checks).
- **Time + token budget consumed** (orchestrator logs to `stage2-orchestration-log.md` immediately).

### 6.4 Wave rollback discipline

Per Opus review: every wave produces a single, squash-merge-able commit cluster on `worktree-refactor+inspector-modularize`. Agents commit per logical unit within a wave (matching Stage-1 commit granularity), but the orchestrator preserves `git rebase -i` viability across the wave so a single-wave rollback is `git reset --hard <commit-before-wave-N>` followed by re-doing only later waves that depended on the rolled-back wave.

Cross-wave dependencies that prevent clean rollback are tracked in the per-wave handoff's "Handoff to next wave" section. If Wave N is rolled back, the orchestrator inspects all subsequent handoffs' "prerequisites" lists to identify which waves must also revert.

### 6.5 Orchestrator discretion

Per refactor-skill guidance, the orchestrator may adjust downstream wave sizing or reviewer allocation based on actual wave metrics. Specifically:
- If a wave's agent consumes > 200k output tokens or > 30 min wall-clock, split subsequent large waves.
- If reviewers surface > 3 genuine issues in one wave, escalate next wave's reviewer tier.
- If a wave lands clean with minimal review findings, downgrade subsequent similar waves' reviewer tier.

This is the mechanism that keeps agent allocation proportional to actual complexity rather than the planning-time estimate.

---

## 7. Pre-flight checks (run at every wave boundary)

Stored as `.refactor/stage2-checks.sh`; agents can append:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd inspector/frontend
npm run typecheck      # tsc --noEmit
npm run lint           # ESLint (import/no-cycle=error enforced)
npm run build          # Vite production build

cd ..
# Catch `global X` keyword usage outside cache.py
grep -rn "^\s*global\s" services/ | grep -v "^\s*#" | (! grep -q ".") && echo "ok: no global keyword outside cache.py" || { echo "FAIL: global keyword leak"; exit 1; }
# Catch the two specific module-level dict cache variables that DON'T use `global` keyword (Sonnet review fix)
grep -rln "_URL_AUDIO_META\|^\s*_phonemizer\s*=" services/ | grep -v "cache.py" | (! grep -q ".") && echo "ok: no orphan global cache vars" || { echo "FAIL: _URL_AUDIO_META or _phonemizer outside cache.py"; exit 1; }
grep -rn "// NOTE: circular dependency" frontend/src/ | (! grep -q ".") && echo "ok: no cycle NOTEs" || { echo "FAIL: cycle comments remain"; exit 1; }

# After Wave 2: Docker smoke
# docker build -t inspector:dev . && docker run --rm -v $(pwd)/data:/data -p 5000:5000 inspector:dev &
# sleep 3 && curl -s -f http://localhost:5000/api/seg/config > /dev/null && echo "ok: docker smoke" || echo "FAIL: docker smoke"
```

---

## 8. Shared documents

| Document | Purpose | Seed content |
|---|---|---|
| `.refactor/stage2-bugs.md` | Bug log | **OPEN seeded rows (4)**: B01, B02, B04, B05 from `stage1-bugs.md`. **No drift rows** (the 7 API drift cases identified during exploration are all CLOSED in `stage1-bugs.md` Section 3 — referenced in §12 below for context, not re-seeded as OPEN — Sonnet review fix). |
| `.refactor/stage2-decisions.md` | Architectural decisions when a fork surfaces mid-wave | **Plan-time decisions (15)** from §10 of this plan, plus the wave-ordering decision from §6.0 and the Wave 2b `save_seg_data` extract-method decision. |
| `.refactor/stage2-orchestration-log.md` | Every agent invocation: model, tokens, duration, wave | Empty at start; orchestrator appends after every agent call. |
| `.refactor/stage2-css-migration-map.md` | CSS selectors with global / structural dependencies, mapped to the wave that rewrites their trigger | Created in pre-Wave 3 artifact step. |
| `.refactor/stage2-store-bindings.md` | Component ↔ store subscription matrix | Created in pre-Wave 5 artifact step. |

**Seeding gate**: `stage2-bugs.md`, `stage2-decisions.md`, and `stage2-orchestration-log.md` are seeded by the orchestrator immediately after final plan approval and before Wave 0.5 starts.

---

## 9. Stop-points

**Declared**:
1. End of Wave 4 (under Hybrid ordering — user reviews Timestamps tab Svelte conversion + Docker artifacts from Wave 2; asks for redirects before Segments work begins in Wave 5).
2. End of Wave 9 (before Wave 10 — history rewrite). Pre-Wave-10 also revisits the Wave 0.5 exploration findings to confirm Wave 10 sub-wave sizing.

**Systemic**:
- Context window ≥ 75%.
- 3-model review disagreement that can't be resolved.
- Plan deviation (wave takes > 1.5× planned effort).
- New OPEN bug with priority ≥ medium-high that isn't fixable in the same wave.
- Pre-merge: pause before any final PR / squash-merge action.

---

## 10. Resolved decisions

All v1 §10 open questions now resolved:

| Question | Decision | Rationale |
|---|---|---|
| Wave ordering | **Hybrid** (Wave 1 → 2 → 3 → 4 → stop → 5-11) | Flipped from v2's Option B per Opus review; backend-first reduces distribution risk |
| Pydantic | **Skip** | User confirmed |
| `validators/` integration | **Vendor** | User confirmed |
| `CACHE_DIR` placement | **Under `DATA_DIR`** | User accepted after explanation |
| `requirements-dev.txt` | **Separate file** | User confirmed |
| Audio tab warm-up | **Skip warm-up; convert in Wave 11 cleanup** | User declined warm-up; Sonnet review caught the orphan in §5 |
| Vitest + testing-library | **Skip (testing out of scope)** | User confirmed all testing deferred |
| God-function decomposition | **Skip 2 of 3** (`validate_reciter_segments`, `apply_reverse_op` stay); **`save_seg_data` extract-method in Wave 2b** | Per Opus review: `save_seg_data` decomposes safely as pure extract-method |
| Agent-per-wave vs per-phase | **Per-wave** (max 3 sub-waves) | User pushback on over-allocation |
| State-object-pattern (CLAUDE.md principle) | **Deprecated for frontend** | Superseded by stores-per-concern; CLAUDE.md updated in Wave 11 |
| Store granularity | **Provisional through Wave 9; locked at Wave 11** | Per Opus review: don't over-commit upfront |
| `waveform-cache.ts` location | **`lib/utils/`, not `lib/stores/`** | It's a non-reactive Map; calling it a store contradicts itself |

---

## 11. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| No testing safety net + 10+ waves of Svelte changes | Certain | Medium | Manual-smoke checklists per wave (per-tab). Reviewers scrutinize diff + verify flows. If regressions spike (≥2 per wave for 2 waves), revisit Playwright at next stop-point. |
| `validators/` vendor clobbers on upstream changes | Medium | Low-Medium | Record source SHA in `stage2-decisions.md`. Add `make update-validators` or periodic rebase reminder. |
| SVG-arrow geometry (Wave 10) has DOM-measurement dependencies that don't cleanly separate | Medium | Medium | Pre-Wave-10 focused exploration characterizes this before Phase 10.1 starts. If separation is infeasible, drop in `leader-line` as fallback. |
| Backend god-functions carry latent bugs we don't touch | Low | Low | Out of scope; Stage-1 exploration didn't surface any new issues. |
| ESLint `import/no-cycle` (already `error` in committed config) catches cycles not visible in exploration once timestamps registry lands | Medium | Low | Wave 1 budgets ~1h for additional fixes if cycles surface beyond the 5 known timestamps NOTEs. |
| Single-agent wave scope overflow (timeout / coherence loss) | Medium | Medium | Sub-wave split (already planned for Waves 4, 7, 10). Orchestrator can split further per §6.4. |
| Hybrid ordering puts Timestamps Svelte conversion before user has seen any Svelte conversion at all | Low | Low | Stop-point 1 after Wave 4 lets user redirect if the Svelte direction feels wrong. Audio tab in Wave 11 is a small validation that the pattern carried through. |
| Store-design choices (per-concern split) don't match actual component binding patterns once components land | Medium | Low-Medium | Stores are tentative at Wave 3; agents have latitude to refactor store shape through Wave 9. Lock stores only at Wave 11 cleanup. |
| `debug=False` default breaks existing local dev UX (auto-reload) | Certain | Low | `FLASK_ENV=development` branch preserves current dev behavior. Document in README. |
| Wave 2 magic-number sweep introduces behavior drift if a literal is actually load-bearing | Low | Medium | Each extraction is a separate commit; per-commit smoke. |

---

## 12. Stage-1 follow-through checklist

- [ ] B01 (filter-saved-view leak) — Wave 5 (filters store reactive restoration).
- [ ] B02 (segData/segAllData chapter-index desync) — Wave 1.
- [ ] B04 (waveform peaks orphaned after audio-proxy URL rewrite) — Wave 6 (waveform-cache store invalidation on URL change).
- [ ] B05 (split chain UID lost on undo) — Wave 9 (undo action restores related state).
- [ ] 7 API drift rows — Wave 2 (types/api.ts cleanup) OR per-wave as consumers are touched.
- [ ] `as any` in `segments/stats.ts:196` — likely persists into Wave 8.4 (Chart.js annotation plugin types still unresolved upstream); acceptable.

---

**END OF PLAN v2.**

Ready for: 3-model plan review (Opus + Sonnet + Haiku), then final user approval, then Wave 1 implementation kickoff.
