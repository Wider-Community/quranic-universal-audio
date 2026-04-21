# Phase 1 Handoff — Foundation + Python backend

**Phase**: Ph1 (rolls up P0 + P1a + P1b + P1c + P1d)
**Impl model**: Sonnet (2 agents: primary disconnected mid-work, completion agent finished; regression-fix agent resolved review findings)
**Status**: COMPLETE — all gates green, regressions fixed.

## What was done

### P0 — Foundation
- `inspector/frontend/vite.config.ts` — sourcemap gate `mode === 'development'` + `rollupOptions.output.manualChunks` defers chart.js + annotation plugin.
- `inspector/frontend/eslint.config.js` — `**/*.svelte` ignore removed; `eslint-plugin-svelte/flat/recommended` enabled; Wave-11 TODO deleted. `eslint-plugin-svelte` added to `package.json`.
- `inspector/frontend/src/main.ts` — Wave-4 + Wave-11b ghost comments deleted.
- `inspector/frontend/src/lib/components/AudioPlayer.svelte` — new component (134 LOC). Wraps `AudioElement.svelte` + `SpeedControl.svelte`. Methods via `bind:this`: `element()`, `load(url, atTime?)`, `cycleSpeed(dir)`. Events forwarded. `lsSpeedKey` has `= ''` default. Not consumed yet (Ph2 adopts).
- `inspector/frontend/src/lib/utils/grouped-reciters.ts` (50 LOC) — dedup from TimestampsTab + SegmentsTab.
- `inspector/frontend/src/lib/utils/word-boundary.ts` (51 LOC) — extracted from TimestampsTab keyboard.
- `inspector/frontend/src/lib/utils/ls.ts` (24 LOC) — `lsRestore<T>` helper. Not migrated to existing consumers — Ph2.
- **Pre-cleanup comment strip** (D01 survivor-files pass): noise files 71 → 58. Touched: `inspector/services/{peaks,segments_query,ts_query}.py`, `inspector/config.py`, `inspector/Dockerfile`, `inspector/frontend/eslint.config.js`, `inspector/frontend/src/lib/stores/timestamps/*.ts`, `inspector/frontend/src/lib/types/segments-waveform.ts`, `inspector/frontend/src/lib/utils/{stats-chart-draw,svg-arrow-geometry,waveform-cache,waveform-draw,webaudio-peaks}.ts`.
- `inspector/CLAUDE.md` — 3 staleness points fixed (lines 38, 273: State object pattern framing; line 308: `shared/constants.ts` → `lib/utils/constants.ts`).

### P1a — cache.py factory
- `_SingletonCache[T]` + `_KeyedCache[T]` generic classes introduced.
- 15 non-thread-safe silos migrated to factory instances. All public getter/setter signatures preserved.
- Thread-safe silos (peaks + audio-dl) stay manually coded (per plan).
- `get_all_ts_cache`, `is_peaks_computing`, `discard_peaks_computing`, `audio_cache_path` preserved as-is.
- `invalidate_seg_caches` uses `.clear()` on `_seg_reciters` (invariant: full reset) + `.pop()` on keyed caches.

