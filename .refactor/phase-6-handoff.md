# Phase 6 — Type remaining segments, timestamps, audio, shared; wire shared/animation; scaffold registry + SegCanvas

**Status:** COMPLETE
**Commit:** pending (this commit's SHA)
**Branch:** `worktree-refactor+inspector-modularize`
**Implementation:** Opus agent (rate-limited before reporting — finished closeout + 3-agent review under orchestrator).

## Scope delivered

### 1. tsconfig (no ratchet)

Flags unchanged from Phase 5 — `strict: true`, `noImplicitAny: true`, `strictNullChecks: true`, `allowJs: true`, `noUncheckedIndexedAccess: false`. Phase 7 flips `allowJs: false` + `noUncheckedIndexedAccess: true`.

### 2. 38 files typed (`@ts-nocheck` removed)

**shared/** (5): `constants.ts`, `arabic-text.ts`, `audio.ts`, `surah-info.ts`, `searchable-select.ts`.

**timestamps/** (7): `waveform.ts`, `animation.ts`, `unified-display.ts`, `validation.ts` (B17 preserved verbatim), `keyboard.ts`, `playback.ts`, `index.ts`.

**audio/** (1): `index.ts` (migrated to a `mustGet<T>()` DOM helper that throws on missing ids — was silently-null before).

**segments/** (24):
- Top-level: `index.ts`, `event-delegation.ts`, `keyboard.ts`, `navigation.ts`, `save.ts`, `undo.ts`, `stats.ts` (Chart.js typed via `ChartConfiguration<'bar'>` + `ChartDataset<'bar'>` from `'chart.js'`; `shared/chart.ts` still @ts-nocheck in Phase 7 scope).
- `edit/`: `common.ts`, `trim.ts`, `split.ts`, `merge.ts`, `delete.ts`, `reference.ts`.
- `history/`: `undo.ts`, `filters.ts`, `rendering.ts` (the 631-LOC monster), `index.ts`.
- `waveform/`: `index.ts`, `draw.ts` — both consume `SegCanvas`.
- `playback/`: `index.ts` (wired to `shared/animation.ts` as `_segAnimLoop`), `audio-cache.ts`.
- `validation/error-card-audio.ts` — minor tightening flowing through from edit/history typing.

**main.ts** also touched (import cleanup).

`audio-cache.ts` and `scroll-preload.ts` from the original plan: `audio-cache.ts` actually lives at `segments/playback/audio-cache.ts` (Phase 2 sub-fold) — typed. `scroll-preload.ts` doesn't exist anywhere in the repo; plan reference was stale.

### 3. Two new type-only scaffolding files

- **`inspector/frontend/src/types/registry.ts`** — Registration-pattern signatures: `PlayErrorCardAudioFn`, `StartRefEditFn`, `EnterEditWithBufferFn`, `MergeAdjacentFn`, `DeleteSegmentFn`, `SegEventHandlerRegistry`, `SegEventHandlerName`, `OnSegSaveClickFn`, `HideSavePreviewFn`, `ConfirmSaveFromPreviewFn`, `ExitEditModeFn`, `ConfirmTrimFn`, `ConfirmSplitFn`, `SegKeyboardHandlerRegistry`, `SegKeyboardHandlerName`, `EnterTrimModeFn`, `EnterSplitModeFn`, `DrawWaveformFn`. Imported by `event-delegation.ts`, `keyboard.ts`, `edit/common.ts`, `waveform/index.ts`.
- **`inspector/frontend/src/segments/waveform/types.ts`** — `SegCanvas` extension declaring all ad-hoc canvas fields (`_wfCache`, `_wfCacheKey`, `_trimHL`, `_splitHL`, `_mergeHL`, `_trimWindow`, `_splitData`, `_trimEls`, `_splitEls`, `_trimBaseCache`, `_splitBaseCache`, `_editCleanup`) + highlight descriptor types (`TrimHighlight`, `SplitHighlight`, `MergeHighlight`, `TrimWindow`, `SplitData`, `TrimEls`, `SplitEls`). Imported by 11 modules.

### 4. `shared/animation.ts` wired into both playback loops

- `segments/playback/index.ts` — `_segAnimLoop = createAnimationLoop(...)`; replaces the inline rAF-chained `animateSeg()`. `state.segAnimId` kept synced (1/null sentinel) so external truthiness checks still work. `stopSegAnimation()` calls `_segAnimLoop.stop()`. Self-cancel path returns `false` from the onFrame callback.
- `timestamps/playback.ts` — `_tsAnimLoop = createAnimationLoop(...)`; same pattern. `state.animationId` synced identically.
- `shared/animation.ts` JSDoc updated to reflect "active use" (was "currently unused" from Phase 3).

### 5. Registration pattern — typed, not redesigned

- `registerHandler<K extends SegEventHandlerName>(name: K, fn: NonNullable<SegEventHandlerRegistry[K]>): void` — constrained generic in `event-delegation.ts`.
- `registerKeyboardHandler<K extends SegKeyboardHandlerName>(name, fn)` — same in `keyboard.ts`.
- `registerEditModes({ enterTrim, enterSplit })`, `registerEditDrawFns({ drawTrim, drawSplit })`, `registerWaveformHandlers({...})` — `edit/common.ts` + `waveform/index.ts` use typed function-object parameters.
- `setClassifyFn(fn: ClassifySegCategoriesFn)` — `state.ts`.
- **No runtime redesign.** Same call sites, same timing, just typed.

### 6. SegCanvas adoption

- All `segments/waveform/**` functions accept/return `SegCanvas`.
- All `segments/edit/**` canvas parameters declared `SegCanvas` (previously `HTMLCanvasElement` with inline `as SegCanvas` casts — cleaned up during review).
- `_getEditCanvas()` returns `HTMLCanvasElement | null`; call sites narrow via `as SegCanvas | null` (justified — DOM query returns bare type).
- IntersectionObserver `entry.target as SegCanvas` (justified — DOM APIs return `Element`).

### 7. Chart.js typed

- `segments/stats.ts` imports `ChartConfiguration` from `'chart.js'`; charts declared with `ChartConfiguration<'bar'>`. Two `any` escapes for the chartjs-plugin-annotation object shape — justified with `eslint-disable-next-line @typescript-eslint/no-explicit-any` comments.
- `shared/chart.ts` still carries `@ts-nocheck` (Phase 7 cleanup — the plugin-register call has opaque typings in the library's own .d.ts).

## Scope deferred

- **`shared/chart.ts`** stays `@ts-nocheck` — Phase 7.
- **`allowJs: false`** flip — Phase 7.
- **`noUncheckedIndexedAccess: true`** flip — Phase 7. Will convert ~12 of the 21 `!` assertions into errors (length-guarded array-index reads in `history/rendering.ts` and dict-init-then-access patterns in `audio/index.ts`, `timestamps/animation.ts`). Rewrite as local-variable guards.
- **B17 one-line fix** — `timestamps/validation.ts:60` tooltip still reads `i.ts_ms` / `i.seg_ms` (server emits `side`/`diff_ms`). Preserved verbatim by design; fix is a separate bug-fix commit (not a typing concern).
- **`state._splitChains: Map<string, unknown>`** — typed as `unknown` to dodge a segments/state.ts ↔ history/rendering.ts circular import. Consumer casts `.values() as unknown as IterableIterator<SplitChain>`. Can be tightened in Phase 7 by moving `SplitChain` to a shared types module.
- **`SurahInfo[k: string]: unknown`** index signature — retained from Phase 5. Remove in Phase 7 after consumer audit.
- **`_renderHistoryDisplayItems` union `HistoryDisplayItem[] | OpFlatItem[]`** — only `OpFlatItem[]` branch ever used. Narrow in Phase 7.
- **First-frame animation timing drift** — `createAnimationLoop.start()` defers the first tick by ~16ms; pre-Phase-6 code invoked the frame synchronously before the first rAF. Not a functional regression; noted in case smoke S2/S4 reveals a visible stutter.

## Deviations from plan

| Plan said | Actual | Reason |
|-----------|--------|--------|
| Single Opus implementation agent completes the phase + writes report | Agent hit per-account rate limit mid-work; orchestrator picked up closeout | Phase 6 scope (~38 files) is genuinely large; agent ran ~48 minutes before rate-limiting. Typecheck/build/lint were all green when rate limit hit — the implementation work was complete; only book-keeping (handoff doc, bug log) remained. Orchestrator finished those + 3-agent review. |
| Type `segments/audio-cache.ts` and `segments/scroll-preload.ts` | `playback/audio-cache.ts` typed; `scroll-preload.ts` doesn't exist | Plan file path was stale. Phase 2 sub-foldering moved audio-cache under `playback/`; `scroll-preload.ts` was never part of the actual codebase (pre-dated Phase 2 or never migrated). |
| Pre-existing scaffolding (`types/registry.ts`, `segments/waveform/types.ts`) | Used as-is + extended with 2 post-review signature tightening changes | These files existed uncommitted at phase start — probably from an earlier aborted Phase 6 attempt or user authoring. Quality was high; integrated rather than re-created. |
| `DrawWaveformFn = (canvas: HTMLCanvasElement) => void` in `types/registry.ts` | Tightened to `(canvas: SegCanvas) => void` | Every producer and consumer already used `SegCanvas`; the `HTMLCanvasElement` type was a false-safety hole. Sonnet review flagged; fix removes 2 internal `as SegCanvas` casts. |
| Single-commit phase | Single commit (plan allowed splitting if bug-log rows needed bisect separation; no non-trivial fixes this phase required separate commits) | B17 is a deliberate no-fix; B18/B19/B20 are zero-runtime-diff type widenings inline with the annotations that enabled them. |

## Verification results

### Build gates (final, after 3-agent review + post-review fixes)
- `npm run typecheck` — **PASS** (0 errors under `strict: true`)
- `npm run build` — **PASS** (65 modules, 435.45 kB js / 134.47 kB gzip, 28.43 kB css / 6.05 kB gzip). +1.47 kB vs. Phase 5 — type-only additions + 2 new scaffolding files.
- `npm run lint` — **0 errors, 11 warnings** (was 1 error + 65 warnings at end of Phase 5). Remaining warnings are all unused-import and unused-eslint-disable nits, none behavior-affecting. 8 of them in the Phase-5-typed files; 3 in Phase-6-typed files.

### Flask prod smoke (port 5000 — note: earlier phases used :5055, this one ran :5000 since no separate :5055 instance was up)
8/8 endpoints 200: `/`, `/assets/index-BWBErJve.css`, `/assets/index-Di7Q7L4u.js`, `/fonts/DigitalKhattV2.otf`, `/api/surah-info`, `/api/ts/reciters`, `/api/seg/reciters`, `/api/audio/sources`.

### Strictness isolation
- Files WITHOUT `@ts-nocheck`: **all files under `inspector/frontend/src/` except `shared/chart.ts`** (1 file).
- Files WITH `@ts-nocheck`: **1** (`shared/chart.ts`, Phase 7).

### Budget (across ALL 38+2 newly-typed files combined)
| Metric | Count | Budget |
|---|---|---|
| `any` | **3** justified (2 in `stats.ts` for chartjs-plugin-annotation, 1 in `timestamps/validation.ts` for B17 preservation — all have eslint-disable comments) | ≤25 |
| `@ts-ignore` / `@ts-expect-error` | **0** | ≤15 |
| `!` non-null assertions | **~21** (10 in `history/rendering.ts` array-index after length check; 3 in `state.ts` `Map.get()` after `set`; rest are init-then-access dict patterns) | ≤25 |

Haiku's mechanical grep returned different numbers (`any: 17`, `!: 1`) due to regex limitations; Sonnet's per-file audit numbers are authoritative. Both well under budget.

## Review findings (3-agent gate)

### Haiku coverage: **21/21 PASS**
All mechanical checks passed. Remaining `@ts-nocheck` pragma count: 1 (`shared/chart.ts`). No stray `.js` files. Flask smoke 8/8.

### Sonnet quality: APPROVE-WITH-FIXES (3 genuine fixes applied, 4 nits noted for Phase 7)
- **Genuine #1** — `shared/animation.ts` JSDoc said "Currently unused by production callers" but Phase 6 wired it. FIXED: doc comment updated to reflect active use.
- **Genuine #2** — `DrawWaveformFn = (canvas: HTMLCanvasElement) => void` but every producer/consumer used `SegCanvas`. FIXED: tightened to `SegCanvas`; removed 2 internal `as SegCanvas` casts in `edit/trim.ts` and `edit/split.ts`.
- **Genuine #3** — `state._splitChains.values() as IterableIterator<SplitChain>` cast inconsistency with the rest of the codebase idiom (`as unknown as X`). FIXED: aligned to `as unknown as IterableIterator<SplitChain>` at `history/rendering.ts:163`.
- **Nits for Phase 7** — `unified-display.ts` double-read pattern (will bite `noUncheckedIndexedAccess`); `_renderHistoryDisplayItems` unused union branch; `SegPeaksEntry` / `SegmentPeaks` DRY violation; `stats.ts` error-property cast.

### Opus verification: APPROVE (no blockers)
- **Dim 1 (zero behavior change)**: ~38 files audited. One subtle timing change (first-frame ~16ms deferral from `createAnimationLoop.start()`) — non-functional, flagged for Phase 7 smoke.
- **Dim 2 (animation wiring)**: both files PASS; no rAF stragglers.
- **Dim 3 (registration pattern)**: all signatures match producers/consumers.
- **Dim 4 (SegCanvas)**: all cache-field reads/writes + `_editCleanup` intact.
- **Dim 5 (B17 preservation)**: YES — verbatim.
- **Dim 6 (drift accuracy)**: B18/B19/B20 all confirmed against `services/peaks.py` + `services/audio_proxy.py`. B18 includes one runtime rename flagged: `ObserverPeaksQueueItem.{startMs,endMs}` → `{start_ms,end_ms}`. The runtime objects ALWAYS used snake_case (waveform pushed `{url, start_ms, end_ms}` pre-Phase-6); the old type was drift. Zero observable change.
- **Dim 7 (`catch (e)`)**: 0 unsafe `e.*` accesses across 17 catch blocks.
- **Dim 8 (state-shape sanctity)**: all changes additive or type-refinement — no state field deletions, no runtime key renames.

## Surprises / lessons

- **Rate limits are a real factor for phases this large.** A 38-file phase comfortably fits a single Opus agent invocation in principle but consumed ~48 minutes of Opus quota before book-keeping. Future large phases should either split (6a/6b) OR plan for orchestrator-finished closeout as the normal path.
- **Typed state-shape changes caught real drift that `@ts-nocheck` had been hiding for months.** `ObserverPeaksQueueItem.{startMs,endMs}` was never consumed as camelCase at runtime — the wire shape was always snake_case — but the state-hub type said otherwise. `@ts-nocheck` on waveform/index.ts meant nobody noticed. B18 closes the drift with zero runtime diff.
- **Pre-existing scaffolding saved meaningful time.** `types/registry.ts` + `segments/waveform/types.ts` were uncommitted at phase start and matched what Phase 6 needed almost exactly. Lesson: when the user hints at prior attempts (or leaves artifacts), read before re-creating.
- **`DrawWaveformFn` type-safety hole** (HTMLCanvasElement where SegCanvas is required) only surfaced through quality review, not through typecheck. `strictFunctionTypes` alone isn't enough — the **intent** behind the parameter type (does this function expect ad-hoc fields?) is a domain-knowledge layer beyond what TSC checks. Review agents are valuable specifically here.
- **B17 is the first preserved-verbatim-latent-bug of the refactor.** All prior `B01`/`B02`/`B04`/`B05` stayed OPEN but without type-system interaction. B17 forced a choice (silently "fix" to match server, or preserve with `any` cast) — we deliberately chose preservation + eslint-disable + bug-log row. This keeps type accuracy and behavior preservation both honest.

## Handoff to Phase 7

- **Known-good entry commit**: (this commit's SHA)
- **Prerequisites Phase 7 must not break**:
  - No new `@ts-nocheck` pragmas. The only remaining one is `shared/chart.ts`, and Phase 7 removes that.
  - `shared/animation.ts` is active production code; don't re-delete.
  - `types/registry.ts` + `segments/waveform/types.ts` are the single source of truth for registration signatures + canvas extension shapes. Consumers should import from them, not re-declare.
  - The `state.segAnimId` / `state.animationId` 1/null sentinel pattern is load-bearing for external truthiness checks. Don't refactor into a single boolean without auditing those consumers.
- **Phase 7 scope (per plan §Phase Breakdown)**:
  - Flip `allowJs: false`. Probable 0-error impact (no `.js` files remain under `inspector/frontend/src/`).
  - Flip `noUncheckedIndexedAccess: true`. Expect ~12–15 errors concentrated in `history/rendering.ts` (array-index `[i]!` after length guards), `audio/index.ts`, `timestamps/animation.ts`, `timestamps/index.ts` (dict-init-then-access patterns). Rewrite each as local-variable guard.
  - Remove `@ts-nocheck` from `shared/chart.ts`; address whatever Chart.js plugin-register typings require. If it blows up, narrow escape-hatch with one `// eslint-disable-next-line @typescript-eslint/no-explicit-any` + `any` for the plugin registration call and move on.
  - Update `inspector/CLAUDE.md` frontend section (currently describes `.js` files under `static/js/` — outdated since Phase 1).
  - Remove any leftover `static/` remnants; prune Flask reloader `extra_files` if present.
  - Finalize `.refactor/stage1-bugs.md` — close every row that's closable; add orchestrator summary at top.
  - Fix B17 as a separate bug-fix commit (one-line tooltip rewrite).
  - Non-blocking cleanup from Phase 6 reviews:
    - Narrow `_renderHistoryDisplayItems` param from `HistoryDisplayItem[] | OpFlatItem[]` → `OpFlatItem[]`.
    - Unify `SegPeaksEntry` with `SegmentPeaks` (DRY).
    - Remove `SurahInfo[k: string]: unknown` index signature.
    - Refactor `timestamps/unified-display.ts` double-read pattern to local-variable guards (pre-empts `noUncheckedIndexedAccess` errors).
    - Tighten `state._splitChains: Map<string, unknown>` if circular-import can be broken.
  - Consider: the 11-site double-cast pattern in `segments/validation/index.ts` descriptor list — Sonnet P5 suggested discriminated union if rigor desired. Judgment call.
- **Risks for Phase 7**:
  - `noUncheckedIndexedAccess` cascade in `history/rendering.ts` may be noisy. Budget some rewrite time.
  - `shared/chart.ts` unknowable until you try; have a fallback `// @ts-expect-error — chartjs-plugin-annotation .d.ts signature` ready.
  - First-frame animation timing (Opus noted) — run S2/S4 smoke after Phase 7 lands to confirm no visible stutter at play-start. If observed, add a `runImmediately?: boolean` option to `createAnimationLoop.start()`.
  - `inspector/CLAUDE.md` file is authoritative for AI helpers; update carefully.

Ready for Phase 7.
