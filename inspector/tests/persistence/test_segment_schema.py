"""Round-trip tests for the shared ``DetailedSegment`` Pydantic schema.

Schema lives at ``qua_shared/schemas/segment.py``. Both the offline
extraction pipeline and the Inspector save flow round-trip through it —
these tests assert the model parses every legitimate seg shape we
encounter on disk + that ``model_dump(exclude_none=True)`` produces the
slim emission shape Migration #5 specifies.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qua_shared.schemas import (
    DetailedDocument,
    DetailedSegment,
    parse_detailed_segment,
)

# -- Sample seg shapes --------------------------------------------------


def _slim_seg() -> dict:
    """Post-#5 slim shape — what the writer should emit going forward."""
    return {
        "time_start": 430,
        "time_end": 4440,
        "matched_ref": "1:1:1-1:1:4",
        "confidence": 1.0,
        "qalqala_letter": None,
        "is_boundary_adj": False,
    }


def _legacy_seg() -> dict:
    """Pre-#5 bloated shape — what stale on-disk data or snapshots
    embedded in legacy ``edit_history.jsonl`` may still contain.

    ``matched_text`` + ``phonemes_asr`` were dropped in Migration #5 and
    the schema now actively strips them on read (with a warning log) so
    they can't sneak back into the typed surface. ``has_repeated_words``
    is the tautology field — never modelled, tolerated via ``extra="allow"``
    so unknown keys don't break parsing.
    """
    return {
        "time_start": 430,
        "time_end": 4440,
        "matched_ref": "1:1:1-1:1:4",
        "matched_text": "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيم",
        "phonemes_asr": "b i s m i ll a: h i rˤrˤ aˤ ħ m a: n i rˤrˤ aˤ ħ i: m",
        "confidence": 1.0,
        "qalqala_letter": None,
        "is_boundary_adj": False,
        "has_repeated_words": False,
    }


def _failed_alignment_seg() -> dict:
    """A seg the DP aligner couldn't match — confidence 0, ref empty."""
    return {
        "time_start": 12000,
        "time_end": 13500,
        "matched_ref": "",
        "confidence": 0.0,
    }


def _wrap_seg() -> dict:
    """Seg with repetition geometry — wrap_word_ranges is the only field
    that drives the ``repetitions`` validation category."""
    return {
        "time_start": 1000,
        "time_end": 5000,
        "matched_ref": "2:30:1-2:30:24",
        "confidence": 0.95,
        "qalqala_letter": "ق",
        "is_boundary_adj": True,
        "wrap_word_ranges": [["2:30:11", "2:30:11", "2:30:24"]],
        "segment_uid": "019e32bb-bef6-7132-b006-72aa4ee485cb",
    }


# -- Validation tests ---------------------------------------------------


def test_slim_seg_validates():
    m = DetailedSegment.model_validate(_slim_seg())
    assert m.time_start == 430
    assert m.matched_ref == "1:1:1-1:1:4"
    assert m.confidence == 1.0
    # matched_text and phonemes_asr were dropped in Migration #5 — the
    # attributes no longer exist on the model.
    assert not hasattr(m, "matched_text")
    assert not hasattr(m, "phonemes_asr")


def test_legacy_seg_strips_dead_fields_on_read(caplog):
    """Legacy seg shape (pre-#5) must parse cleanly with every dead and
    unknown field stripped by the pre-validator. ``model_extra`` should be
    empty (extras handling = warn-then-strip, not silent-allow)."""
    import logging

    caplog.set_level(logging.INFO, logger="qua_shared.schemas._extras")
    m = DetailedSegment.model_validate(_legacy_seg())
    # Dead fields are gone — neither typed attributes nor extras.
    assert not hasattr(m, "matched_text")
    assert not hasattr(m, "phonemes_asr")
    assert not hasattr(m, "has_repeated_words")
    assert (m.model_extra or {}) == {}
    # And the pre-validator logged the strip at INFO level (legacy class).
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "matched_text" in msgs and "phonemes_asr" in msgs
    assert "has_repeated_words" in msgs


def test_failed_alignment_seg_validates():
    m = DetailedSegment.model_validate(_failed_alignment_seg())
    assert m.matched_ref == ""
    assert m.confidence == 0.0


def test_wrap_seg_validates():
    m = DetailedSegment.model_validate(_wrap_seg())
    assert m.wrap_word_ranges is not None
    assert m.qalqala_letter == "ق"
    assert m.is_boundary_adj is True
    assert m.segment_uid is not None


