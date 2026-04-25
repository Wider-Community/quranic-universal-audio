# Bug Log — Inspector Segments Refactor

Append-only. Append entries as bugs / divergences surface during implementation.
Pre-phase check verifies no unsubstituted `_(this commit's SHA)_` placeholders remain.

ID prefix: `B`

---

## Section 1 — Seeded entries (from Stage 1 exploration)

| ID | Title | Phase | Status |
|---|---|---|---|
| B-1 | Frontend repetitions classifier extends `wrap_word_ranges` with `has_repeated_words` | 2 | RESOLVED-fix-_(this commit's SHA)_ |
| B-2 | `boundary_adj` phoneme tail check is backend-only | 2 | RESOLVED-fix-_(this commit's SHA)_ |
| B-3 | `audio_bleeding` algorithm differs across 3 stacks | 2 | RESOLVED-fix-_(this commit's SHA)_ |

---

## Section 2 — Active

(empty)

---

## Section 3 — Resolved

### B-1 — Frontend repetitions classifier extends `wrap_word_ranges` with `has_repeated_words`

**Surfaced in:** Phase 2 (audit during Stage 1 exploration)
**Status:** RESOLVED-fix-_(this commit's SHA)_

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
- _(this commit's SHA)_

---

### B-2 — `boundary_adj` phoneme tail check is backend-only

**Surfaced in:** Phase 2 (audit during Stage 1 exploration)
**Status:** RESOLVED-fix-_(this commit's SHA)_

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
- _(this commit's SHA)_

---

### B-3 — `audio_bleeding` algorithm differs across 3 stacks

**Surfaced in:** Phase 2
**Status:** RESOLVED-fix-_(this commit's SHA)_

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
- _(this commit's SHA)_

---

## Append protocol

When a new bug surfaces during implementation:

1. Pick the next `B-N` ID.
2. Append a row to Section 1 with status OPEN.
3. Append the full entry to Section 2 with `_(this commit's SHA)_` placeholder in Resolution.
4. When the fix lands, replace the placeholder with the actual commit SHA in the same commit.
5. When the bug is closed, move the entry from Section 2 to Section 3 and update Section 1 status.

Pre-phase check (`.refactor/checks.sh`) flags unresolved placeholders.
