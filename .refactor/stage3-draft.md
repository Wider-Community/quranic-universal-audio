# Stage 3 — Draft (minimal; populate later)

**Status**: DRAFT. Not approved. Planning artifact only.
**Intent**: Finish what Stage 2 didn't — eliminate the imperative core + clean up the tree so it matches idiomatic Svelte conventions.

---

## Known gaps carried forward from Stage 2

Four structural smells the Stage-2 shipped-state retains. Stage 3's primary charter is to close these:

1. **`src/segments/` (~6,358 LOC, 29 `.ts` files)** — imperative helpers (edit/drag logic, event delegation, navigation, save/undo orchestration, waveform IO, keyboard, validation audio, rebuild helpers). Svelte shells in `src/tabs/segments/` delegate into this directory. Target: Svelte-ify or move to `lib/utils/`; delete `src/segments/` entirely.

2. **`src/shared/` (3 files: `accordion.ts`, `dom.ts`, `searchable-select.ts`)** — legacy helpers still consumed by `src/segments/*.ts` imperative code. Target: delete once their callers are gone (Stage 3 item 1 unblocks this).

3. **`src/types/` (2 files: `api.ts`, `domain.ts`) parallel to `src/lib/types/`** — Wave 3 migration mapping had them moving to `lib/types/` but it didn't happen. Target: merge into `src/lib/types/`; delete `src/types/`.

4. **`src/styles/` (8 global CSS files)** — only `base.css` is idiomatic; the other 7 (`components`, `timestamps`, `segments`, `filters`, `validation`, `history`, `stats`) should be scoped `<style>` blocks per component. Blocker: imperative `classList.add/remove` + `querySelector('.X')` calls in `src/segments/*.ts`. Target: ports naturally fall out once Stage 3 item 1 eliminates the imperative callers.

---

## Other candidates (from Stage 3 pre-plan survey — Opus, 2026-04-15)

### High-leverage refactor candidates
- **`tabs/timestamps/TimestampsTab.svelte` (806 LOC)** — largest non-segments file; dropdowns + audio + keyboard + CSS vars + view toggle all in one shell. Splittable into TimestampsControls / TimestampsAudio / TimestampsKeyboard subcomponents.
- **`tabs/segments/SegmentsTab.svelte` (603 LOC)** — tab shell does selectors AND store-bridging the imperative `state.*` (per the bridge NOTEs in `lib/stores/segments/*.ts`). Bridge layer goes away once `src/segments/` does, but the shell itself is split-ready now.
- **`lib/stores/segments/history.ts` (550 LOC)** — single store file holding history data + splitChains + chainedOpIds + filter pills. Largest non-shell store; candidate for `history-data.ts` / `history-chains.ts` split.
- **`tabs/segments/validation/ErrorCard.svelte` (458 LOC)** — single component holds 11 category render branches; per-category subcomponents would shrink it ~70%.
- **Python validators** (`validators/validate_segments.py:1017`, `validate_timestamps.py:911`, `validate_audio.py:852`) — out of `inspector/`, but `validate_reciter` is 265 LOC and `_print_verbose` 235 LOC. Not in Stage 2 plan §4 (which only flagged service-layer god-funcs); decide if they're in scope.

### Tech debt surface
- **5 TODOs** across the whole tree: 3 in `inspector/README.md` (docker, tech-stack, dev sections), 1 in `eslint.config.js:8` (enable svelte lint rules — explicitly Wave-11 deferred), 0 FIXME/HACK/XXX anywhere. Stage 2's NOTE cleanup left **7 `NOTE:` comments** in frontend (mostly Wave-N bridge annotations in `lib/stores/segments/{history,stats,validation}.ts` — informational, not actionable).
- **16 `as unknown as` casts** in frontend (state.ts sentinel pattern + 5 genuine narrowing escapes in `webaudio-peaks`, `stats-chart-draw`, `history/undo.ts`). `history/undo.ts:210,212` casts `Map<number>` keys to/from string — smells like a real bug, worth a look.