def test_time_end_before_time_start_fails():
    """time_end < time_start is corrupt data — must raise."""
    with pytest.raises(ValueError, match="time_end .* must be >= time_start"):
        DetailedSegment.model_validate(
            {
                "time_start": 5000,
                "time_end": 4000,
                "matched_ref": "1:1:1",
                "confidence": 1.0,
            }
        )


def test_confidence_out_of_range_fails():
    with pytest.raises(ValueError):
        DetailedSegment.model_validate(
            {
                "time_start": 0,
                "time_end": 1000,
                "matched_ref": "1:1:1",
                "confidence": 1.5,  # out of [0, 1]
            }
        )


# -- Round-trip emission tests ----------------------------------------


def test_slim_seg_emits_slim_shape():
    """``model_dump(exclude_none=True)`` drops absent optional fields.

    This is what Migration #5 specifies the new writer must emit.
    """
    seg = _slim_seg()
    m = DetailedSegment.model_validate(seg)
    out = m.model_dump(exclude_none=True)

    # qalqala_letter is None in input — exclude_none drops it. But the
    # default is also None, so excluded.
    assert "qalqala_letter" not in out
    # is_boundary_adj=False is the default; with exclude_none it stays
    # (None vs False distinction). Migration #5 emits it anyway since it
    # IS persisted; verify it's there.
    assert out["is_boundary_adj"] is False
    # The four banned-or-deferred-drop fields are absent from input + None
    # default → must be absent from output.
    for banned in ("matched_text", "phonemes_asr", "wrap_word_ranges", "segment_uid"):
        assert banned not in out, f"{banned} leaked into slim emission"


def test_dead_fields_dont_round_trip():
    """Round-tripping a legacy seg through the schema strips every dead +
    unknown field — they all get warn-then-stripped by the pre-validator
    so emitted JSON is clean."""
    seg = _legacy_seg()
    m = DetailedSegment.model_validate(seg)
    out = m.model_dump(exclude_none=True)

    for banned in ("matched_text", "phonemes_asr", "has_repeated_words"):
        assert banned not in out, f"{banned} leaked into emitted seg"


def test_parse_detailed_segment_helper():
    """Module-level helper used by extraction + inspector both."""
    m = parse_detailed_segment(_slim_seg())
    assert isinstance(m, DetailedSegment)


# -- Document-level tests -----------------------------------------------


def test_detailed_document_with_alias_meta():
    """``_meta`` JSON key maps to ``.meta`` Python attribute via alias."""
    raw = {
        "_meta": {
            "pad_left_ms": 150,
            "pad_right_ms": 500,
            "min_silence_floor_ms": 40,
            "audio_source": "qul",
        },
        "entries": [
            {"ref": "1", "segments": [_slim_seg()]},
            {"ref": "2", "segments": [_legacy_seg()]},
        ],
    }
    doc = DetailedDocument.model_validate(raw)
    assert doc.meta.pad_left_ms == 150
    assert doc.meta.audio_source == "qul"
    assert len(doc.entries) == 2

    # Round-trip via by_alias=True to get _meta back in the JSON output.
    out = doc.model_dump(by_alias=True, exclude_none=True)
    assert "_meta" in out and "meta" not in out


def test_entry_with_legacy_audio_field(caplog):
    """``entry.audio`` was dropped in Migration #5 — the pre-validator
    strips it on read with an INFO log; readers must not see it."""
    import logging

    caplog.set_level(logging.INFO, logger="qua_shared.schemas._extras")
    raw = {
        "_meta": {},
        "entries": [
            {
                "ref": "75",
                "audio": "https://audio-cdn.tarteel.ai/quran/surah/abuBakrAlShatri/murattal/mp3/075.mp3",  # legacy
                "segments": [_slim_seg()],
            },
        ],
    }
    doc = DetailedDocument.model_validate(raw)
    entry = doc.entries[0]
    assert (entry.model_extra or {}) == {}
    assert not hasattr(entry, "audio")
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "audio" in msgs  # stripped + logged


# -- Real on-disk sample (optional; runs if a fixture is available) ----


@pytest.mark.parametrize(
    "fixture_name",
    [
        "112-ikhlas.detailed.json",
        "113-falaq.detailed.json",
    ],
)
def test_on_disk_fixture_validates(fixture_name):
    """Validate the shipped fixtures parse via the schema — protects
    against schema regressions that would break tests using fixtures."""
    fixture_path = Path(__file__).parents[2] / "tests" / "fixtures" / "segments" / fixture_name
    if not fixture_path.is_file():
        pytest.skip(f"fixture missing: {fixture_path}")
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    doc = DetailedDocument.model_validate(raw)
    assert len(doc.entries) >= 1
    total_segs = sum(len(e.segments) for e in doc.entries)
    assert total_segs >= 1
