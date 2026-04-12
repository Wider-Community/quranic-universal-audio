# Phase 4 — Type state hubs + flip global `noImplicitAny` / `strictNullChecks`

**Status:** COMPLETE
**Commit:** pending
**Branch:** `worktree-refactor+inspector-modularize`
**Implementation:** Opus agent (delegated per refactor skill).

## Scope delivered

### 1. tsconfig strictness ratchet

`inspector/frontend/tsconfig.json`:
- `noImplicitAny`: false → **true**
- `strictNullChecks`: false → **true**
- `strict`: unchanged (stays false — Phase 5 flips it)
- `noUncheckedIndexedAccess`: unchanged (stays false — Phase 7 flips it)

### 2. `inspector/frontend/src/segments/state.ts` typed (489 insertions)

- Declared exported interfaces: `SegmentsState`, `DomRefs`, `SegActiveFilter`, `SegSavedFilterView`, `SegAllDataState`, `DirtyEntry`, `AccordionOpCtx`, `SavedChainsSnapshot`, `SegPeaksRangeEntry`, `PreviewLoopMode`, etc.
- Typed every helper: `setClassifyFn`, `createOp`, `snapshotSeg`, `finalizeOp`, `markDirty`, `unmarkDirty`, `isDirty`, `isIndexDirty`, `_findCoveringPeaks`.
- `@ts-nocheck` removed.
- Field count in `SegmentsState`: ~70, matching the exploration inventory.

### 3. `inspector/frontend/src/timestamps/state.ts` typed (164 insertions)

- Declared `TimestampsState`, `TimestampsDomRefs`, `TsAnimCache`, `TsAnimCacheItem`.
- `@ts-nocheck` removed.
- Post-review fix: `TimestampsDomRefs.ctx` typed as `CanvasRenderingContext2D | null` (not non-null) because `canvas.getContext('2d')` legitimately returns null; pushes the null-check discipline onto `timestamps/waveform.ts` when it's typed in Phase 6.

### 4. API-drift fixes in `inspector/frontend/src/types/domain.ts` (+15 LOC)

Four rows logged in `.refactor/stage1-bugs.md §Section 3`:
- **B09** — `Segment.has_repeated_words?: boolean`, `Segment.phonemes_asr?: string`. Server persists via `services/save.py`; consumed by `services/validation.py` and client `_classifySegCategories` / `snapshotSeg`. Both added.
- **B10** — `Segment.ignored?: boolean`. Legacy pre-`ignored_categories` fallback read by `validation/categories.ts:_isIgnoredFor`. Added with back-compat doc comment.
- **B11** — `PhonemeInterval.geminate_start?`, `PhonemeInterval.geminate_end?`. Emitted by MFA aligner; consumed by `timestamps/playback.ts` + `timestamps/unified-display.ts`. Added as optional booleans.
- **B12** — `SurahInfo` renamed `{en, ar}` → `{name_en, name_ar, num_verses?}`. Server emits the longer names (`services/data_loader.py:267-269`); `shared/surah-info.ts` already reads the correct fields. All four rows marked CLOSED (no runtime diff; type now matches reality).

## Scope deferred

- **Consumer cascade**: removing `@ts-nocheck` from the 43 other source files stays deferred to Phases 5–6 per plan. The global strictness flip only affected the 7 files without `@ts-nocheck`; everything else is transparent.
- **`_splitChains` / `_allHistoryItems` typed as `unknown`** — opaque until `history/**` is typed in Phase 6. Opus verification flagged these as worth tightening proactively; noted but deferred to keep Phase 4 scope tight.
- **`shared/chart.ts` still carries `@ts-nocheck`** — Phase 2 added it blanket; Phase 7 cleanup will remove. Not in Phase 4 scope.
- **B01/B05** (filter saved-view, split-chain UID) did NOT surface as `strictNullChecks` errors because they live in `filters.ts` / `save.ts` / `navigation.ts` — all still `@ts-nocheck`'d. They'll surface in Phase 5.

## Deviations from plan

| Plan said | Actual | Reason |
|-----------|--------|--------|
| Phase 4 may split into 4a/4b if >400 errors | No split | Post-flip error count was 0. Cascade blocked at `@ts-nocheck` boundary exactly as Phase 3 handoff predicted. |
| DOM refs seeded with `T \| null` OR `null as unknown as T` — pick one | `null as unknown as never` via shared `_UNSET` sentinel, with fields declared non-null | Non-null by contract; 28 consumers read dom refs without null checks; `T \| null` would force church across every call site. Documented trade-off at the `_UNSET` declaration site. Caveat: a forgotten `document.getElementById(...)` lookup would NPE at first use without TSC catching it. |
| — | Fixed 4 drift rows inside `types/domain.ts` | Brief allowed fixing `types/*` if it blocked state typing. Zero runtime diff; types now match Python. Logged as B09–B12. |

## Verification results

