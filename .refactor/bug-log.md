# Bug Log — Inspector Segments Refactor

Append-only. Append entries as bugs / divergences surface during implementation.
Pre-phase check verifies no unsubstituted SHA placeholders (the `_(this
commit's S<!---->HA)_` token below) remain in resolution lines.

ID prefix: `B`

---

## Section 1 — Seeded entries (from Stage 1 exploration)

| ID | Title | Phase | Status |
|---|---|---|---|
| B-1 | Frontend repetitions classifier extends `wrap_word_ranges` with `has_repeated_words` | 2 | RESOLVED-fix-3a5dca8 |
| B-2 | `boundary_adj` phoneme tail check is backend-only | 2 | RESOLVED-fix-3a5dca8 |
| B-3 | `audio_bleeding` algorithm differs across 3 stacks | 2 | RESOLVED-fix-3a5dca8 |
| B-4 | Phase 3 backend pytest markers require route-level changes that fall outside Phase 3 scope | 3 | DEFERRED |

---

## Section 2 — Active

### B-4 — Phase 3 backend pytest markers require route-level changes that fall outside Phase 3 scope

**Surfaced in:** Phase 3
**Status:** DEFERRED

**Symptom**
- Four pytest files retain `@pytest.mark.xfail(reason="phase-3", strict=False)` markers after Phase 3 lands:
  - `inspector/tests/command/test_apply_command.py::test_history_record_reflects_command_result_metadata` — asserts backend rejects ops without a `command` envelope (HTTP 400).
  - `inspector/tests/command/test_auto_suppress.py::test_edit_from_card_records_suppression_per_registry` — parametrized over per-segment categories; asserts the SAVE handler reads the registry and writes `ignored_categories` even when the payload omits the field.
  - `inspector/tests/command/test_command_per_op.py::test_command_save_round_trip` — parametrized over op types; asserts backend rejects `command.type !== op.type` mismatches (HTTP 400).
  - `inspector/tests/routes/test_route_save.py::test_save_payload_is_correctly_built_from_command_results` — asserts schema-strict validation on `command.type` (rejects unknown types, HTTP 400).
- Two parametrized cases (`failed`, `muqattaat`) of `test_edit_from_card_records_suppression_per_registry` xpass because they're negative assertions.

**Root cause**
- Each of these tests exercises the `/api/seg/save` route's payload acceptance behavior:
  - Schema validation on the new `command` envelope.
  - Registry-driven write of `ignored_categories` from the SAVE handler (rather than from the payload as today).
  - Strict rejection of malformed `command` shapes.
- Plan §Invariants pins MUST-1 (HTTP routes additive). The Phase 3 dispatch
  brief restates: "Phase 3 should NOT change route shapes (no `services/`
  or `routes/` touches)" and "If you find that the save endpoint requires
  a change to accept the new op-record shape, surface it as a SCOPE
  EXPANSION REQUEST (S4)."
- The frontend `applyCommand` reducer now produces operations with `type`,
  `kind`, `snapshots`, `targetSegmentIndex` fields, plus the existing
  `op_id`, `op_type`, `targets_before`, `targets_after`. Save-route
  acceptance is unchanged; the new fields ride along as additive shape.
  The route does not yet validate the `command` envelope, look up the
  registry to filter `ignored_categories` writes, or reject malformed
  payloads — those changes belong in a route-validation phase (Phase 4
  adapters or a dedicated 3.5 scope expansion).

**Fix**
- DEFERRED. Frontend Phase 3 work is complete. Backend route-validation
  changes are out-of-scope; surface as scope expansion if/when the
  orchestrator decides the SAVE handler should validate the `command`
  envelope.
- Route-additive properties (MUST-1) are preserved: the new fields on
  operations are accepted and round-tripped through the history record
  without rejection. `test_save_payload_carries_op_log_in_canonical_shape`
  (which only verifies round-trip persistence) xpassed pre-Phase-3 and
  cleanly passes post-Phase-3 with its marker removed.

**Test coverage**
- Frontend tests under `inspector/frontend/src/tabs/segments/__tests__/command/`
  cover the `applyCommand` reducer, command shapes, and auto-suppress
  behavior end-to-end. 61 tests pass; 0 phase-3 vitest markers remain.
- Backend round-trip persistence is covered by the unmarked
  `test_save_payload_carries_op_log_in_canonical_shape`.

---

## Section 3 — Resolved

### B-1 — Frontend repetitions classifier extends `wrap_word_ranges` with `has_repeated_words`

**Surfaced in:** Phase 2 (audit during Stage 1 exploration)
**Status:** RESOLVED-fix-3a5dca8

**Symptom**
- Frontend `_classifySegCategories` (`inspector/frontend/src/tabs/segments/utils/validation/classify.ts:81-82`) classified `repetitions` if `seg.wrap_word_ranges || seg.has_repeated_words`.
- Backend `_classify_segment` (`inspector/services/validation/_classify.py:116-117`) classified `repetitions` only if `seg.wrap_word_ranges`.
- CLI `validate_segments.py:239-240` matched the backend.

