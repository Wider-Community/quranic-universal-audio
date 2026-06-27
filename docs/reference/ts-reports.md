# Timestamps reports

Reader-facing issue reporting on the **Timestamps** tab: a visitor (anonymous or
signed-in) flags a problem on the verse they're hearing, an owner resolves it,
and everyone sees persisted flags in the analysis grid. Two surfaces:

- **Drop-up** (footer Report button) — pick a category. `audio` / `other` open an
  inline comment composer (verse-level). `timing` / `tajweed` enter report mode.
  `mapping` is present but deferred (`soon`).
- **Report mode** — an in-grid mode that replaces the waveform with a control
  strip and turns the analysis grid into the click surface, so a contributor
  annotates specific cells without a modal blocking them.

Backed by one SQLite table; the per-reciter shard content is never touched.

## Data model — table `ts_reports`

Migrations: `0025_ts_reports.sql` (table), `0026_ts_reports_hidden.sql`
(`hidden_at` soft delete), `0027_ts_reports_rule_tags.sql` (`selected_rule_tags`).
The legacy `ts_verse_flags` table (`0024`) is superseded and left in place
pending a manual row migration.

One row per `(slug, verse_key, category, target_key, identity)` — identity is
EITHER a signed-in `hf_user_id` OR an anonymous browser `anon_token` (exactly
one). Re-filing the same category+target updates in place (upsert). Key columns:

| Column | Meaning |
|---|---|
| `category` | `audio` · `timing` · `mapping` · `tajweed` · `other` |
| `subtype` | timing `too_long\|too_short\|other`; tajweed `wrong_rule\|missing_rule\|should_be_silent\|should_not_be_silent`; else NULL |
| `target_kind` + `word_index` / `source_letter_index` / `cell_index` / `phoneme_flat_index` / `share_group` | the flexible target descriptor (`verse\|word\|cell\|phoneme\|column\|cell_group`) |
| `target_key` | canonical descriptor string (`kind:wi:sli:ci:pi:sg`) the per-identity unique index keys on |
| `snap_*` | denormalized snapshot of the targeted shard content at create time — the drift fingerprint (no per-cell hash) |
| `selected_rule_tags` | JSON: the internal tajweed tag id(s) the reporter marked wrong (`wrong_rule` only) |
| `comment` | mandatory for `audio`/`mapping`/`other` + `timing.other` + every tajweed; optional otherwise |
| `status` / `resolved_*` | single terminal `resolved` outcome + optional owner note |
| `stale` / `stale_at` | set when a shard regen changed the targeted content |
| `hidden_at` | soft-delete stamp — NULL = visible. Every read filters `hidden_at IS NULL`; re-filing un-hides |

### Grouping (a domain concept, no schema column)

- **Timing** reports group by **word**: every cell flagged in one
  `(slug, verse_key, word_index, category='timing', identity)` is ONE logical
  report — one owner notification, resolved as a unit. Computed from existing
  columns via `repo_ts_reports.word_group_key()`; never a stored `group_key`.
- **Tajweed** reports are **per cell** (each flagged cell is its own report).

Rows stay per-cell either way (so per-cell subtype + comment survive); grouping
lives only in the notify/resolve/display layers.

## Backend

| File | What |
|---|---|
| `inspector/services/db/repo_ts_reports.py` | `create` (upsert), `create_many` (batch, one identity/verse/txn), `resolve` (per id), `resolve_group` (timing word-group, all identities), `delete` (soft), `verse_counts`, `list_for_verse`, `my_reports`, `list_open_for_recheck`, `word_group_key` |
| `inspector/routes/timestamps/reports.py` | thin blueprint over the repo + snapshot + notify (see endpoints below) |
| `inspector/services/ts_reports/ts_target_snapshot.py` | `build_snapshot` (resolve a target → snapshot dict), `recheck_reports_staleness` (post-regen: re-resolve open reports, `mark_stale` the changed; per-category relevant fields; `audio` never stales) |
| `inspector/services/notifications/emit.py` | `notify_owners_ts_report` (optional `source_key` for word-group coalescing) + `notify_reporter_ts_report_resolved` |
| `qua_shared/schemas/wire/ts_reports.py` | wire models + `_validate_report_item` (shared single + batch validation) |

⚠️ The package is `services/ts_reports/` (NOT `services/timestamps/`, which would
collide with the `services.timestamps` attribute bound in `services/__init__.py`).

### Endpoints (`/api/ts/<slug>/reports`)

| Method + path | Body → response | Gate |
|---|---|---|
| `GET /reports` | → `TsReciterReports` (per-verse open/resolved counts) | public |
| `GET /reports/<verse_key>` | → `TsVerseReports` (`?stale=1` owner-only; author redacted) | public |
| `GET /reports/mine` | caller's own (cookie, or `?anon_token=`) | public |
| `POST /reports` | `TsReportCreateRequest` → `TsReport` | `timestamps.report` (anon) |
| `POST /reports/batch` | `TsReportBatchCreateRequest` → `TsReportBatchResult` | `timestamps.report` |
| `POST /reports/<id>/resolve` | `TsReportResolveRequest` → `TsReport` | `timestamps.resolve_report` |
| `POST /reports/<verse_key>/word/<wi>/<cat>/resolve` | `TsReportResolveRequest` → `TsVerseReports` (timing only) | `timestamps.resolve_report` |
| `DELETE /reports/<id>` | soft-delete the caller's own | `timestamps.report` |

