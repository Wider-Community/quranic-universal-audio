# Timestamps reports

Reader-facing issue reporting on the **Timestamps** tab: a visitor (anonymous or
signed-in) flags a problem on the verse they're hearing, an owner resolves it,
and everyone sees persisted flags in the analysis grid. Two surfaces:

- **Drop-up** (footer Report button) — pick a category, in order `timing` →
  `tajweed` → `phonemes` → `silence` → `audio` → `other`. `audio` / `other` open an
  inline comment composer (verse-level); `timing` / `tajweed` / `phonemes` /
  `silence` enter report mode (`tajweed` + `silence` expand to subtype rows first).
  `mapping` is a valid backend category but not surfaced — kept as
  `MAPPING_CATEGORY` in `domain/report-categories.ts` for if the letter↔sound flow
  is revisited.
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
| `category` | `audio` · `timing` · `mapping` · `tajweed` · `phonemes` · `silence` · `other` |
| `subtype` | tajweed: `wrong_rule\|missing_rule\|should_be_silent\|should_not_be_silent`; silence: `pause_boundary\|pause_wasl\|pause_missed`; else NULL |
| `timing_onset` / `timing_offset` | timing (and silence `pause_boundary`): each `early\|late\|NULL` (NULL = that boundary is fine), ≥1 set. The human label (too short/long, shifted, starts/finishes early/late) is derived via `qua_shared...ts_reports.timing_label()` — never stored |
| `target_kind` + `word_index` / `source_letter_index` / `cell_index` / `phoneme_flat_index` / `share_group` | the flexible target descriptor (`verse\|word\|cell\|phoneme\|column\|cell_group\|gap`). `phonemes` reports only target `phoneme`. **`silence` reports target a `gap`** — the word-boundary between `word_index` and `word_index+1`, keyed on the preceding word (only `word_index` is set). A cross-word merger/bridge phoneme has `phoneme_flat_index = -1` (see Bridge phonemes) |
| `target_key` | canonical descriptor string (`kind:wi:sli:ci:pi:sg`, **plus `:subtype` for tajweed only**) the per-identity unique index keys on — built in `repo_ts_reports.target_key()`. Timing/phonemes/**silence** are subtype-free in the key → one report per target+identity (so a gap holds **one** silence stance per user — last write wins) |
| `snap_*` | denormalized snapshot of the targeted shard content at create time — the drift fingerprint (no per-cell hash). Includes `snap_onset_ms`/`snap_offset_ms`, the target's boundary ms for timing + silence-gap staleness |
| `selected_rule_tags` | JSON: the internal tajweed tag id(s) the reporter marked wrong (`wrong_rule` only) |
| `comment` | mandatory for `audio`/`mapping`/`other` + every tajweed; optional for timing; never for phonemes or silence |
| `status` / `resolved_*` | single terminal `resolved` outcome + optional owner note |
| `stale` / `stale_at` | set when a shard regen changed the targeted content (see Staleness below) |
| `hidden_at` | soft-delete stamp — NULL = visible. Every read filters `hidden_at IS NULL`; re-filing un-hides |

### Grouping (a domain concept, no schema column)

- **Timing** and **phonemes** reports group by **word**: every cell/phoneme
  flagged in one `(slug, verse_key, word_index, category, identity)` is ONE logical
  report — one owner notification, resolved as a unit via the
  `/word/<wi>/<category>/resolve` endpoint. Computed from existing columns via
  `repo_ts_reports.word_group_key()`; never a stored `group_key`. The route
  word-grouped set is `_WORD_GROUPED = {timing, phonemes}`.
- **Tajweed** reports are **per cell PER subtype** — the same cell can carry both
  a `wrong_rule` and a `missing_rule` report (two rows, two notifications). The
  `subtype` rides in `target_key` for tajweed only, so same cell + same subtype
  still upserts. No SQL migration: the unique index is unchanged; the key string
  carries the distinction.
- **Silence** reports are **per gap** (one stance per boundary per identity) and
  each fires its own owner notification (the batch `else` branch, one-per-gap). The
  three subtypes share the subtype-free gap `target_key`, so switching subtype on
  the same gap upserts.

Rows stay per-cell either way (so per-cell subtype + comment survive); grouping
lives only in the notify/resolve/display layers.

### Bridge phonemes (cross-word mergers)

A cross-word merger (idgham / iltiqaa) phoneme sits in the gap between two words.
The FE renderer stamps it with `phoneme_flat_index = -1` and `word_index` = the
word it renders **before** (the following word for a cross-word idgham). Since at
most one bridge renders before any word, `(word_index, -1)` is already a unique
`kind='phoneme'` key — no schema change. Such a report groups under that following
word. The snapshot resolver (`_bridge_phone_for_target`) re-finds the merger phone
by walking each word's `phones[]` for a row carrying a `bridge` rule (slot 5),
mapping it to `wi` when it is the word's first phone else `wi+1` (the iltiqaa-kasra
connector is found via its cell tag on the preceding word).

### Staleness (per-category, on shard regen)

`recheck_reports_staleness` re-resolves every open report against the new shard and
`mark_stale`s only those whose **category-relevant** content changed (`audio` never
stales). For **timing**, that is the targeted cell's identity (chars/role) changing
OR a boundary the report flagged moving: if `onset` is set and the target's start ms
shifted by more than `config.TS_REPORT_BOUNDARY_STALE_MS` (default 100), or likewise
`offset` and the end ms — staled for owner re-check (NOT auto-resolved). A pure ms
shift on a boundary the report did **not** flag does not stale it. The boundary ms
are captured at create in `snap_onset_ms`/`snap_offset_ms`. For **phonemes**, the
targeted phone's identity (`chars` / `role` / rule `tag`, incl. a bridge's merger
rule) changing — or the phone vanishing — stales it.

**Silence reports don't just stale, they AUTO-RESOLVE** when the regen confirms
them (`_silence_action`, gap-present = `offset_ms > onset_ms` from the gap
snapshot): a `pause_missed` resolves once a gap appears at its boundary, a
`pause_wasl` (and a `pause_boundary` whose gap vanished entirely) once the gap is
gone. A `pause_boundary` whose gap remains stales on a flagged-boundary shift past
the threshold (like timing). A vanished boundary (word structure changed) stales for
owner re-check. Auto-resolve goes through `repo_ts_reports.resolve_auto` (system
resolver, `resolved_by_*` NULL, the reason in `resolver_comment`) and notifies
**both** owners and the (signed-in) reporter via `notify_ts_report_auto_resolved` —
all inside the regen transaction (`durable_transaction` is nesting-safe).

## Visibility

`timing` grid flags + the verse-level `audio`/`other`/`mapping` reports are
**public** — returned to every viewer. `silence` gap flags are **public** too. `tajweed` + `phonemes` flags are
**non-public**: the repo (`_visibility_filter`, applied in `verse_counts` +
`list_for_verse`) returns them only to the reporter (matched by `hf_user_id` or
`anon_token`) or to a caller holding `timestamps.view_nonpublic_reports`
(maintainer + owner by default). Non-holders never receive those rows or their
counts (true hide, not just un-rendered) — so the FE simply renders what it gets.
The read endpoints pass an **existing** anon token (never minting one — see
`peekAnonToken`) so an anonymous reporter still sees their own non-public flags.

## Backend

| File | What |
|---|---|
| `inspector/services/db/repo_ts_reports.py` | `create` (upsert), `create_many` (batch, one identity/verse/txn), `resolve` (per id), `resolve_group` (timing/phoneme word-group, all identities), `resolve_auto` (system-resolve a silence report on regen), `delete` (soft), `verse_counts` + `list_for_verse` (both take the viewer ctx + `_visibility_filter`), `my_reports`, `list_open_for_recheck`, `word_group_key` |
| `inspector/routes/timestamps/reports.py` | thin blueprint over the repo + snapshot + notify (see endpoints below) |
| `inspector/services/ts_reports/ts_target_snapshot.py` | `build_snapshot` (resolve a target → snapshot dict, incl. the `gap` kind), `_silence_action` (silence resolve/stale decision), `recheck_reports_staleness` (post-regen: re-resolve open reports — `mark_stale` the changed, auto-resolve + notify the agreed silence ones; `audio` never stales) |
| `inspector/services/notifications/emit.py` | `notify_owners_ts_report` (optional `source_key` for word-group coalescing), `notify_reporter_ts_report_resolved`, `notify_ts_report_auto_resolved` (reporter + owners, regen auto-resolve) |
| `qua_shared/schemas/wire/ts_reports.py` | wire models + `_validate_report_item` (shared single + batch validation) |

⚠️ The package is `services/ts_reports/` (NOT `services/timestamps/`, which would
collide with the `services.timestamps` attribute bound in `services/__init__.py`).

### Endpoints (`/api/ts/<slug>/reports`)

| Method + path | Body → response | Gate |
|---|---|---|
| `GET /reports` | → `TsReciterReports` (per-verse open/resolved counts; non-public counts filtered by viewer) | public |
| `GET /reports/<verse_key>` | → `TsVerseReports` (`?stale=1` owner-only; author redacted; non-public rows filtered by viewer) | public |
| `GET /reports/mine` | caller's own (cookie, or `?anon_token=`) | public |
| `POST /reports` | `TsReportCreateRequest` → `TsReport` | `timestamps.report` (anon) |
| `POST /reports/batch` | `TsReportBatchCreateRequest` → `TsReportBatchResult` | `timestamps.report` |
| `POST /reports/<id>/resolve` | `TsReportResolveRequest` → `TsReport` | `timestamps.resolve_report` |
| `POST /reports/<verse_key>/word/<wi>/<cat>/resolve` | `TsReportResolveRequest` → `TsVerseReports` (timing/phonemes) | `timestamps.resolve_report` |
| `DELETE /reports/<id>` | soft-delete the caller's own | `timestamps.report` |

Batch create builds each snapshot BEFORE the transaction (shard reads out of the
write window), then `_fan_batch_notifications` fires **one owner notification per
new timing/phoneme word-group** (`source_key=word_group_key(...)`, coalesced by
`repo_notifications.create`'s `(hf_user_id, source_key)` idempotency) and **one
per new tajweed cell / silence gap**; re-submitted (`created=False`) rows never notify.
Capabilities: `timestamps.report` (anon-eligible), `timestamps.resolve_report`,
`timestamps.see_reporter_identity`, `timestamps.view_stale_reports`,
`timestamps.view_nonpublic_reports` (maintainer-default; gates seeing tajweed +
phoneme flags) — registered in `qua_shared/schemas/config/capabilities.py`.

## Frontend (`inspector/frontend/src/tabs/timestamps/`)

| File | What |
|---|---|
| `stores/report-mode.ts` | the mode state machine (`inactive` / `timing` / `tajweed` + subtype / `phonemes` / `silence` + subtype), `staged` Map keyed by cell, `focusedCellKey`, `reportContext`; `enterTiming` / `enterTajweed` / `enterSilence` pause + force letters-only (snapshot/restore `showLetters`/`showPhonemes`), tajweed additionally `forceAllTajweedEnabled`; `enterPhonemes` instead forces `showPhonemes` ON and leaves `showLetters` at the user's setting (the inverse). Seed own flags by category+subtype; a `StagedPhoneme` carries just the target and a `StagedSilence` carries the gap + (for `pause_boundary`) onset/offset — both complete on select (binary silence subtypes too); `focusCell`/`isStagedComplete` auto-discard an incomplete cell on focus-move; `exitReportMode` restores display + tajweed snapshots, `exitLoop`, clears |
| `stores/tajweed-settings.ts` | `forceAllTajweedEnabled()` / `restoreTajweedSettings()` — transient (non-persisted) bulk enable used by tajweed report mode |
| `stores/ts-reports.ts` | `reportedVerses` (reciter counts → button highlight) + `currentVerseReports` / `loadVerseReports` (the focus verse's reports → in-grid public flags + report-mode seeds) |
| `utils/report-target.ts` | the ONE keying place — `cellKey`/`wordKey`/`gapKey`/`targetCellKey` (DOM- and wire-derived keys must agree), `cellTargetFromEl`, `elCellKey`, `elHasTajweed`. A gap tile (pause bridge / missed slot) carries `data-gap-word-index` → `gapKey` |
| `utils/rendered-blocks.ts` | builds the analysis grid — `RenderedPauseBridge.fromWordIndex` (the gap's preceding word) + per-`RenderedUnit` `gapWordIndex`/`missedMark` for the **missed-pause slot** at each contiguous word boundary (`splitWaqf` lifts the preceding word's stop sign, else `\|\|`) |
| `utils/cell-model.ts` | threads `cellIndex` (raw `word.cells[]` index = the target's `cell_index`) and `ruleTags` (internal tajweed tag ids = the picker's options) onto rendered cells |
| `components/UnifiedDisplay.svelte` | stamps `data-cell-index`/`-source-letter-index`/`-share-group`/`-has-tj`/`-tj-tags`/`-phoneme-flat-index`/`-gap-word-index` (pause bridges + missed slots); a delegated capture-phase click that STAGES via `focusCell` (auto-discard) instead of seeking. Timing + **silence** loop/seek (silence loops the two words straddling the gap); tajweed/phonemes stage only. Phonemes mode is a multi-select **toggle**. **Silence** spotlights the gap tiles: `pause_boundary`/`pause_wasl` target the existing `.pause-bridge`, `pause_missed` targets the inserted `.missed-slot`; everything else dims (`report-dim` on words + off-type gaps) + inerts. Reactive `report-*` passes (mode-scoped `report-timing`/`-tajweed`/`-phonemes`/`-silence`/`-missed`/`-existing`; staged/focused/public flags). A publicly-flagged missed slot gets a native "Reported missing pause" title. `data-has-tj='1'` ⇐ the cell carries a `ruleTag` (pickable rule) OR a badge/silent name |
| `components/TimestampsFooterReport.svelte` + `report/ReportMenu.svelte` + `ReportComposer.svelte` | the drop-up: category list, inline audio/other composer (fixed-height field so it never reflows the drop-up), and `onenterMode('timing'\|'tajweed'\|'phonemes'\|'silence', subtype?)` → report mode (timing/phonemes enter directly; tajweed + silence expand subtype rows) |
| `components/report/ReportControlStrip.svelte` | the strip that replaces the waveform — header (title + static subtype label), Cancel + Submit, and ONE inline row per staged cell (`label · control · comment · ✕`). Phonemes collapse to ONE row per word of removable chips. **Silence** rows: `pause_boundary` reuses the Start/End onset/offset axes + derived label; `pause_wasl` / `pause_missed` are binary (a static stance label, no control, no comment) |
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
too-long/short — words stay live); in **phonemes**, every `[data-cell-index]`
letter/diacritic cell (only `.mega-phoneme` spans stay live). So only rule-bearing
cells (tajweed), timed letters (timing), or phoneme spans (phonemes) stay
interactive. Because flag rows render only what the backend returns, non-public
tajweed/phoneme flags simply don't appear for non-reporters (no FE gate needed). The `wrong_rule` rule-picker offers
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
  `reportModeActive`). Selecting a **timing** cell narrows the loop to that cell,
  and selecting a **silence** gap loops the two words straddling it (audio context);
  selecting a **tajweed** or **phonemes** cell does NOT touch the loop or play/pause
  (you judge a rule/phoneme against the running verse, not an isolated cell). Only a
  **manual** ayah/reciter change moves the focus verse → `_syncVerseReports` exits
  the session + discards staged. `exitReportMode` clears the loop.
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
- **Display forcing differs by mode.** `timing` + `tajweed` + `silence` force
  letters-only (the click surface is cells / gap tiles, not phonemes) — both footer
  toggles are locked. `phonemes` mode forces the phoneme row ON and leaves the
  letters row at the user's setting, so the letters toggle stays operable while the
  phonemes toggle is locked on.
- **Missed-pause slots are always in the DOM, invisible until needed.** A
  `.missed-slot` renders at every contiguous word boundary but is `display:none` at
  rest; it's revealed (spotlit, clickable) only in `pause_missed` report mode, or
  shown with a red ring + native title for ALL viewers when publicly flagged — so the
  "red border in the gap with no cell there" works without re-rendering the grid.
- **One key function.** DOM keys (`elCellKey`) and wire keys (`targetCellKey`)
  must agree or public flags won't land on the right cell.
- **dev-remote can't exercise the real endpoints** (the deployed dev Space
  predates this) — drive the FE with Playwright route stubs; the real flow is
  covered by the backend tests.

## Tests

- `inspector/tests/db/test_repo_ts_reports.py` — create/upsert/counts, soft-delete
  + re-file un-hide, `create_many` word-grouping (timing + phonemes),
  `resolve_group`, bridge-phoneme target uniqueness, visibility filtering of
  non-public counts + rows, silence one-stance-per-gap upsert + public visibility +
  `resolve_auto`.
- `inspector/tests/routes/test_route_ts_reports.py` — gating, redaction, batch
  notification counts (one per timing/phoneme word, one per tajweed cell), group
  resolve (timing + phonemes), non-public visibility (hidden from other viewers,
  shown to the reporter + a capability holder).
- `inspector/tests/services/test_ts_target_snapshot.py` — phoneme + bridge-phoneme
  resolution, per-category staleness, and the silence gap resolution + auto-resolve
  decision matrix (`_silence_action`).
- `qua_shared/tests/test_ts_reports_wire.py` — per-category validators (incl.
  phonemes + silence/gap), batch models, `selected_rule_tags` gate, single/batch
  validation parity.
