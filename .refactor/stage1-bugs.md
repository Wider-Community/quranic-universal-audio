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
| B08 | /api/seg/edit-history returns JSONL but JS calls r.json()      | inspector/frontend/src/segments/data.ts:138          | SEEDED | exploration    | CLOSED | phase-3 | **Not a bug** — the Flask route `seg_edit_history` reads `edit_history.jsonl` server-side, parses each line, and returns `jsonify({batches, summary})` (one JSON object). The exploration agent misread the route. Re-verified at `inspector/routes/segments_validation.py:63-151`. `r.json()` is correct. `fetchJsonl` helper consequently not needed and was omitted from `shared/api.ts`. |

## Section 2 — TypeScript-caught

_No rows yet — agents append during Phases 3–7 as TSC flags real issues._

| ID | Title | File:Line | TSC rule | Phase | Status | Fix-SHA | Notes |
|----|-------|-----------|----------|-------|--------|---------|-------|

## Section 3 — API-drift findings (authored while writing `types/api.ts`)

| ID | Endpoint | Drift summary | Python route:line | types/api.ts:line | Phase | Status | Resolution |
|----|----------|---------------|--------------------|---------------------|-------|--------|------------|
| B09 | /api/seg/data, /api/seg/all | `Segment` missed `has_repeated_words?: boolean` and `phonemes_asr?: string` — both persisted by `services/save.py` and read by `services/validation.py` and the client's `_classifySegCategories` / `snapshotSeg`. | inspector/services/save.py:107-122, inspector/services/validation.py:122-318 | inspector/frontend/src/types/domain.ts:24-50 | 4 | CLOSED | Added both fields as optional on `Segment`. No runtime change. |
| B10 | /api/seg/data, /api/seg/all | `Segment` missed legacy `ignored?: boolean` fallback used by `validation/categories.ts:_isIgnoredFor` for pre-`ignored_categories` rows. | inspector/frontend/src/segments/validation/categories.ts:41 | inspector/frontend/src/types/domain.ts:24-50 | 4 | CLOSED | Added `ignored?: boolean` with a doc comment flagging it as back-compat. |
| B11 | /api/ts/data | `PhonemeInterval` missed `geminate_start?` / `geminate_end?` — emitted by `mfa_aligner/app.py:605-607` and consumed by `timestamps/playback.ts`, `timestamps/unified-display.ts`. | mfa_aligner/app.py:605-607 | inspector/frontend/src/types/domain.ts:158-168 | 4 | CLOSED | Added both as optional booleans. |
| B12 | /api/surah-info | `SurahInfo` declared `{en, ar}`; server returns `{name_en, name_ar, num_verses}` (see `services/data_loader.py:267-268`), which is what `shared/surah-info.ts:surahOptionText` actually reads. | inspector/services/data_loader.py:267-268 | inspector/frontend/src/types/domain.ts:228-234 | 4 | CLOSED | Renamed fields on `SurahInfo` to match server payload. |

## Section 4 — New bugs introduced by refactor

_No rows yet — review agents append if regressions appear in the per-phase gate._

| ID | Title | File:Line | Introduced-in-phase | Detected-in-phase | Status | Fix-SHA |
|----|-------|-----------|---------------------|-------------------|--------|---------|

## Section 5 — Closed

| ID | Origin section | Fix summary | Fix-SHA | Phase |
|----|----------------|-------------|---------|-------|
| B08 | Section 1 | Not a bug — `/api/seg/edit-history` returns `{batches, summary}` as JSON; the server parses JSONL internally. `fetchJsonl` helper omitted. | _(this phase)_ | 3 |
