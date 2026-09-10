"""The classifier under a non-Hafs edition.

Every table it reads moves between editions. These cases are the ones where a
Hafs-keyed table gives a DIFFERENT answer, so each is a bug the edition
parameter exists to prevent — not a restatement of the Hafs behaviour.
"""

from __future__ import annotations

import pytest

from services.reference import editions
from services.validation.classifier import (
    classify_segment,
    compute_is_boundary_adj,
)

pytestmark = pytest.mark.skipif(
    not editions.available(), reason="qua-domain not installed (Hafs-only runtime)"
)


@pytest.fixture(autouse=True)
def _clear_edition_caches():
    yield
    editions.clear_caches()


def seg(ref: str, confidence: float = 1.0) -> dict:
    return {"segment_uid": "u1", "matched_ref": ref, "confidence": confidence}


# ---------------------------------------------------------------------------
# muqattaat — Warsh merges Hafs 42:1 + 42:2 into one two-word verse
# ---------------------------------------------------------------------------


def test_the_second_opening_of_the_merged_shura_verse_is_still_muqattaat():
    # Hafs 42:2 (`ayn-sin-qaf`) is Warsh 42:1:2. A Hafs-keyed rule fires only on
    # word 1, so this opening would be classified as a one-word fragment.
    assert "muqattaat" in classify_segment(seg("42:1:2-42:1:2"), riwayah="warsh")
    assert "boundary_adj" not in classify_segment(seg("42:1:2-42:1:2"), riwayah="warsh")


def test_the_same_ref_is_not_muqattaat_under_hafs():
    # Guards the test above against passing for the wrong reason: 42:1:2 does
    # not exist as an opening in Hafs, where 42:1 is one word.
    assert "muqattaat" not in classify_segment(seg("42:1:2-42:1:2"), riwayah="hafs")


def test_a_hafs_muqattaat_ref_is_not_one_in_warsh():
    # Hafs 42:2:1 is not a Warsh coordinate at all.
    assert "muqattaat" in classify_segment(seg("42:2:1-42:2:1"), riwayah="hafs")
    assert "muqattaat" not in classify_segment(seg("42:2:1-42:2:1"), riwayah="warsh")


# ---------------------------------------------------------------------------
# boundary_adj — the single-word-verse set collapses from 28 to 3
# ---------------------------------------------------------------------------


def test_al_baqarahs_opening_word_is_a_fragment_in_warsh_but_a_verse_in_hafs():
    # Hafs 2:1 IS the muqattaat verse, one word long. In Warsh 2:1 is an
    # eight-word verse that merely begins with it — so a segment covering only
    # the opening word is exempt as muqattaat, while word 2 is a real fragment.
    assert compute_is_boundary_adj(seg("2:1:2-2:1:2"), 2, 1, 2, 2, set(), None, "hafs") is False
    assert compute_is_boundary_adj(seg("2:1:2-2:1:2"), 2, 1, 2, 2, set(), None, "warsh") is False
    # 2:2 is a plain verse in Warsh and the muqattaat exemption does not reach
    # it, so a bare one-word segment there is flagged.
    assert compute_is_boundary_adj(seg("2:2:2-2:2:2"), 2, 2, 2, 2, set(), None, "warsh") is True


def test_a_muqattaat_verse_exempts_words_past_its_opening_letters():
    # 13:1 opens with the letters and runs on. The exemption is verse-keyed in
    # every edition, so a one-word segment deep inside it is not flagged.
    assert compute_is_boundary_adj(seg("13:1:5-13:1:5"), 13, 1, 5, 5, set(), None, "hafs") is False
    assert compute_is_boundary_adj(seg("13:1:5-13:1:5"), 13, 1, 5, 5, set(), None, "shuba") is False


# ---------------------------------------------------------------------------
# standalone tables — four refs renumber, one skeleton is respelled
# ---------------------------------------------------------------------------


def test_a_renumbered_standalone_ref_is_recognised_at_its_warsh_coordinate():
    # Hafs 43:35:1 is Warsh 43:34:1. Under the Hafs table the Warsh coordinate
    # is unknown and the segment would be flagged as needing adjustment.
    assert (
        compute_is_boundary_adj(seg("43:34:1-43:34:1"), 43, 34, 1, 1, set(), None, "warsh") is False
    )
    assert (
        compute_is_boundary_adj(seg("43:34:1-43:34:1"), 43, 34, 1, 1, set(), None, "hafs") is True
    )


def test_the_respelled_standalone_skeleton_matches_in_its_own_script():
    # `wa-bi-al-layl` at 37:138:1 is the one skeleton that changes spelling:
    # Hafs writes it with an alif-wasla, Warsh without. Each edition matches its
    # own spelling; neither would match the other's, which is why the skeleton
    # table is projected rather than shared.
    ref, position = "37:138:1-37:138:1", (37, 138, 1, 1)
    for riwayah in ("hafs", "warsh", "qalun", "shuba"):
        assert compute_is_boundary_adj(seg(ref), *position, set(), None, riwayah) is False, riwayah

    from services.reference import edition_tables

    assert edition_tables.standalone_words("warsh") != edition_tables.standalone_words("hafs")


# ---------------------------------------------------------------------------
# confidence cutoff
# ---------------------------------------------------------------------------


def test_the_low_confidence_cutoff_is_read_per_edition(monkeypatch):
    from config import LOW_CONFIDENCE_THRESHOLDS

    monkeypatch.setitem(LOW_CONFIDENCE_THRESHOLDS, "warsh", 0.5)
    lowish = seg("2:2:1-2:2:3", confidence=0.6)
    assert "low_confidence" in classify_segment(lowish, riwayah="hafs")
    assert "low_confidence" not in classify_segment(lowish, riwayah="warsh")
