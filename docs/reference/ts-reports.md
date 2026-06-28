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
| `subtype` | tajweed only: `wrong_rule\|missing_rule\|should_be_silent\|should_not_be_silent`; else NULL |
| `timing_onset` / `timing_offset` | timing only: each `early\|late\|NULL` (NULL = that boundary is fine), ≥1 set. The human label (too short/long, shifted, starts/finishes early/late) is derived via `qua_shared...ts_reports.timing_label()` — never stored |
| `target_kind` + `word_index` / `source_letter_index` / `cell_index` / `phoneme_flat_index` / `share_group` | the flexible target descriptor (`verse\|word\|cell\|phoneme\|column\|cell_group`) |
| `target_key` | canonical descriptor string (`kind:wi:sli:ci:pi:sg`, **plus `:subtype` for tajweed**) the per-identity unique index keys on — built in `repo_ts_reports.target_key()`. Timing is subtype/axis-free → one timing report per target+identity |
| `snap_*` | denormalized snapshot of the targeted shard content at create time — the drift fingerprint (no per-cell hash). Includes `snap_onset_ms`/`snap_offset_ms`, the target's boundary ms for timing staleness |
| `selected_rule_tags` | JSON: the internal tajweed tag id(s) the reporter marked wrong (`wrong_rule` only) |
| `comment` | mandatory for `audio`/`mapping`/`other` + every tajweed; optional for timing |
| `status` / `resolved_*` | single terminal `resolved` outcome + optional owner note |
| `stale` / `stale_at` | set when a shard regen changed the targeted content (see Staleness below) |
| `hidden_at` | soft-delete stamp — NULL = visible. Every read filters `hidden_at IS NULL`; re-filing un-hides |

### Grouping (a domain concept, no schema column)

- **Timing** reports group by **word**: every cell flagged in one
  `(slug, verse_key, word_index, category='timing', identity)` is ONE logical
  report — one owner notification, resolved as a unit. Computed from existing
  columns via `repo_ts_reports.word_group_key()`; never a stored `group_key`.
- **Tajweed** reports are **per cell PER subtype** — the same cell can carry both
  a `wrong_rule` and a `missing_rule` report (two rows, two notifications). The
  `subtype` rides in `target_key` for tajweed only, so same cell + same subtype
  still upserts. No SQL migration: the unique index is unchanged; the key string
  carries the distinction.

Rows stay per-cell either way (so per-cell subtype + comment survive); grouping
lives only in the notify/resolve/display layers.

### Staleness (per-category, on shard regen)