Batch create builds each snapshot BEFORE the transaction (shard reads out of the
write window), then `_fan_batch_notifications` fires **one owner notification per
new timing word-group** (`source_key=word_group_key(...)`, coalesced by
`repo_notifications.create`'s `(hf_user_id, source_key)` idempotency) and **one
per new tajweed cell**; re-submitted (`created=False`) rows never notify.
Capabilities: `timestamps.report` (anon-eligible), `timestamps.resolve_report`,
`timestamps.see_reporter_identity`, `timestamps.view_stale_reports` — registered
in `qua_shared/schemas/config/capabilities.py`.

## Frontend (`inspector/frontend/src/tabs/timestamps/`)

| File | What |
|---|---|
| `stores/report-mode.ts` | the mode state machine (`inactive` / `timing` / `tajweed` + subtype), `staged` Map of annotations keyed by cell, `focusedCellKey`, `reportContext`; `enterTiming`/`enterTajweed` (pause playback, snapshot+force display toggles, seed own flags) / `exitReportMode` (restore toggles, `exitLoop`, clear) |
| `stores/ts-reports.ts` | `reportedVerses` (reciter counts → button highlight) + `currentVerseReports` / `loadVerseReports` (the focus verse's reports → in-grid public flags + report-mode seeds) |
| `utils/report-target.ts` | the ONE keying place — `cellKey`/`wordKey`/`targetCellKey` (DOM- and wire-derived keys must agree), `cellTargetFromEl`, `elCellKey`, `elHasTajweed` |
| `utils/cell-model.ts` | threads `cellIndex` (raw `word.cells[]` index = the target's `cell_index`) and `ruleTags` (internal tajweed tag ids = the picker's options) onto rendered cells |
| `components/UnifiedDisplay.svelte` | stamps `data-cell-index`/`-source-letter-index`/`-share-group`/`-has-tj`/`-tj-tags`; a delegated capture-phase click that STAGES (and loops, for timing) instead of seeking; three reactive `report-*` passes (spotlight dim, staged flag, public flag) |
| `components/TimestampsFooterReport.svelte` + `report/ReportMenu.svelte` + `ReportComposer.svelte` | the drop-up: category list, inline audio/other composer, and `onenterMode` → report mode |
| `components/report/ReportControlStrip.svelte` | the strip that replaces the waveform — header + tajweed wrong/missing toggle, staged chips, per-cell annotation editor (timing subtype / tajweed rule picker), Cancel + Submit |
| `services/report-submit.ts` + `reports-client.ts` | build `TsReportBatchCreateRequest` from staged + reconcile removed own reports (`deleteReport`); the fetch client |

Mount: `TimestampsTab.svelte` swaps `<TimestampsWaveform>` ↔ `<ReportControlStrip>`
on `$reportModeActive` in `.waveform-words-row`, and `loadVerseReports` on every
verse change (also exits an active session if the verse moves — report mode is
verse-scoped).

### Flag rendering

The `report-*` classes are toggled **imperatively on a cached node list from a
reactive one-shot, never inside the 60fps `updateHighlights()`** (the disjoint
class names keep the two off each other). `report-dim` (opacity) spotlights
tajweed wrong-rule cells; `report-flag-staged` / `report-flag-public` draw a red
`outline` ring (outline, not box-shadow, so it never collides with the tajweed
underline and never reflows); `report-focused` adds the accent ring. Styles live
in `styles/timestamps.css`; the tooltip line is appended by `_tipTextFor`.

## Invariants / gotchas

- **Pause + loop on entry.** Entering report mode pauses playback; selecting a
  timing cell **sets its loop directly** (not a seek) so the focus verse can't
  auto-advance out of the session.
- **`cell_index` is the raw `word.cells[]` index** (matches backend
  `word_cells(word)`), captured before the hamza-waṣl transform; synthesized
  cells fall back to `source_letter_index`.
- **Phoneme-direct tajweed targeting is deferred** — the FE phoneme index is
  verse-flat while the wire `phoneme_flat_index` is word-local; report mode
  targets cells (which carry the rule via `phoneme_rule_tags`), not phonemes.
- **One key function.** DOM keys (`elCellKey`) and wire keys (`targetCellKey`)
  must agree or public flags won't land on the right cell.
- **dev-remote can't exercise the real endpoints** (the deployed dev Space
  predates this) — drive the FE with Playwright route stubs; the real flow is
  covered by the backend tests.

## Tests

- `inspector/tests/db/test_repo_ts_reports.py` — create/upsert/counts, soft-delete
  + re-file un-hide, `create_many` word-grouping, `resolve_group`.
- `inspector/tests/routes/test_route_ts_reports.py` — gating, redaction, batch
  notification counts (one per timing word, one per tajweed cell), group resolve.
- `qua_shared/tests/test_ts_reports_wire.py` — per-category validators, batch
  models, `selected_rule_tags` gate, single/batch validation parity.