### Build gates (final, after post-review fixes)
- `npm run typecheck` — **PASS** (0 errors under stricter flags)
- `npm run build` — **PASS** (63 modules, 433.87 kB js, 28.43 kB css)
- `npm run lint` — green (the 3 pre-existing errors + 84 warnings are all in `@ts-nocheck`'d files and pre-date Phase 4; verified via pre-stash comparison)

### Flask prod smoke (port 5055)
8/8 endpoints 200: `/`, `/assets/<css>`, `/assets/<js>`, `/fonts/DigitalKhattV2.otf`, `/api/surah-info`, `/api/ts/reciters`, `/api/seg/reciters`, `/api/audio/sources`.

### Strictness isolation
- Files WITHOUT `@ts-nocheck`: 7 → `shared/api.ts`, `shared/animation.ts`, `shared/chart.ts` (wait: still has nocheck; actual count is 6), `types/api.ts`, `types/domain.ts`, `segments/state.ts`, `timestamps/state.ts`. Verification agent confirmed 6 files without nocheck; `shared/chart.ts` still has it (Phase 7 cleanup).
- Files WITH `@ts-nocheck`: 43 (down from 45 at end of Phase 3).
- Cascade contained: TSC only checks the 6 foundation + 2 state files; everything else is transparent.

### Budget
| Metric | segments/state.ts | timestamps/state.ts | Total | Budget |
|---|---|---|---|---|
| `any` | 0 | 0 | **0** | ≤8 |
| `@ts-ignore` | 0 | 0 | **0** | ≤3 |
| `!` non-null assertion | 2 | 0 | **2** | ≤5 |

Both `!` in `segments/state.ts` are `Map.get(k)!` immediately after an `if (!map.has(k)) map.set(k, …)` guard (lines 585, 597). Verification agent confirmed correctness.

## Review findings (3-agent gate)

- **Haiku coverage**: 24/24 checks PASS.
- **Sonnet quality**: 11 findings. 1 genuine type hole fixed: `dom.ctx: CanvasRenderingContext2D` accepted `null` from `canvas.getContext('2d')` — changed to `CanvasRenderingContext2D | null`. Rest are deferrable cosmetic/consequence-of-design:
  - Vacuous `if (dom.X)` guards in `@ts-nocheck`'d consumers — clean up when those files are typed.
  - `surahOptionText(num)` parameter untyped — surah-info.ts still `@ts-nocheck`; will be addressed in Phase 5.
  - `SurahInfo` index signature `[k: string]: unknown` — was pre-existing (inherited from the old shape); not introduced by Phase 4; can tighten in Phase 5 if it bites.
- **Opus verification**: PASS across all 5 parts (build gates, Flask smoke, cascade isolation, state-typing correctness, drift-fix validation). Two minor notes:
  - `shared/chart.ts` still has `@ts-nocheck` (Phase 7 cleanup).
  - `_splitChains` / `_allHistoryItems` typed `unknown` — could tighten proactively to save Phase 5 casts. Deferred.

## Surprises / lessons

- **Cascade actually was 0**, not the feared 300+. The `@ts-nocheck` blanket pattern from Phase 2 is paying off exactly as designed — flipping global strictness affects only foundation files.
- **The non-null DOM-ref convention is a pragmatic bet.** It preserves the current code shape (consumers reading `dom.X.foo` without null-checks) at the cost of the TSC-can't-catch-forgotten-id hazard. If one id lookup silently fails, it's a silent runtime NPE. Mitigation for later: a one-line `assertDomRefsPopulated()` at the end of DOMContentLoaded that throws on the first null.
- **Hand-written API types caught real drift in Phase 3 (0 rows) but Phase 4 surfaced 4 rows during state typing.** Lesson: drift shows up when you actually USE the types, not when you declare them.
- **`dom.ctx` null hole was easy to miss.** TSC couldn't catch it (file is `@ts-nocheck`'d); the implementation agent's self-review didn't catch it; only Sonnet's quality review did. Reinforces the value of the review step.

## Handoff to Phase 5

- **Known-good entry commit**: (this commit's SHA)
- **Prerequisites Phase 5 must not break**:
  - `state.ts` / `timestamps/state.ts` stay typed — do not re-add `@ts-nocheck`.
  - The 43 `@ts-nocheck`'d files: Phase 5 removes `@ts-nocheck` from `data.ts`, `validation/**`, `categories.ts`, `references.ts`, `filters.ts`, `rendering.ts` (per plan), and leaves the rest alone.
  - The non-null DOM-ref convention in `DomRefs` — if Phase 5 consumers genuinely need null-checks (e.g., a ref that's conditionally present), flip the specific field to `T | null` in state.ts rather than ignoring the type.
- **Phase 5 scope (per plan §Phase Breakdown)**:
  - Flip `strict: true` at phase start (adds strictFunctionTypes, strictBindCallApply, strictPropertyInitialization, alwaysStrict).
  - Type (in dependency order): `segments/data.ts` → `segments/validation/index.ts` → `validation/categories.ts` + `validation/error-cards.ts` + `validation/error-card-audio.ts` → `segments/references.ts` → `segments/filters.ts` → `segments/rendering.ts`.
  - Remove `@ts-nocheck` from each file as it's typed.
  - Bugs expected to surface: B01 (filter saved-view), B06 (silence-after staleness), B03 (missing_words fixup).
  - Mitigate B07 (accordion half-state) via new `shared/accordion.ts` (deferred from Phase 3).
  - Budget: <15 combined `any` / `@ts-ignore` / `!` across the typed files.
- **Risks for Phase 5**:
  - `_allHistoryItems: unknown[]` in state.ts — history-filters.ts consumes these. When history-filters.ts is typed (Phase 6), it'll need a proper `HistoryItem` type; until then it stays `@ts-nocheck`.
  - `dom.ctx: CanvasRenderingContext2D | null` forces the consumer in `timestamps/index.ts` and `timestamps/waveform.ts` to null-check — addressed when those files are typed (Phase 6).
  - `SurahInfo` index signature may force narrowing. If problematic, remove `[k: string]: unknown` and add explicit optional fields.

Ready for Phase 5.
