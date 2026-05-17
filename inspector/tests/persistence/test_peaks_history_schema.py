"""Round-trip tests for the shared ``PeaksRecord`` Pydantic schema.

Schema lives at ``scripts/lib/schemas/peaks_history.py``. Both writers
(offline extraction's ``audio_persist.write_edit_history_peaks`` and
runtime Inspector's ``peaks_backfill.backfill_pipeline_peaks``) round-
trip through it — these tests assert the model parses every legitimate
record shape we encounter on disk + that ``model_dump(exclude_none=True)``
produces the slim emission shape Migration #5 specifies.
"""
from __future__ import annotations

import base64

import pytest

from scripts.lib.schemas import PeaksRecord, parse_peaks_record


# -- Sample record shapes -----------------------------------------------


def _slim_record() -> dict:
    """Post-#5 slim shape with int8-b64 packed peaks."""
    # 3 buckets × 2 (min,max) int8s = 6 bytes
    blob = bytes([-3 & 0xFF, 5, -2 & 0xFF, 4, -1 & 0xFF, 3])
    return {
        "op_id": "019e32c1-0757-7eb5-a7a2-308f45e2bb28",
        "url": "https://audio-cdn.tarteel.ai/quran/surah/abdulBasit/murattal/mp3/075.mp3",
        "start_ms": 159970,
        "end_ms": 164060,
        "bps": 10,
        "peaks_b64": base64.b64encode(blob).decode("ascii"),
    }


def _legacy_record() -> dict:
    """Pre-#5 bloated shape: list[list[float]] peaks + 3 dead fields."""
    return {
        "op_id": "019e32c1-0758-7ad0-9234-02dd45f78d53",
        "batch_id": "019e32c1-07d1-739e-be84-94514b5b90f8",
        "url": "https://audio-cdn.tarteel.ai/quran/surah/abdulBasit/murattal/mp3/083.mp3",
        "start_ms": 84110,
        "end_ms": 93160,
        "duration_ms": 9050,
        "saved_at_utc": "2026-05-16T21:46:39.362Z",
        "peaks": [[-0.0012, 0.0012], [-0.0013, 0.0013], [-0.0007, 0.0006]],
    }


# -- Validation tests ---------------------------------------------------


def test_slim_record_validates():
    m = PeaksRecord.model_validate(_slim_record())
    assert m.op_id.startswith("019e32c1")
    assert m.bps == 10
    assert m.peaks_b64 is not None
    assert m.peaks is None  # only peaks_b64 in this shape
    assert m.end_ms > m.start_ms


def test_legacy_record_validates_via_extra_allow():
    m = PeaksRecord.model_validate(_legacy_record())
    assert m.peaks is not None
    assert len(m.peaks) == 3
    assert m.peaks_b64 is None
    # Legacy fields tolerated via extra="allow"
    extras = m.model_extra or {}
    assert extras.get("batch_id") is not None
    assert extras.get("duration_ms") == 9050
    assert extras.get("saved_at_utc") is not None


def test_record_with_no_peaks_payload_fails():
    """A record without either peaks_b64 OR peaks is corrupt."""
    rec = _slim_record()
    rec.pop("peaks_b64")
    rec.pop("bps")
    with pytest.raises(ValueError, match="must carry peaks payload"):
        PeaksRecord.model_validate(rec)


def test_peaks_b64_without_bps_fails():
    """peaks_b64 needs the density tag — bps is non-optional alongside."""
    rec = _slim_record()
    rec.pop("bps")
    with pytest.raises(ValueError, match=r"`peaks_b64` requires `bps` density tag"):
        PeaksRecord.model_validate(rec)


def test_inverted_time_range_fails():
    rec = _slim_record()
    rec["end_ms"] = rec["start_ms"]  # equal is also invalid (need > )
    with pytest.raises(ValueError, match="must be > start_ms"):
        PeaksRecord.model_validate(rec)


# -- Round-trip emission tests ----------------------------------------


def test_slim_record_emits_slim_shape():
    """exclude_none drops absent legacy ``peaks`` field."""
    m = PeaksRecord.model_validate(_slim_record())
    out = m.model_dump(exclude_none=True)
    # The new canonical encoding fields are present:
    assert "peaks_b64" in out and "bps" in out
    # The legacy fields are absent (none in input, none in default):
    for banned in ("peaks", "batch_id", "duration_ms", "saved_at_utc"):
        assert banned not in out, f"{banned} leaked into slim emission"


def test_legacy_record_round_trips_legacy_fields_via_extra():
    """When a writer re-emits a legacy record (e.g. the migration script
    reads + writes), the legacy fields propagate via extra."""
    m = PeaksRecord.model_validate(_legacy_record())
    out = m.model_dump(exclude_none=True)
    # peaks (declared optional, value present) survives
    assert "peaks" in out
    # batch_id / duration_ms / saved_at_utc came in via extra="allow" —
    # they're in model_extra, NOT in model_dump output by default. The
    # migration script's job is to drop them explicitly; round-trip
    # default doesn't preserve extras in model_dump.
    extras = m.model_extra or {}
    assert "batch_id" in extras


def test_parse_peaks_record_helper():
    m = parse_peaks_record(_slim_record())
    assert isinstance(m, PeaksRecord)


def test_url_required():
    rec = _slim_record()
    rec["url"] = ""
    with pytest.raises(ValueError):
        PeaksRecord.model_validate(rec)