`recheck_reports_staleness` re-resolves every open report against the new shard and
`mark_stale`s only those whose **category-relevant** content changed (`audio` never
stales). For **timing**, that is the targeted cell's identity (chars/role) changing
OR a boundary the report flagged moving: if `onset` is set and the target's start ms
shifted by more than `config.TS_REPORT_BOUNDARY_STALE_MS` (default 100), or likewise
`offset` and the end ms — staled for owner re-check (NOT auto-resolved). A pure ms
shift on a boundary the report did **not** flag does not stale it. The boundary ms
are captured at create in `snap_onset_ms`/`snap_offset_ms`.

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
| `stores/report-mode.ts` | the mode state machine (`inactive` / `timing` / `tajweed` + subtype fixed at entry), `staged` Map keyed by cell, `focusedCellKey`, `reportContext`; `enterTiming` / `enterTajweed` both pause + force letters-only (snapshot/restore `showLetters`/`showPhonemes`) — phonemes are never a target; tajweed additionally `forceAllTajweedEnabled` so every legend colour shows. Seed own flags by category+subtype; `focusCell`/`isStagedComplete` auto-discard an incomplete cell on focus-move; `exitReportMode` restores display + tajweed snapshots, `exitLoop`, clears |
| `stores/tajweed-settings.ts` | `forceAllTajweedEnabled()` / `restoreTajweedSettings()` — transient (non-persisted) bulk enable used by tajweed report mode |
| `stores/ts-reports.ts` | `reportedVerses` (reciter counts → button highlight) + `currentVerseReports` / `loadVerseReports` (the focus verse's reports → in-grid public flags + report-mode seeds) |
| `utils/report-target.ts` | the ONE keying place — `cellKey`/`wordKey`/`targetCellKey` (DOM- and wire-derived keys must agree), `cellTargetFromEl`, `elCellKey`, `elHasTajweed` |
| `utils/cell-model.ts` | threads `cellIndex` (raw `word.cells[]` index = the target's `cell_index`) and `ruleTags` (internal tajweed tag ids = the picker's options) onto rendered cells |
| `components/UnifiedDisplay.svelte` | stamps `data-cell-index`/`-source-letter-index`/`-share-group`/`-has-tj`/`-tj-tags`; a delegated capture-phase click that STAGES via `focusCell` (auto-discard) instead of seeking. **Only timing loops/seeks the cell** — tajweed stages only, leaving play/pause + the whole-verse loop untouched. In tajweed only cells stage (words swallowed). Reactive `report-*` passes (`report-dim`+`report-inert` spotlight, staged/focused/public flags). `data-has-tj='1'` ⇐ the cell carries a `ruleTag` (pickable rule) OR a badge/silent name |
| `components/TimestampsFooterReport.svelte` + `report/ReportMenu.svelte` + `ReportComposer.svelte` | the drop-up: category list, inline audio/other composer (fixed-height field so it never reflows the drop-up), and `onenterMode` → report mode |
| `components/report/ReportControlStrip.svelte` | the strip that replaces the waveform — header (title + static subtype label, no toggle), Cancel + Submit, and ONE inline row per staged cell (`label · subtype/rule control · comment · ✕`) |
| `services/report-submit.ts` + `reports-client.ts` | build `TsReportBatchCreateRequest` from staged + reconcile removed own reports (`deleteReport`); the fetch client |

Mount: `TimestampsTab.svelte` swaps `<TimestampsWaveform>` ↔ `<ReportControlStrip>`
on `$reportModeActive` in `.waveform-words-row`, and `loadVerseReports` on every
verse change (also exits an active session if the verse moves — report mode is
verse-scoped).

### Flag rendering

The `report-*` classes are toggled **imperatively on a cached node list from a
reactive one-shot, never inside the 60fps `updateHighlights()`** (the disjoint
class names keep the two off each other). The spotlight dims + inerts
(`report-dim` opacity + `report-inert` `pointer-events:none`, killing click AND
hover tooltip) the cells that can't carry the current report: in tajweed
`wrong_rule`, every cell with `data-has-tj!='1'` (no rule); in **timing**, every
cell with `data-cell-timed!='1'` (a silent letter has no duration to call
too-long/short — words stay live). So only rule-bearing cells (tajweed) or
timed letters (timing) stay interactive. The `wrong_rule` rule-picker offers
only **labelable** tags — sentinels like `silent_unclassified` are dropped
(`ruleHasLabel`), so it never shows a raw tag id; the cell's true rule name still
shows on the grid hover tooltip via `data-tj-rules`. `report-flag-staged` / `report-flag-public` draw a red `outline` ring
(outline, not box-shadow, so it never collides with the tajweed underline and
never reflows); `report-focused` adds the accent ring. Styles live in
`styles/timestamps.css`; the tooltip line is appended by `_tipTextFor`.

## Invariants / gotchas

- **Verse lock for the whole session.** Entering report mode pauses playback and
  `TimestampsTab.armVerseLock()` arms a whole-verse loop (`[verse start, next
  verse start)` — covers the trailing silence). That pin stops free play from
  auto-advancing and suppresses shuffle (`maybeFireShuffle` also bails on
  `reportModeActive`). Selecting a **timing** cell narrows the loop to that cell;
  selecting a **tajweed** cell does NOT touch the loop or play/pause (you judge a
  rule against the running verse, not an isolated cell). Only a **manual**
  ayah/reciter change moves the focus verse → `_syncVerseReports` exits the
  session + discards staged. `exitReportMode` clears the loop.
- **Auto-discard incomplete.** Moving focus to another cell drops the previously
  focused annotation when it is still missing a required field (timing subtype /
  tajweed rule pick when >1 option / mandatory comment); `report-submit` re-filters
  defensively. No hard block — keeps flagging frictionless.
- **Subtype is fixed at entry.** The drop-up's `wrong_rule` / `missing_rule` rows
  enter the session with that subtype; the strip shows it as a static label (no
  in-mode toggle). A different subtype on the same cell is a separate session +
  separate report.
- **`cell_index` is the raw `word.cells[]` index** (matches backend
  `word_cells(word)`), captured before the hamza-waṣl transform; synthesized
  cells fall back to `source_letter_index`.
- **Phonemes are hidden in report mode** — both modes force letters-only and
  disable the letters/phonemes footer toggles (`reportModeActive`), so phonemes
  are never a click target. Report mode targets cells (which carry the rule via
  `phoneme_rule_tags`); phoneme-direct targeting stays deferred.
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
