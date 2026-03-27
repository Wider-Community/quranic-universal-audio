# Inspector Segments Edit History Plan

Date: 2026-03-28
Scope: `inspector` Segments tab edit-audit design (planning only, no implementation yet)

## Goal
Capture and persist a robust edit history for all Segments-tab edits, including:
- edit type
- fix description
- before and after state
- timestamp (UTC + local)
- time spent on the edit
- whether the edit removed errors
- support for overlapping errors and complex structural edits (split/merge/delete/re-reference)

## Current System Findings

### Save and edit flow
- Client saves chapter-scoped edits via `/api/seg/save/<reciter>/<chapter>`.
- Two save modes exist:
  - `patch` for non-structural edits (index-based updates)
  - `full_replace` for structural edits (replace full chapter segment list)
- Structural edits include trim, split, merge, and delete.
- Reference edits, auto-fix, and ignore currently go through patch behavior.

### Validation categories currently available
- `failed`
- `missing_verses`
- `missing_words`
- `errors` (structural)
- `low_confidence`
- `oversegmented`
- `cross_verse`
- `audio_bleeding`

### Important constraint
`index` is re-assigned after structural edits. Therefore index is not a stable identifier for long-term history. We need a persistent segment ID (`segment_uid`) plus lineage tracking.

## Recommended Storage Strategy
Use an append-only file per reciter:

`data/recitation_segments/<reciter>/edit_history.jsonl`

Reason:
- `detailed.json` is rewritten on save, so embedding a growing history array there is expensive and fragile.
- JSONL is append-friendly, immutable by default, and easy to audit.

## Proposed Data Model

## Top-level record (one row per save batch)
```json
{
  "schema_version": 1,
  "record_type": "save_batch",
  "batch_id": "uuid",
  "reciter": "ali_jaber",
  "chapter": 2,
  "saved_at_utc": "2026-03-28T01:23:45.123Z",
  "saved_at_local": "2026-03-28T12:23:45.123+11:00",
  "timezone": "Australia/Sydney",
  "save_mode": "patch|full_replace",
  "client_session_id": "uuid",
  "actor": { "id": "local_user", "name": null },
  "operations": [],
  "validation_before": {},
  "validation_after": {},
  "batch_error_impact": {
    "removed_any": true,
    "removed_issue_keys": [],
    "added_issue_keys": [],
    "removed_count_by_category": {},
    "added_count_by_category": {}
  },
  "status": "applied|reverted_by_undo_save",
  "reverted_by_batch_id": null
}
```

## Per-operation record (inside `operations`)
```json
{
  "op_id": "uuid",
  "op_seq": 3,
  "op_type": "trim_segment",
  "op_source": "main_list|validation_panel",
  "op_context_category": "missing_words|low_confidence|oversegmented|cross_verse|null",
  "started_at_utc": "2026-03-28T01:22:10.000Z",
  "applied_at_utc": "2026-03-28T01:22:18.200Z",
  "edit_duration_ms": 8200,
  "fix": {
    "kind": "manual|auto_fix|ignore",
    "description": "short human-readable summary"
  },
  "targets_before": [],
  "targets_after": [],
  "lineage": {
    "parent_segment_uids": [],
    "child_segment_uids": []
  },
  "error_impact": {
    "removed_any": true,
    "removed_issue_keys": [],
    "added_issue_keys": [],
    "attribution_mode": "direct|shared_overlap|unknown"
  }
}
```

## Segment snapshot shape (for before/after)
```json
{
  "segment_uid": "seg_01HT...",
  "chapter": 2,
  "entry_ref": "2:7",
  "index_at_edit_time": 10,
  "audio_url": "https://...",
  "time_start": 11180,
  "time_end": 15300,
  "matched_ref": "2:7:10-2:7:12",
  "matched_text": "وَلَهُمْ عَذَابٌ عَظِيمٌ",
  "confidence": 0.99
}
```

## Edit Types To Capture
- `edit_reference`
- `confirm_reference_no_ref_change`
- `trim_segment`
- `split_segment`
- `merge_segments`
- `delete_segment`
- `auto_fix_missing_word`
- `ignore_issue`
- `undo_local_edit` (local pre-save undo actions)
- `undo_save` (server restore from `.bak`)

## Overlapping Errors Strategy
Use stable `issue_key` values and store `related_segment_uids`.

If multiple edits could resolve one issue, mark attribution as:
- `direct` when confidently attributable
- `shared_overlap` when multiple edits jointly affected the issue
- `unknown` when not safely attributable

This avoids false precision in overlap-heavy cases.

## Schema Extensions Recommended

### Segment identity and lineage
Add and preserve:
- `segment_uid` (stable UUID)
- optional `lineage` fields for split/merge ancestry

### Validation snapshots
Store normalized snapshots before and after each save to compute:
- issues removed
- issues added
- category-level deltas

## Phased Implementation Plan

1. Stable IDs and lineage foundation
- Add `segment_uid` to segments and preserve through save/rebuild flows.
- Ensure split/merge operations populate lineage metadata.

2. Client operation capture
- Record every user edit action in-memory with start/apply timestamps and fix context.
- Attach operation list + `client_session_id` to save payload.

3. Server batch assembly
- On save, compute `validation_before` and `validation_after`.
- Compute issue-level diff and derive per-op / batch impact.

4. History persistence
- Append one `save_batch` JSON object per save to `edit_history.jsonl`.

5. Undo integration
- On undo save, append `undo_save` record and mark reverted batch linkage.

6. Optional read API/UI
- Add endpoint(s) for browsing history and filtering by category/edit type.

## Compatibility Notes
- Keep `segments.json` and `detailed.json` operationally compatible with existing validators and dataset pipelines.
- Prefer additive fields and separate history files over format-breaking changes.

## Risks and Considerations
- Index instability requires stable IDs to avoid broken audit links.
- Attribution for overlapping errors should be conservative.
- Validation diffing may add save latency; cache and normalized keys should be used.
- History file growth should be expected; JSONL supports later compaction or archival.

