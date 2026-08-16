"""Tests for per-character cells — the 6th word slot, a seven-slot row since v11.

The pure accessor (``ts_shard_cells``) and the schema's v4/v11 tolerance are tested
deterministically; the producer-backed stamping is exercised on the real Nasser
fixtures when the SDK's projection reader and the phonemizer are both installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qua_shared import ts_shard_cells
from qua_shared.schemas.bucket.ts_shard import TsShardDoc, TsShardWord

_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES = _ROOT / "inspector/frontend/src/lib/recitation-data/__tests__/fixtures"


def _has_producer() -> bool:
    try:
        import quranic_phonemizer  # noqa: F401
        from qua_sdk.integrations import cellrows  # noqa: F401
    except ImportError:
        return False
    return True


needs_producer = pytest.mark.skipif(
    not _has_producer(), reason="phonemizer / qua_sdk not installed"
)


# --- pure accessor ---------------------------------------------------------


def test_parse_cell_named():
    row = ["ِ", "haraka", "present", [1], 0, ["iltiqaa"], 3]
    c = ts_shard_cells.parse_cell(row)
    assert (c.chars, c.role, c.status) == ("ِ", "haraka", "present")
    assert c.phoneme_indices == [1]
    assert c.source_letter_index == 0
    assert c.rules == ["iltiqaa"]
    assert c.share_group == 3


def test_parse_cell_keeps_every_rule_in_order():
    # There is no primary tag: a grapheme that fired several rules carries all of
    # them, in the producer's order, and nothing is demoted or dropped.
    c = ts_shard_cells.parse_cell(["ا", "madd", "present", [3], 1, ["madd_lazim", "tafkheem"], 2])
    assert c.rules == ["madd_lazim", "tafkheem"]


def test_parse_cell_rules_may_be_empty():
    c = ts_shard_cells.parse_cell(["س", "base", "present", [0], 0, [], None])
    assert c.rules == []


def test_parse_cell_reads_a_pre_v11_single_tag_as_one_rule():
    # A shard written before the rule list carried one tag string in slot 5;
    # splitting it into characters would be silent nonsense.
    c = ts_shard_cells.parse_cell(["ب", "base", "present", [0], 0, "qalqala_sughra", None])
    assert c.rules == ["qalqala_sughra"]


def test_parse_cell_tolerates_minimal_and_trailing():
    # 5-slot minimal (rules/share_group default to empty/None)
    c = ts_shard_cells.parse_cell(["م", "tanween", "dropped", [], 1])
    assert c.rules == [] and c.share_group is None
    # a future trailing slot (beyond the 7th) is ignored, not an error
    c2 = ts_shard_cells.parse_cell(["م", "tanween", "dropped", [], 1, [], None, "future"])
    assert c2.source_letter_index == 1
    with pytest.raises(ValueError):
        ts_shard_cells.parse_cell(["م", "haraka"])  # < 5 slots


def test_word_cells_tolerates_missing_slot():
    v4_word = [1, 10, 200, [["ب", 10, 90, False]], [["b", 10, 50]]]
    assert ts_shard_cells.word_cells(v4_word) == []  # no 6th slot (v3/v4)
    v11_word = v4_word + [[["ِ", "haraka", "present", [], 0, [], None]]]
    assert len(ts_shard_cells.word_cells(v11_word)) == 1


# --- schema tolerates both arities ----------------------------------------


def test_schema_accepts_v4_and_v11_words():
    v4 = [1, 10, 200, [["ب", 10, 90, False]], [["b", 10, 50], ["i", 50, 90]]]
    v11 = v4 + [[["ِ", "haraka", "present", [1], 0, [], None]]]
    assert TsShardWord.model_validate(v4) is not None
    assert TsShardWord.model_validate(v11) is not None
    doc = {
        "_meta": {"schema_version": 11, "chapter": 101, "audio_category": "by_surah"},
        "segments": [{"ref": "101:1", "t": [10, 200], "words": [v11]}],
    }
    assert len(TsShardDoc.model_validate(doc).segments[0].words) == 1


def test_word_with_multi_rule_cell_round_trips():
    # A cell carrying several rules round-trips byte-equal through TsShardWord.
    cell = ["ا", "madd", "present", [0], 1, ["madd_arid_lil_sukun", "tafkheem"], None]
    word = [1, 10, 200, [["ا", 10, 90, False]], [["aˤ:", 10, 200]], [cell]]
    model = TsShardWord.model_validate(word)
    # model_dump(mode="json") yields the on-disk list shape (tuples -> lists).
    assert model.model_dump(mode="json") == word


def test_word_with_ruleless_cell_round_trips():
    cell = ["ا", "madd", "present", [3], 1, [], 2]
    word = [1, 10, 200, [["ا", 10, 90, False]], [["a:", 10, 90]], [cell]]
    model = TsShardWord.model_validate(word)
    assert model.model_dump(mode="json") == word
    doc = {
        "_meta": {"schema_version": 11, "chapter": 101, "audio_category": "by_surah"},
        "segments": [{"ref": "101:1", "t": [10, 200], "words": [word]}],
    }
    assert len(TsShardDoc.model_validate(doc).segments[0].words) == 1


# --- producer-backed stamping on the real fixtures -------------------------


@needs_producer
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
                # base cells are emitted alongside haraka/tanween/madd — the
                # producer owns the full per-character breakdown.
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
    assert saw_base, "expected base cells in stamped shard output"


@needs_producer
@pytest.mark.parametrize("chapter", [101, 102])
def test_stamped_cell_rules_are_known_tags(chapter):
    """Every rule a stamped cell carries is a ``TajweedRule`` member — the mirror
    the FE types against, so an unmirrored tag would render with no badge."""
    from qua_sdk.components.timing.lib.cells import annotate_segment_words

    from qua_shared.schemas.bucket.tajweed_vocab import TajweedRule

    fix = _FIXTURES / f"nasser_al_qatami_mp3quran_{chapter}.shard.json"
    if not fix.exists():
        pytest.skip(f"fixture missing: {fix}")
    known = {r.value for r in TajweedRule}
    doc = json.loads(fix.read_text(encoding="utf-8"))
    seen: set[str] = set()
    for seg in doc["segments"]:
        annotate_segment_words(seg["ref"], seg["words"])
        for wd in seg["words"]:
            for c in ts_shard_cells.word_cells(wd):
                seen.update(c.rules)
    assert seen, "expected at least one tagged cell in the fixture"
    assert seen <= known, f"unmirrored tag(s): {sorted(seen - known)}"


@needs_producer
def test_unwritten_madd_gets_a_cell_of_its_own():
    """`ٱللَّهِ` says a long alif the rasm does not write.

    The reading writes it, so the producer gives it a cell of its own carrying
    the letter the renderer spelt, sharing the sound with the fatha that writes
    its quality. A written dagger alif gets the same pair off the rasm alone.
    """
    from qua_sdk.integrations.cellrows import cell_rows
    from qua_sdk.integrations.phonemizer import result_for_ref

    unwritten = cell_rows(result_for_ref("1:1"))[1]
    fatha = next(c for c in unwritten if c.chars == "َ")
    alif = next(c for c in unwritten if c.status == "inserted" and c.role == "madd")
    assert alif.chars == "ا"
    assert unwritten.index(alif) == unwritten.index(fatha) + 1
    assert alif.phoneme_indices == fatha.phoneme_indices
    assert alif.source_letter_index == fatha.source_letter_index
    assert alif.share_group is not None and alif.share_group == fatha.share_group
    assert alif.rules == fatha.rules == ["madd_tabii"]

    # ذَٰلِكَ writes its dagger, so no cell is invented for it.
    written = cell_rows(result_for_ref("2:2"))[0]
    assert not [c for c in written if c.status == "inserted" and c.role == "madd"]
    dagger = next(c for c in written if c.chars == "ٰ")
    assert dagger.share_group == next(c for c in written if c.chars == "َ").share_group


@needs_producer
@pytest.mark.parametrize("chapter", [101, 102])
def test_cells_only_restamp_preserves_slot3_letters(chapter):
    """A cells-only re-stamp must NOT empty the legacy slot-3 ``letters``.

    The teleprompter / filmstrip drive their per-letter reveal off slot-3; a
    re-stamp that dropped it collapsed char mode to whole-word lighting (the FE
    ``lettersFromCells`` fallback then had to rebuild it). The backfill's
    ``_stamp_doc(restamp=True)`` truncates from the cells slot onward (``wd[5:]``)
    and re-derives cells via the SDK annotator — slot-3 (and its char/timings)
    must ride through untouched, only growing the silent flag.
    """
    import scripts.backfills.backfill_cells as bc

    fix = _FIXTURES / f"nasser_al_qatami_mp3quran_{chapter}.shard.json"
    if not fix.exists():
        pytest.skip(f"fixture missing: {fix}")

    doc = json.loads(fix.read_text(encoding="utf-8"))
    before = [[[lt[1], lt[2]] for lt in wd[3]] for seg in doc["segments"] for wd in seg["words"]]
    _n, _sd, _td, violations = bc._stamp_doc(doc, restamp=True)
    assert not violations
    after = [wd for seg in doc["segments"] for wd in seg["words"]]
    assert len(after) == len(before)
    for orig_timings, wd in zip(before, after, strict=True):
        # slot-3 still present and non-empty (re-stamp did not drop it) — and each
        # letter's [start, end] is preserved verbatim (a silence MARK may fold onto
        # the char and the silent flag is appended, but the timings never move).
        assert wd[3], f"w{wd[0]} lost its slot-3 letters on re-stamp"
        assert [[lt[1], lt[2]] for lt in wd[3]] == orig_timings
