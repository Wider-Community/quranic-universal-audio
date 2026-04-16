# Stage 3 — Refactor Plan

**Status**: DRAFT — pending 3-model review.
**Branch**: `inspector-refactor` (worktree `refactor+inspector-modularize`).
**Interview Summary**: `.refactor/stage3-interview.md`.
**Seed doc**: `.refactor/stage3-draft.md`.

---

## §1 Invariants & Success Criteria

### MUST stay true
- **Behavior**: every tab loads, dropdowns populate, segment edit (trim/split/merge/delete/ref-edit/auto-fix/ignore) works, save preview works, undo batch/op/chain works, timestamps waveform + phoneme animation render, audio playback works in all three tabs, validation accordions render every category, stats charts render, history panel loads + diffs render + arrows draw.
- **API**: every `/api/*` endpoint returns the same JSON shape. No route signatures change.
- **Typing**: `strict: true`, `noUncheckedIndexedAccess: true`, `allowJs: false`. Zero `@ts-nocheck`, zero `@ts-ignore` added.
- **Build gates**: `cd inspector/frontend && npm run build` passes clean; `npm run lint` passes; `python3 -c "from inspector.app import create_app; create_app()"` succeeds.
- **Cache invariants**: `services/cache.py` remains the single owner of all cache state. No `global` for caches outside `cache.py`. `invalidate_seg_caches(reciter)` still fully clears `_SEG_RECITERS_CACHE` (not `.pop(reciter)`).
- **Comments**: remaining code comments explain WHY not WHAT. No references to wave numbers, stage numbers, S2-D*, "refactored in", "bridge for", "previously lived", "moved from ... Wave N", or dated process-status markers.
- **Prod bundle**: does not ship `.map` sourcemaps.
- **Historical context**: `inspector/CLAUDE.md` keeps stage/wave terminology ONLY where it describes an existing-state invariant. `.refactor/*.md` workflow artifacts untouched.

### MAY change
- Any file path under `inspector/frontend/src/{segments,shared,styles,types}/`.
- Any comment that matches the refactor-noise patterns in `MUST > Comments`.
- Internal structure of `inspector/services/*.py`, `config.py`, `routes/*.py` — route signatures + public service function signatures preserved; helpers may split.
- `inspector/frontend/{vite.config.ts, eslint.config.js, svelte.config.js}`.
- `inspector/CLAUDE.md` obsoleted sections (State object pattern, Registration pattern, file tree, `shared/constants.ts` path).

### IS being intentionally changed
See §2 phase-level IS-changing manifests (each phase declares its own slice).

### Success criteria (testable at Stage 5)
1. `inspector/frontend/src/segments/` does not exist.
2. `inspector/frontend/src/shared/` does not exist.
3. `inspector/frontend/src/types/` does not exist.
4. `inspector/frontend/src/styles/` contains only `base.css`.
5. `grep -rln -E '(Wave [0-9]|Stage [0-9]|S2-[A-Z]|refactored in|bridge for|\(Wave|previously lived|moved from.*Wave|moved in Wave)' inspector/ --include='*.ts' --include='*.svelte' --include='*.py' | grep -v node_modules | grep -v '.refactor/'` returns zero lines. (CLAUDE.md intentionally exempt.)
6. No file in `inspector/frontend/src/` except `src/lib/components/SearchableSelect.svelte` and `src/lib/utils/*` contains `classList.` or `querySelector`/`querySelectorAll` (apart from `document.body.classList` for global loading spinner which lives in `base.css`).
7. `inspector/frontend/vite.config.ts` has conditional sourcemap (dev-only) + `rollupOptions.output.manualChunks` defers Chart.js to Segments tab.
8. `inspector/frontend/eslint.config.js` does NOT ignore `**/*.svelte`; `eslint-plugin-svelte` enabled.
9. `inspector/services/validation.py::validate_reciter_segments` ≤ 100 LOC (orchestrator only). Same for `undo.py::apply_reverse_op` ≤ 30 LOC.
10. `inspector/services/cache.py` ≤ 250 LOC (down from 348).
11. `inspector/frontend/src/tabs/timestamps/TimestampsTab.svelte` ≤ 300 LOC.
12. `inspector/frontend/src/tabs/segments/SegmentsTab.svelte` ≤ 250 LOC (post-bridge-removal).
13. `inspector/frontend/src/tabs/segments/validation/ErrorCard.svelte` ≤ 80 LOC (dispatcher only).
14. `inspector/frontend/src/lib/stores/segments/history.ts` ≤ 150 LOC OR split into 3 files each ≤ 280 LOC.
15. `grep -rn "as unknown as" inspector/frontend/src/` returns ≤ 5 hits, all in `lib/utils/webaudio-peaks.ts` + `lib/utils/stats-chart-draw.ts` (genuine platform escapes).
16. `npm run build` dist size: main JS chunk < 300 KB (Chart.js split off; tightened from initial 400 KB per Stage-3 review W3).
17. `inspector/CLAUDE.md` File Structure section reflects final tree.
18. Post-Ph6: `grep -rn "from ['\"].*segments/" inspector/frontend/src/lib/` returns zero — no bridge imports remain in `lib/`.
19. Post-Ph4: `grep -rn "String(.*) as unknown as number" inspector/frontend/src/` returns zero — B01 Map-key cast fixed via `dirty.ts` store.
20. Post-Ph11 manual smoke: timestamps animation at 60fps under waveform scroll; playback sync remains tight (reactive `class:active` cadence preserved, not reactive-throttled).

### Testing strategy
**Branch**: build-gate + manual smoke, NO new test suite. User explicit (interview Q1 excluded tests). Per-phase verification = build passes + typecheck passes + lint passes + `create_app()` works + S7 final smoke by user.

---

## §2 Phase Breakdown

Eight top-level phases (P0–P7), some with sub-phases. Rough-ordered by dependency-safety.

### P0 — Foundation (tooling + pure utilities + pre-cleanup)

**Scope**: non-behavior changes only. No risk of regression.

- `vite.config.ts`: sourcemap gate (`sourcemap: mode === 'development'`) + `rollupOptions.output.manualChunks` defers `chart.js` + `chartjs-plugin-annotation` into a separate chunk (loaded only when StatsPanel mounts).
- `eslint.config.js`: remove `**/*.svelte` ignore; enable `eslint-plugin-svelte`; delete wave-11 TODO comment at line 8.
- `src/main.ts`: delete Wave-4 ghost comment (line 19) + Wave-11b comment (line 22). Keep structural side-effect import; comment on `import './segments/index'` will be removed when P3 deletes the target file.
- Create `src/lib/components/AudioPlayer.svelte` wrapper per exploration agent's signature: `load(url, atTime?)` method, `element()` accessor, `cycleSpeed()`, event-forwarding + named slots. Not consumed yet.
- Create shared utilities in `src/lib/utils/`:
  - `grouped-reciters.ts` — `buildGroupedReciters(reciters)` (dedup from both shells).
  - `word-boundary.ts` — `wordBoundaryScan(words, currentTime, direction)` (extracted from TimestampsTab keyboard).
  - `ls.ts` — `lsRestore<T>(key, parser)` helper.
- **Pre-cleanup comment strip** on files that SURVIVE the refactor and will NOT be heavily edited in later phases:
  - `inspector/services/*.py` (6 files)
  - `inspector/config.py`
  - `inspector/frontend/src/lib/stores/timestamps/*.ts`
  - `inspector/frontend/src/lib/types/*.ts`
  - `inspector/frontend/src/lib/utils/*.ts` (waveform-cache, waveform-draw, webaudio-peaks, svg-arrow-geometry, stats-chart-draw)
  - `inspector/frontend/eslint.config.js`, `inspector/Dockerfile`
  - Strip PURE-NOISE lines; reword INFORMATIONAL to remove wave/stage terminology; flag AMBIGUOUS for P7 final review.
- `inspector/CLAUDE.md`: fix the 3 identified staleness points (lines 38, 273, 308 — State object pattern + wrong `shared/constants.ts` path — delete MUST-follow framing, correct path). Leave remaining wave/stage terminology for P7.

**Target structure after P0**:
```
src/lib/components/AudioPlayer.svelte   (new)
src/lib/utils/grouped-reciters.ts       (new)
src/lib/utils/word-boundary.ts          (new)
src/lib/utils/ls.ts                     (new)
[all pre-cleanup survivor files: noise-stripped]
```

