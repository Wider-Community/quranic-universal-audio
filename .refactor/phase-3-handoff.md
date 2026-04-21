# Phase 3 — Shared API wrapper, hand-written type contracts, animation helper

**Status:** COMPLETE
**Commit:** pending (this phase)
**Branch:** `worktree-refactor+inspector-modularize`

## Scope delivered

### 1. `inspector/frontend/src/shared/api.ts`

Single fetch boundary:
- `fetchJson<T>(url, init?)` — parses `res.json()` regardless of status. Matches the legacy `fetch(url).then(r => r.json())` semantic so callers that check `data.error` on 4xx responses keep working.
- `fetchJsonOrNull<T>(url, init?)` — returns `null` on non-2xx. Used for endpoints where "not found" is a meaningful response (e.g. `/api/seg/edit-history` before first save).
- `fetchArrayBuffer(url, init?)` — strict (throws on non-2xx) for audio decoder paths.
- `ApiError` class with `url`/`status`/`body` fields.

Design note: `fetchJsonl` was planned but omitted — the `/api/seg/edit-history` route returns a single JSON object (batches + summary built server-side from the JSONL file), not line-delimited JSON. See B08 resolution below.

### 2. `inspector/frontend/src/types/domain.ts`

Core cross-tab domain types, hand-mirrored from Python services:
- Reference strings: `Ref`, `VerseRef`
- Segments: `Segment`, `SegmentsChapterSummary`, `EditOp`, `ValidationSummarySnapshot`, `HistoryBatch`, `HistorySummary`
- Peaks: `AudioPeaks`, `SegmentPeaks`
- Reciters: `TsReciter`, `SegReciter`
- Timestamps: `PhonemeInterval`, `Letter`, `TsWord`, `TsVerseData`, plus validation row types (`TsMfaFailure`, `TsMissingWords`, `TsBoundaryMismatch`)
- Surah info: `SurahInfo`, `SurahInfoMap`
- Errors: `ApiErrorBody`

### 3. `inspector/frontend/src/types/api.ts`

One request/response type per blueprint endpoint, mirrored from `inspector/routes/**`:
- Cross-tab: `SurahInfoResponse`
- `/api/ts/*` (8 endpoints): config, reciters, chapters, verses, data, random, random/:reciter, validate
- `/api/seg/*` data (5 endpoints): config, reciters, chapters, data, all
- `/api/seg/*` edit (4 endpoints): resolve_ref, save (req+resp), undo-batch, undo-ops
- `/api/seg/*` validation + stats + history (5 endpoints)
- `/api/seg/*` peaks (2 endpoints)
- `/api/seg/*` audio proxy + cache (3 endpoints)
- `/api/audio/*` (2 endpoints): sources, surahs

Types are permissive where shape varies (e.g. `SegValidateResponse` uses `unknown[]` for each category list) and strict where the shape is stable (e.g. `SegConfigResponse`, `TsVerseData`).

### 4. All `fetch('/api/...')` call sites routed through `shared/api.ts`

~40 call sites in 15 files migrated. Generic annotations added at call sites (`fetchJson<SegDataResponse>(...)`). Remaining raw `fetch(...)` is exactly:
- 3 internal uses in `shared/api.ts` (the wrappers themselves)
- 1 in `segments/playback/index.ts:62` — `_prefetchNextSegAudio` stores the raw `fetch(url).then(r => r.blob())` Promise in `state._segPrefetchCache` to pre-warm the HTTP cache without consuming the body. Documented as an intentional exception in `shared/api.ts` preamble.

Binary audio decoder (`timestamps/waveform.ts:decodeWaveform`) uses `fetchArrayBuffer` instead of raw `fetch → arrayBuffer`.

### 5. `inspector/frontend/src/shared/animation.ts`

`createAnimationLoop(onFrame)` — generic rAF loop helper. Exposed as `{start, stop, running}`.

