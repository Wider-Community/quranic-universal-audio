# Stage-2 Decisions Log

Append-only record of architectural decisions made during the Svelte 4 migration. Every decision has a stable ID (`S2-D01`...). New decisions get a row when a fork surfaces mid-wave that isn't already covered by the plan.

## Append protocol

- Orchestrator seeds initial decisions from §10 of `stage2-plan.md` before Wave 0.5 starts (done — see below).
- Implementation agents append a row when they need to make a fork-decision that affects subsequent waves.
- Reviewers append a row when they recommend a decision change that the orchestrator accepts.
- Each row records: options considered, chosen, rationale, who decided, when. **Never** rewrite history — if a decision is reversed, add a new row that supersedes the old (`SUPERSEDED-BY-S2-Dxx`).

## Legend

- **DECIDER**: `USER` | `ORCHESTRATOR` | `OPUS-REVIEW` | `SONNET-REVIEW` | `IMPL-AGENT-WAVE-N`
- **STATUS**: `ACTIVE` | `SUPERSEDED-BY-S2-Dxx`

---

## Plan-time decisions (seeded 2026-04-13 from stage2-plan.md §10 + review revisions)

| ID | Decision | Options considered | Chosen | Decider | Status | Notes |
|----|----------|-------------------|--------|---------|--------|-------|
| S2-D01 | Wave ordering | A backend-first, B Svelte-first, Hybrid (1→2→3→4→stop→5-11) | **Hybrid** | OPUS-REVIEW (orchestrator initially picked B in v2; flipped on review) | ACTIVE | Backend first banks distribution-readiness before any frontend churn; removes context-switch cost of interleaving Python/Docker work inside a Svelte stream |
| S2-D02 | Pydantic full schema layer | Adopt, TypedDict-only, skip | **Skip** | USER | ACTIVE | TypedDict can be added incidentally during service signature work; full Pydantic costs ~850 LOC for marginal ROI |
| S2-D03 | `validators/` package handling | Vendor into inspector/, feature-flag, leave as sibling | **Vendor** | USER | ACTIVE | Vendored at Wave 2a from sibling `validators/` at SHA `fb889d7` (2026-04-10, fix(validators): replace confidence=1.0 skip with per-category ignored_categories). Copied `validate_segments.py`, `validate_timestamps.py`, `validate_audio.py`, `validate_audio_ci.py`, `validate_edit_history.py`, `README.md` plus added `__init__.py` to make it a proper package. `sys.path.insert` hack in `routes/timestamps.py` removed; late imports `from validators.validate_segments import ...` resolve to `inspector/validators/` because `python3 inspector/app.py` puts `inspector/` on `sys.path[0]`. Sibling `validators/` retained at repo root for extract-pipeline CLIs; the two copies diverge freely from here. |
| S2-D04 | `CACHE_DIR` placement under Docker | Under DATA_DIR (persistent), container-local (volatile) | **Under DATA_DIR** | USER (after explanation) | ACTIVE | Peak cache survives container restarts; one-time ffmpeg cost per reciter |
| S2-D05 | Dev dependencies file | Single requirements.txt, separate requirements-dev.txt | **Separate `requirements-dev.txt`** | USER | ACTIVE | Empty for now; placeholder for future use; keeps prod Docker image lean |
| S2-D06 | Audio tab Svelte conversion timing | Wave 3 warm-up, dedicated wave, deferred to cleanup | **Wave 11 cleanup** | USER (declined warm-up) + ORCHESTRATOR (placement) | ACTIVE | 341 LOC self-contained; small enough to bundle into cleanup wave |
| S2-D07 | Automated testing in Stage 2 | Full (Vitest + pytest + Playwright), partial, none | **None** | USER | ACTIVE | All testing deferred to a separate future refactor cycle |
| S2-D08 | God-function decomposition | Decompose all 3, decompose `save_seg_data` only, decompose none | **`save_seg_data` only** (Wave 2b) | OPUS-REVIEW | ACTIVE | Pure extract-method (4 sequential phase helpers); behavior-preserving by construction. `validate_reciter_segments` (393 LOC) and `apply_reverse_op` (105 LOC) too risky without tests |
| S2-D09 | Agent allocation per wave | One per phase (~56 invocations), one per wave (max 3 sub-waves) | **One per wave** | USER | ACTIVE | Reviewers at wave boundaries, not per-phase. Orchestrator can adjust per §6.5 based on actual metrics |
| S2-D10 | State-object-pattern (CLAUDE.md principle) | Keep, deprecate for frontend | **Deprecate for frontend** | ORCHESTRATOR | ACTIVE | Superseded by stores-per-concern + Svelte template-bound DOM refs. Wave 11 updates inspector/CLAUDE.md |
| S2-D11 | Store granularity for Segments | Mega-store, fine-grained per-concern (10 stores), provisional | **Provisional through Wave 9, locked at Wave 11** | OPUS-REVIEW | ACTIVE | Some stores will collapse to derived(); some may merge. Implementation agents have latitude to refactor |
| S2-D12 | `waveform-cache.ts` location | lib/stores/, lib/utils/ | **lib/utils/** | OPUS-REVIEW | ACTIVE | Non-reactive Map-based cache; calling it a store contradicts itself |
| S2-D13 | Svelte version | Svelte 4 (stores), Svelte 5 (runes) | **Svelte 4** | USER | ACTIVE | Predictable ecosystem, mature tooling for solo maintainer |
| S2-D14 | Bundle-size as exit criterion | ±10%, ±25%, ≤current, ignore | **Ignore** | USER | ACTIVE | Not a meaningful gate for this refactor |
| S2-D15 | Plan approval gate | Auto-proceed, after draft, after 3-model review | **After draft (v1, v2) + after 3-model review (v3)** | USER | ACTIVE | User reviewed v1 and v2; v3 incorporates Opus + Sonnet review and is the final |
| S2-D16 | History view SVG arrows | Imperative rewrite, helper + reactive binding, leader-line library | **Helper + reactive binding** (leader-line as fallback, near-zero probability) | ORCHESTRATOR | ACTIVE (refined by S2-D19) | Initial assumption `computeArrowPath(fromRect, toRect) → string` was 1:1; Wave 0.5 found the real mapping is branching (1:1 / 1:N / N:1 / N:N / deletion-with-X). Refined helper signature in S2-D19. ~60 LOC pure helper, no resize/scroll re-layout (single `afterUpdate` is sufficient). |
| S2-D17 | ErrorCard component granularity | Single with `category` prop, 11 per-category files | **Single component** with `{#if}`/`{:else if}` branches | OPUS-REVIEW (advisor pass) | ACTIVE | Mirrors current `renderCategoryCards` structure; split into per-category files only if a branch >100 LOC |
| S2-D18 | Pre-Wave-10 exploration timing | At stop-point 2, at Wave 0.5 | **Wave 0.5** (before Wave 1) | OPUS-REVIEW | ACTIVE | Cheap insurance against Wave 10 sizing surprise; the initial exploration agent timed out on this file |

---

## Wave-time decisions

| ID | Wave | Decision | Options | Chosen | Decider | Status | Notes |
|----|------|----------|---------|--------|---------|--------|-------|
| S2-D19 | 0.5 | `svg-arrow-geometry.ts` helper signature | (a) `computeArrowPath(fromRect, toRect) → string` (1:1 only — original plan); (b) `computeArrowLayout(input) → { paths, xMark }` (handles 5 mapping branches) | **(b) `computeArrowLayout(input)`** | OPUS-WAVE-0.5 | ACTIVE | Real mapping is branching (deletion / 1:1 / 1:N / N:1 / N:N). Pre-measured numbers (`colHeight`, `beforeMidYs`, `afterMidYs`, `emptyMidY`) flow into pure helper from Svelte's `bind:this`-driven measurement. No callback injection needed. ~60 LOC. |
| S2-D20 | 0.5 | `HistoryOp.svelte` consolidation | Keep `renderHistoryOp` + `renderHistoryGroupedOp` as 2 components OR collapse to 1 with `group: EditOp[]` prop | **Collapse to 1** | OPUS-WAVE-0.5 | ACTIVE | The two are ~90% duplicate (46+54=100 LOC → ~100 LOC single component, length-1 group degrades cleanly to single-op render). |
| S2-D21 | 0.5 | Global SVG marker `<defs>` placement in Svelte | (a) `<svelte:head>` at App.svelte; (b) `<svelte:head>` at HistoryArrows.svelte; (c) inline `<marker>` in each `HistoryArrows.svelte` instance | **(c) Inline per-instance** | OPUS-WAVE-0.5 | ACTIVE | Negligible duplication (~5 diffs on screen × 4 lines), no cross-component coupling, simpler. |
| S2-D22 | 0.5 | `_appendValDeltas` dead code | Keep for future use, drop at Wave 10 | **Drop at Wave 10** | OPUS-WAVE-0.5 | ACTIVE | Grep confirms zero call sites in repo. |
| S2-D23 | 0.5 | `SegmentRow.svelte` history-mode props requirement | (a) Generic SegmentRow with optional history props; (b) Dedicated HistorySegmentRow.svelte | **(a) Generic with optional props** | OPUS-WAVE-0.5 + ORCHESTRATOR | ACTIVE | Wave 5 must provision: `readOnly`, `showChapter`, `showPlayBtn`, `splitHL?`, `trimHL?`, `mergeHL?`, `changedFields?: Set<'ref'\|'duration'\|'conf'\|'body'>`, `mode?: 'normal'\|'history'` (controls horizontal-vs-vertical layout). |
| S2-D24 | 1 | `import/no-cycle` severity + TS resolver config | (a) keep `error` + fix all 24 cycles now (~1 day scope-creep); (b) `warn` + defer segments cycles to Waves 5-10; (c) keep `error` but only include timestamps files | **(b) warn, defer** | IMPL-AGENT-WAVE-1 | ACTIVE | Plan §11 assumed `import/no-cycle:error` was already in force; Wave 1 discovered the rule was silently no-op because `eslint-plugin-import` had no TS resolver configured. Installed `eslint-import-resolver-typescript` + added `import/parsers: {@typescript-eslint/parser: [.ts, .tsx]}` — both required for cycle detection on extensionless `.ts` imports. Rule now fires correctly (22 warnings, all pre-existing segments runtime-safe cycles; timestamps tab cycles all dissolved via Item 2 registry + `shared/active-tab.ts` extraction). Downgraded to `warn` until Svelte migration (Waves 5-10) dissolves segments cycles; Wave 11 re-promotes to `error`. See S2-B06. |
| S2-D25 | 1 | `getActiveTab` extraction target | (a) keep in `main.ts` (cycle with keyboard modules); (b) extract to `shared/active-tab.ts` | **(b) extract** | IMPL-AGENT-WAVE-1 (advisor-recommended) | ACTIVE | Both `{timestamps,segments}/keyboard.ts` read `getActiveTab` from `main.ts`, and `main.ts` imports each tab's `index.ts` (which imports its `keyboard.ts`). The 3-module cycle is benign at runtime but the lint rule correctly flags it once the TS resolver works. Moving `getActiveTab` + `setActiveTab` to `shared/active-tab.ts` (a leaf module with no tab deps) breaks the cycle by construction. Zero behavior change; `main.ts` now calls `setActiveTab(tab)` + `getActiveTab()` where it used to mutate a local. |
| S2-D26 | 1 (post-review) | Cycle-count ceiling gate in pre-flight | (a) defer to Wave 5 per Wave-1 handoff; (b) land immediately at Wave 1 end | **(b) immediately** | OPUS-REVIEW-WAVE-1 | ACTIVE | Added Gate [7/7] to `stage2-checks.sh` that asserts `npm run lint` warning count for `import/no-cycle` does not exceed `$CYCLE_CEILING` (default 22; override via env). Prevents any wave from silently introducing a new cycle during the deferral window. Ceiling decrements per wave as segments migrate; set to 0 at Wave 11 re-promote. |
