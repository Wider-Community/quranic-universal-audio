# Stage-1 Bug Log

## Stage 1 final summary — added 2026-04-12

- **Total rows:** 20 (B01-B20, no gaps)
- **Seeded bugs (Section 1):** 4 of 8 still OPEN — B01, B02, B04, B05. Closed this stage: B03 (not-a-bug per code audit), B06 (not-a-bug per Phase 7 audit — segData/segAllData share references), B07 (mitigated via typed shared/accordion helpers), B08 (not-a-bug per Phase 3 route re-read).
- **TS-caught (Section 2):** 3 / 3 CLOSED — B13 (Phase 5), B14 (Phase 5), B17 (Phase 7 — the sole preserved-verbatim latent bug, finally fixed in Block 3).
- **API-drift (Section 3):** 9 / 9 CLOSED — B09-B12 (Phase 4), B15-B16 (Phase 5), B18-B20 (Phase 6). Zero runtime diffs; all were type-level contract alignments against the actual server emit.
- **New introduced (Section 4):** 0 — no regressions observed across 7 phases of typing + sub-foldering + strictness ratchet.
- **Total CLOSED:** 16 / 20.
- **Remaining OPEN, with priority hint for Stage 2 or follow-up work:**
  - **B01** (Filter state saved-view leak) — UX-visible wedge; medium priority. Fix at `inspector/frontend/src/segments/filters.ts:166-168` + `:255-258` — restore `state.segDisplayedSegments` when re-applying filters after a saved view is cleared.
  - **B02** (segData / segAllData chapter-index desync) — data-integrity risk on save; medium-high priority. Two branches in `inspector/frontend/src/segments/edit/delete.ts:30-43` diverge on how they re-index. Unify.
  - **B04** (waveform peaks orphaned after audio-proxy URL rewrite) — cosmetic (black canvas until re-fetch); low-medium. Invalidate `state.segPeaksByAudio` inside `_rewriteAudioUrls` at `inspector/frontend/src/segments/playback/audio-cache.ts:27-40`.
  - **B05** (split chain UID lost on undo) — minor state-loss on undo; low. Restore `state._splitChainUid` alongside `_segSavedChains` in the undo path.

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
| B03 | Validation missing_words `target_seg_index` not re-indexed on manual-fix rows | inspector/static/js/segments/validation.js:386-409 | SEEDED | exploration | CLOSED | a9f8b62 | Moved to Section 5 in Phase 5 as not-a-bug. `target_seg_index` only exists inside `auto_fix`, so the `if (item.auto_fix)` guard correctly covers every occurrence; items without `auto_fix` have no such field. Original exploration row was a misread. |
| B04 | Waveform peaks orphaned after audio-proxy URL rewrite          | inspector/static/js/segments/audio-cache.js:27-31    | SEEDED | exploration    | OPEN   |         | `segAllData.audio_by_chapter` + per-segment `audio_url` rewritten to proxy URLs; `segPeaksByAudio` cache (keyed by original URL) is NOT invalidated → black canvas until re-fetch. |
| B05 | Split chain UID lost on undo                                   | inspector/static/js/segments/state.js:111-112        | SEEDED | exploration    | OPEN   |         | `state._splitChainUid` set but never restored after undo; next history view loses parent/child linkage. |
| B06 | Silence-after staleness if computed without re-render          | inspector/static/js/segments/filters.js:25-41        | SEEDED | exploration    | CLOSED | 7ce3bc2 | **Not a bug** — re-audited in Phase 7 under strict typing. `state.segData.segments = state.segAllData.segments.filter(...)` (see `segments/data.ts:241`) returns references to the SAME segment objects, so mutations to `seg.silence_after_ms` on `segAllData` are visible via `segData` immediately. No stale-display path. |
| B07 | Validation accordion half-state when some categories null      | inspector/static/js/segments/validation.js:72-76     | SEEDED | exploration    | CLOSED | a9f8b62 | Moved to Section 5 in Phase 5 — mitigated via extracted `shared/accordion.ts` helpers + existing `cat.items.length === 0` skip guard in the render loop. Half-state cannot occur in practice. |
| B08 | /api/seg/edit-history returns JSONL but JS calls r.json()      | inspector/frontend/src/segments/data.ts:138          | SEEDED | exploration    | CLOSED | phase-3 | **Not a bug** — the Flask route `seg_edit_history` reads `edit_history.jsonl` server-side, parses each line, and returns `jsonify({batches, summary})` (one JSON object). The exploration agent misread the route. Re-verified at `inspector/routes/segments_validation.py:63-151`. `r.json()` is correct. `fetchJsonl` helper consequently not needed and was omitted from `shared/api.ts`. |