**IS-changing (P0)**: sourcemap gate, manualChunks, svelte lint enable, ghost comments, new utilities, pre-cleanup survivor files.

**Review allocation (P0)**: Sonnet quality + Haiku coverage (mechanical comment strip across many files).

**Risk**: low. Tooling changes tested via `npm run build` + `npm run dev` smoke. New utilities unused until later phases — no runtime risk.

**Size**: ~15 files new/modified; ~0 LOC net (additions roughly cancel strips); ~30 min agent.

---

### P1 — Python backend

**Scope**: all four `services/*.py` targets + pre-cleanup their comments.

#### P1a — `services/cache.py` factory

- Introduce `_SingletonCache` + `_KeyedCache` generic classes.
- Migrate all non-thread-safe silos (actual count: ~15 — ts-cache keyed + ts-reciters singleton + seg-cache keyed + seg-meta keyed + seg-reciters singleton + seg-verses keyed + url-audio-meta + phonemizer + canonical-phonemes + phoneme-sub-pairs + audio-url + word-counts + audio-sources + qpc + dk + surah-info-lite) to factory instances. Public getter/setter functions remain as thin wrappers — no caller change.
- **Stage-3-review coverage — explicit dispositions for non-pattern accessors**:
  - `get_all_ts_cache` — special accessor (returns full dict). Stays as thin wrapper over `_ts.all()`.
  - `is_peaks_computing(url)` / `discard_peaks_computing(url)` — companions to `add_peaks_computing`. Stay manually coded with their `threading.Lock` siblings.
  - `audio_cache_path(reciter, url)` — path utility, not a cache silo. Stays as-is in `cache.py`.
- Thread-safe silos (peaks, audio-dl) stay manually coded — do not migrate to factory.
- Rewrite `invalidate_seg_caches` using factory `.clear()` + `.pop(reciter)`. **Preserve invariant**: `_seg_reciters.clear()` (not `.pop`) — full reset on invalidation, as documented today.
- Strip PURE-NOISE comments in `cache.py` (done in P0; P1a just eliminates `global` ceremony).

**Target LOC**: `cache.py` ≤ 250.

#### P1b — `services/undo.py` apply_reverse_op split

- Extract 6 branch helpers: `_reverse_trim`, `_reverse_split`, `_reverse_merge`, `_reverse_delete`, `_reverse_ref_edit`, `_reverse_ignore`.
- Extract `_find_and_verify(entries, snap_after, chapter_set) -> tuple[dict, int, dict]` to dedupe the find+verify pattern.
- `apply_reverse_op` becomes ~15-line dispatcher.
- Extract `_write_and_rebuild` into shared `save.py::persist_detailed(reciter, meta, entries) -> str` — and `undo.py` imports it.
- Extract `_parse_history` into `history_query.py::parse_history_file(path) -> list[dict]`.
- **Helpers staying in `undo.py`** (Stage-3-review Sonnet coverage gaps — explicit disposition):
  - `_get_affected_chapters(batch)` — stays; used by both `undo_batch` + `undo_ops`.
  - `_append_revert_record(history_path, …)` — stays; internal to `undo_batch`/`undo_ops`.
  - `_merge_val_summaries(val_map)` — stays; internal helper.
  - `find_segment_by_uid`, `find_entry_for_insert`, `snap_to_segment`, `verify_segment_matches_snapshot` — stay; called from branch helpers via `_find_and_verify`.

**Target LOC**: `undo.py` ≤ 300; `apply_reverse_op` ≤ 30.

#### P1c — `services/validation.py` package split

- Create `services/validation/` package:
  - `__init__.py` — re-exports `is_ignored_for`, `chapter_validation_counts`, `validate_reciter_segments`, `run_validation_log`. Also holds the orchestrator body of `validate_reciter_segments` (≤ 100 LOC after extraction).
  - `_classify.py` — `_classify_segment(seg, ...)` + `_check_boundary_adj`.
  - `_missing.py` — `_build_missing_words`.
  - `_structural.py` — `_check_structural_errors`.
- `chapter_validation_counts` stays in `__init__.py` (public API).
- Both `chapter_validation_counts` and the orchestrator consume `_classify.py._classify_segment` — eliminates per-segment detection duplication.
- Drop dead imports `load_audio_urls`, `dk_text_for_ref` from `validation.py`.
- Update callers: route stays `from inspector.services.validation import validate_reciter_segments`; works via `__init__.py` re-export.

**Target LOC**: `services/validation/__init__.py` ≤ 200; each `_*.py` ≤ 150.

#### P1d — data_loader + save.py housekeeping

- Do NOT split `data_loader.py` (316 LOC — within tolerance per agent finding).
- `save.py`: fold in `persist_detailed` shared helper (paired with P1b).
- S2-D28 `_apply_full_replace` + S2-D29 `_error` discriminant — **defer**. Both work correctly; deferred per agent risk assessment. Note in decision log.
- Post-P1 comment sweep on all touched backend files.

**IS-changing (P1)**: backend factoring as above; cache factory; undo dispatch; validation package split; shared persist helper; shared parse_history.

**Review allocation (P1)**: Sonnet quality + Opus verification (logic preservation in god-func splits).

**Risk**: medium. `apply_reverse_op` 6-branch split has per-op-type edge cases (seg-uid lookup, sort order). Opus verifier confirms each branch's logic preservation. `chapter_validation_counts` and `validate_reciter_segments` converging on `_classify_segment` must preserve the `verse_segments` tuple-shape difference (2-tuple vs 3-tuple) — flagged risk.

**Size**: ~8 files touched; ~800 LOC refactored; ~60 min agent.

**Split trigger**: if agent hits >400 typecheck errors after `_classify_segment` extraction, split into P1c-i (extract helper only, keep both call sites duplicating call) + P1c-ii (converge both to use helper).

---

### P2 — Frontend tab-tree prep (shell splits not dependent on imperative-kill)

**Scope**: three shell splits + AudioPlayer adoption in Timestamps. Safe pre-`src/segments/` deletion.

#### P2a — TimestampsTab → AudioPlayer + 4-way shell split

- Migrate `TimestampsTab.svelte` to use `<AudioPlayer>` (delete `loadAudioAndPlay`, `_pendingOnMeta` — move into `AudioPlayer.load()`).
- Split into 4 subcomponents per agent spec:
  - `TimestampsControls.svelte` — info bar, view toggle, mode toggle, auto toggles (~180 LOC).
  - `TimestampsAudio.svelte` — wraps `<AudioPlayer>` + auto-advance + `tick()` rAF (~180 LOC).
  - `TimestampsKeyboard.svelte` — `<svelte:window on:keydown>` + switch (~140 LOC).
  - `TimestampsShortcutsGuide.svelte` — static markup (~45 LOC).
- `TimestampsTab.svelte` shrinks to ~250 LOC (composition + cascade + reactive CSS vars).
- Consumes `buildGroupedReciters`, `wordBoundaryScan`, `lsRestore` from P0 utilities.

#### P2b — ErrorCard 3-way split

- Create three category-specific subcomponents:
  - `MissingWordsCard.svelte` — missing-words render path + auto-fix handlers (~140 LOC).
  - `MissingVersesCard.svelte` — missing-verses path (~70 LOC).
  - `GenericIssueCard.svelte` — catch-all 9-category path + phoneme tail branch + ignore flow (~170 LOC).
- `ErrorCard.svelte` becomes ~60-LOC dispatcher that forwards `bind:this` to the matching subcomponent.
- Extract `lib/utils/validation-card-inject.ts` — `_injectCard` helper consumed by all three.
- **Imperative calls preserved** (`renderSegCard`, `state.*`, `createOp`, `finalizeOp`, `markDirty`, etc.) — those die in P3; safe to keep during shell split.
- **Keep public 3-method API** (`getIsContextShown`, `showContextForced`, `hideContextForced`) on dispatcher via forwarding.

#### P2c — SegmentsAudioControls → AudioPlayer

- Replace ad-hoc `<audio>` + manual speed select with `<AudioPlayer lsSpeedKey={LS_KEYS.SEG_SPEED}>`.
- Continuous-play + segment-end clamping logic stays in `SegmentsAudioControls.svelte`, consuming AudioPlayer events.
- `bind:audioEl={segAudioEl}` in `SegmentsTab.svelte` continues to work via `$: segAudioEl = _player?.element() ?? null`.
- `seg-speed-select` markup duplication in `SegmentsTab.svelte` (lines 487–499) deletes; speed now inside `<AudioPlayer>`.

