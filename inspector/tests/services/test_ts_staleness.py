"""Unit tests for the computed TS-track staleness signal.

``ts_stale_info`` compares the edit-history batches against the last TS
generation time. Timestamp-affecting edits saved after the generation make the
generated timestamps stale; annotation-only edits and pre-generation edits do
not. The edit-history read is stubbed via ``parse_history_for_reciter`` so the
test exercises the comparison + op-type filtering directly.
"""

from __future__ import annotations

from services.activity import history_query
from services.segments import ts_staleness

_GEN_AT = "2026-03-01T12:00:00Z"


def _batch(saved_at: str, op_type: str) -> dict:
    return {"saved_at_utc": saved_at, "operations": [{"op_type": op_type}]}


def _patch_history(monkeypatch, batches):
    monkeypatch.setattr(history_query, "parse_history_for_reciter", lambda _slug: batches)


def test_structural_edit_after_generation_is_stale(monkeypatch):
    _patch_history(
        monkeypatch,
        [
            _batch("2026-03-02T09:00:00Z", "trim_segment"),
            _batch("2026-03-03T09:00:00Z", "split_segment"),
        ],
    )
    info = ts_staleness.ts_stale_info("slug", produced_at=_GEN_AT)
    assert info == {"stale_since": "2026-03-02T09:00:00Z", "edits_since": 2}


def test_reference_edit_after_generation_is_stale(monkeypatch):
    """edit_reference changes which ayah a segment maps to → artifact changes."""
    _patch_history(monkeypatch, [_batch("2026-03-02T09:00:00Z", "edit_reference")])
    info = ts_staleness.ts_stale_info("slug", produced_at=_GEN_AT)
    assert info is not None and info["edits_since"] == 1


def test_annotation_only_edits_after_generation_are_not_stale(monkeypatch):
    _patch_history(
        monkeypatch,
        [
            _batch("2026-03-02T09:00:00Z", "confirm_reference"),
            _batch("2026-03-02T10:00:00Z", "ignore_issue"),
            _batch("2026-03-02T11:00:00Z", "flag_segment"),
            _batch("2026-03-02T12:00:00Z", "set_is_wasl"),
        ],
    )
    assert ts_staleness.ts_stale_info("slug", produced_at=_GEN_AT) is None


def test_edit_before_generation_is_not_stale(monkeypatch):
    _patch_history(monkeypatch, [_batch("2026-02-01T09:00:00Z", "trim_segment")])
    assert ts_staleness.ts_stale_info("slug", produced_at=_GEN_AT) is None


def test_edit_history_read_failure_is_not_stale(monkeypatch):
    """A failed edit-history read (e.g. bucket unavailable) must not propagate —
    the status grid calls this per reciter and one failure can't 500 the page."""

    def _boom(_slug):
        raise RuntimeError("bucket 401")

    monkeypatch.setattr(history_query, "parse_history_for_reciter", _boom)
    assert ts_staleness.ts_stale_info("slug", produced_at=_GEN_AT) is None


def test_mixed_batch_counts_only_affecting_and_keeps_earliest(monkeypatch):
    _patch_history(
        monkeypatch,
        [
            _batch("2026-03-05T09:00:00Z", "merge_segments"),
            _batch("2026-03-02T09:00:00Z", "delete_segment"),  # earliest affecting
            _batch("2026-03-04T09:00:00Z", "ignore_issue"),  # excluded
        ],
    )
    info = ts_staleness.ts_stale_info("slug", produced_at=_GEN_AT)
    assert info == {"stale_since": "2026-03-02T09:00:00Z", "edits_since": 2}