## Section 2 — TypeScript-caught

| ID | Title | File:Line | TSC rule | Phase | Status | Fix-SHA | Notes |
|----|-------|-----------|----------|-------|--------|---------|-------|
| B13 | `renderValidationPanel` re-reads `state.segValidation` inside deferred rAF after a reciter change could null it | inspector/frontend/src/segments/data.ts:194 | `strictNullChecks` | 5 | CLOSED | a9f8b62 | The rAF callback inside `onSegChapterChange` referenced `state.segValidation` that TSC flagged as possibly null at callback-time (outer guard is at deferral-time). Added an inner `if (!state.segValidation) return;` — prevents a theoretical NPE on rapid reciter-change race. Zero runtime diff in the common path. |
| B14 | `silence_after_ms` domain type was `number?` but code writes literal `null` | inspector/frontend/src/types/domain.ts:48-53, inspector/frontend/src/segments/filters.ts:38-42 | `strictNullChecks` | 5 | CLOSED | a9f8b62 | `computeSilenceAfter` assigns `null` on no-neighbour (pre-existing behavior). Type was tightened to `number \| null`. All consumers use `!= null` already, so no runtime diff. |
| B17 | Timestamps-tab "Boundary Mismatches" tooltip reads `i.ts_ms` / `i.seg_ms`, but server only emits `{side, diff_ms, label}` for that category. Tooltip silently renders `undefined ms vs undefined ms`. | inspector/frontend/src/timestamps/validation.ts:54-61 | `noImplicitAny` (surfaced while typing `TsBoundaryMismatch`) | 6 | CLOSED | 2bf6efc | Fixed in Phase 7 — tooltip now reads `${i.side} boundary drift: ${i.diff_ms}ms` against actual server fields. Removed the `(i: any)` cast + eslint-disable. See Section 5. |

## Section 3 — API-drift findings (authored while writing `types/api.ts`)

| ID | Endpoint | Drift summary | Python route:line | types/api.ts:line | Phase | Status | Resolution |
|----|----------|---------------|--------------------|---------------------|-------|--------|------------|
| B09 | /api/seg/data, /api/seg/all | `Segment` missed `has_repeated_words?: boolean` and `phonemes_asr?: string` — both persisted by `services/save.py` and read by `services/validation.py` and the client's `_classifySegCategories` / `snapshotSeg`. | inspector/services/save.py:107-122, inspector/services/validation.py:122-318 | inspector/frontend/src/types/domain.ts:24-50 | 4 | CLOSED | Added both fields as optional on `Segment`. No runtime change. |
| B10 | /api/seg/data, /api/seg/all | `Segment` missed legacy `ignored?: boolean` fallback used by `validation/categories.ts:_isIgnoredFor` for pre-`ignored_categories` rows. | inspector/frontend/src/segments/validation/categories.ts:41 | inspector/frontend/src/types/domain.ts:24-50 | 4 | CLOSED | Added `ignored?: boolean` with a doc comment flagging it as back-compat. |
| B11 | /api/ts/data | `PhonemeInterval` missed `geminate_start?` / `geminate_end?` — emitted by `mfa_aligner/app.py:605-607` and consumed by `timestamps/playback.ts`, `timestamps/unified-display.ts`. | mfa_aligner/app.py:605-607 | inspector/frontend/src/types/domain.ts:158-168 | 4 | CLOSED | Added both as optional booleans. |
| B12 | /api/surah-info | `SurahInfo` declared `{en, ar}`; server returns `{name_en, name_ar, num_verses}` (see `services/data_loader.py:267-268`), which is what `shared/surah-info.ts:surahOptionText` actually reads. | inspector/services/data_loader.py:267-268 | inspector/frontend/src/types/domain.ts:228-234 | 4 | CLOSED | Renamed fields on `SurahInfo` to match server payload. |
| B15 | /api/seg/config | `SegConfigResponse.accordion_context` typed as `Record<string, number>`, but `inspector/config.py:70-79` defines `ACCORDION_CONTEXT` with string values (`"hidden"`, `"shown"`, `"next_only"`) and the route jsonifies the dict directly. State hub `_accordionContext: Record<string, string>` was correct; the `api.ts` type was off. Surfaced by Sonnet review of Phase 5. | inspector/config.py:70-79 | inspector/frontend/src/types/api.ts:107 | 5 | CLOSED | Changed to `Record<string, string>`. Prevents a blocker in Phase 6 when `segments/index.ts` is typed and assigns `cfg.accordion_context → state._accordionContext`. |
| B16 | /api/seg/validate | `SegValMissingVerseItem.msg` typed optional; server emits literal `"missing verse"` unconditionally at `inspector/services/validation.py`. Flagged by Sonnet nit review. | inspector/services/validation.py | inspector/frontend/src/types/domain.ts:269 | 5 | CLOSED | Tightened to required `msg: string`. All consumers already handle it safely. |
| B18 | POST /api/seg/segment-peaks | `ObserverPeaksQueueItem` wire shape wasn't declared anywhere; the IntersectionObserver pipeline was accumulating untyped `{url, start_ms, end_ms}` objects and shipping them directly as `segments:[]`. | inspector/services/peaks.py | inspector/frontend/src/segments/state.ts:133-140 | 6 | CLOSED | Added `ObserverPeaksQueueItem` to the state-hub types. Field names match the route's payload contract exactly so the queue can still be sent as `segments:[...]` with zero translation. |
| B19 | GET /api/seg/peaks / /api/seg/segment-peaks | `AudioPeaks.peaks` and `SegmentPeaks.peaks` were typed as `number[]` but the server emits `[[min, max], ...]` (2-tuple pairs) — see `services/peaks.py`. Consumer already correctly indexes `peaks[i][0]` / `peaks[i][1]`; type just didn't match reality. | inspector/services/peaks.py | inspector/frontend/src/types/domain.ts:137-149 | 6 | CLOSED | Introduced `type PeakBucket = [number, number]` and changed both peaks fields to `PeakBucket[]`. Zero runtime diff; matches actual consumer access pattern. |
| B20 | GET /api/seg/audio-cache-status | Response shape was unspecified; consumers in `segments/audio-cache.ts` were reading `{cached_count, total, cached_bytes, downloading, download_progress}` untyped. `download_progress` nests `{total, downloaded, complete}` per `services/audio_proxy.py`. | inspector/services/audio_proxy.py:50 | inspector/frontend/src/types/api.ts:251-262 | 6 | CLOSED | Declared `SegAudioCacheStatusResponse` with the exact shape the server emits, including the nested `download_progress` object. |