**IS-changing (P2)**: TimestampsTab restructure + 4 new subcomponents; ErrorCard restructure + 3 new subcomponents; SegmentsAudioControls audio wiring. `src/segments/` untouched in this phase.

**Review allocation (P2)**: Sonnet quality + Opus verification (logic preservation on audio wiring; Keyboard ref-chain ordering).

**Risk**: medium. AudioPlayer's `load()` replacing `loadAudioAndPlay` choreography (pending-metadata guard, same-src short-circuit). SegmentsAudioControls continuous-play relies on cross-chapter `src` mutation — verify AudioPlayer's same-src handling. ErrorCard dispatcher `bind:this` forwarding must preserve "Show All Context" global toggle.

**Size**: ~12 files touched; ~1500 LOC reorganized; ~90 min agent.

**Split trigger**: if agent touches > 25 files (counting all tab+child edits), split P2a / P2b / P2c into separate agents.

---

### P3 — `src/segments/` elimination (sequential dependency-order sub-waves)

**Scope**: delete all 29 files under `src/segments/` by migrating each to Svelte component, lib/store, lib/util, or deleting dead code. Follows the phase-order hint from the exploration agent's dependency graph.

Per user Q4: per-file classification applied below.

#### P3a — Pure leaves → lib/utils + early type/ops extraction (PROMOTED from P3e per Stage 3 review CRITICAL 1-2)

- `src/segments/constants.ts` → `src/lib/utils/segments/constants.ts` — **explicit extracts**:
  - `EDIT_OP_LABELS`, `ERROR_CAT_LABELS`, `SEG_FILTER_OPS`, `SEG_SPEEDS`, `_ARABIC_DIGITS`, `_MN_RE`, `_STRIP_CHARS`, `_LETTER_RE` move verbatim.
  - `_VAL_SINGLE_INDEX_CATS` — currently a field on `SegmentsState` interface (not a const export). Extract as standalone `const _VAL_SINGLE_INDEX_CATS: readonly string[]` in `lib/utils/segments/constants.ts`; state.ts field dies in P3e.
  - `_SEG_NORMAL_IDS` — currently referenced in save.ts + history/index.ts for sibling-hide pattern. Extract to `lib/utils/segments/constants.ts`; its callers migrate to store-driven `$showingSavePreview` / `$showingHistoryView` in P3c/P3d; **delete at end of P3d** when no consumer remains.