### Documentation staleness
- **`inspector/CLAUDE.md` Code Principles**: "State object pattern" still listed as MUST-follow despite S2-D10 superseding it for new code. "localStorage keys defined in `frontend/src/shared/constants.ts`" — `shared/` is a Stage-3 deletion target; keys actually live in `lib/utils/constants.ts` now.
- **`inspector/CLAUDE.md` File Structure**: lists `src/styles/` correctly (8 files) but documents `src/segments/` and `src/shared/` as current architecture without flagging them as legacy/deletion targets.
- **`inspector/README.md`**: 3 user-facing TODO holes (setup/tech-stack/dev). User-modified during Stage 2; review-doc parts are good but devops is empty.
- **`docs/inspector-refactor-notes.md`**: lengthy Stage 1 / Stage 2 narrative; its "5 NOTE: circular dependency" section is stale (those were resolved). Worth a consolidating pass post-Stage-3.

### Testing gap (now viable)
- **Zero test files** anywhere (no `*.test.ts`, `*.spec.ts`, `test_*.py`, no `vitest.config`, no `pytest.ini`). Stage-2 isolated stores in `lib/stores/segments/*.ts` (10 files, pure writables/derived) — these are the lowest-friction Vitest entry point. Component testing for `SearchableSelect`, `AccordionPanel`, `WaveformCanvas`, `ValidationBadge` is straightforward props-in/events-out. Backend services (`save.py` extract-method helpers, `validation.py::is_ignored_for`, `utils/references.py`) are pure-function pytest candidates.

### Backend cleanup
- **`services/validation.py:154 validate_reciter_segments`** (393 LOC) and **`services/undo.py:94 apply_reverse_op`** (105 LOC) are the known Stage-2 deferrals — confirmed still untouched. `services/save.py::save_seg_data` was decomposed in Wave 2b (good); the leftover S2-D28 `_apply_full_replace` return-type union and S2-D29 `_error` discriminant are still smells. `services/cache.py` (348 LOC) has 12 cache silos with near-identical getter/setter shapes — a `make_cache(name)` factory could halve it. Routes are thin (max 190 LOC `timestamps.py`); no regressions.

### Bundle / tooling
- **Build output 535 KB JS + 31 KB CSS + 2 MB sourcemap** in one chunk. Chart.js + annotation plugin alone are ~200 KB and only the Segments StatsPanel uses them — dynamic `import('chart.js')` would defer ~40% of the bundle. No `rollupOptions.output.manualChunks` / `build.chunkSizeWarningLimit` configured. tsconfig is still strict (`allowJs:false`, `noUncheckedIndexedAccess:true`) — no relaxations crept in. ESLint ignores `**/*.svelte` (per Wave-11 TODO) — gap means `simple-import-sort` and `import/no-cycle` don't run on Svelte files.

### Other / surprises
- **`segments/state.ts` field liveness**: ~50% live, ~50% bridge-only. State has 60+ fields; spot-checks (`_segPrefetchCache`, `_segContinuousPlay`, `segOpLog`, `_VAL_SINGLE_INDEX_CATS`, `_lcDefaultThreshold`, `valCardAudio`, `_segScrubActive`) yield 53 outside-state.ts references — none are obviously dead, but the `_audioCachePollTimer`, `_peaksPollTimer`, `_observerPeaks*`, error-card audio (`valCard*`) clusters are all imperative-only and disappear with `src/segments/` removal.
- **`SegmentRow.svelte` uses `lib/components/AudioElement.svelte`** but `SegmentsAudioControls.svelte` and `TimestampsTab.svelte` each independently wire audio — `safePlay` + `bind:this` patterns aren't consolidated into one shared `<AudioPlayer>` despite the `AudioElement` primitive. Cross-tab dedup low-hanging fruit.
- **`lib/components/Button.svelte:8`** comment "Optional extra class names to apply (for legacy compatibility)" — leaky abstraction worth revisiting once segments imperative code is gone.
- **`lib/utils/waveform-draw.ts`** still serves both legacy `segments/waveform/draw.ts` AND the Svelte `WaveformCanvas` — drawing duplicated across two paths (matches Stage-2 risk row "two drawing paths" — not yet collapsed).

---

## Out of scope for this draft

Wave ordering, per-wave effort estimates, reviewer allocation, invariants, success criteria, risks — all to be populated during the Stage 3 interview phase when the user is ready to commit.
