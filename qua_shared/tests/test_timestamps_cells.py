"""Tests for per-character (haraka/tanween) cells — schema v5, the 6th word slot.

The pure accessor (``ts_shard_cells``) and the schema's v4/v5 tolerance are tested
deterministically; the phonemizer-backed stamping is exercised on the real Nasser
fixtures when a phonemizer exposing ``character_phoneme_mappings()`` is installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qua_shared import ts_shard_cells
from qua_shared.schemas.bucket.ts_shard import TsShardDoc, TsShardWord

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = _ROOT / "inspector/frontend/src/lib/recitation-data/__tests__/fixtures"


def _has_cpm() -> bool:
    try:
        from quranic_phonemizer import PhonemizeResult
    except ImportError:
        return False
    return hasattr(PhonemizeResult, "character_phoneme_mappings")


needs_cpm = pytest.mark.skipif(
    not _has_cpm(),
    reason="phonemizer lacks character_phoneme_mappings() (pre-v5 install)",
)


# --- pure accessor ---------------------------------------------------------


def test_parse_cell_named():
    row = ["ِ", "haraka", "present", [1], 0, "iltiqaa", 3]
    c = ts_shard_cells.parse_cell(row)
    assert (c.chars, c.role, c.status) == ("ِ", "haraka", "present")
    assert c.phoneme_indices == [1]
    assert c.source_letter_index == 0
    assert c.tag == "iltiqaa"
    assert c.share_group == 3


def test_parse_cell_carries_new_open_form_tag():
    # `tag` is open-form (phonemizer-owned vocabulary): a v7 madd-subtype / plain-
    # ghunnah tag rides through the accessor unchanged, no enum to extend.
    assert (
        ts_shard_cells.parse_cell(["ا", "madd", "present", [3], 1, "madd_lazim", 2]).tag
        == "madd_lazim"
    )
    assert (
        ts_shard_cells.parse_cell(["ن", "base", "present", [0], 0, "noon_ghunnah", None]).tag
        == "noon_ghunnah"
    )


def test_parse_cell_tolerates_minimal_and_trailing():
    # 5-slot minimal (tag/share_group default to None)
    c = ts_shard_cells.parse_cell(["م", "tanween", "dropped", [], 1])
    assert c.tag is None and c.share_group is None
    # a future trailing slot (beyond the 8th) is ignored, not an error
    c2 = ts_shard_cells.parse_cell(["م", "tanween", "dropped", [], 1, None, None, None, "future"])
    assert c2.source_letter_index == 1
    with pytest.raises(ValueError):
        ts_shard_cells.parse_cell(["م", "haraka"])  # < 5 slots


def test_parse_cell_reads_phoneme_rule_tags_slot():
    # v8 8th slot: per-phoneme tag list parallel to phoneme_indices.
    c = ts_shard_cells.parse_cell(
        [
            "لٓ",
            "madd",
            "present",
            [0, 1, 2],
            0,
            "madd_lazim",
            4,
            [None, "madd_lazim", "idgham_shafawi"],
        ]
    )
    assert c.phoneme_rule_tags == [None, "madd_lazim", "idgham_shafawi"]


def test_parse_cell_absent_phoneme_rule_tags_is_none():
    # v5-v7 rows (no 8th slot) parse with phoneme_rule_tags=None.
    c7 = ts_shard_cells.parse_cell(["ا", "madd", "present", [3], 1, "madd_lazim", 2])
    assert c7.phoneme_rule_tags is None
    # an explicit null 8th slot also normalizes to None.
    c8_null = ts_shard_cells.parse_cell(["ا", "madd", "present", [3], 1, "madd_lazim", 2, None])
    assert c8_null.phoneme_rule_tags is None


def test_word_cells_tolerates_missing_slot():
    v4_word = [1, 10, 200, [["ب", 10, 90, False]], [["b", 10, 50]]]
    assert ts_shard_cells.word_cells(v4_word) == []  # no 6th slot (v3/v4)
    v5_word = v4_word + [[["ِ", "haraka", "present", [], 0, None, None]]]
    assert len(ts_shard_cells.word_cells(v5_word)) == 1


# --- schema tolerates both arities ----------------------------------------


def test_schema_accepts_v4_and_v5_words():
    v4 = [1, 10, 200, [["ب", 10, 90, False]], [["b", 10, 50], ["i", 50, 90]]]
    v5 = v4 + [[["ِ", "haraka", "present", [1], 0, None, None]]]
    assert TsShardWord.model_validate(v4) is not None
    assert TsShardWord.model_validate(v5) is not None
    doc = {
        "_meta": {"schema_version": 5, "chapter": 101, "audio_category": "by_surah"},
        "segments": [{"ref": "101:1", "t": [10, 200], "words": [v5]}],
    }
    assert len(TsShardDoc.model_validate(doc).segments[0].words) == 1


def test_word_with_v8_phoneme_rule_tags_cell_round_trips():
    # A muqattaat cell WITH the 8th slot round-trips byte-equal through TsShardWord.
    cell = [
        "لٓ",
        "madd",
        "present",
        [0, 1, 2],
        0,
        "madd_lazim",
        4,
        [None, "madd_lazim", "idgham_shafawi"],
    ]
    phones = [["l", 10, 50], ["a:", 50, 150], ["m", 150, 200]]
    word = [1, 10, 200, [["ل", 10, 90, False]], phones, [cell]]
    model = TsShardWord.model_validate(word)
    # model_dump(mode="json") yields the on-disk list shape (tuples -> lists).
    assert model.model_dump(mode="json") == word


def test_word_without_phoneme_rule_tags_cell_still_parses():
    # A v7 cell (no 8th slot) still validates and round-trips unchanged.
    cell = ["ا", "madd", "present", [3], 1, "madd_lazim", 2]
    word = [1, 10, 200, [["ا", 10, 90, False]], [["a:", 10, 90]], [cell]]
    model = TsShardWord.model_validate(word)
    assert model.model_dump(mode="json") == word
    doc = {
        "_meta": {"schema_version": 8, "chapter": 101, "audio_category": "by_surah"},
        "segments": [{"ref": "101:1", "t": [10, 200], "words": [word]}],
    }
    assert len(TsShardDoc.model_validate(doc).segments[0].words) == 1


# --- phonemizer-backed stamping on the real fixtures -----------------------


@needs_cpm
@pytest.mark.parametrize("chapter", [101, 102])
def test_cells_stamped_and_valid_on_fixture(chapter):
    fix = _FIXTURES / f"nasser_al_qatami_mp3quran_{chapter}.shard.json"
    if not fix.exists():
        pytest.skip(f"fixture missing: {fix}")
    from qua_sdk.components.timing.lib.cells import _is_indexable, annotate_segment_words

    doc = json.loads(fix.read_text(encoding="utf-8"))
    total_words = 0
    saw_base = False
    for seg in doc["segments"]:
        words = seg["words"]
        annotate_segment_words(seg["ref"], words)
        for wd in words:
            total_words += 1
            # every word gets the 6th slot (no run silently skipped)
            assert len(wd) > 5, f"{seg['ref']} w{wd[0]} missing cells slot"
            n_idx = sum(1 for ph in wd[4] if _is_indexable(ph[0]))
            by_index: dict[int, set] = {}
            for c in ts_shard_cells.word_cells(wd):
                # base cells are now emitted (the SDK annotator owns the full
                # per-character breakdown), alongside haraka/tanween/madd.
                if c.role == "base":
                    saw_base = True
                for i in c.phoneme_indices:
                    assert 0 <= i < n_idx, f"{seg['ref']} w{wd[0]} index {i} >= {n_idx}"
                    by_index.setdefault(i, set()).add(c.share_group)
            # a phone shared by >1 cell must carry one (non-None) share_group.
            # (base + haraka can legitimately share a consonant index; when they
            # do, the index must still resolve to a single non-None group.)
            for groups in by_index.values():
                if len(groups) > 1:
                    assert None not in groups and len(groups) == 1
    assert total_words > 0
    assert saw_base, "expected base cells in v5 shard output"