- `src/segments/references.ts` → `src/lib/utils/segments/references.ts`. `_getVwc()` state-reader becomes parameter.
- `src/segments/validation/categories.ts` → `src/lib/utils/segments/classify.ts`. `state._muqattaatVerses` / `_qalqalaLetters` / `_standaloneRefs` / `_standaloneWords` / `_validationCategories` / `_lcDefaultThreshold` / `SHOW_BOUNDARY_PHONEMES` become store reads from a new `src/lib/stores/segments/config.ts` (seeded from `/api/seg/config` in existing `loadSegConfig`).
- `src/segments/waveform/draw.ts` → `src/lib/utils/segments/waveform-draw-seg.ts`.
- `src/segments/history/undo.ts` → `src/lib/utils/segments/undo.ts`. The `btn.disabled = true; btn.textContent = 'Undoing…'` pattern moves into `HistoryBatch/Op/SplitChainRow.svelte` as a local `loading` state prop. **B01 Map-key cast stays in code through Ph3; removed in Ph4 when `dirty.ts` store replaces `state.segDirtyMap`.**
- `src/segments/waveform/types.ts` → **DELETE**; update callers to import types from `src/lib/types/segments-waveform.ts` directly.
- `src/segments/registry.ts` → **DELETE**; Registration pattern dies (functions imported directly).
- `src/segments/filters.ts` → **DELETE** (shim-only; all callers route directly to stores after P3b–P3d).
- `SEG_FILTER_FIELDS` → `src/lib/utils/segments/filter-fields.ts` (**renamed from `lib/stores/` per review W8 — it's a const, not a reactive store**). Extracted to unblock `lib/stores/segments/filters.ts` bridge import.

**PROMOTED from P3e (was in Ph6, now lands in Ph3 per Stage 3 review CRITICAL 1–2)**:
- **Canonical types** → `src/lib/types/segments.ts` (NEW FILE): `SplitChain`, `SplitChainOp`, `HistorySnapshot`, `OpFlatItem`, `DirtyEntry`, `AccordionOpCtx`, `SavedChainsSnapshot`, `SegSavedPreviewState`, `SegAllDataState`, `SegDataState`, `SegActiveFilter`, `SegSavedFilterView`, `TimerHandle`, `RafHandle`, `PreviewLoopMode`, `ClassifyFn`, `CreateOpOptions`, `SegSnapshot`. Callers (`lib/stores/segments/history.ts` line 44 bridge, validation store, filters store, tabs components) update import paths to `../../types/segments` atomically with this phase. **Rationale: `lib/stores/segments/history.ts` currently bridge-imports from `segments/state.ts`; leaving until Ph6 creates 5-phase broken-import window.**
- **`ops.ts` extraction** → `src/lib/utils/segments/ops.ts` (NEW FILE): `createOp`, `snapshotSeg`, `finalizeOp`. **Rationale: Ph4 edit-commit utilities (`trim-commit.ts` etc.) need these; if still in `state.ts`, Ph4's new `dirty.ts` store splits-brain with `state.segOpLog` writes.** `snapshotSeg` imports `classify.ts` directly (not via `_classifyFn` global) — resolves review W9. `state.setClassifyFn` then becomes dead immediately (registration pattern gone).

**Required new store**: `src/lib/stores/segments/config.ts` — holds `TRIM_DIM_ALPHA`, `TRIM_PAD_LEFT`, `TRIM_PAD_RIGHT`, `SHOW_BOUNDARY_PHONEMES`, `_muqattaatVerses`, `_qalqalaLetters`, `_standaloneRefs`, `_standaloneWords`, `_validationCategories`, `_lcDefaultThreshold`, `_accordionContext`. Populated by `loadSegConfig` in `SegmentsTab.svelte`. Pure data holder.

**Callers to update**: `SegmentsTab.svelte` CSS-var reactive block (lines 587–615) reads from `$segConfig` instead of `state.*`. `TrimPanel.svelte`/`SplitPanel.svelte` drop `state.TRIM_PAD_*` in favor of `$segConfig`. `ErrorCard.svelte` reads `$segConfig.SHOW_BOUNDARY_PHONEMES`, `$segConfig._accordionContext`.

#### P3b — Mid-layer (rendering, playback/audio-cache, validation/index, waveform/index)

- `segments/rendering.ts`:
  - `getConfClass` → `lib/utils/segments/conf-class.ts`.
  - `renderSegCard` / `updateSegCard` / `syncAllCardsForSegment` — **DELETE**. Callers (ErrorCard, HistoryOp) already use `<SegmentRow>` Svelte component; the imperative paths retire.
  - `resolveSegFromRow` — **DELETE**; Svelte components pass `seg` as prop.
  - `_getEditCanvas` — **DELETE**; edit canvases owned by Svelte.
- `segments/playback/audio-cache.ts`:
  - `_isCurrentReciterBySurah` → `lib/utils/segments/reciter.ts`.
  - `_formatBytes` → `lib/utils/formatting.ts`.
  - Status/progress/action functions → new `SegmentsCacheBar.svelte` + new `lib/stores/segments/audio-cache.ts` store.
  - `_rewriteAudioUrls` — **DELETE** (no-op body).
- `segments/validation/index.ts`:
  - `refreshValidation` → `lib/utils/segments/validation-refresh.ts`.
  - `_fixupValIndicesFor{Split,Merge,Delete}` + `_forEachValItem` → `lib/utils/segments/validation-fixups.ts`.
  - `invalidateLoadedErrorCards` / `refreshOpenAccordionCards` — **DELETE** (already no-op).
- `segments/waveform/index.ts`:
  - `_ensureWaveformObserver` → `lib/utils/segments/waveform-observer.ts`.
  - Fetch/index/queue functions → `lib/utils/segments/peaks-fetch.ts`.
  - Registration shims → **DELETE**.

**Required extractions**: promote `_deriveOpIssueDelta` from `segments/validation/categories` (already in P3a) to ensure `lib/stores/segments/history.ts` line 45 bridge import resolves.

#### P3c — Edit core + cross-cutting UI

- `segments/edit/common.ts`:
  - `enterEditWithBuffer` / `exitEditMode` → merged into `EditOverlay.svelte` lifecycle (entry on `$editMode` write; teardown on clear).
  - `_playRange` → `lib/utils/segments/play-range.ts` (takes audio + canvas + window as parameters).
  - `registerEditModes` / `registerEditDrawFns` — **DELETE**.
- `segments/edit/trim.ts`:
  - UI (enter/setup/preview/update) → `TrimPanel.svelte`.
  - Canvas draw → `lib/utils/segments/trim-draw.ts`.
  - `confirmTrim` → `lib/utils/segments/trim-commit.ts` (pure; mutates via stores).
- `segments/edit/split.ts`: symmetric split (→ `SplitPanel.svelte` + `split-draw.ts` + `split-commit.ts`).
- `segments/edit/merge.ts`: `MergePanel.svelte` for confirm-UI + `merge-commit.ts` for mutation.
- `segments/edit/delete.ts`: `DeletePanel.svelte` for confirm-UI + `delete-commit.ts` for mutation.
- `segments/edit/reference.ts`: `ReferenceEditor.svelte` for inline input + `reference-commit.ts` (already consumed directly by ErrorCard — proves portability).
- `segments/navigation.ts`:
  - `jumpToSegment` / `jumpToVerse` / `jumpToMissingVerseContext` / `_showBackToResultsBanner` / `_restoreFilterView` → store actions on `lib/stores/segments/navigation.ts`. Scroll side-effects become derived-store + `SegmentRow.svelte` reactive `scrollIntoView` on `$targetSegmentIndex`.
  - `findMissingVerseBoundarySegments` / `_parseVerseFromKey` → `lib/utils/segments/missing-verse-context.ts`.
- `segments/event-delegation.ts` → **DELETE**. Svelte per-row event handlers replace it (on `SegmentRow.svelte`, `EditOverlay.svelte`, `ErrorCard.svelte`, `SegmentWaveformCanvas.svelte` for canvas mousedown).
- `segments/keyboard.ts`:
  - Handler switch → `SegmentsTab.svelte` `onMount` attaches document-level keydown (pattern from TimestampsTab).
  - Registry types → **DELETE**.
- `segments/save.ts`:
  - `buildSavePreviewData` → `lib/utils/segments/save-preview.ts`.
  - `showSavePreview` / `hideSavePreview` / `confirmSaveFromPreview` / `onSegSaveClick` → `SavePreview.svelte` + `lib/stores/segments/save.ts` actions. `_SEG_NORMAL_IDS` sibling-hide becomes a `$showingSavePreview` derived consumed by sibling `<div hidden={$showingSavePreview}>`.
  - `executeSave` → `lib/utils/segments/save-execute.ts`.

**Dirty/op-log migration requirement**: this sub-phase is where `state.segDirtyMap`, `state.segOpLog`, `state._pendingOp`, `createOp`, `snapshotSeg`, `finalizeOp`, `markDirty`, `unmarkDirty`, `isDirty`, `isIndexDirty` move from `state.ts` into a new `src/lib/stores/segments/dirty.ts` store. All edit commits write to the store; SavePreview / SaveExecute read from it. **Fixes the history/undo Map-key bug** — new store's write API takes `number` only; no `String(chapter) as unknown as number` casts.

#### P3d — Audio + data + history migration

- `segments/playback/index.ts`:
  - Playback + continuous-play + animation → `SegmentsAudioControls.svelte` (already owns `<audio>` via AudioPlayer).
  - `startSegAnimation` / `stopSegAnimation` / `drawActivePlayhead` / `updateSegHighlight` / `updateSegPlayStatus` → reactive `$: playingIndex` prop on each `SegmentRow.svelte`; playhead draw inside `SegmentWaveformCanvas.svelte`'s rAF.
  - `_prefetchNextSegAudio` / `_nextDisplayedSeg` → `lib/utils/segments/prefetch.ts`.
- `segments/validation/error-card-audio.ts`:
  - `getValCardAudio` / `stopErrorCardAudio` / `_startValCardAnimation` / `playErrorCardAudio` → `ErrorCard.svelte`'s own `<audio>` + rAF. Single-instance constraint via new `lib/stores/segments/error-audio.ts` store (only one error card plays at a time).
- `segments/data.ts`:
  - Reciter/chapter flow (`loadSegReciters`, `filterAndRenderReciters`, `onSegReciterChange`, `onSegChapterChange`, `clearSegDisplay`) → `SegmentsTab.svelte` reactive `$:` blocks.
  - `getChapterSegments` / `getSegByChapterIndex` / `getAdjacentSegments` / `syncChapterSegsToAll` / `_getChapterSegs` → `lib/stores/segments/chapter.ts` (or new `chapter-lookup.ts` from P5).
  - Registration shims → **DELETE**.
- `segments/history/index.ts`:
  - `showHistoryView` / `hideHistoryView` → `HistoryPanel.svelte` + `lib/stores/segments/history.ts` visibility actions. `_SEG_NORMAL_IDS` sibling-hide → `$showingHistoryView` derived.
  - `renderEditHistoryPanel` → one-line LIB-UTIL; external history button `hidden` → derived from `$historyData`.
  - `registerOnSegReciterChange` → **DELETE**.

#### P3e — Accordion + state.ts finalize + index.ts + directory deletion

- `segments/validation/error-cards.ts` → **DELETE all 6 functions**. `ValidationPanel.svelte` + `ErrorCard.svelte` own the accordion DOM reactively from `$segValidation` — post-split/merge rebuilds happen via store update + Svelte `{#each}` reconciliation automatically.
- `segments/state.ts` FINALIZE (types + ops already moved in P3a; dirty store already created in P3c):
  - `markDirty`/`unmarkDirty`/`isDirty`/`isIndexDirty` + `segDirtyMap`/`segOpLog`/`_pendingOp` already moved to `src/lib/stores/segments/dirty.ts` in P3c.
  - `_findCoveringPeaks` → `src/lib/utils/segments/peaks-cache.ts`.
  - `setClassifyFn` → already dead after P3a (classify.ts imported directly by ops.ts).
  - State singleton + dom singleton + `_UNSET` sentinel + every remaining field → **DELETE per state-field destination table below**.
- `segments/index.ts` → **DELETE**; remove side-effect import from `main.ts`.
- `src/segments/` directory removed entirely.

##### State.ts field destination table (reviewer CRITICAL C1–C3)

Every field on `SegmentsState` + `DomRefs` interfaces. Column "Lands" = destination phase. Column "Target" = final home.

**Live store fields** (already migrated pre-P3e):
| Field | Lands | Target |
|---|---|---|
| `segAllData`, `segData`, `segAllReciters`, `selectedReciter`, `selectedChapter`, `selectedVerse`, `segCurrentIdx`, `segDisplayedSegments`, `segActiveFilters`, `_segSavedFilterView`, `segValidation`, `_segIndexMap`, `segChapterSS` | migrated P3d | `lib/stores/segments/chapter.ts` + `filters.ts` + `validation.ts` + `SegmentsTab.svelte` local refs |
| `segDirtyMap`, `segOpLog`, `_pendingOp`, `_segSavedChains`, `_segSavedPreviewState` | P3c | `lib/stores/segments/dirty.ts` + `save.ts` stores |
| `segEditMode`, `segEditIndex`, `_splitChainUid`, `_splitChainCategory` | P3c | `lib/stores/segments/edit.ts` |
| `_segContinuousPlay`, `_segAutoPlayEnabled`, `_segPlayEndMs`, `_segPrefetchCache` | P3d | `lib/stores/segments/playback.ts` + prefetch utility |
| `_muqattaatVerses`, `_qalqalaLetters`, `_standaloneRefs`, `_standaloneWords`, `_validationCategories`, `_lcDefaultThreshold`, `_accordionContext`, `TRIM_DIM_ALPHA`, `TRIM_PAD_LEFT`, `TRIM_PAD_RIGHT`, `SHOW_BOUNDARY_PHONEMES` | P3a | `lib/stores/segments/config.ts` |
| `_segPeaksByUrl` | P3b | `lib/utils/segments/peaks-cache.ts` (via `_findCoveringPeaks` migration) |
| `_waveformObserver`, `_observerPeaksQueue`, `_observerPeaksTimer`, `_observerPeaksRequested`, `_peaksPollTimer` | P3b | `lib/utils/segments/waveform-observer.ts` + `peaks-fetch.ts` (module-local vars) |
| `_audioCachePollTimer` | P3b | `lib/stores/segments/audio-cache.ts` (module-local) |
| `_segDataStale` | P3d | `lib/stores/segments/history.ts` derived (`$historyDataStale`) |
| `segHistoryData`, `_histFilterOpTypes`, `_histFilterErrCats`, `_histSortMode`, `_allHistoryItems`, `_splitChains`, `_chainedOpIds` | — | **already removed in Wave 11a** (see `state.ts` comment block); the earlier plan-draft's "24 dead fields" line referred to this already-retired set |

**Local-to-Svelte-component fields** (become `let` inside owning component; no store needed):
| Field | Lands | Target component |
|---|---|---|
| `segAnimId`, `_cardRenderRafId`, `_playRangeRAF` | P3c/P3d | rAF handles — local to `SegmentsAudioControls.svelte` + `SegmentWaveformCanvas.svelte` + `EditOverlay.svelte` |
| `_prevHighlightedRow`, `_prevHighlightedIdx`, `_prevPlayheadIdx`, `_currentPlayheadRow` | P3d | replaced by reactive `$: playingIndex` prop — no local equivalent needed |
| `_previewStopHandler`, `_previewLooping`, `_previewJustSeeked` | P3c | local to `play-range.ts` util closure |
| `_segScrubActive` | P3c | `SegmentWaveformCanvas.svelte` local |
| `_activeAudioSource` | P3d | dies; replaced by single-owner audio (only one `<audio>` plays at a time — enforced by `error-audio.ts` store single-instance) |
| `_segFilterDebounceTimer` | P3c | `FiltersBar.svelte` local |
| `valCardAudio`, `valCardPlayingBtn`, `valCardStopTime`, `valCardAnimId`, `valCardAnimSeg` | P3d | local to `ErrorCard.svelte` + `error-audio.ts` singleton |
| `_accordionOpCtx`, `_splitChainWrapper` | P3c | `EditOverlay.svelte` local state + split-commit.ts parameter |

**Registration-pattern fields** (die with pattern):
| Field | Lands | Note |
|---|---|---|
| `_classifyFn`, `_stopSegAnimationFn`, `_fetchChapterPeaksIfNeeded` setter targets | P3a | `setClassifyFn` + related registration functions retire; consumers import directly |

**Dom singletons** (every field on `DomRefs`):
| Field | Lands | Replacement |
|---|---|---|
| `segChapterSelect` | P3d | `$selectedChapter` store |
| `segSaveBtn`, `segPlayBtn`, `segPlayStatus`, `segHistoryBtn` | P3d | reactive `disabled` + text bound from stores |
| every other `dom.*` field (`segAudioEl`, `segList`, `segRangeEnd`, etc.) | P3c/P3d | `bind:this` refs inside Svelte components |

**UNSET sentinel** (`_UNSET = null as unknown as never`) + `mustGet<T>()` helper (`src/shared/dom.ts`) both die in P4 (no remaining consumer after P3e).

**IS-changing (P3)**: elimination of `src/segments/`; all DOM imperative calls for edit/playback/history/validation/waveform removed; `state`/`dom` singletons removed; registration pattern removed; new stores `dirty.ts`, `config.ts`, `audio-cache.ts`, `error-audio.ts`, `filter-fields.ts` created; many new lib/utils/segments/* files.

**Review allocation (P3)**: Sonnet quality + Opus verification + Haiku coverage. Every sub-phase gets all three — highest-risk block.

**Risk**: HIGH. Each sub-phase touches dozens of imports. `clearPerReciterState` (SegmentsTab.svelte:281–338) has implicit ordering dependencies (stop animation → clear edit → clear validation → clear stats → clear history → save preview → peak timers → cache timers → save/play buttons). Whole block rewrites atomically once dirty store + config store + audio-cache store exist.

**Size per sub-phase**:
- P3a: ~10 files touched, ~800 LOC moved; ~45 min.
- P3b: ~8 files, ~900 LOC; ~60 min.
- P3c: ~18 files, ~1800 LOC; ~90 min. **Split trigger likely** — if agent projects > 45 min, split into P3c-i (edit/ subtree) + P3c-ii (navigation + keyboard + event-delegation + save).
- P3d: ~8 files, ~700 LOC; ~50 min.
- P3e: ~10 files (mostly deletions), ~1000 LOC removed net; ~45 min.

**Invariant check per sub-phase**: all MUST invariants (behavior) must hold after each sub-phase. Each commit keeps build + lint green. Between P3a and P3e the `src/segments/` tree shrinks monotonically.

---

### P4 — Legacy dir cleanup + SegmentsTab shell finalize

**Scope**: after `src/segments/` is gone, mop up `src/shared/`, `src/types/`, and finalize SegmentsTab.

- `src/shared/` (3 files) → **DELETE**:
  - `accordion.ts` — callers migrate to `<AccordionPanel>` Svelte primitive.
  - `dom.ts::mustGet<T>()` — dies with `state.ts`.
  - `searchable-select.ts` — legacy imperative duplicate of `SearchableSelect.svelte`; delete after confirming no non-Svelte consumers remain.
- `src/types/api.ts`, `src/types/domain.ts` → **MERGE** into `src/lib/types/`:
  - Move `api.ts` → `src/lib/types/api.ts`.
  - Move `domain.ts` → `src/lib/types/domain.ts`.
  - Update ~18 import sites across `lib/stores/*`, `lib/utils/*`, `lib/components/*`, `lib/types/segments-waveform.ts`.
  - Delete `src/types/` directory.
- `SegmentsTab.svelte` finalize:
  - Extract `SegmentsSelectorBar.svelte` (~90 LOC) and `SegmentsShortcutsGuide.svelte` (~45 LOC).
  - Extract `SegmentsCacheBar.svelte` (~50 LOC) from the `#seg-cache-bar` markup — consumes `$audioCacheStore` from P3b.
  - Delete the `$: state.X = $Y` bridge block (lines 145–153) — all `state` consumers gone.
  - `clearPerReciterState` shrinks from 57 LOC to ~20 (stores self-clear; no `state.*` writes; no `document.getElementById` for buttons gone-to-Svelte).
  - `onChapterChange` loses direct `seg-audio-player.src =` manipulation — reactive from `$segData.audio_url` via `SegmentsAudioControls`.
  - `onChapterSelectChange` simplifies — subscribe to `$selectedChapter` now that `navigation.jumpToSegment` doesn't set `dom.segChapterSelect.value` imperatively.

**IS-changing (P4)**: `src/shared/`, `src/types/` deleted; SegmentsTab shell ≤ 250 LOC; 3 new subcomponents created.

**Review allocation (P4)**: Sonnet + Haiku coverage (large import-path diff from types merge).

**Risk**: medium. Type-merge is mechanical but high-volume (~18 sites). SegmentsTab bridge-block removal must verify every `state.*` reader migrated in P3. Coverage reviewer scans for residual `state.` references.

**Size**: ~25 files touched; ~500 LOC net; ~60 min agent.

---

### P5 — Store splits

**Scope**: `lib/stores/segments/history.ts`, `filters.ts`, `chapter.ts`.

- `history.ts` split (per exploration agent proposal):
  - `history-store.ts` (~100 LOC) — 8 stores + 7 API functions + exported types + SHORT_LABELS. Barrel-re-exports for existing import paths.
  - `history-chains.ts` (~80 LOC) — `buildSplitLineage`, `buildSplitChains`, `BuildChainsResult`.
  - `history-items.ts` (~270 LOC) — all item/display/filter/chain-leaf helpers.
  - Resolve `_deriveOpIssueDelta` bridge by promoting it to `lib/utils/segments/classify.ts` (done in P3a) — then `history-items.ts` imports from lib/utils.
  - Resolve types bridge by importing canonical types from `lib/types/segments.ts` (done in P3e state-split).
- `filters.ts` light split:
  - Keep `filters.ts` at ~210 LOC.
  - `filter-fields.ts` extracted in P3a (already done).
  - Migrate `countSegWords`, `parseSegRef` references to `lib/utils/segments/references.ts` (P3a).
- `chapter.ts` light split (optional — 190 LOC within tolerance):
  - Extract `chapter-lookup.ts` (~110 LOC) holding `ensureChapterIndex`, `getChapterSegments`, `getSegByChapterIndex`, `getAdjacentSegments`, `invalidateChapterIndex`, `syncChapterSegsToAll`, `getCurrentChapterSegs`.
  - `chapter.ts` shrinks to ~80 LOC (stores + derived only).

**IS-changing (P5)**: three store-file restructures; no behavior change.

**Review allocation (P5)**: Sonnet only. Pure mechanical split; no logic changes.

**Risk**: low. All consumers import named symbols; barrel/re-export keeps paths stable.

**Size**: ~10 files; ~1000 LOC reorganized; ~30 min.

---

### P6 — CSS migration (global → scoped)

**Scope**: the 7 global CSS files in `src/styles/` (excluding `base.css`) → scoped `<style>` blocks per Svelte component. Phase-order follows agent's risk-ordered map.

#### P6a — stats.css + filters.css (low-risk, small)

- `stats.css` (151 LOC):
  - Delete `#seg-stats-fullscreen` / `.seg-stats-fs-*` — already duplicated in `ChartFullscreen.svelte`.
  - `.seg-stats-panel`, `.seg-stats-summary`, `.seg-stats-charts` → `StatsPanel.svelte` scoped.
  - `.seg-stats-chart-wrap*`, `.seg-stats-chart-btn*` → `StatsChart.svelte` scoped.
  - `.seg-stats-saved-tip` + `@keyframes seg-stats-fade` → **`base.css`** (dynamically injected into `document.body`).
- `filters.css` (54 LOC):
  - `.seg-filter-bar`, `.seg-filter-header`, `.seg-filter-title`, `.seg-filter-count`, `.seg-filter-status`, `.seg-filter-rows`, `.seg-filter-row` → `FiltersBar.svelte` scoped.
  - `.seg-filter-field`, `.seg-filter-op`, `.seg-filter-value`, `.seg-filter-remove` → `FilterCondition.svelte` scoped.
  - `.seg-back-banner`, `.seg-back-btn` → `Navigation.svelte` scoped.
  - Replace `rowsEl?.querySelectorAll('.seg-filter-value')` with proper bound refs inside `FiltersBar.svelte`.
- Delete `stats.css` + `filters.css` from `src/styles/`; remove from `main.ts` imports.

#### P6b — segments.css (selector bar + list/rows)

- Selector bar + cache bar + autoplay status → `SegmentsTab.svelte` / `SegmentsCacheBar.svelte` / `SegmentsAudioControls.svelte` scoped.
- `.seg-list`, `.seg-silence-gap*` → `SegmentsList.svelte` scoped.
- `.seg-row`, `.seg-row.playing/.dirty/.seg-neighbour/.seg-edit-target`, `.seg-left`, `.seg-text*`, `.seg-tag*`, `.seg-play-col`, `.seg-card-play-btn`, `.seg-card-goto-btn`, `.seg-actions` → `SegmentRow.svelte` scoped.
- `.seg-edit-overlay` → `EditOverlay.svelte` scoped.
- Defer `.seg-edit-inline*` to P6g (blocked by TrimPanel/SplitPanel being fully Svelte — done in P3c, verify).
- `.seg-loading` duplicated small in `SegmentsList.svelte` + `ErrorCard.svelte`.

#### P6c — components.css (SearchableSelect + shortcuts + Button kill extraClass)

- SearchableSelect `.ss-*` rules already duplicated in `SearchableSelect.svelte` — **delete global copies**.
- `.info-bar` → `base.css` (shared by 3 tabs).
- `.shortcuts-guide*` → duplicated into `SegmentsTab.svelte` + `TimestampsTab.svelte` scoped.
- `.audio-controls`, `.ts-speed-label`, `.ts-random-group`, `#audio-player` → `TimestampsTab.svelte` (+ `.audio-controls` copied to `AudioTab.svelte`).
- **Button.svelte extraClass elimination**:
  - Extend `variant` type: `'primary' | 'secondary' | 'danger' | 'cancel' | 'confirm' | 'save' | 'history' | 'nav' | 'preview' | 'small' | 'delete' | 'adjust' | 'split' | 'edit-ref' | 'merge-prev' | 'merge-next'`.
  - Add scoped style rules for each variant inside `Button.svelte`.
  - Delete `extraClass` prop + line-8 "legacy compatibility" comment.
  - Migrate all callers from raw `<button class="btn btn-X">` to `<Button variant="X">`. Any remaining one-off usage keeps raw `<button>`.
- Delete `.btn*` rules from `components.css`.
- Delete `components.css` from `src/styles/` + `main.ts` imports.

#### P6d — validation.css

- **Prerequisite**: ErrorCard cross-component `querySelector('.seg-row')` / `querySelector('.seg-text')` (lines 178/190/207/296/355) replaced with `bind:this` refs or callback-prop API. Done as part of P3e (accordion rebuild becomes reactive; imperative DOM queries retire).
- **Additional DOM query replacements flagged by Stage-3 review Sonnet coverage**:
  - `ErrorCard.svelte:150` — `card.querySelectorAll('canvas[data-needs-waveform]')` — replace with a Svelte `{#each}` over declared canvas refs (bound via `bind:this` array inside the card).
  - `ValidationPanel.svelte:211` — `containerEl.querySelectorAll('.val-ctx-toggle-btn')` — replace with bound array of button refs or iterate reactive state driving the toggles.
  - `ValidationPanel.svelte:231` — `detailsEl?.querySelector('.val-cards-container')` — replace with `bind:this` on the container element.
- `.val-btn*`, `.val-count*`, `.val-section-label`, `.lc-slider*`, `.qalqala-filter-row`, `.val-ctx-all-row` → `ValidationPanel.svelte` scoped. Subset (`.val-btn`, `.val-items`, `.val-error`, `.val-warning`) duplicated into `TimestampsValidationPanel.svelte`.
- `.val-cards-container`, `.val-card-*`, `.val-action-btn*`, `.val-phoneme-tail*` → `ErrorCard.svelte` scoped (or into one of the 3 new card subcomponents).
- `.seg-row-context`, `.seg-row-context .seg-text` → `ErrorCard.svelte`; `seg-text` override via `SegmentRow.svelte`'s `isContext` prop with `class:seg-row-context`.
- `#seg-validation-global`/`#seg-validation` layout rules → `base.css` (adjacent sibling combinator; structural).
- `.seg-validation` accordion shell rules → `base.css` until shared `ValidationAccordion.svelte` component is extracted (out of scope — keep global).
- Delete per-card-owned rules from `validation.css` → keep only genuinely shared (accordion shell); rename surviving file or fold into `base.css`.

#### P6e — history.css (HIGH RISK: cross-component diff overrides)

- **Prerequisite**: Add `mode: 'history' | undefined` prop to `SegmentRow.svelte`. When `mode === 'history'`, apply `class:seg-history-row`; scoped rules inside `SegmentRow.svelte` style the history-mode variant directly. Eliminates need for `:global(.seg-row)` reach-in from `HistoryOp.svelte`.
- `.seg-history-view`, `.seg-history-toolbar`, `.seg-history-title`, `.seg-history-stats*`, `.seg-history-batches`, `.seg-history-empty` → `HistoryPanel.svelte` scoped.
- `.seg-history-filters*`, `.pill-count` → `HistoryFilters.svelte` scoped.
- `.seg-history-batch*`, `.seg-history-undo-btn` → `HistoryBatch.svelte` scoped (shared with `SplitChainRow.svelte` — duplicate subset).
- `.seg-history-op*`, `.seg-history-val-delta*`, `.seg-history-op-undo-btn`, `.seg-history-diff`, `.seg-history-before/.after`, `.seg-history-arrows` → `HistoryOp.svelte` scoped.
- `.seg-history-diff .seg-row/seg-left/seg-text` cross-component rules **deleted** — replaced by `SegmentRow`'s `mode="history"` variant styles.
- `.seg-history-changed` → `SegmentRow.svelte` scoped (already applied via `class:seg-history-changed`).
- `.seg-save-preview-warning`, `.seg-save-preview-toolbar` → `SavePreview.svelte` scoped.
- `.seg-history-split-chain` → `SplitChainRow.svelte` scoped.
- Delete `history.css` + main.ts import.

#### P6f — timestamps.css

- **Prerequisite**: `UnifiedDisplay.svelte` + `AnimationDisplay.svelte` replace `classList.add/remove/toggle('active'|'past'|'reached')` imperative loops with reactive `class:active={isActive}` / `class:past={isPast}` bindings driven by a derived store (`$activeMegaBlock`, `$activeAnimIndex`). `querySelectorAll('.mega-block')`/`'.mega-phoneme'`/`'.mega-letter'`/`'.anim-word'`/`'.anim-char'` all die.
- `.waveform-words-row` → `TimestampsTab.svelte` scoped.
- `.visualization`, `#waveform-canvas`, `.phoneme-labels`, `.phoneme-label*` → `TimestampsWaveform.svelte` scoped.
- `.unified-display`, `.mega-*`, `.crossword-bridge` → `UnifiedDisplay.svelte` scoped.
- `#animation-display`, `.anim-*` → `AnimationDisplay.svelte` scoped.
- `.ts-view-controls`, `.ts-view-toggle`, `.ts-mode-toggle`, `.ts-view-btn`, `.ts-mode-btn`, `.ts-auto-toggles`, `.ts-auto-btn` → `TimestampsTab.svelte` scoped. For `AudioTab.svelte`'s `.ts-view-btn` usage: rename AudioTab's buttons to `.audio-view-btn` to eliminate coupling.
- `body.loading` handling stays: `document.body.classList.add('loading')` in TimestampsTab stays, `.loading` rule stays in `base.css`.
- Delete `timestamps.css` + main.ts import.

#### P6g — segments.css edit-mode (cleanup remainder)

- `.seg-edit-inline*` → split between `TrimPanel.svelte` + `SplitPanel.svelte` scoped.
- Any remaining `.seg-edit-target` variants covered in `SegmentRow.svelte` scoped (via `class:seg-edit-target={$isEditingThis}`).
- Delete remainder of `segments.css`; kill file + main.ts import.

**IS-changing (P6)**: all 7 global CSS files deleted; ~140 rule blocks scoped into owning components; Button.svelte API extended + `extraClass` removed; `UnifiedDisplay` + `AnimationDisplay` reactive migration.

**Review allocation (P6)**: Sonnet + Haiku per sub-phase (mechanical high-volume; coverage ensures every rule migrated). Opus added for P6d (ErrorCard cross-component ref surgery) + P6e (SegmentRow mode variant) + P6f (reactive animation state) — logic-preservation risk.

**Risk**: HIGH at P6d/P6e/P6f (cross-component CSS + reactive state migration). LOW at P6a/P6b/P6c.

**Size**: 7 sub-phases × ~30 min each. Total ~3h 30min across P6.

**Split trigger per sub-phase**: if reactive-state migration in P6f projects > 45 min (UnifiedDisplay/AnimationDisplay both large), split into P6f-i (UnifiedDisplay) + P6f-ii (AnimationDisplay).

---

### P7 — Final cleanup sweep

**Scope**: comment cleanup residue + CLAUDE.md finalize + verification.

- Full sweep of all 72-file refactor-noise list, recheck with the success-criterion grep command. Reduce to zero matches in code files (CLAUDE.md excluded).
- `lib/utils/waveform-draw.ts` — confirm duplicate path eliminated (was shared between `src/segments/waveform/draw.ts` + Svelte `WaveformCanvas`; `segments/waveform/draw.ts` dies in P3a → P6f).
- `lib/components/Button.svelte` — confirm `extraClass` + line-8 comment both gone (done in P6c; verify).
- `inspector/CLAUDE.md` update pass:
  - File Structure: remove `src/{segments,shared,styles,types}/` sections; update to reflect final tree.
  - Architecture > Frontend Layers: remove "hybrid: imperative + Svelte" framing; remove Registration pattern section; remove State object pattern MUST-follow framing (already done in P0 lightly — finalize here).
  - Conventions: correct `localStorage keys` path to `lib/utils/constants.ts`.
  - Segments Editing Operations: update module references (no more `segments/edit/*.ts`; replace with `lib/utils/segments/*-commit.ts` + `tabs/segments/edit/*Panel.svelte`).
  - Segments Validation Categories: update key-module references (no more `segments/validation/*.ts`; replace with `lib/utils/segments/classify.ts` + `lib/utils/segments/validation-*.ts`).
- `inspector/README.md`: leave the 3 TODO holes as-is unless user requests otherwise (not in scope per interview — informational only).
- Final `.refactor/orchestration-log.md` cumulative totals block.

**IS-changing (P7)**: CLAUDE.md final alignment; comment residue eliminated.

**Review allocation (P7)**: Haiku only (mechanical verification) + final Sonnet pass for CLAUDE.md quality.

**Risk**: low.

**Size**: ~10 files; ~30 min.

---

## §3 Phase summary table (CONSOLIDATED — 12 phases)

Sub-phases from §2 merged into 12 implementation phases with mixed model allocation. Sonnet for phases that fit comfortably in 200K context + low-to-medium logic risk. Opus for high-risk / long / logic-dense / state-migration / reactive-migration phases.

| Ph | Name | Rolled-up sub-phases | Impl model | Files | Est LOC churn | Risk | Reviewers | Est. agent time |
|---|---|---|---|---|---|---|---|---|
| Ph1 | Foundation + Python backend | P0 + P1a + P1b + P1c + P1d | **Sonnet** | ~30 | ~-200 net | mixed low-med | S + H + O (validation split) | 105 min |
| Ph2 | Shell splits (pre-bridge) | P2a + P2b + P2c | **Sonnet** | ~12 | -40 | medium | S + O | 100 min |
| Ph3 | segments pure leaves + mid-layer | P3a + P3b | **Sonnet** | ~22 | net 0 (moves) | medium | S + O + H | 105 min |
| Ph4 | segments edit + cross-cutting UI | P3c | **Opus** | ~18 | net 0 (~1800 moves) | HIGH | S + O + H | 90 min |
| Ph5 | segments audio + data + history | P3d | **Sonnet** | ~10 | net 0 | HIGH scope | S + O + H | 50 min |
| Ph6 | accordion + state.ts split + dir delete | P3e | **Opus** | ~10 | -1000 net | HIGH | S + O + H | 45 min |
| Ph7 | legacy dirs + SegmentsTab finalize + store splits | P4 + P5 | **Sonnet** | ~35 | -600 | medium | S + H | 90 min |
| Ph8 | CSS low-risk batch | P6a + P6b + P6c | **Sonnet** | ~30 | -680 CSS, -50 JSX | low-med | S + H | 95 min |
| Ph9 | CSS validation scoped | P6d | **Opus** | ~6 | -300 CSS | HIGH | S + H + O | 40 min |
| Ph10 | CSS history + SegmentRow mode prop | P6e | **Opus** | ~8 | -350 CSS | HIGH | S + H + O | 45 min |
| Ph11 | CSS timestamps + reactive Unified/Animation + segments edit-mode | P6f + P6g | **Opus** | ~10 | -360 CSS, +100 reactive | HIGH | S + H + O | 70 min |
| Ph12 | final sweep + CLAUDE.md tree | P7 | **Sonnet** | ~10 | -100 comments | low | H + S | 30 min |

**Totals**: 12 phases; ~865 min ≈ 14.4h agent runtime (consolidated from 23 sub-phases / ~1100 min). Expect ~18h with splits.

**Model distribution**: Sonnet ×7 (Ph1, Ph2, Ph3, Ph5, Ph7, Ph8, Ph12). Opus ×5 (Ph4, Ph6, Ph9, Ph10, Ph11). Opus concentrated on highest-risk + state-migration + reactive-migration + cross-component CSS.

**Sub-phase retention**: §2 sub-phases (P0, P1a–d, P2a–c, P3a–e, P4, P5, P6a–g, P7) remain as the internal blueprint. Implementation agents receive the merged phase scope; if an agent projects > 45 min wall-clock OR > 25 files touched mid-way, the sub-phase split triggers apply (per-phase split triggers noted in sidecar).

---

## §4 Import/Export Strategy

- **Barrel indexes**: `src/lib/utils/segments/index.ts` + `src/lib/types/index.ts` barrel exports keep import paths stable where practical. Prefer explicit paths for new code.
- **Zero breakage rule**: after each sub-phase, every existing import resolves. Pre-phase check greps for all imports from deletion-target paths; if any consumer not yet migrated, block dispatch.
- **Type exports**: types move from `src/types/` → `src/lib/types/`; re-exported via `src/lib/types/index.ts` barrel. Bulk rename of import paths in P4 is mechanical.
- **No re-export shim**: do NOT keep `src/segments/` stubs re-exporting from new locations. Atomic delete per sub-phase. Callers update in same commit.

---

## §5 Pre-flight automations (`.refactor/stage3-checks.sh`)

Run before each phase dispatch:

```bash
#!/usr/bin/env bash
set -euo pipefail
cd inspector/frontend

# 1. Build + lint + typecheck
npm run build > /tmp/build.log 2>&1 || { echo "BUILD FAIL"; cat /tmp/build.log; exit 1; }
npm run lint > /tmp/lint.log 2>&1 || { echo "LINT FAIL"; cat /tmp/lint.log; exit 1; }

# 2. Python smoke
cd .. && python3 -c "from inspector.app import create_app; create_app()" || exit 1

# 3. Refactor-noise grep (success-criterion #5)
NOISE=$(grep -rln -E '(Wave [0-9]|Stage [0-9]|S2-[A-Z]|refactored in|bridge for|\(Wave|previously lived|moved from.*Wave|moved in Wave)' inspector/ --include='*.ts' --include='*.svelte' --include='*.py' 2>/dev/null | grep -v node_modules | grep -v '.refactor/' | grep -v 'CLAUDE.md' | wc -l)
echo "Refactor-noise files: $NOISE"

# 4. Imperative DOM call count (success-criterion #6)
DOM=$(grep -rn -E '\.classList\.|\.querySelector|\.querySelectorAll' inspector/frontend/src --include='*.ts' --include='*.svelte' 2>/dev/null | grep -v 'document.body' | grep -v 'lib/components/SearchableSelect' | wc -l)
echo "Imperative DOM calls: $DOM"

# 5. src/segments, src/shared, src/types, src/styles existence
for d in segments shared types; do
  if [ -d "inspector/frontend/src/$d" ]; then echo "LEGACY DIR STILL EXISTS: src/$d"; fi
done
if [ -d "inspector/frontend/src/styles" ]; then
  COUNT=$(ls inspector/frontend/src/styles/*.css 2>/dev/null | wc -l)
  if [ "$COUNT" -gt 1 ]; then echo "src/styles has $COUNT files (expected 1: base.css)"; fi
fi
```

Per-phase handoff may append new checks (e.g., specific store existence, bundle size gate) — growing snippet.

---

## §6 Stop-points

- **Autonomous between phases by default** (per `feedback_autonomous_pipeline` memory).
- **Systemic**:
  - S2 context-window ≥ 75% → fire before dispatching next phase.
  - S3 review disagreement unresolved by orchestrator → fire.
  - S4 scope overreach (implementation agent touched files outside `scope_files`) → fire.
  - S7 pre-merge → after Ph12, hand off for user smoke-test (full tab sweep + save/undo cycle).
- **User-declared phase-gates** (added per Stage-3 review W6, W7):
  - **After Ph6** (state.ts split + dir delete) — user runs smoke on segment edit/save/undo/validation/history flows. `state.ts` removal is the single biggest invariant check; verify post-removal before CSS phases bury any regression.
  - **After Ph11** (reactive UnifiedDisplay/AnimationDisplay migration) — user verifies timestamps tab visual correctness + animation cadence. Reactive `class:active` cadence change is visual; build+lint don't catch jitter.

---

## §7 Review-allocation defaults (12-phase consolidated)

| Phase | Impl | Sonnet review | Haiku coverage | Opus verification |
|---|---|---|---|---|
| Ph1  | sonnet | ✓ | ✓ (comment sweep volume) | ✓ (validation split only) |
| Ph2  | sonnet | ✓ | — | ✓ (audio wiring logic) |
| Ph3  | sonnet | ✓ | ✓ | ✓ |
| Ph4  | opus   | ✓ | ✓ | ✓ (highest risk) |
| Ph5  | sonnet | ✓ | ✓ | ✓ |
| Ph6  | opus   | ✓ | ✓ | ✓ (state.ts split) |
| Ph7  | sonnet | ✓ | ✓ | — |
| Ph8  | sonnet | ✓ | ✓ | — |
| Ph9  | opus   | ✓ | ✓ | ✓ |
| Ph10 | opus   | ✓ | ✓ | ✓ |
| Ph11 | opus   | ✓ | ✓ | ✓ |
| Ph12 | sonnet | ✓ | ✓ | — |

Per `feedback_sonnet_impl_agents` memory: **default Sonnet**. Opus used only for: (a) highest-risk phases where logic preservation across many files is needed (Ph4, Ph6); (b) cross-component CSS + reactive migration (Ph9, Ph10, Ph11). User confirmed mixed allocation at plan-approval time (2026-04-16).

---

## §8 Shared documents

Per interview §2g:
- **`.refactor/stage3-decisions.md`** — decision log. Append-only. Each row: decision ID (D01, D02, …), phase, title, context, chosen option + rationale, one-liner status. Seeded pre-P0 with plan-time decisions. Phases append new decisions.
- **`.refactor/stage3-bugs.md`** — bug log. Pre-seeded with: **B01**: `history/undo.ts:210,212` Map-key cast (SUSPECTED — dies in P3c via new dirty store; confirm no regression at P3c handoff).

---

## §9 Stage 3 review findings applied

All three review agents (Opus architectural / Sonnet coverage / Haiku sanity) completed. Genuine fixes applied in-line above. Summary:

**Opus CRITICAL fixes applied**:
- Canonical types + `ops.ts` extraction PROMOTED from P3e (Ph6) to P3a (Ph3). Eliminates the 5-phase broken-bridge window for `lib/stores/segments/history.ts` type imports.
- state.ts field destination table added to P3e (every field tagged with landing phase).
- `setClassifyFn` dies in P3a (not P3e) — `snapshotSeg` imports `classify.ts` directly rather than via global.

**Opus WARNING fixes applied**:
- `lib/stores/segments/filter-fields.ts` renamed → `lib/utils/segments/filter-fields.ts` (const, not store).
- Added user-declared stops after Ph6 and Ph11.
- Added success criterion #20 (animation cadence manual smoke).
- Added success criterion #18 (no `from.*segments/` bridge imports in `src/lib/` post-Ph6).
- Added success criterion #19 (B01 `String(...) as unknown as number` zero post-Ph4).
- Tightened criterion #16 (main JS chunk < 300 KB from 400).

**Sonnet coverage gaps fixed**:
- P1b explicit dispositions for `_get_affected_chapters`, `_append_revert_record`, `_merge_val_summaries` (stay in undo.py).
- P1a explicit dispositions for `get_all_ts_cache`, `is_peaks_computing`, `discard_peaks_computing`, `audio_cache_path`.
- P3a explicit extraction of `_SEG_NORMAL_IDS` and `_VAL_SINGLE_INDEX_CATS` as standalone consts.
- P6d explicit replacements for `ErrorCard:150` canvas query + `ValidationPanel:211, 231` queries.

**Haiku sanity fixes applied**:
- YAML `success_criteria` glob patterns will be quote-fixed in next edit.
- Plan.md §1 #6 vs YAML: exclusion uses full path `lib/components/SearchableSelect.svelte`.
- Haiku's "orchestration log missing" was a false positive — file exists as `stage3-orchestration-log.md`.

**Items left as-is (not actioned)**:
- Opus W1 (Ph1 scope large): split trigger at 90 min already in sidecar; kept as reactive trigger rather than pre-splitting.
- Opus W2 (save.py S2-D28 visibility): added note in decision log D06 that save.py is touched in Ph1 for persist_detailed.

---

## §10 Open planning decisions (surface pre-dispatch)

1. **P3c scope size** — as written ~18 files + ~1800 LOC + 90 min. Likely split to P3c-i (edit/ subtree) + P3c-ii (nav + keyboard + event-delegation + save). Agent should pre-flight compute and split if projected > 45 min.
2. **Button.svelte variant explosion** — extending to 10+ variants may be too coarse. Alternative: keep `variant` at 5 values + introduce `icon`/`size` modifier props. Deferred to P6c dispatch time.
3. **`:global()` vs mode-prop for history diff CSS** — plan commits to mode-prop (adds `mode: 'history'` prop to `SegmentRow.svelte` in P6e). Alternative: `:global(.seg-history-diff .seg-row)` is simpler if mode-prop cascades get complicated. Review to flag.
4. **P6f reactive migration split** — whether to combine UnifiedDisplay + AnimationDisplay reactive conversion with CSS move, or pre-reactive-migrate separately. Plan currently couples them — risk is scope creep.
5. **SegmentsCacheBar extraction timing** — currently in P4, but its store (`audio-cache.ts`) is created in P3b. Could move extraction up to P3b. Plan leaves in P4 to keep P3 focused on deletion.