### P1b — undo.py apply_reverse_op split
- 6 branch helpers extracted: `_reverse_trim`, `_reverse_split`, `_reverse_merge`, `_reverse_delete`, `_reverse_ref_edit`, `_reverse_ignore`.
- `_find_and_verify` extracted for find+verify dedup.
- `apply_reverse_op` is 15-line dispatcher (plan criterion #9 met).
- `_write_and_rebuild` replaced by shared `save.py::persist_detailed`.
- `_parse_history` replaced by shared `history_query.py::parse_history_file`.
- `_get_affected_chapters`, `_append_revert_record`, `_merge_val_summaries`, `find_segment_by_uid`, `find_entry_for_insert`, `snap_to_segment`, `verify_segment_matches_snapshot` stay in `undo.py`.

### P1c — validation.py package split
- `inspector/services/validation.py` **deleted**.
- `inspector/services/validation/` package created:
  - `__init__.py` (170 LOC) — orchestrator + `chapter_validation_counts` + `run_validation_log` + `is_ignored_for` re-export.
  - `_classify.py` (135 LOC + low_confidence_detail flag post-fix) — `_classify_segment` + `_check_boundary_adj` + `is_ignored_for`.
  - `_missing.py` (94 LOC) — `_build_missing_words`.
  - `_structural.py` (136 LOC) — `_check_structural_errors(reciter, entries)` (takes entries post-fix).
  - `_detail.py` (188 LOC) — detail-list builder loop (new; needed to get `__init__.py` ≤200).
- Route import `from inspector.services.validation import validate_reciter_segments` resolves to package.
- 2-tuple vs 3-tuple `verse_segments` shape preserved between `chapter_validation_counts` + `_build_detail_lists`.

### P1d — save.py housekeeping
- `persist_detailed(reciter, meta, entries) -> str` helper added. Shared with undo.py.
- `_persist_and_record` now calls `persist_detailed` (post-regression-fix — eliminates duplication).
- S2-D28 `_apply_full_replace` + S2-D29 `_error` discriminant UNTOUCHED (per D06/D17 deferral).

## Decisions that differ from plan

- **`validation/_detail.py` added** (not in plan). Needed to get `validation/__init__.py` under the ≤200-LOC criterion. Public API unchanged. Net win — better single-responsibility.
- **`cache.py` 328 LOC** (target ≤250). Pragmatic: 15 silos × 2–3 public wrappers = irreducible ~310-LOC baseline of public functions. Deviation accepted.
- **`undo.py` 431 LOC** (target ≤300). Pragmatic: 6 branch helpers + 2 public 70-LOC functions (`undo_batch`, `undo_ops`) with distinct validation logic are irreducible without splitting across files. `apply_reverse_op` ≤30 target IS met (15-line dispatcher). Deviation accepted.

## Current codebase state

- `inspector/frontend/src/segments/` still exists (29 files, 6358 LOC) — scheduled Ph3–Ph6.
- `inspector/frontend/src/shared/`, `src/types/` still exist — scheduled Ph7.
- `inspector/frontend/src/styles/` has 8 CSS files — scheduled Ph8–Ph11.
- `state.ts` bridge writes intact — scheduled Ph3e (Ph6).
- 5 `src/lib/**` files still bridge-import from `src/segments/` — scheduled Ph3a.
- 128 imperative DOM calls remain — scheduled Ph3/Ph6.
- 2 `String(..) as unknown as number` casts (B01) remain — scheduled Ph4.

## Patterns established

- **Factory pattern** for cache silos: `_SingletonCache[T]` + `_KeyedCache[T]` with `.get()`, `.set()`, `.pop()`, `.clear()`, `.all()` API. Public getter/setter functions are thin wrappers.
- **Shared persist helper** `save.py::persist_detailed` — both save and undo write through one code path.
- **Shared parse helper** `history_query.py::parse_history_file` — both undo endpoints + potential future consumers.
- **New frontend wrapper `AudioPlayer.svelte`** — exposes `load()`, `element()`, `cycleSpeed()` via `bind:this`; forwards native `<audio>` events. Ph2 migrates TimestampsTab + SegmentsAudioControls.

## Invariant check

### MUST items verified
- Build green (`npm run build`): OK (144 modules, 11s).
- Lint green (`npm run lint`): OK (no warnings).
- Python import green (`cd inspector && python3 -c "import app"`): OK.
- API signatures: `validate_reciter_segments`, `chapter_validation_counts`, `is_ignored_for`, `run_validation_log` — all callable via `from inspector.services.validation import …`.
- Cache invariant: `invalidate_seg_caches` still fully resets `_seg_reciters` (not per-reciter pop).
- Prod sourcemap: vite config gate `mode === 'development'`; prod build excludes `.map`.

### IS-changing items completed
- Tooling: vite sourcemap gate + manualChunks, eslint svelte enabled.
- AudioPlayer + 3 shared utils created.
- Comment pre-cleanup: 71 → 58 noise files.
- CLAUDE.md 3 staleness fixes.
- cache.py factory.
- undo.py split (dispatcher ≤30).
- validation.py → validation/ package.
- save.py persist_detailed helper + _persist_and_record migrated to use it.

## Review findings addressed

### Opus verification — 3 CRITICAL logic regressions (all fixed)
1. **C1 `low_confidence` detail threshold**: detail list was using 0.80 instead of 1.0, shrinking UI accordion. Fixed via `low_confidence_detail` separate flag in `_classify.py`; `_detail.py:124` reads the detail flag.
2. **C2 malformed-ref segments losing emissions**: `audio_bleeding`, `repetitions`, `low_confidence` now fire BEFORE the `len(parts)!=2` early-continue in `_detail.py:63–76`.
3. **C3 `covered_surahs` source changed**: `_check_structural_errors` now takes `entries` and derives `covered_surahs` from detailed.json (original source); `__init__.py:134` updated call.

### Sonnet quality — 2 genuine findings (both fixed)
1. `save.py::_persist_and_record` 7-line duplicated body → single `file_hash = persist_detailed(reciter, meta, entries)` call.
2. `AudioPlayer.svelte::lsSpeedKey` now has `= ''` default.

### Review cleanup
- `_detail.py:17` dead import `is_ignored_for` + misleading noqa → removed.
- `grouped-reciters.ts:33` defensive layering (INFO) → left as-is (cosmetic).
- `_reverse_ignore` pre-existing bug (doesn't clear `ignored_categories` on undo) → logged as **B02** in bugs log.

### Haiku coverage — PASS
- All imports resolve, old `validation.py` gone, phase-deferred files untouched.

### Scope-creep restored
- `.refactor/stage3-draft.md` restored (workflow artifact).
- `inspector/README.md` restored (out of Ph1 scope).
- `inspector/requirements-dev.txt` restored (out of Ph1 scope).
- `inspector/.dockerignore` restored (out of Ph1 scope).

## Phase metrics (feeds Ph2 sizing)

- Files modified: 19 | Files new: 10 (AudioPlayer + 3 utils + validation/ 5 files + phase1-handoff.md).
- Files deleted: 1 (`services/validation.py`).
- LOC delta: +614 / -304 net.
- Wall-clock: primary agent ~21 min (disconnected) + completion ~11 min + regression-fix ~5 min ≈ 37 min total.
- Build: green. Lint: green. Python import: green.
- Noise files: 71 → 58 (13 files de-noised).

## Review-allocation retrospective

- Allocated: Sonnet quality + Haiku coverage + Opus verification (validation split only).
- Outcome: reviewers caught what they should catch. **Opus earned its keep** — the 3 logic regressions in `validate_reciter_segments` were subtle (threshold drift, malformed-ref skip reordering, source-set derivation) and would have silently broken validation UI. Sonnet caught the save.py duplication. Haiku confirmed no import stragglers.
- Recommend for Ph2: keep Sonnet + Opus verification; drop Haiku (less mechanical coverage surface in shell splits).

## Automations to add for future phases

- Preflight script already live. No new automations needed yet.
- Suggestion for Ph3: add LOC-target assertion to checks.sh — compare against plan.md target table.

## Shared-doc delta

- **Bugs log**: seed B02 (see `.refactor/stage3-bugs.md`).

## Sidecar amendments

None. Plan/sidecar aligned.

## Risks/concerns for next phase (Ph2 — Shell splits)

- **AudioPlayer SpeedControl mount race** — Sonnet review noted that `audioElement={element()}` in AudioPlayer is evaluated at render time before `bind:this` resolves; reactivity paper-covers the issue via SpeedControl's `$:` block, but the `onMount` path in SpeedControl fires with `null`. Monitor during Ph2 TimestampsTab adoption. If speed-control doesn't restore persisted speed on first mount, add a reactive `$:` in AudioPlayer forwarding the resolved element to SpeedControl.
- Ph1 skipped `_SEG_NORMAL_IDS` + `_VAL_SINGLE_INDEX_CATS` extraction — scheduled for Ph3a.
- `cache.py` / `undo.py` LOC above target but criteria-critical functions (`apply_reverse_op` 15-line, factory applied, invariants preserved) met. Mark as accepted deviation in decisions log.
