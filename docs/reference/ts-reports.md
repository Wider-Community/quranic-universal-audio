# Timestamp reports

Timestamp reports address stable native entities in shard v12. Renderer positions are never persisted.

## Target contract

Every report target contains:

```json
{
  "reading_id": "r12",
  "kind": "sound",
  "target_id": "41"
}
```

`kind` is one of:

| Kind | `target_id` |
| --- | --- |
| `verse` | Verse ref such as `2:255`. |
| `word` | Native word ID. |
| `column` | Native cell-column ID. |
| `sound` | Native sound ID. |
| `group` | Shared package group key made from the native group's ordered column IDs. |
| `boundary` | Native boundary ID. |
| `bridge` | Native merger-bridge ID. |

The target is scoped to the reciter, chapter, and `reading_id`. A DOM index or repeated glyph is insufficient identity.

## Snapshot and staleness

Creation stores a snapshot beside the target:

```json
{
  "native_schema_version": 2,
  "shard_schema_version": 12,
  "native": {},
  "timing": {"start_ms": 1200, "end_ms": 1300}
}
```

`native` contains the target-specific identity/content fingerprint. `timing` records the absolute interval when the report was created, or `null` for an untimed target. Regeneration resolves the same native target and compares the snapshot; it never searches for the nearest cell or first matching glyph.

## Categories

| Category | Allowed target kinds | Additional data |
| --- | --- | --- |
| `audio` | verse, word | Mandatory comment. |
| `timing` | word, column, sound, group, boundary, bridge | At least one onset/offset direction. |
| `tajweed` | column, sound, group, bridge | `wrong_rule` or `missing_rule`; mandatory comment. |
| `phonemes` | sound, bridge | Selection/comment policy from the report UI. |
| `silence` | boundary | `pause_boundary`, `pause_wasl`, or `pause_missed`. |
| `other` | any native kind | Mandatory comment. |

Timing directions are `early` or `late`. `pause_boundary` also uses onset/offset; the other silence subtypes are binary.

## Frontend capture

`TimedAnalysisRow` wraps `@quranic-phonemizer/cells` and indexes its public `data-qc-*` hooks once. Playback keeps sound-derived intervals, while a timed column report uses the native report interval: its sparse exact override, or the union of its source-unit letter timing and sound timing. This keeps a sounding letter's report loop aligned with the backend snapshot. Native columns, groups, and bridges that have no report interval remain in the identity cache as report-only entities: their owning word/boundary span is used for interaction context, but they do not participate in playback highlighting or looping. Report mode turns a clicked native hook into the discriminated target above and asks the backend to capture the authoritative snapshot.

The shared renderer owns the identity hooks and documented native group key. The Inspector owns report selection, dimming, comments, rule selection, tooltips, and audio intervals.

## Storage

The live `ts_reports` table stores:

- `reading_id`, `target_kind`, `target_id`, and canonical `target_key`;
- `snapshot_json`;
- category/subtype/timing directions;
- reporter identity, comment, selected rule IDs, status, staleness, and resolution fields.

It contains no cell index, source-letter index, flat phoneme index, or synthetic share-group coordinate.

## Migration

`scripts/migrations/migrate_ts_reports_v12.py` is the one-time cutover mapper. For each legacy report it loads the old chapter and its staged v12 counterpart, resolves exactly one native target, and writes `ts_report_v12_map`.

Migration 28 refuses to replace the report table while any row is absent from that map. Ambiguous or unresolved rows block cutover. There is no fallback mapping.

Boot also calls `services.ts_reports.legacy_target_migration.prepare_native_report_map` before the SQL runner. This recovers a deployed v27 database after v12 shards are already active: it resolves each retained canonical verse/word position against the current v12 document and verifies the stored text, role, status, and timing fingerprints before writing the same guarded map. Any missing, drifted, or ambiguous target aborts boot without a partial map. After migrations, a schema assertion prevents native report code from running over a legacy table.

The database, v12 Inspector, and active shard manifest move in the same cutover. Afterward only native targets are accepted by request validation and persistence.

## Routes

The report API remains under `/api/ts/<slug>/reports`:

- list reciter counts;
- list one verse's reports;
- create one or a batch;
- resolve one or all matching native targets;
- delete the caller's report.

Wire models live in `qua_shared.schemas.wire.ts_reports`; persistence lives in `inspector.services.db.repo_ts_reports`; snapshot resolution lives in `inspector.services.ts_reports.ts_target_snapshot`.

## Verification

Cutover requires:

- every existing report mapped exactly once;
- row counts and report metadata preserved by migration 28;
- all positional columns absent afterward;
- target IDs resolving in the staged v12 document;
- snapshot round trips and staleness checks passing;
- report capture working for every native target kind exposed by the renderer.