## Section 4 — New bugs introduced by refactor

_No rows yet — review agents append if regressions appear in the per-phase gate._

| ID | Title | File:Line | Introduced-in-phase | Detected-in-phase | Status | Fix-SHA |
|----|-------|-----------|---------------------|-------------------|--------|---------|

## Section 5 — Closed

| ID | Origin section | Fix summary | Fix-SHA | Phase |
|----|----------------|-------------|---------|-------|
| B08 | Section 1 | Not a bug — `/api/seg/edit-history` returns `{batches, summary}` as JSON; the server parses JSONL internally. `fetchJsonl` helper omitted. | ef53776 | 3 |
| B03 | Section 1 | Not a bug — `target_seg_index` lives inside `auto_fix`, so the `if (item.auto_fix)` guard correctly covers the only place that index exists on a `missing_words` row. Items without `auto_fix` have no `target_seg_index` field to re-index. Verified while typing `_forEachValItem` in `validation/index.ts`; server emit in `services/validation.py:375-394` confirms `target_seg_index` is only nested in `auto_fix`. | a9f8b62 | 5 |
| B07 | Section 1 | Mitigated — extracted accordion primitives to `shared/accordion.ts` (`collapseSiblingDetails`, `capturePanelOpenState`, `restorePanelOpenState`) used by the now-typed `validation/index.ts`. The "half-state" concern in the original note was speculative: the render loop already skips empty categories (`if (!cat.items \|\| cat.items.length === 0) return`), and `restoreValPanelState` silently skips categories that no longer have a `<details>` element. No runtime fix needed; behavior documented via the typed shared API. | a9f8b62 | 5 |
| B17 | Section 2 | Tooltip rewritten to use actual server fields (`i.side`, `i.diff_ms`): `"${i.side} boundary drift: ${i.diff_ms}ms"`. Removed the `(i: any)` cast + eslint-disable. `TsBoundaryMismatch` now type-checks the consumer without the escape hatch. | 2bf6efc | 7 |
| B06 | Section 1 | Not a bug — `segData.segments = segAllData.segments.filter(...)` shares object references, so `computeSilenceAfter`'s in-place mutations are immediately visible via `segData`. Re-audited under Phase 7 strict typing. | 7ce3bc2 | 7 |
