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
| B-4 | Phase 3 backend pytest markers require route-level changes that fall outside Phase 3 scope | 3 | RESOLVED-fix-2c191aa |
| B-5 | Validation-panel mid-load race: empty `liveUids` while `segAllData` is loading | 7 | OPEN-LOW-PRIORITY |

---

## Section 2 — Active

### B-5 — Validation-panel mid-load race: empty `liveUids` while `segAllData` is loading

**Surfaced in:** Phase 7 (Opus finding from Phase 6 review)
**Status:** OPEN-LOW-PRIORITY

**Symptom**
- ``filterStaleIssues`` (``inspector/frontend/src/tabs/segments/utils/validation/stale.ts``) drops every issue whose ``segment_uid`` is not in ``liveUids``. The set is built from ``$segAllData.segments`` in ``ValidationPanel.svelte``.
- During the brief window where the validation response has resolved but ``segAllData`` has not, ``liveUids`` is empty and every uid-bearing issue would be filtered out.

**Root cause**
- Validation and ``segAllData`` are fetched in parallel inside ``reloadCurrentReciter`` (``utils/data/reciter-actions.ts``). Both share the same ``await Promise.allSettled`` boundary, so the panel doesn't render between the two resolutions in the current code path.
- The race is reachable only if a future change splits the two fetches (e.g. lazy per-chapter ``segAllData`` loading) so the validation response can land while ``liveUids`` is still empty.

**Fix**
- Documented inline in ``utils/validation/stale.ts`` (module docstring) and via this entry. No production code change today — the panel never renders during the empty-uids gap because both fetches resolve together.
- If lazy chapter loading is added later, the filter must consult a per-chapter uid set or wait for the relevant chapter's uids before filtering.

**Test coverage**
- None today (race is unreachable in the current load path). A regression test would gate-add when lazy loading lands.

---

## Section 3 — Resolved

### B-4 — Phase 3 backend pytest markers require route-level changes that fall outside Phase 3 scope

**Surfaced in:** Phase 3
**Status:** RESOLVED-fix-2c191aa

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
- The Phase 3 dispatch brief restated MUST-1 (HTTP routes additive only) and explicitly fenced the SAVE route off from Phase 3 scope. The route did not yet validate the `command` envelope, look up the registry to filter `ignored_categories` writes, or reject malformed payloads.

**Fix**
- Phase 7 added two helpers in ``inspector/services/save.py``:
  - ``_validate_command_envelopes(operations)`` rejects (HTTP 400) any op
    that declares a ``type`` discriminator without a matching ``command``
    envelope, with a known string ``command.type`` from the allowed set
    (``trim``/``split``/``merge``/``delete`` and the snake- and camelCase
    variants of ``edit_reference``/``ignore_issue``/``auto_fix_missing_word``).
  - ``_apply_registry_auto_suppress(matching, operations, explicit_ic_uids)``
    runs after ``_apply_full_replace`` / ``_apply_patch`` and before
    persistence. For each op carrying ``command.sourceCategory``, it calls
    the registry's ``apply_auto_suppress`` against the targeted segment
    when the payload omitted ``ignored_categories`` for that uid (MUST-7
    compliance). The result is then re-filtered through
    ``filter_persistent_ignores`` so non-persistent categories don't bleed
    through to disk.
- Pre-existing fixtures in ``test_route_save.py`` (Phase 5 patch-synth test) and
  the Phase 5 patch tests (``test_route_undo.py``, ``test_route_history.py``,
  ``test_patch_undo.py``) gained a ``command`` envelope to comply with the new
  contract — assertion behavior unchanged, only fixture shape.
- All 4 ``phase-3`` xfail decorators removed; total xfail count now 0.

**Resolution**
- 2c191aa

**Test coverage**
- ``inspector/tests/command/test_apply_command.py::test_history_record_reflects_command_result_metadata`` — HTTP 400 on missing ``command`` envelope.
- ``inspector/tests/command/test_command_per_op.py::test_command_save_round_trip`` — HTTP 400 on ``command.type != op.type`` mismatch (parametrized over 6 op types).
- ``inspector/tests/routes/test_route_save.py::test_save_payload_is_correctly_built_from_command_results`` — HTTP 400 on unknown ``command.type`` value.
- ``inspector/tests/command/test_auto_suppress.py::test_edit_from_card_records_suppression_per_registry`` — registry-driven ``ignored_categories`` write, parametrized over all per-segment categories. Negative assertions for ``failed`` / ``muqattaat`` confirm non-persistent / non-auto-suppress categories are NOT written.
- ``inspector/tests/persistence/test_save_clears_ignores.py`` (existing, unchanged) verifies MUST-7 — explicit ``[]`` continues to clear.

---

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
