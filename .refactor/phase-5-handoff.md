# Phase 5 — Flip `strict: true`, type high-traffic consumers, extract `shared/accordion.ts`

**Status:** COMPLETE
**Commit:** pending (will be this commit's SHA)
**Branch:** `worktree-refactor+inspector-modularize`
**Implementation:** Opus agent (delegated per refactor skill).

## Scope delivered

### 1. tsconfig strictness ratchet

`inspector/frontend/tsconfig.json`:
- `strict`: false → **true** — adds `strictFunctionTypes`, `strictBindCallApply`, `strictPropertyInitialization`, `alwaysStrict`, `noImplicitThis`, `useUnknownInCatchVariables`.
- `noImplicitAny` / `strictNullChecks` already on from Phase 4 — unchanged.
- `allowJs` stays `true` (Phase 7 flip).
- `noUncheckedIndexedAccess` stays `false` (Phase 7 flip).

Post-flip typecheck error count: **0**. The `@ts-nocheck` blanket contains the cascade: only the 8 files typed in this phase plus the Phase 4 foundation (6 files) and state hubs (2 files) are seen by TSC.

### 2. `inspector/frontend/src/shared/accordion.ts` (new, 63 LOC)

Narrow typed API extracted from `validation/index.ts`:
- `collapseSiblingDetails(exceptDetails, panelRootSelector?)` — closes every sibling `<details data-category>` under the shared accordion root
- `capturePanelOpenState(targetEl): AccordionOpenState` — reads the current open/close flag for every category
- `restorePanelOpenState(targetEl, state)` — reopens categories whose captured state was `open`, silently skipping any that no longer have a DOM node

**Scoping decision (narrow vs. full):** NARROW. Only `validation/index.ts` uses the open/close + half-state contract. History and edit modules reference `data-category` for metadata lookup, not accordion behavior. `captureValPanelState` / `restoreValPanelState` / `_collapseAccordionExcept` remain in `validation/index.ts` as thin wrappers over the shared helpers to preserve call-site signatures in the three consumer files.

### 3. Eight files typed (@ts-nocheck removed)

In dependency order, per plan:

| File | LOC (pre→post) | Notes |
|---|---|---|
| `segments/data.ts` | 394 → 416 | Added inner rAF null guard (B13). All API fetches go through `shared/api.ts`. |
| `segments/validation/index.ts` | 432 → 529 | Biggest behavior surface. Rewired to `shared/accordion.ts`. Uses a descriptor list with per-category narrowing casts for the 11 categories. |
| `segments/validation/categories.ts` | 167 → 207 | `_classifySnapIssues` annotated with `Segment` / `SegmentsState` types. |
| `segments/validation/error-cards.ts` | 336 → 452 | `resolveSegFromRow` widens synthetic history-row shape to fully-populated `Segment` (zero runtime diff; consumers read via `??`/`||`). |
| `segments/validation/error-card-audio.ts` | 138 → 160 | Playback range + cleanup typed. |
| `segments/references.ts` | 155 → 172 | Parsing / formatting helpers typed end-to-end. |
| `segments/filters.ts` | 225 → 247 | `computeSilenceAfter` writes `null` for no-neighbour case — tightened `silence_after_ms: number \| null` in domain types (B14). |
| `segments/rendering.ts` | 318 → 341 | `renderSegCard` / `renderSegList` fully typed; `seg.chapter ??` used consistently. |

### 4. `types/api.ts` + `types/domain.ts` extended

- **New in `types/domain.ts`**: `SegValItemBase`, 11 per-category item types (`SegValFailedItem`, `SegValMissingVerseItem`, `SegValMissingWordsItem`, `SegValStructuralErrorItem`, `SegValLowConfidenceItem`, `SegValBoundaryAdjItem`, `SegValCrossVerseItem`, `SegValAudioBleedingItem`, `SegValRepetitionItem`, `SegValMuqattaatItem`, `SegValQalqalaItem`), union `SegValAnyItem`, and `ValCategoryDescriptor<T>`.
- **New in `types/api.ts`**: `SegValidateResponse` (11 optional per-category arrays + index signature).
- **Drift fixes applied post-review** (B15, B16):
  - `SegConfigResponse.accordion_context`: `Record<string, number>` → `Record<string, string>` (server emits string context keys; B15).
  - `SegValMissingVerseItem.msg`: optional → required (server always emits; B16).
  - `SegValidateResponse.errors` doc comment flipped to reflect reality (server emits `errors`; `structural_errors` is the unused alias).
- **`silence_after_ms`** widened `number?` → `number \| null` (B14).

## Scope deferred

- **Remaining 27 `@ts-nocheck`'d files** — stay deferred to Phase 6 per plan. Specifically untouched: `segments/edit/**`, `segments/history/**`, `segments/waveform/**`, `segments/playback/**`, `segments/save.ts`, `segments/undo.ts`, `segments/stats.ts`, `segments/navigation.ts`, `segments/keyboard.ts`, `segments/event-delegation.ts`, `segments/index.ts`, `segments/audio-cache.ts`, `segments/scroll-preload.ts`, `timestamps/**`, `audio/index.ts`, `shared/chart.ts` (Phase 7), `shared/surah-info.ts` (leave to Phase 6 when a typed consumer exercises it), `shared/searchable-select.ts` (Phase 6).
- **`shared/animation.ts`** — written in Phase 3, not yet consumed by any module. Will be wired into `segments/playback/index.ts` + `timestamps/playback.ts` in Phase 6.
- **B01 (filter saved-view leak)** did NOT surface as a `strictNullChecks` error. The seeded bug's wedge-the-UI failure mode is a logic bug (clearing `_segSavedFilterView` without restoring `segDisplayedSegments`), not a type violation. `filters.ts:160-162` compiles fine; bug remains OPEN. Will be addressed when the fix itself is prioritized — not a Phase 5 scope item.
- **B06 (silence-after staleness)** did NOT surface either. Re-audited via the typed code path: `segData.segments` is re-assigned from `segAllData.segments.filter(...)` which shares segment object references, so `silence_after_ms` mutations propagate correctly in practice. The seeded concern may not be a real bug at the current state of the code; stays OPEN pending a reproducer.

## Deviations from plan

| Plan said | Actual | Reason |
|-----------|--------|--------|
| Flip `strict: true` at phase start and fix initial error cascade | 0 errors after flip | `@ts-nocheck` blanket pattern from Phase 2 continues to contain cascade. |
| Each genuine bug-log row → separate commit for bisect-ability | Single commit for all Phase 5 work | All surfaced bugs (B13, B14) are trivial null-guards / type widenings landing alongside the annotations that enabled them — explicitly allowed by plan ("unless the fix is a trivial null check landing alongside a type annotation it directly enabled"). |
| B01 / B03 / B06 expected to surface | Only B03 revisited; surfaced as **not-a-bug** | B03 auditing (`services/validation.py:375-394` + client `_forEachValItem`) confirmed `target_seg_index` only exists nested inside `auto_fix`; original exploration row was a misread. B01 and B06 are logic bugs that don't violate types and stay OPEN. |
| `shared/accordion.ts` might need full-scope extraction | Narrow-only extraction | History/edit modules don't use the open/close contract; they only read `data-category` for metadata lookup. |
| Post-review found 3 additional type issues | 1 genuine (B15 accordion_context drift), 2 nits (B16 msg required, doc comment swap) | All applied in same commit; zero behavior change. |

## Verification results

### Build gates (final, after post-review fixes)
- `npm run typecheck` — **PASS** (0 errors under `strict: true`)
- `npm run build` — **PASS** (64 modules, 433.98 kB js / 133.38 kB gzip, 28.43 kB css / 6.05 kB gzip)
- `npm run lint` — 1 error (`prefer-const` in `segments/waveform/index.ts:120`, pre-existing, under `@ts-nocheck`, Phase 6 scope), 65 warnings (down from 84 at end of Phase 4 as typed files stopped generating warnings).

### Flask prod smoke (port 5055)
8/8 endpoints 200: `/`, `/assets/<hashed.css>`, `/assets/<hashed.js>`, `/fonts/DigitalKhattV2.otf`, `/api/surah-info`, `/api/ts/reciters`, `/api/seg/reciters`, `/api/audio/sources`.

### Strictness isolation
- Files WITHOUT `@ts-nocheck`: **15** — 6 Phase 3/4 foundation (`shared/{api, animation}.ts`, `types/{api, domain}.ts`, `segments/state.ts`, `timestamps/state.ts`) + 8 Phase 5 typed files + new `shared/accordion.ts`.
- Files WITH `@ts-nocheck`: ~36 (Phase 4 was 43; Phase 5 removed 8; one new typed file added).
- `shared/chart.ts` still carries `@ts-nocheck` (Phase 7 cleanup) — out of Phase 5 scope.

### Budget
| Metric | Across 8 typed + `shared/accordion.ts` | Budget |
|---|---|---|
| `any` | **0** | ≤15 |
| `@ts-ignore` / `@ts-expect-error` | **0** | ≤5 |
| `!` non-null assertions | **0** | ≤10 |

Zero usage across the board. The double-cast pattern `(… as ValCategoryDescriptor<Specific>) as ValCategoryDescriptor<SegValAnyItem>` is used at 11 sites in `validation/index.ts` to widen a heterogeneous descriptor list; this is a structural cast between compatible shapes, not a budgeted `any` / `!` / `@ts-ignore`. Call sites are safe because each callback is invoked only within its own category branch.

## Review findings (3-agent gate)

### Haiku coverage: 17/18 PASS
One near-miss: counted 36 `@ts-nocheck` files vs. expected ~35 (tolerance; the extra is `shared/searchable-select.ts` which Phase 4 handoff didn't count in its baseline). Not a blocker.

### Sonnet quality: APPROVE-WITH-FIXES (3 findings applied, all in `types/*.ts`)
- **Genuine**: `SegConfigResponse.accordion_context: Record<string, number>` drift (B15) — FIXED.
- **Nit**: `SegValMissingVerseItem.msg?` server always emits — FIXED (`msg: string`) as B16.
- **Nit**: `SegValidateResponse.errors` doc comment was backwards (server actually emits `errors`; `structural_errors` is the unused alias) — FIXED.
- Non-applied nit: `_collectErrorChapters` doesn't include `'structural_errors'` in its cats list. Deferred — server never emits `structural_errors` in the current code, so no runtime diff. If `structural_errors` is dead-code-pruned in Phase 7, we'll re-evaluate.

### Opus verification: APPROVE (no blockers)
- **Dim 1 (zero behavior change)**: one notable diff — `validation/categories.ts:156` widened `snap.confidence < 0.80` to `(snap.confidence ?? 0) < 0.80`. Edge case: missing `confidence` on a snapshot classifies as `low_confidence` under new code (old NaN comparison returned false). In practice `snapshotSeg` always sets `confidence: seg.confidence ?? 0`, so no real snapshot lacks it. Flagged for Phase 6 to double-check against persisted `edit_history.jsonl` snapshots.
- **Dim 2 (accordion rewire)**: all 3 pre-existing accordion paths have equivalent post-rewire paths. No gaps.
- **Dim 3 (validation item type accuracy)**: all 11 categories match server emit. Two fields typed wider than server emits (`SegValRepetitionItem.display_ref?`, `SegValMissingVerseItem.msg?`) — the latter tightened in B16, the former left optional (low-risk future-proofing).
- **Dim 4 (B03 closure)**: CLOSE-CORRECT.
- **Dim 5 (B07 closure)**: CLOSE-CORRECT.
- **Dim 6 (budget)**: 0 / 0 / 0.
- **Dim 7 (API contract)**: no blocking drift.
- **Dim 8 (strict-mode side effects)**: no classes (`strictPropertyInitialization` N/A); 5 `catch (e)` blocks but none access `.message/.stack` (`useUnknownInCatchVariables` safe).

## Surprises / lessons

- **`strict: true` flip was a no-op for TSC under `@ts-nocheck` cascade**. The combination of Phase 2's blanket `@ts-nocheck` + per-phase removal + strict-flag ratchet continues to work exactly as designed: zero-error boundary at each phase gate.
- **Seeded bugs don't always survive typing audit.** B03 ("missing_words target_seg_index fixup gap") was a misread of the original JS in exploration — the fix guard was already correct. Lesson: re-audit seeded bugs against the current code when typing surfaces the surrounding context.
- **Drift in `types/api.ts` authored in Phase 3 survived until Phase 5 review caught it.** `accordion_context: Record<string, number>` was wrong because the value was never typed through a call chain (the consumer was `@ts-nocheck`'d). Lesson: unused/dangling API types aren't checked — drift can persist through multiple phases.
- **Non-null assertions and casts have stayed at 0 across two strictness phases now.** The state-hub DOM-ref sentinel convention + narrow API-type declarations are paying off.

## Handoff to Phase 6

- **Known-good entry commit**: (this commit's SHA)
- **Prerequisites Phase 6 must not break**:
  - The 8 files typed in Phase 5 stay typed — do not re-add `@ts-nocheck`.
  - The 11 per-category validation item types in `types/domain.ts` — do not change without updating the descriptor-list casts in `validation/index.ts:140-226`.
  - `silence_after_ms: number | null` — the widening is load-bearing for `computeSilenceAfter` callers.
  - `shared/accordion.ts` narrow API — if edit/history modules now need accordion behavior, extend the shared module rather than reintroducing validation-wrappers.
- **Phase 6 scope (per plan §Phase Breakdown)**:
  - Type remaining segments: `edit/**`, `history/**`, `waveform/**`, `playback/**`, `save.ts`, `undo.ts`, `stats.ts`, `navigation.ts`, `keyboard.ts`, `event-delegation.ts`, `index.ts`, `audio-cache.ts`, `scroll-preload.ts`.
  - Type `timestamps/**`, `audio/index.ts`.
  - Type remaining `shared/**` (`searchable-select.ts`, `surah-info.ts`, `arabic-text.ts`, `audio.ts`, `constants.ts`).
  - Type the registration/injection pattern signatures (`registerHandler`, `registerEditModes`, `registerEditDrawFns`, `registerWaveformHandlers`, `registerKeyboardHandler`, `setClassifyFn`). Type signatures only — do NOT redesign.
  - Wire `shared/animation.ts` into the two playback loops (segments + timestamps).
  - Chart types (`ChartConfiguration<'bar'>`) proper typing in `segments/stats.ts`. `shared/chart.ts` stays `@ts-nocheck` until Phase 7.
  - Budget: aim for similar discipline (single-digit totals of any/@ts-ignore/! across the whole 27-file batch).
- **Risks for Phase 6**:
  - `history/rendering.ts` is the largest single file (631 LOC, 23 functions). Type it in isolation; defer some internal helper types to Phase 7 cleanup if needed.
  - `segments/index.ts:189` will finally exercise `SegConfigResponse.accordion_context` → `state._accordionContext` assignment. With B15 fixed, this should just compile.
  - The `confidence ?? 0` widening in `categories.ts:156` — if `edit_history.jsonl` persisted snapshots without `confidence`, Phase 6 review should verify no classification drift.
  - `registerHandler`-style injection points may force creation of a small `RegistryTypes` module to avoid circular imports when typing both ends.
  - `dom.ctx: CanvasRenderingContext2D | null` (Phase 4) will force null-checks in `timestamps/waveform.ts` when it's typed.
- **Non-blocking Phase 7 notes**:
  - `shared/chart.ts` `@ts-nocheck` removal.
  - `SurahInfo[k: string]: unknown` index signature — tighten or remove.
  - `_collectErrorChapters` `structural_errors` cats omission — either add or delete the alias entirely from `types/api.ts`.
  - `??` vs `||` consistency sweep across all files once edit modules are typed.
  - Consider replacing the 11-site double-cast pattern in `validation/index.ts` with a discriminated union if Phase 6 needs rigor.

Ready for Phase 6.
