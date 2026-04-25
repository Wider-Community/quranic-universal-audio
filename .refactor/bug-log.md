# Bug Log — Inspector Segments Refactor

Append-only. Append entries as bugs / divergences surface during implementation.
Pre-phase check verifies no unsubstituted `_(this commit's SHA)_` placeholders remain.

ID prefix: `B`

---

## Section 1 — Seeded entries (from Stage 1 exploration)

| ID | Title | Phase | Status |
|---|---|---|---|
| B-1 | Frontend repetitions classifier extends `wrap_word_ranges` with `has_repeated_words` | 2 | OPEN |
| B-2 | `boundary_adj` phoneme tail check is backend-only | 2 | OPEN |
| B-3 | `audio_bleeding` algorithm differs across 3 stacks | 2 | OPEN |

---

## Section 2 — Active

### B-1 — Frontend repetitions classifier extends `wrap_word_ranges` with `has_repeated_words`

**Surfaced in:** Phase 2 (audit during Stage 1 exploration)
**Status:** OPEN

**Symptom**
- Frontend `_classifySegCategories` (`inspector/frontend/src/tabs/segments/utils/validation/classify.ts:81-82`) classifies `repetitions` if `seg.wrap_word_ranges || seg.has_repeated_words`.
- Backend `_classify_segment` (`inspector/services/validation/_classify.py:116-117`) classifies `repetitions` only if `seg.wrap_word_ranges`.
- CLI `validate_segments.py:239-240` matches backend.

**Root cause**
- Independent implementations diverged. Frontend was permissive about which field signals repetitions; backend chose a single canonical field.

**Fix**
- Phase 2 tie-breaker: backend wins. The unified classifier checks `wrap_word_ranges` only.
- If production fixtures contain segments with `has_repeated_words=true` and `wrap_word_ranges` empty, those segments STOP classifying as `repetitions` after Phase 2. Mitigation:
  1. Phase 2 implementation prompt includes a data audit: grep `data/recitation_segments/*/detailed.json` for the divergent shape.
  2. If found, Phase 2 sub-task: add a one-shot migration step that propagates `has_repeated_words=true` to populate `wrap_word_ranges`, OR widen the unified classifier to check both (and document why).

**Test coverage**
- `inspector/tests/classifier/test_classify_per_category.py::test_repetitions_only_wrap_word_ranges` asserts the post-Phase-2 behavior.

**Resolution**
- _(this commit's SHA)_

---

### B-2 — `boundary_adj` phoneme tail check is backend-only

**Surfaced in:** Phase 2 (audit during Stage 1 exploration)
**Status:** OPEN (planned no-op)

**Symptom**
- Backend `_check_boundary_adj` (`inspector/services/validation/_classify.py:31-64`) optionally compares the last K=3 phonemes of `phonemes_asr` against the canonical reference text when canonical is provided; flags only if both the structural rule passes AND the tail mismatches.
- CLI `validate_segments.py:269-275` skips the phoneme check entirely.
- Frontend `classify.ts:103-108` skips the phoneme check entirely.

**Root cause**
- Phoneme tail check requires the canonical Quranic phoneme map, which is loaded only on the backend's segment build path. CLI and frontend cannot easily access it without serializing the canonical phonemes through their own paths.

**Fix**
- Phase 2: backend wins. The unified classifier retains the optional tail check; CLI and frontend simply call the unified classifier and benefit from the check whenever canonical phonemes are available.
- Practical effect: CLI invocations may now produce different boundary_adj counts than before, when canonical phonemes are loaded. This is a feature, not a regression. Documented in MAY-9 (CLI output format / counts may shift).

**Test coverage**
- `inspector/tests/classifier/test_classify_per_category.py::test_boundary_adj_phoneme_tail_optional`.

**Resolution**
- _(this commit's SHA)_

---

### B-3 — `audio_bleeding` algorithm differs across 3 stacks

**Surfaced in:** Phase 2
**Status:** OPEN

**Symptom**
- Backend uses `seg_belongs_to_entry(matched_ref, entry_ref)` helper from `utils/references.py` (parsed-structure-aware).
- CLI parses `entry_ref` manually inline (`validate_segments.py:248-260`).
- Frontend checks `chapterAudio[seg.chapter] !== seg.audio_url` first (audio-URL-aware), then verse mismatch (`classify.ts:123-135`).

**Root cause**
- Frontend's audio-URL check is not part of the backend's algorithm but it's defensible: the same segment URL across two different chapter playback contexts could imply audio bleeding.

**Fix**
- Phase 2 tie-breaker: backend's `seg_belongs_to_entry`. The frontend's audio-URL aspect is dropped. If this surfaces a regression in audio bleeding detection, document it here and reconsider — likely this is fine because by-ayah audio is the primary trigger (already covered by backend's reference-based check).

**Test coverage**
- `inspector/tests/classifier/test_classify_per_category.py::test_audio_bleeding_uses_seg_belongs_to_entry`.

**Resolution**
- _(this commit's SHA)_

---

## Section 3 — Resolved

(empty)

---

## Append protocol

When a new bug surfaces during implementation:

1. Pick the next `B-N` ID.
2. Append a row to Section 1 with status OPEN.
3. Append the full entry to Section 2 with `_(this commit's SHA)_` placeholder in Resolution.
4. When the fix lands, replace the placeholder with the actual commit SHA in the same commit.
5. When the bug is closed, move the entry from Section 2 to Section 3 and update Section 1 status.

Pre-phase check (`.refactor/checks.sh`) flags unresolved placeholders.
