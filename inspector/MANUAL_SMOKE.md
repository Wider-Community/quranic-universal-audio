# Inspector editing-refactor — manual smoke checklist

Coverage gaps from automated tests (pytest 139 + vitest ~95) that need human eyes.
Use one of: `bandar_balilah`, `maher_al_meaqli`, `saad_al_ghamdi`, `mohammed_siddiq_al_minshawi`.

## 1. End-to-end edit round-trip
- [x] Load reciter, pick a chapter with low-confidence segments.
- [ ] **Trim** a boundary, save → reload page → boundary persisted.
- [ ] **Split** a segment, save → reload → both halves present, uids stable.
- [ ] **Merge** adjacent segments, save → reload → merged segment present.
- [ ] **Edit reference**, save → reload → new reference persisted, audit-confirm path on unchanged ref still bumps confidence.
- [ ] **Delete**, save → reload → segment gone, neighbours' silence_after_ms recomputed correctly.

## 2. Phase 3b dispatcher edges
- [ ] After each op above: dirty flag flips on, save button enables, finalizeOp clears dirty.
- [ ] Refresh button after edit prompts for unsaved changes.

## 3. Phase 4b — derived silence_after_ms
- [ ] After delete/merge/split, the gap shown in `SegmentsList.svelte` between adjacent segments matches the new neighbour timing (no stale value).
- [ ] Cross-verse compound segments (look for keys like `"X:Y:Z-X:Y':Z'"`) render correct silence on both sides.

## 4. Phase 5 — patch-based undo
- [ ] Edit, save, hit undo → segment restored exactly.
- [ ] Multi-op undo stack: trim → split → undo → undo → both reverted in reverse order.
- [ ] **Legacy fallback**: load `saad_al_ghamdi` (has pre-Phase-5 history). Add a new edit, save, then attempt to undo a *pre-refactor* op record → field-restore path engages without errors.
- [ ] Undo after structural edit (split/merge/delete): ignored_categories restored, ids re-inserted/removed correctly.

## 5. Phase 6 — stale issue filtering
- [ ] Open Validation panel, note an issue tied to segment X.
- [ ] Delete segment X → validation panel updates: that issue disappears (filtered, not orphan-rendered).
- [ ] Split segment Y that had an issue → issue resolves to one of the new halves via uid (or vanishes if uid no longer matches).
- [ ] Jump-to-Verse from a structural-error card lands on the correct segment (Phase 1 alias fix).

## 6. Cross-verse compound keys
- [ ] Find a `X:Y:Z-X':Y':Z'` key in segments.json (grep). Open in inspector; chapter selector resolves it.
- [ ] Edit it (trim or reference), save → key preserved on disk; uid stable.

## 7. Validation route surface
- [ ] DevTools → Network → `/api/seg/validate` response includes:
  - `category_counts` (Phase 2)
  - `structural_errors` mirrors `errors` (Phase 1 alias)
  - all 11 categories from registry present in `/api/seg/config`.

## 8. Save payload
- [ ] DevTools → Network → save POST body for any op:
  - `op_log` entries carry `patch` field (Phase 5)
  - `ignored_categories` filtered through registry (no non-persisting categories on the wire)
  - empty `ignored_categories: []` clears persisted ignores (set then unset, save twice).

## 9. Edit-history file
- [ ] After several saves, open `edit_history.jsonl` in the reciter dir:
  - Each record has `classified_issues` on snapshots (Phase 2)
  - Each post-Phase-5 record has `patch` field
  - Records form a valid batch chain (validate via `validators/validate_edit_history.py`).

## 10. Smoke — both new reciters
Run the full flow end-to-end on `bandar_balilah` AND `maher_al_meaqli`. They have fresh segments + history fetched from open PRs. Mismatches between them often surface reciter-specific bugs the fixtures don't cover.
