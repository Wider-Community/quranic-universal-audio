"""Unit tests for ``build_ts_validation`` — verse-level multi-beam flagging.

A verse passes under a beam when every segment mapping to it aligned; it is
flagged when it fails under at least one beam it was tested under (tighter-beam
disagreement = low confidence). The widest beam is canonical.
"""
from __future__ import annotations

from qua_shared.timestamps_pipeline import build_ts_validation

OK = {"status": "ok"}
FAIL = {"status": "error", "error": "boom"}


def _chapters():
    return [
        {
            "ref": "1",
            "segments": [
                {"matched_ref": "1:1:1-1:1:4"},  # verse 1:1
                {"matched_ref": "1:2:1-1:2:3"},  # verse 1:2
                {"matched_ref": "1:3:1-1:3:5"},  # verse 1:3
            ],
        }
    ]


def test_flags_verse_failing_under_tighter_beam():
    beams = [50, 20]  # canonical 50, probe 20
    results_by_beam = {
        50: {0: [(0, OK), (1, OK), (2, OK)]},          # all pass canonical
        20: {0: [(0, OK), (1, FAIL), (2, OK)]},        # verse 1:2 fails tight
    }
    doc = build_ts_validation(
        _chapters(), results_by_beam, beams, reciter="x", method="kalpy")

    assert doc["verses"] == {
        "1:2": {"failed_beams": [20], "min_passing_beam": 50}
    }
    assert doc["_meta"]["canonical_beam"] == 50
    assert doc["_meta"]["beams"] == [50, 20]  # sorted desc
    assert doc["_meta"]["reciter"] == "x"


def test_single_beam_flags_nothing():
    beams = [50]
    results_by_beam = {50: {0: [(0, OK), (1, OK), (2, OK)]}}
    doc = build_ts_validation(
        _chapters(), results_by_beam, beams, reciter="x", method="kalpy")
    assert doc["verses"] == {}


def test_verse_failing_every_beam_has_no_min_passing():
    beams = [50, 20]
    results_by_beam = {
        50: {0: [(0, OK), (1, FAIL), (2, OK)]},
        20: {0: [(0, OK), (1, FAIL), (2, OK)]},
    }
    doc = build_ts_validation(
        _chapters(), results_by_beam, beams, reciter="x", method="kalpy")
    assert doc["verses"] == {
        "1:2": {"failed_beams": [50, 20], "min_passing_beam": None}
    }


def test_multiple_probes_record_all_failing_beams():
    beams = [50, 35, 20]
    results_by_beam = {
        50: {0: [(0, OK), (1, OK), (2, OK)]},
        35: {0: [(0, OK), (1, OK), (2, FAIL)]},   # 1:3 fails at 35
        20: {0: [(0, OK), (1, FAIL), (2, FAIL)]}, # 1:2 + 1:3 fail at 20
    }
    doc = build_ts_validation(
        _chapters(), results_by_beam, beams, reciter="x", method="kalpy")
    # 1:2 passes at 50 and 35, fails at 20 → narrowest passing beam is 35.
    assert doc["verses"]["1:2"] == {"failed_beams": [20], "min_passing_beam": 35}
    # 1:3 only passes at canonical 50, fails at both 35 and 20.
    assert doc["verses"]["1:3"] == {"failed_beams": [35, 20], "min_passing_beam": 50}
    assert "1:1" not in doc["verses"]
