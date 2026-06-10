"""``POST /api/seg/segment-peaks`` per-item tolerance.

The route validates each requested slice individually so one malformed item is
skipped while its valid siblings still render — rather than a single bad item
wiping the whole batch (the regression a naive whole-request ``model_validate``
would introduce).
"""

from __future__ import annotations

from routes.segments import peaks as peaks_route


def _fake_compute(url, start_ms, end_ms, reciter, chapter=None, bps=None):
    return {
        "schema_version": 3,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "duration_ms": end_ms - start_ms,
        "peaks": [[0.0, 0.1]],
    }


def test_segment_peaks_skips_only_the_malformed_item(flask_client, monkeypatch):
    """A batch with one valid slice and one malformed slice (an unknown key,
    rejected by the ``extra="forbid"`` item model) returns the valid slice's
    peaks — the bad item is dropped, not the whole batch."""
    monkeypatch.setattr(peaks_route, "compute_segment_peaks", _fake_compute)

    body = {
        "segments": [
            {"url": "good", "start_ms": 0, "end_ms": 1000},
            {"url": "bad", "start_ms": 0, "end_ms": 1000, "unknown_key": "x"},
        ]
    }
    resp = flask_client.post("/api/seg/segment-peaks/some_reciter", json=body)

    assert resp.status_code == 200
    peaks = resp.get_json()["peaks"]
    assert "good:0:1000" in peaks  # valid sibling survived
    assert "bad:0:1000" not in peaks  # malformed item skipped
    assert peaks["good:0:1000"]["duration_ms"] == 1000


def test_segment_peaks_empty_batch_returns_empty(flask_client, monkeypatch):
    """An all-malformed batch returns 200 with no peaks (graceful fallback),
    never a 500."""
    monkeypatch.setattr(peaks_route, "compute_segment_peaks", _fake_compute)

    resp = flask_client.post(
        "/api/seg/segment-peaks/some_reciter",
        json={"segments": [{"oops": 1}]},
    )

    assert resp.status_code == 200
    assert resp.get_json()["peaks"] == {}