**Not migrated to yet**: the two playback callers (`segments/playback/index.ts`, `timestamps/playback.ts`) continue to manage their own `state.segAnimId` / `state.animationId`. Reason: segments' stop logic entangles loop cancellation with button-text reset and active-audio-source clearing. A safe migration wants the stop side-effects separated first, which fits better during Phase 6 when those files get typed. The helper is in place for that migration.

### 6. `shared/accordion.ts` — DEFERRED

Plan originally paired this with Phase 3. Deferred to Phase 5 when `validation/index.ts` gets typed — the half-state guard fix (B07) is more naturally addressed alongside typing, not before.

## Scope deferred

- `shared/accordion.ts` + B07 half-state fix → Phase 5.
- Playback rAF migration onto `shared/animation.ts` → Phase 6.
- Removing `@ts-nocheck` from the newly-typed `shared/api.ts`, `types/domain.ts`, `types/api.ts`, `shared/animation.ts` → done (these files never had `@ts-nocheck` since they're new).
- Removing `@ts-nocheck` from call-site files — NOT done. Phase 4+ removes per-file as typing proceeds.
- Tightening global `tsconfig` strictness (`noImplicitAny`, `strictNullChecks`) — deferred to Phase 4 per plan.

## Deviations from plan

| Plan said | Actual | Reason |
|-----------|--------|--------|
| `fetchJsonl<T>` helper fixes B08 by construction | No `fetchJsonl` helper; B08 closed as "not a bug" | Route actually returns JSON (`{batches, summary}`), not JSONL — exploration agent misread. |
| `fetchJson<T>` throws on non-2xx | Lenient — parses JSON regardless | Flask routes return `jsonify({error: "..."})` with non-2xx status; callers check `data.error`. A strict variant remains available if needed later. |
| Phase 3 enables `noImplicitAny` on `shared/**` + `types/**` only | Global tsconfig unchanged | New files are typed explicitly; `@ts-nocheck` elsewhere prevents cascade. Strictness ratchet happens cleanly at Phase 4 start. |
| Phase 3 extracts `shared/accordion.ts` | Deferred to Phase 5 | Half-state fix makes more sense alongside the `validation/index.ts` typing pass. |
| Phase 3 migrates rAF loops to `shared/animation.ts` | Helper created, callers not migrated | Segments loop entangles stop with button/state side-effects; safer refactor during Phase 6 typing. |

## Verification results

- `npm run typecheck` — **PASS** (0 errors; call-site files still `@ts-nocheck`, typed files pass inference)
- `npm run build` — **PASS** (63 modules, 4.27s; bundle 434.02 kB/133.17 kB gzipped — no growth since Phase 2 despite new files because `shared/animation.ts` and unused portions of `types/*.ts` are tree-shaken)
- Flask prod smoke (port 5055): `/`, `/api/surah-info`, `/api/ts/reciters`, `/api/seg/reciters`, `/api/audio/sources`, `/api/ts/config`, `/api/seg/config` all **200**.
- `grep 'fetch(' inspector/frontend/src` — only allowed exceptions remain: 3 inside `shared/api.ts` (wrapper implementation) + 1 in `segments/playback/index.ts:62` (intentional prefetch cache, documented).

## Bug-log delta

- **Rows added:** none. While authoring `types/api.ts` I read every `routes/*.py` handler carefully and flagged no mismatches beyond what was already seeded — the types are permissive enough that obvious drift would show up as "caller accesses `.foo` not declared on type T", which with `@ts-nocheck` on call sites won't surface until Phase 4+.
- **Rows closed:** **B08** — "not a bug", moved to Section 5 with a detailed resolution.
- **Status changes:** B08 OPEN → CLOSED.

## tsconfig state at phase end

Unchanged from Phase 2 (flags flip starting in Phase 4):
- `strict`: false
- `noImplicitAny`: false
- `strictNullChecks`: false
- `noUncheckedIndexedAccess`: false
- `allowJs`: true
- `checkJs`: false

## Review findings

- **Sonnet quality** — one critical finding: `segments/history/undo.ts` was missing its `fetchJson` / `fetchJsonOrNull` / type imports. My earlier Edit to add them silently failed to apply (the same `from '../save';` anchor was already the final line so the edit matched but the replacement didn't land as expected). Would have been a runtime `TypeError` on every undo action. **Fixed before commit.** Sonnet also flagged minor type-tightening opportunities (`EditOp.targets_*` → `Record<string, unknown>[]`; `TsMissingWords.missing` → `Array<string | Record<string, unknown>>`; `SegDataResponse` should include `error?`) — all applied. Documentation gap on `shared/animation.ts` re: stop-inside-onFrame noted as future work.
- **Opus verification** — all 11 checks PASS. 13 files import from `shared/api` (after the `undo.ts` fix, this grows to 14 — within tolerance). Flask smoke 7/7 endpoints 200. Typecheck + build green. No `r.json()` outside `shared/api.ts`. No unexpected `fetch(` in source.

## Surprises / lessons

- **B08 was a false alarm from the exploration phase.** Agent-3 mis-identified the `/api/seg/edit-history` route as returning JSONL; it actually parses JSONL server-side and returns a single JSON object. This highlights the value of "read the Python route before writing the type" — had we trusted the bug log, we'd have built an unnecessary `fetchJsonl` helper.
- **`fetchJson` lenient-parsing was the right call.** Initial draft threw on non-2xx; that would have broken every call site's `if (data.error)` check. Matching legacy behavior was simpler than refactoring error handling in every caller during a "build foundation" phase.
- **DRY extraction for `shared/animation.ts` was premature.** The two rAF loops LOOK similar but have meaningfully different stop semantics. Helper is in place for Phase 6; forcing migration now would have required refactoring unrelated state-reset code.
- **Hand-written types scale.** Each blueprint's routes file is ~100-300 lines; typing the responses took ~2 minutes per endpoint and surfaced a few latent mutation patterns (e.g. `state.segData.audio_url` gets overwritten client-side with a proxy URL after the fetch — this is a state mutation anti-pattern worth noting in Phase 4 when `state.ts` is typed).
- **Generic annotations at call sites are "free" for now** because `@ts-nocheck` ignores them, but they document the expected shape and will activate when `@ts-nocheck` is removed per-file.

## Handoff to Phase 4

- **Known-good entry commit**: (this commit's SHA)
- **Prerequisites Phase 4 must not break**:
  - The `@ts-nocheck` on call-site files stays until each is actually typed.
  - `shared/api.ts`, `types/**`, `shared/animation.ts`, `shared/chart.ts` stay typed (no `@ts-nocheck` on them ever).
  - Flask routes remain unchanged. Any API contract drift discovered during Phase 4 typing work goes to bug log §Section 3.
- **Phase 4 tasks per plan**:
  - Flip `noImplicitAny: true` and `strictNullChecks: true` globally at Phase 4 start.
  - Type `segments/state.ts` — the 60-field hub + typed `createOp`, `snapshotSeg`, `finalizeOp`, `markDirty`, `isDirty`, `_findCoveringPeaks`. Declare `SegmentsState` and `DomRefs` interfaces.
  - Type `timestamps/state.ts` similarly.
  - Remove `@ts-nocheck` from both state files.
  - Fix cascade errors in the 28 modules that import `segments/state.ts` — most with `as Segment` or concrete element types; keep `@ts-nocheck` on those until they're individually typed (Phases 5-6).
  - Budget: <15 total `any`/`@ts-ignore`/`!` across repo. Review enforces.
  - Latent bugs expected to surface: B01 (filter saved-view), B05 (split chain UID), and possibly mutation anti-pattern for `state.segData.audio_url` post-fetch.
- **Questions / decisions for Phase 4**:
  - Scope of strictness flip: global (expect ~300 initial errors, most quieted by `@ts-nocheck`) OR project-reference split. Recommend global — `@ts-nocheck` already isolates call-site files.
  - State-field nullability: many fields are `null` by default and populated later. Default to `T | null` for those and use `!` sparingly at genuine invariants.
- **Risks**: the hub typing may cascade too far. Split into 4a (state.ts only, with `as any` boundaries) + 4b (tighten consumers) if error count explodes past ~400.