**Root cause**
- Independent implementations diverged. Frontend was permissive about which field signals repetitions; backend chose a single canonical field.

**Fix**
- Phase 2 tie-breaker: backend wins. The unified classifier
  (`inspector/services/validation/classifier.py:classify_flags`) checks
  `wrap_word_ranges` only.
- The frontend live-segment classifier was deleted entirely
  (`inspector/frontend/src/tabs/segments/utils/validation/classify.ts`);
  the frontend now reads `classified_issues` off backend DTOs and saved
  history snapshots.
- Data audit (production
  `data/recitation_segments/*/detailed.json`): zero segments carry
  `has_repeated_words=true` without `wrap_word_ranges`. No data
  migration needed.

**Test coverage**
- `inspector/tests/classifier/test_classify_per_category.py::test_repetitions_only_wrap_word_ranges`
  asserts the post-Phase-2 behavior.
- `inspector/tests/classifier/test_classify_parity.py::test_backend_and_cli_classify_identically_per_fixture`
  asserts backend ↔ CLI agreement on per-segment categories including
  `repetitions`.

**Resolution**
- 3a5dca8

---

### B-2 — `boundary_adj` phoneme tail check is backend-only

**Surfaced in:** Phase 2 (audit during Stage 1 exploration)
**Status:** RESOLVED-fix-3a5dca8

**Symptom**
- Backend `_check_boundary_adj` (`inspector/services/validation/_classify.py:31-64`) optionally compared the last K=3 phonemes of `phonemes_asr` against the canonical reference text when canonical was provided; flagged only if both the structural rule passed AND the tail mismatched.
- CLI `validate_segments.py:269-275` skipped the phoneme check entirely.
- Frontend `classify.ts:103-108` skipped the phoneme check entirely.

**Root cause**
- Phoneme tail check requires the canonical Quranic phoneme map, which is loaded only on the backend's segment build path. CLI and frontend cannot easily access it without serializing the canonical phonemes through their own paths.

**Fix**
- Phase 2: backend wins. The unified classifier
  (`inspector/services/validation/classifier.py:_check_boundary_adj`)
  retains the optional tail check; CLI and frontend route through
  `classify_segment` / `classify_snapshot` and benefit from the check
  whenever canonical phonemes are available to the caller.
- Practical effect on the CLI: invocations with the canonical phonemes
  loaded may now produce different `boundary_adj` counts than before.
  Documented in MAY-9 (CLI output format / counts may shift).

**Test coverage**
- `inspector/tests/classifier/test_classify_per_category.py::test_boundary_adj_phoneme_tail_optional`.

**Resolution**
- 3a5dca8

---

### B-3 — `audio_bleeding` algorithm differs across 3 stacks

**Surfaced in:** Phase 2
**Status:** RESOLVED-fix-3a5dca8

**Symptom**
- Backend used `seg_belongs_to_entry(matched_ref, entry_ref)` helper from `utils/references.py` (parsed-structure-aware).
- CLI parsed `entry_ref` manually inline (`validate_segments.py:248-260`).
- Frontend checked `chapterAudio[seg.chapter] !== seg.audio_url` first (audio-URL-aware), then verse mismatch (`classify.ts:123-135`).

**Root cause**
- Frontend's audio-URL check was not part of the backend's algorithm but it was defensible: the same segment URL across two different chapter playback contexts could imply audio bleeding.

**Fix**
- Phase 2 tie-breaker: backend's `seg_belongs_to_entry`. The frontend's
  audio-URL aspect was dropped. The unified classifier
  (`inspector/services/validation/classifier.py:classify_flags`) is the
  single predicate; CLI imports it and the frontend reads
  `classified_issues` off backend DTOs.
- `seg_belongs_to_entry` is the most precise of the three predicates
  (parses entry-ref structure rather than substring-matching).

**Test coverage**
- `inspector/tests/classifier/test_classify_per_category.py::test_audio_bleeding_uses_seg_belongs_to_entry`.
- `inspector/tests/parity/test_classifier_parity_backend_cli.py::test_backend_cli_parity_holistic`.

**Resolution**
- 3a5dca8

---

## Append protocol

When a new bug surfaces during implementation:

1. Pick the next `B-N` ID.
2. Append a row to Section 1 with status OPEN.
3. Append the full entry to Section 2 with the literal token
   `_(this c<!---->ommit's SHA)_` in the Resolution line; the
   pre-phase check normalizes this comment-out so the docstring
   doesn't match its own grep.
4. When the fix lands, replace the placeholder with the actual commit SHA in the same commit.
5. When the bug is closed, move the entry from Section 2 to Section 3 and update Section 1 status.

Pre-phase check (`.refactor/checks.sh`) flags unresolved placeholders.
