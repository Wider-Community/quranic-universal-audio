# Phase 2 Handoff — Shell splits pre-bridge

**Phase**: Ph2 (P2a + P2b + P2c)
**Impl model**: Sonnet (1 agent) + Sonnet fix agent
**Status**: COMPLETE — all gates green, review findings fixed.
**Commit**: `eb1790b`

## What was done

### P2a — TimestampsTab 4-way split (806 → 392 LOC)

- `TimestampsControls.svelte` (159 LOC) — info bar (reciter/chapter/verse dropdowns + random buttons), view/mode/auto toggles. Dispatches events for selection changes. Consumes `buildGroupedReciters` from `lib/utils/grouped-reciters.ts`.
- `TimestampsAudio.svelte` (134 LOC) — wraps `<AudioPlayer>` + owns rAF animation loop + auto-advance logic. Replaces old `loadAudioAndPlay` + `_pendingOnMeta` pattern with `AudioPlayer.load()`. Dispatches `tick`, `prev`, `next`, `autoNext`, `autoRandom` events.
- `TimestampsKeyboard.svelte` (112 LOC) — `<svelte:window on:keydown>` handler. Uses `wordBoundaryScan` from `lib/utils/word-boundary.ts`. Dispatches typed events for all key actions.
- `TimestampsShortcutsGuide.svelte` (41 LOC) — static shortcut help markup.
- `TimestampsTab.svelte` (392 LOC) — composition shell + cascade fetch logic + store wiring + CSS vars.

### P2b — ErrorCard 3-way split (458 → 79 LOC)

- `MissingWordsCard.svelte` (182 LOC) — missing-words render path + auto-fix/undo handlers + opacity dim on fix.
- `MissingVersesCard.svelte` (83 LOC) — missing-verses render path + context toggle.
- `GenericIssueCard.svelte` (208 LOC) — catch-all 9-category path + phoneme tail branch + ignore flow + context toggle.
- `ErrorCard.svelte` (79 LOC) — dispatcher. Forwards `getIsContextShown`, `showContextForced`, `hideContextForced` via `bind:this`.
- `lib/utils/validation-card-inject.ts` (50 LOC) — shared `injectCard()` helper.

### P2c — SegmentsAudioControls AudioPlayer adoption (133 → 124 LOC)

- Manual `<audio>` + speed select replaced by `<AudioPlayer audioId="seg-audio-player" speedSelectId="seg-speed-select" lsSpeedKey={LS_KEYS.SEG_SPEED}>`.
- `audioEl` export preserved via `$: audioEl = _player?.element() ?? null`.
- SegmentsTab: deleted 13-line `seg-speed-select` markup block.
- AudioPlayer: added `audioId` + `speedSelectId` props.
- SpeedControl: added `selectId` prop.

## Decisions that differ from plan

- **TimestampsTab 392 LOC** (target ~250). Composition shell retains fetch cascade + store subscription wiring + CSS vars that couldn't split further without fragmenting reactive dependencies. Deviation accepted — shell is clean composition, not logic.
- **MissingWordsCard 182 LOC** (target ~140). Auto-fix + undo handlers + context toggle + opacity dim = irreducible baseline. Deviation accepted.
- **GenericIssueCard 208 LOC** (target ~170). 9-category catch-all with phoneme + ignore branches. Deviation accepted.

## Review findings addressed

### Sonnet quality — 2 genuine + 4 cleanup
1. **MissingWordsCard auto-fix opacity dim dropped** — fixed: added `wrapperEl` ref + opacity set/remove in handlers.
2. **AudioPlayer `_pendingOnMeta` not cleared on error** — fixed: `fwd()` clears listener when `name === 'error'`.
3. Dead imports removed: `chaptersOptions`/`versesOptions` from TimestampsTab, `autoAdvancing` from TimestampsControls, `safePlay` from TimestampsAudio.
4. Stale doc comment "Not consumed until Ph2" removed from AudioPlayer.

### Opus verification — PASS (1 MEDIUM confirmed = same as Sonnet #1)
- All keyboard bindings preserved. ErrorCard method forwarding correct. SegmentsAudioControls `audioEl` export, DOM IDs, event wiring all correct. rAF lifecycle preserved. Auto-advance preserved.

## Current codebase state

- `src/segments/` still exists (29 files) — scheduled Ph3–Ph6.
- `src/shared/`, `src/types/` still exist — scheduled Ph7.
- `src/styles/` has 8 CSS files — scheduled Ph8–Ph11.
- `state.ts` bridge writes intact — scheduled Ph6.
- 7 `src/lib/**` files bridge-import from `src/segments/` — scheduled Ph3 (5 pre-existing + 2 new from `validation-card-inject.ts`).
- 128 imperative DOM calls remain — scheduled Ph3/Ph6.
- 2 `String(..) as unknown as number` casts (B01) remain — scheduled Ph4.
- Refactor-noise files: 56 (was 58 at Ph1 end).

## Patterns established

- **AudioPlayer adoption pattern**: `<AudioPlayer audioId={id} speedSelectId={id} lsSpeedKey={key}>` with `$: audioEl = _player?.element() ?? null` for parent access to raw `HTMLAudioElement`.
- **Shell-split pattern**: parent keeps composition + store wiring + CSS vars. Children own focused behavior + markup. Communication via props down / events up / `bind:this` for imperative API.
- **ErrorCard dispatcher pattern**: category-based routing with `bind:this` method forwarding to active child.

## Invariant check

- Build green (`npm run build`): OK.
- Lint green (`npm run lint`): OK.
- Python import green: OK (no Python changes).
- Refactor-noise: 56 files (down from 58).
- Imperative DOM: 128 (unchanged — later phases).
- Bridge imports from segments in lib: 7 (5 pre-existing + 2 new in validation-card-inject.ts).

## Phase metrics

- Files modified: 6 | Files new: 8 (4 timestamps subcomponents + 3 validation subcomponents + 1 shared util).
- LOC delta: +1485 / -1324 net (reorganization, not growth).
- Wall-clock: impl ~14 min + reviews ~12 min (parallel) + fix ~4 min ≈ 30 min total.
- Agents: impl (Sonnet, 93k tok, 52 tools) + quality review (Sonnet, 86k tok, 37 tools) + verification (Opus, 81k tok, 35 tools) + fix (Sonnet, 49k tok, 27 tools) = 4 agents.

## Review-allocation retrospective

- Allocated: Sonnet quality + Opus verification.
- Outcome: Both caught the same opacity regression (Sonnet called CRITICAL, Opus MEDIUM). Opus confirmed all logic preservation — no additional criticals. Sonnet found dead imports Opus missed. Good complementary coverage.
- Recommend for Ph3: Sonnet quality + Opus verification (segment migration has complex import chain logic).

## Risks/concerns for Ph3

- **validation-card-inject.ts bridge imports**: 2 new imports from `src/segments/` (`rendering.ts`, `waveform/index.ts`). These must migrate in Ph3 when those files move to lib.
- **TimestampsTab 392 LOC** — still above #11 success criterion (≤300). Could be tightened in Ph12 final sweep if fetch cascade can be extracted.
- Ph2 did not touch `src/segments/` at all (clean scope boundary).
