# Stage 3 — Decisions Log

Append-only. Each phase may append new decisions. Each row: id · phase · title · context · chosen · rationale · status.

---

## Seeded at plan time

### D01 — Comment cleanup two-pass strategy
**Phase**: P0 + P7
**Context**: 72 files have refactor-noise. Doing one sweep at end means structural phases touch lots of files with wave/stage refs; doing it at start means moves preserve cleaned comments.
**Chosen**: Two passes. P0 strips from files that SURVIVE structurally (stores, utils, services, config). P7 sweeps residue on files touched by structural phases.
**Rationale**: balances risk — P0 strips the static set before agents see noisy surroundings; P7 catches what structural phases may have re-introduced via copy-paste.
**Status**: active.

### D02 — Tests explicitly out of scope
**Phase**: cross-cutting
**Context**: Interview Q1 answered with "tests no need".
**Chosen**: build-pass + typecheck + lint + `create_app()` + S7 user smoke are the only verification layers.
**Rationale**: per user instruction.
**Status**: active.

### D03 — Button.svelte variant extension vs modifier props
**Phase**: P6c
**Context**: Eliminating `extraClass` requires choosing between (a) exploding `variant` enum to ~15 values, (b) keeping 5 core variants + adding `icon`/`size`/`role` modifier props.
**Chosen**: Option (a) — extend variant enum.
**Rationale**: each button role is visually distinct; the styling is not composable (a "save history" button doesn't make sense). Modifier-prop approach would require redesign. Flagged for P6c dispatch review if agent sees cleaner factoring.
**Status**: tentative — revisit at P6c.

### D04 — history diff CSS: mode-prop vs :global()
**Phase**: P6e
**Context**: `.seg-history-diff .seg-row/.seg-text/.seg-left` overrides reach from `HistoryOp.svelte` into `SegmentRow.svelte`. Scoping needs either `:global(...)` or a mode-prop on SegmentRow.
**Chosen**: `mode: 'history' | undefined` prop on SegmentRow.
**Rationale**: keeps SegmentRow self-contained; `:global()` is an escape hatch that signals component leakage. Mode-prop scales if more row contexts emerge.
**Status**: active — agent may propose `:global()` fallback for compound selectors hard to translate to mode.

### D05 — SegmentsCacheBar extraction timing
**Phase**: P4 (not P3b)
**Context**: `lib/stores/segments/audio-cache.ts` is created in P3b for the imperative-kill of `playback/audio-cache.ts`. Cache-bar markup in `SegmentsTab.svelte` could be extracted into its own component at the same time.
**Chosen**: Keep extraction in P4.
**Rationale**: P3 focuses on deletion; P4 owns Svelte tree reshaping post-bridge-removal. Separation keeps phases scannable.
**Status**: active.

### D06 — S2-D28/S2-D29 backend deferred
**Phase**: P1d
**Context**: `save.py::_apply_full_replace` return-type union and `ts_query.py::_error` discriminant are both Stage-2 deferrals. Stage-3 interview said Python backend in scope.
**Chosen**: Defer both — NOT in Stage 3 scope.
**Rationale**: neither is causing active pain; redesign needs broader route-shape decisions; Stage 3 already has heavy backend work (validation package + undo split + cache factory). Add to decisions log as explicit out-of-scope so future passes aren't surprised.
**Status**: out-of-scope for this refactor.

### D07 — history/undo.ts Map-key bug fix via store migration, not standalone
**Phase**: P3c
**Context**: `src/segments/history/undo.ts:210,212` uses `.delete(String(chapter) as unknown as number)`. Exploration agent confirmed SUSPECTED-BUG (no-op).
**Chosen**: Don't fix standalone. Fix implicitly when `segDirtyMap`/`segOpLog` migrate to new `lib/stores/segments/dirty.ts` whose write API takes `number` only.
**Rationale**: standalone fix creates a commit that the larger P3c refactor rewrites anyway. Verifying the migration eliminates the cast is cleaner.
**Status**: ties to B01 in bugs log.

### D08 — data_loader.py not split
**Phase**: P1d
**Context**: 316 LOC is at upper boundary. Exploration agent recommended not splitting (loader pattern already clean; 5-line-per-loader doesn't factor).
**Chosen**: Leave as single file; apply comment cleanup only.
**Rationale**: splitting would add barrel ceremony without DRY benefit.
**Status**: active.

### D09 — Implementation model: Sonnet not Opus
**Phase**: all P* except planning/review agents
**Context**: `feedback_sonnet_impl_agents` memory.
**Chosen**: Sonnet.
**Rationale**: user preference; Sonnet handles the volume of structural moves well without Opus cost.
**Status**: active.

### D10 — CLAUDE.md wave/stage terminology partial retention
**Phase**: P7
**Context**: Interview Q1 rejected "Everything including docs" (full normalization of CLAUDE.md).
**Chosen**: Keep CLAUDE.md wave/stage terminology where it describes a current invariant. Remove OBSOLETED sections (State object pattern, Registration pattern, file tree).
**Rationale**: historical context preserved; no invariant lost.
**Status**: active.

---

## Added at Stage 3 plan review (2026-04-16)

### D11 — Types + ops extraction promoted from Ph6 to Ph3
**Phase**: P3a (Ph3)
**Context**: Opus plan review CRITICAL 1–2: `lib/stores/segments/history.ts` bridge-imports canonical types (`HistorySnapshot`, `OpFlatItem`, `SplitChain`, `SplitChainOp`) from `segments/state.ts` line 44. Plan originally extracted these in P3e (Ph6). Between Ph3 and Ph6 the `history.ts` bridge would break or require a temporary shim. Similarly `createOp`/`snapshotSeg`/`finalizeOp` (state.ts) are called by Ph4's new edit-commit utilities — if they don't extract early, Ph4 dirty store creates a split-brain with `state.segOpLog`.
**Chosen**: Move canonical types → `src/lib/types/segments.ts` and ops → `src/lib/utils/segments/ops.ts` in P3a (Ph3), not P3e (Ph6).
**Rationale**: avoids 5-phase broken-bridge window; eliminates dirty-store split-brain risk.
**Status**: active. Implemented in plan §2 P3a + P3e edits.

### D12 — filter-fields.ts lives in lib/utils, not lib/stores
**Phase**: P3a
**Context**: Plan originally placed `SEG_FILTER_FIELDS` extraction in `src/lib/stores/segments/filter-fields.ts`. Opus review W8 flagged: it's a const array, not a reactive store.
**Chosen**: relocate to `src/lib/utils/segments/filter-fields.ts`.
**Rationale**: naming accuracy; prevents misleading namespace.
**Status**: active.

### D13 — User stops after Ph6 and Ph11
**Phase**: cross-cutting (stop-point policy)
**Context**: Opus review W6/W7: Ph6 (state.ts split + dir delete) + Ph11 (reactive Unified/Animation migration) are the two highest-risk visual-invariant phases. Build + lint alone don't catch behavioral drift (animation cadence, visual sync).
**Chosen**: add two user-declared stop-points after Ph6 and Ph11.
**Rationale**: visual-only regressions are only catchable by manual smoke; system stops too late.
**Status**: active. Encoded in plan §6 + sidecar `stop_points.user_declared`.

### D14 — Bundle size criterion tightened to 300 KB
**Phase**: Stage 5 success-gate
**Context**: Opus review W3 — original criterion (<400 KB main) was too lenient. Chart.js is ~200 KB; after manualChunks split, main realistically drops to ~220–240 KB.
**Chosen**: <300 KB.
**Rationale**: actually gates on the work done; provides meaningful measurement.
**Status**: active.

### D15 — setClassifyFn registration retires in P3a
**Phase**: P3a
**Context**: Opus review W9 — `state._classifyFn` module-mutable closure + `setClassifyFn` writer. `snapshotSeg` calls `_classifyFn(seg)`. When `ops.ts` extracts `snapshotSeg` in P3a, wiring must be clear.
**Chosen**: `ops.ts` directly imports `classify.ts::_classifySegCategories`. `setClassifyFn` retires in P3a (not P3e).
**Rationale**: eliminates registration pattern at earliest point; removes boundary contract violation.
**Status**: active.

### D16 — Three new success criteria added
**Phase**: Stage 5
**Context**: Opus review C4 + W10 + W3 gaps in verifiability.
**Chosen**: Add criteria #18 (no `from.*segments/` in `src/lib/` post-Ph6), #19 (B01 Map-key cast zero post-Ph4), #20 (animation cadence smoke at Ph11).
**Rationale**: machine-checkable (#18, #19) + explicit user gate (#20) covers the review's risk surface.
**Status**: active.

### D17 — save.py S2-D28 visibility note
**Phase**: P1b (deferral context)
**Context**: Opus review W2 flagged that D06 defers S2-D28 but save.py is heavily touched in Ph1 (for `persist_detailed` shared helper). Reviewers of Ph1 commits should know the touched file has a deferred smell.
**Chosen**: Make D06 explicit that save.py is touched but `_apply_full_replace` return-type union is intentionally untouched.
**Rationale**: reviewer context; no scope change.
**Status**: active (note added below).

### D06 (amended) — see D17 above for save.py touch visibility
D06's "deferred" status is unchanged. Ph1's save.py edit adds `persist_detailed` function for atomic-write-backup-rebuild; does NOT modify `_apply_full_replace` or its return-type union. Deferral remains out-of-scope.

