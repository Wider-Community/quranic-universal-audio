"""Re-deriving a projected segment's Hafs provenance when an edit moves its ref.

The Segments editor works in the delivery edition's coordinates, so the save
payload never carries ``source_ref``. Inheriting it kept a value the new
``matched_ref`` had invalidated; dropping it made the timestamps engine refuse
the delivery. Both are wrong — it is recomputed.
"""

from __future__ import annotations

import pytest

from services.reference import editions
from services.reference.editions import RefNotInEdition
from services.segments.projection_stamp import stamp_projection

has_editions = pytest.mark.skipif(
    not editions.available(), reason="qua-domain not installed (Hafs-only runtime)"
)


@pytest.fixture(autouse=True)
def _clear():
    yield
    editions.clear_caches()


def test_hafs_segments_gain_nothing():
    # 37 published Hafs deliveries must round-trip byte-identically.
    seg = {"matched_ref": "1:1:1-1:1:4"}
    stamp_projection(seg, "hafs")
    assert seg == {"matched_ref": "1:1:1-1:1:4"}


def test_a_hafs_delivery_sheds_provenance_it_should_never_have_had():
    seg = {"matched_ref": "1:1:1-1:1:4", "source_ref": "1:1:1-1:1:4", "projection_support": "full"}
    stamp_projection(seg, "hafs")
    assert seg == {"matched_ref": "1:1:1-1:1:4"}


@has_editions
def test_a_ref_edit_moves_the_hafs_span_with_it():
    """Warsh 57:23 IS Hafs 57:24 — the ref edit must carry the source across.

    Keeping the previous span would align the wrong verse's audio; dropping it
    would make the timestamps engine refuse the whole delivery.
    """
    seg = {
        "matched_ref": "57:23:1-57:23:11",
        "source_ref": "112:1:1-112:1:4",
        "projection_support": "full",
    }
    stamp_projection(seg, "warsh")

    assert seg["source_ref"] == "57:24:1-57:24:12"
    # Hafs 57:24:10 is a word Warsh does not write, so the span is not whole.
    assert seg["projection_support"] == "partial"


@has_editions
def test_a_clean_span_is_full():
    seg = {"matched_ref": "112:1:1-112:1:4"}
    stamp_projection(seg, "qalun")

    assert seg["source_ref"] == "112:1:1-112:1:4"
    assert seg["projection_support"] == "full"


@has_editions
def test_a_merged_target_word_pulls_in_both_of_its_hafs_sources():
    """Warsh writes Hafs 40:26:13+14 as one word.

    A segment ending on that target word needs BOTH Hafs words to align it, and
    the reverse projection says so — so the span it hands MFA is whole, and the
    support flag stays ``full``. Taking the ref literally would give the aligner
    half the phones the word is made of.
    """
    seg = {"matched_ref": "40:26:1-40:26:13"}
    stamp_projection(seg, "warsh")

    assert seg["source_ref"] == "40:26:1-40:26:14"
    assert seg["projection_support"] == "full"


@has_editions
@pytest.mark.parametrize("ref", ["Takbir", "", "Basmala"])
def test_a_transition_segment_carries_no_provenance(ref):
    # The timestamps engine skips these, so demanding a Hafs span from them
    # would fail every non-Hafs run on rows nothing aligns.
    seg = {"matched_ref": ref, "source_ref": "1:1:1-1:1:4"}
    stamp_projection(seg, "warsh")

    assert "source_ref" not in seg
    assert "projection_support" not in seg


@has_editions
@pytest.mark.parametrize(
    ("ref", "why"),
    [
        ("2:286:1-2:286:1", "Qalun's al-Baqarah ends at 285 — this verse is not in it"),
        ("112:2:1-112:2:9", "the verse exists but has nowhere near nine words"),
        ("999:1:1-999:1:1", "no such surah in any edition"),
    ],
)
def test_a_ref_this_edition_does_not_have_is_the_clients_error(ref, why):
    """``reverse_range`` raises, it never returns an empty span.

    Two different types, at that — a malformed ref is an
    ``InvalidQuranReferenceError`` and an out-of-edition one is a bare
    ``KeyError`` — so letting them through gave a 500 for what is a bad ref in
    the request. Warsh and Qalun renumber 50 surahs, which makes this ordinary:
    a ref that is perfectly valid in Hafs can name nothing here.
    """
    with pytest.raises(RefNotInEdition, match="qalun"):
        stamp_projection({"matched_ref": ref}, "qalun")
