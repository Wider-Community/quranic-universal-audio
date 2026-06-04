"""Round-trip tests for the shared ``PeaksRecord`` Pydantic schema.

Schema lives at ``qua_shared/schemas/peaks_history.py``. Both writers
(offline extraction's ``audio_persist.write_edit_history_peaks`` and
the one-shot ``scripts/backfills/backfill_pipeline_peaks.py``) round-
trip through it — these tests assert the canonical Migration #5 shape
(``peaks_b64`` + ``bps``) is the only one accepted, and that the
pre-#5 ``peaks: list[list[float]]`` shape is rejected so a stale
on-disk record can't ride into the live cache.
"""

from __future__ import annotations

import base64

import pytest

from qua_shared.schemas import PeaksRecord, parse_peaks_record

# -- Sample record shapes -----------------------------------------------


def _slim_record() -> dict:
    """Canonical Migration #5 shape — int8-b64 packed peaks."""
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
    """Pre-#5 bloated shape — REJECTED by schema. Existing bucket
    records in this shape must be re-encoded via
    ``migrate_wip5_in_place.py`` before they reach the validator.
    """
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
    assert m.peaks_b64
    assert m.end_ms > m.start_ms


def test_legacy_record_rejected():
    """Pre-#5 ``peaks: list[list[float]]`` shape must NOT validate.

    The schema requires ``peaks_b64`` + ``bps``; legacy records have
    neither and would slip through with an unguarded validator. The
    migration script re-encodes such records before they hit the cache.
    """
    with pytest.raises(ValueError):
        PeaksRecord.model_validate(_legacy_record())


def test_record_missing_peaks_b64_fails():
    rec = _slim_record()
    rec.pop("peaks_b64")
    with pytest.raises(ValueError):
        PeaksRecord.model_validate(rec)


def test_record_missing_bps_fails():
    rec = _slim_record()
    rec.pop("bps")
    with pytest.raises(ValueError):
        PeaksRecord.model_validate(rec)


def test_record_with_empty_peaks_b64_fails():
    rec = _slim_record()
    rec["peaks_b64"] = ""
    with pytest.raises(ValueError):
        PeaksRecord.model_validate(rec)


def test_inverted_time_range_fails():
    rec = _slim_record()
    rec["end_ms"] = rec["start_ms"]  # equal is also invalid (need > )
    with pytest.raises(ValueError, match="must be > start_ms"):
        PeaksRecord.model_validate(rec)


def test_bps_must_be_positive():
    rec = _slim_record()
    rec["bps"] = 0
    with pytest.raises(ValueError):
        PeaksRecord.model_validate(rec)


# -- Round-trip emission tests ----------------------------------------


def test_slim_record_emits_canonical_shape():
    """``model_dump(exclude_none=True)`` should emit exactly the 6
    canonical fields. Legacy fields never leak."""
    m = PeaksRecord.model_validate(_slim_record())
    out = m.model_dump(exclude_none=True)
    assert set(out.keys()) == {
        "op_id",
        "url",
        "start_ms",
        "end_ms",
        "bps",
        "peaks_b64",
    }
    # Pre-#5 legacy keys must not appear:
    for banned in ("peaks", "batch_id", "duration_ms", "saved_at_utc"):
        assert banned not in out, f"{banned} leaked into canonical emission"


def test_record_with_legacy_fields_strips_them_on_read(caplog):
    """A record that carries the canonical payload AND extra legacy
    fields (mid-migration partially-rewritten record) validates cleanly:
    the schema's ``strip_and_warn`` pre-validator drops the legacy keys
    with a warning and ``model_extra`` stays empty so writers can't
    accidentally round-trip them back to disk."""
    import logging

    caplog.set_level(logging.INFO, logger="qua_shared.schemas._extras")
    rec = _slim_record()
    rec["batch_id"] = "legacy-batch"
    rec["duration_ms"] = 4090
    m = PeaksRecord.model_validate(rec)
    assert (m.model_extra or {}) == {}
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "batch_id" in msgs and "duration_ms" in msgs


def test_parse_peaks_record_helper():
    m = parse_peaks_record(_slim_record())
    assert isinstance(m, PeaksRecord)


def test_url_required():
    rec = _slim_record()
    rec["url"] = ""
    with pytest.raises(ValueError):
        PeaksRecord.model_validate(rec)
