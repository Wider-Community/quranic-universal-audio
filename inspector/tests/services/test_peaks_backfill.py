"""Tests for ``services.audio.peaks_backfill``.

The backfill is the inspector's catch-up for pipeline ops whose peaks the
alignment-time post-passes never wrote. It must be idempotent, must skip ops
with no resolvable audio URL or no usable time range, and must produce
records that ``append_peaks_records`` accepts.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def patch_backfill(monkeypatch):
    """Patch the seams ``backfill_pipeline_peaks`` depends on.

    Returns a small container so each test can wire its own history records,
    detailed-json entries, and ``compute_segment_peaks`` stub.
    """
    from services.audio import peaks_backfill as backfill_mod

    state = {
        "history_records": [],
        "detailed_entries": [],
        "persisted_peaks": [],
        "compute_calls": [],
        "appended": [],
    }

    def fake_parse_history(reciter):
        return list(state["history_records"])

    def fake_load_detailed(reciter):
        return list(state["detailed_entries"])

    def fake_load_peaks_records(reciter, exclude_op_ids=None):
        return list(state["persisted_peaks"])

    def fake_compute_segment_peaks(url, start_ms, end_ms, reciter):
        state["compute_calls"].append((url, start_ms, end_ms, reciter))
        return {
            "schema_version": 2,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "duration_ms": end_ms - start_ms,
            "peaks": [[-0.1, 0.1]] * 5,
        }

    def fake_append_peaks_records(reciter, records, batch_id=None):
        state["appended"].append((reciter, list(records), batch_id))
        return len(records)

    monkeypatch.setattr(backfill_mod, "parse_history_for_reciter", fake_parse_history)
    monkeypatch.setattr(backfill_mod, "load_detailed", fake_load_detailed)
    monkeypatch.setattr(backfill_mod, "load_peaks_records", fake_load_peaks_records)
    monkeypatch.setattr(
        backfill_mod, "compute_segment_peaks", fake_compute_segment_peaks,
    )
    monkeypatch.setattr(backfill_mod, "append_peaks_records", fake_append_peaks_records)

    return state, backfill_mod


def _batch(batch_type=None, chapter=None, ops=None, batch_id="b1"):
    return {
        "schema_version": 1,
        "batch_id": batch_id,
        "batch_type": batch_type,
        "chapter": chapter,
        "operations": ops or [],
    }


def _strip_op(op_id: str, *, chapter: int | None, t0: int, t1: int, ref="Basmala",
              audio_url: str | None = None):
    return {
        "op_id": op_id,
        "op_type": "delete_segment",
        "targets_before": [{
            "segment_uid": f"snap-{op_id}",
            "chapter": chapter,
            "audio_url": audio_url,
            "time_start": t0,
            "time_end": t1,
            "matched_ref": ref,
            "matched_text": "x",
            "confidence": 0.95,
        }],
        "targets_after": [],
    }


def _waqf_op(op_id: str, *, chapter: int, t0: int, t1: int,
             audio_url: str | None = None):
    snap = {
        "segment_uid": f"snap-{op_id}",
        "chapter": chapter,
        "audio_url": audio_url,
        "time_start": t0,
        "time_end": t1,
        "matched_ref": f"{chapter}:27:2-{chapter}:27:2",
        "matched_text": "x",
        "confidence": 1.0,
    }
    return {
        "op_id": op_id,
        "op_type": "waqf_sakt",
        "targets_before": [snap],
        "targets_after": [snap],
    }


def test_backfill_writes_peaks_for_missing_pipeline_ops(patch_backfill):
    state, backfill_mod = patch_backfill
    state["detailed_entries"] = [
        {"ref": "2", "audio": "https://example/002.mp3", "segments": []},
        {"ref": "5", "audio": "https://example/005.mp3", "segments": []},
    ]
    state["history_records"] = [
        _batch(
            batch_type="strip_specials",
            ops=[
                _strip_op("op-2", chapter=2, t0=0, t1=2000),
                _strip_op("op-5", chapter=5, t0=100, t1=2400),
            ],
        ),
    ]

    written = backfill_mod.backfill_pipeline_peaks("rec_a")

    assert written == 2
    # Two compute calls, one per op, with the chapter's audio URL.
    urls = sorted(call[0] for call in state["compute_calls"])
    assert urls == ["https://example/002.mp3", "https://example/005.mp3"]
    # Records appended carry the op_id and URL we expect.
    assert len(state["appended"]) == 1
    _, records, batch_id = state["appended"][0]
    assert batch_id == "b1"
    op_ids = sorted(r["op_id"] for r in records)
    assert op_ids == ["op-2", "op-5"]


def test_backfill_is_idempotent(patch_backfill):
    state, backfill_mod = patch_backfill
    state["detailed_entries"] = [
        {"ref": "2", "audio": "https://example/002.mp3", "segments": []},
    ]
    state["history_records"] = [
        _batch(
            batch_type="strip_specials",
            ops=[_strip_op("op-2", chapter=2, t0=0, t1=2000)],
        ),
    ]
    state["persisted_peaks"] = [{"op_id": "op-2", "url": "x", "peaks": []}]

    written = backfill_mod.backfill_pipeline_peaks("rec_a")

    assert written == 0
    assert state["compute_calls"] == []
    assert state["appended"] == []


def test_backfill_skips_ops_with_no_audio_url(patch_backfill):
    state, backfill_mod = patch_backfill
    # Chapter 17 has NO detailed entry — backfill cannot resolve a URL.
    state["detailed_entries"] = [
        {"ref": "2", "audio": "https://example/002.mp3", "segments": []},
    ]
    state["history_records"] = [
        _batch(
            batch_type="strip_specials",
            ops=[
                _strip_op("op-2", chapter=2, t0=0, t1=2000),
                _strip_op("op-17", chapter=17, t0=0, t1=2000),
            ],
        ),
    ]

    written = backfill_mod.backfill_pipeline_peaks("rec_a")

    # Only chapter-2 has a resolvable URL; chapter-17 is skipped (not failed).
    assert written == 1
    assert len(state["compute_calls"]) == 1
    assert state["compute_calls"][0][0] == "https://example/002.mp3"


def test_backfill_prefers_snapshot_audio_url_over_chapter_lookup(patch_backfill):
    state, backfill_mod = patch_backfill
    # detailed.json says chapter 2 → fallback.mp3, but the snapshot already
    # carries its own URL (extraction-fix path). The snapshot wins.
    state["detailed_entries"] = [
        {"ref": "2", "audio": "https://example/fallback.mp3", "segments": []},
    ]
    state["history_records"] = [
        _batch(
            batch_type="strip_specials",
            ops=[_strip_op(
                "op-2", chapter=2, t0=0, t1=2000,
                audio_url="https://example/from-snap.mp3",
            )],
        ),
    ]

    written = backfill_mod.backfill_pipeline_peaks("rec_a")

    assert written == 1
    assert state["compute_calls"][0][0] == "https://example/from-snap.mp3"


def test_backfill_handles_waqf_sakt_ops(patch_backfill):
    state, backfill_mod = patch_backfill
    state["detailed_entries"] = [
        {"ref": "75", "audio": "https://example/075.mp3", "segments": []},
    ]
    state["history_records"] = [
        _batch(
            batch_type=None,
            chapter=75,
            ops=[_waqf_op("op-w", chapter=75, t0=1000, t1=4000)],
        ),
    ]

    written = backfill_mod.backfill_pipeline_peaks("rec_a")

    assert written == 1
    assert state["compute_calls"][0] == (
        "https://example/075.mp3", 1000, 4000, "rec_a",
    )


def test_backfill_ignores_genesis_and_user_edits(patch_backfill):
    state, backfill_mod = patch_backfill
    state["detailed_entries"] = [
        {"ref": "2", "audio": "https://example/002.mp3", "segments": []},
    ]
    state["history_records"] = [
        {"record_type": "genesis", "batch_id": "g", "operations": []},
        _batch(
            batch_type=None,
            chapter=2,
            ops=[{
                "op_id": "op-user",
                "op_type": "edit_boundary",  # not a pipeline op
                "targets_before": [{"chapter": 2, "time_start": 0, "time_end": 1000}],
                "targets_after": [],
            }],
        ),
    ]

    written = backfill_mod.backfill_pipeline_peaks("rec_a")

    assert written == 0
    assert state["compute_calls"] == []
