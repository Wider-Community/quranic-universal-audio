# Stage-1 Bug Log

Shared append-only document maintained by the orchestrator and every refactor agent during
the TypeScript + Vite migration (Stage 1 only — no Svelte).

All rows have a stable ID (`B01`..`B99`). **Append** new rows to the appropriate section;
**never delete** a row. Status transitions move a row to the Closed section at the bottom
with the fixing commit SHA and phase.

## Legend

- **STATUS**: `OPEN` | `TS-CAUGHT` | `CLOSED` | `DEFERRED`
- **ORIGIN**: `SEEDED` (pre-existing, identified during exploration) | `TS-CAUGHT` (surfaced by typechecker) | `DRIFT` (API contract mismatch found while authoring `types/api.ts`) | `INTRODUCED` (regression from the refactor itself)
- Cite code as `relative/path/from/repo/root.ts:LINE` (use post-Phase-2 paths once `.ts` + sub-foldering lands; pre-Phase-2 rows may still reference `.js`).

## Append protocol

- Orchestrator seeds Section 1 before Phase 0 starts (done).
- Implementation agents append to Sections 2–4 the moment they surface a finding — **before** any fix.
- Review agents append to Section 4 if they spot regressions during the per-phase gate, and verify the phase handoff cites the bug-log diff.
- Fixes go in **separate commits** for bisect-ability (one bug = one commit), unless the fix is a trivial null check landing alongside a type annotation it directly enabled.

---

## Section 1 — Seeded (pre-existing, from Phase 1 exploration)

| ID  | Title                                                          | File:Line                                            | Origin | Found-in-phase | Status | Fix-SHA | Notes |
|-----|----------------------------------------------------------------|------------------------------------------------------|--------|----------------|--------|---------|-------|
| B01 | Filter state saved-view leak                                   | inspector/static/js/segments/filters.js:140-142      | SEEDED | exploration    | OPEN   |         | Saved filter view discarded without restoring `segDisplayedSegments`; UI can wedge showing no segments while `segAllData.segments` still populated. |
| B02 | segData / segAllData chapter-index desync                      | inspector/static/js/segments/edit-delete.js:38-39    | SEEDED | exploration    | OPEN   |         | After splice, chapter indices re-numbered on `segAllData` but `segData` re-assigned elsewhere without the same rewrite; save can persist mismatched indices. |
| B03 | Validation missing_words `target_seg_index` not re-indexed on manual-fix rows | inspector/static/js/segments/validation.js:386-409 | SEEDED | exploration | OPEN |  | Inside `_forEachValItem`, `seg_indices[i]` is always re-indexed (line ~400), but `target_seg_index` is only re-indexed when `item.auto_fix` exists (line ~408). Rows without `auto_fix` keep stale `target_seg_index` after split/merge/delete. Scoped to that one field, not the whole row. |
| B04 | Waveform peaks orphaned after audio-proxy URL rewrite          | inspector/static/js/segments/audio-cache.js:27-31    | SEEDED | exploration    | OPEN   |         | `segAllData.audio_by_chapter` + per-segment `audio_url` rewritten to proxy URLs; `segPeaksByAudio` cache (keyed by original URL) is NOT invalidated → black canvas until re-fetch. |
| B05 | Split chain UID lost on undo                                   | inspector/static/js/segments/state.js:111-112        | SEEDED | exploration    | OPEN   |         | `state._splitChainUid` set but never restored after undo; next history view loses parent/child linkage. |
| B06 | Silence-after staleness if computed without re-render          | inspector/static/js/segments/filters.js:25-41        | SEEDED | exploration    | OPEN   |         | `computeSilenceAfter` mutates segments in `segAllData`; `segData` (chapter view) is a filtered copy and may show stale `silence_after_ms` until next `renderSegList`. |
| B07 | Validation accordion half-state when some categories null      | inspector/static/js/segments/validation.js:72-76     | SEEDED | exploration    | OPEN   |         | `hasAny` check tolerates mixed null/empty categories; panel opens with some sections unrendered → empty accordions. |
| B08 | /api/seg/edit-history returns JSONL but JS calls r.json()      | inspector/static/js/segments/data.js:136             | SEEDED | exploration    | OPEN   |         | Response is newline-delimited JSON; `r.json()` fails or silently returns null. Fixed-by-construction in Phase 3 via `shared/api.fetchJsonl`. |

## Section 2 — TypeScript-caught

_No rows yet — agents append during Phases 3–7 as TSC flags real issues._

| ID | Title | File:Line | TSC rule | Phase | Status | Fix-SHA | Notes |
|----|-------|-----------|----------|-------|--------|---------|-------|

## Section 3 — API-drift findings (authored while writing `types/api.ts`)

_No rows yet — agents append during Phase 3 while mirroring Python response shapes._

| ID | Endpoint | Drift summary | Python route:line | types/api.ts:line | Phase | Status | Resolution |
|----|----------|---------------|--------------------|---------------------|-------|--------|------------|

## Section 4 — New bugs introduced by refactor

_No rows yet — review agents append if regressions appear in the per-phase gate._

| ID | Title | File:Line | Introduced-in-phase | Detected-in-phase | Status | Fix-SHA |
|----|-------|-----------|---------------------|-------------------|--------|---------|

## Section 5 — Closed

_No rows yet — rows move here with commit SHA and closing phase when resolved._

| ID | Origin section | Fix summary | Fix-SHA | Phase |
|----|----------------|-------------|---------|-------|
