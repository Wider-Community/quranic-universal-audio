"""Staged-run reader tests — the QUA half of the cross-repo contract.

The three golden files under ``qua_shared/schemas/bucket/fixtures/`` are
byte-identical copies of the ones the producer's own contract test emits, so a
rename on the monorepo side reds here instead of inside promote. The stamping
tests pin the type boundary: ``stamp_operation`` returns a dict, leaves the
read-only event untouched, and the result validates as a real ``EditOperation``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from qua_shared.schemas import DetailedSegment, EditHistoryBatch
from qua_shared.schemas.bucket import staged_run
from qua_shared.schemas.bucket.staged_run import (
    ChapterCandidateDoc,
    PipelineAuditEvent,
    RunManifestDoc,
    stamp_operation,
)

FIXTURES = Path(staged_run.__file__).parent / "fixtures"

AUDIO_URL = "https://example.invalid/media/075.mp3"


def _load(name: str):
    return json.loads((FIXTURES / f"{name}.golden.json").read_text(encoding="utf-8"))


def _events() -> list[PipelineAuditEvent]:
    return [PipelineAuditEvent.model_validate(raw) for raw in _load("audit_events")]


def _waqf_event() -> PipelineAuditEvent:
    return next(ev for ev in _events() if ev.kind == "waqf_sakt")


def _delete_event() -> PipelineAuditEvent:
    return next(ev for ev in _events() if ev.kind == "delete_segment")


def test_golden_manifest_validates():
    manifest = RunManifestDoc.model_validate(_load("run_manifest"))
    assert manifest.slug == manifest.inputs.slug
    assert set(manifest.required) <= {entry.path for entry in manifest.artifacts}
    assert manifest.model_revisions["asr"]
    assert manifest.model_revisions["vad"]
    assert manifest.inputs.audio_source


def test_golden_candidate_validates():
    candidate = ChapterCandidateDoc.model_validate(_load("chapter_candidate"))
    assert candidate.chapter == 1
    assert [entry.ref for entry in candidate.entries] == ["1", "2"]
    assert candidate.trim_span_ms == (120, 12500)


def test_golden_events_validate():
    events = _events()
    assert [ev.kind for ev in events] == ["waqf_sakt", "delete_segment", "delete_segment"]
    assert len(_waqf_event().targets_before) == 2
    assert _delete_event().targets_after == []


@pytest.mark.parametrize(
    ("fixture", "reader"),
    [
        ("run_manifest", RunManifestDoc),
        ("chapter_candidate", ChapterCandidateDoc),
    ],
)
def test_unknown_producer_field_is_ignored(fixture, reader):
    raw = _load(fixture) | {"a_field_the_producer_added": 1}
    assert reader.model_validate(raw)


def test_unknown_producer_field_on_an_event_is_ignored():
    raw = _load("audit_events")[0] | {"a_field_the_producer_added": 1}
    assert PipelineAuditEvent.model_validate(raw)


@pytest.mark.parametrize(
    ("fixture", "reader", "dropped"),
    [
        ("run_manifest", RunManifestDoc, "run_id"),
        ("run_manifest", RunManifestDoc, "required"),
        ("chapter_candidate", ChapterCandidateDoc, "source_url"),
    ],
)
def test_missing_declared_field_is_rejected(fixture, reader, dropped):
    raw = _load(fixture)
    del raw[dropped]
    with pytest.raises(ValidationError):
        reader.model_validate(raw)


def test_missing_declared_field_on_an_event_is_rejected():
    raw = _load("audit_events")[0]
    del raw["chapter"]
    with pytest.raises(ValidationError):
        PipelineAuditEvent.model_validate(raw)


def test_candidate_segments_validate_as_detailed_segments_unchanged():
    """Every staged segment is a persisted segment already — promote renames nothing."""
    candidate = ChapterCandidateDoc.model_validate(_load("chapter_candidate"))
    segments = [seg for entry in candidate.entries for seg in entry.segments]
    assert len(segments) == 3
    for seg in segments:
        parsed = DetailedSegment.model_validate(seg)
        for key, value in seg.items():
            assert getattr(parsed, key) == value


def test_waqf_final_index_differs_from_index_at_save():
    """A producer that reverts to the pre-strip index fails here, not at a user's undo."""
    after = _waqf_event().targets_after[0]
    assert after.final_index is not None
    assert after.final_index != after.index_at_save


def test_stamped_waqf_event_is_a_dict_and_leaves_the_event_untouched():
    ev = _waqf_event()
    before = ev.model_dump()

    op = stamp_operation(ev, op_id="op-1", audio_url=AUDIO_URL, after_uid="uid-after")

    assert isinstance(op, dict)
    assert ev.model_dump() == before
    assert op["op_type"] == "waqf_sakt"
    assert op["fix_kind"] == "auto_fix"
    assert all("final_index" not in snap for snap in op["targets_before"] + op["targets_after"])
    assert [snap["segment_uid"] for snap in op["targets_before"]] == [None, None]
    assert op["targets_after"][0]["segment_uid"] == "uid-after"
    assert {snap["chapter"] for snap in op["targets_before"]} == {ev.chapter}
    assert {snap["audio_url"] for snap in op["targets_after"]} == {AUDIO_URL}
    assert op["targets_after"][0]["index_at_save"] == ev.targets_after[0].index_at_save


def test_stamped_event_validates_as_an_edit_history_batch():
    ev = _waqf_event()
    op = stamp_operation(ev, op_id="op-1", audio_url=AUDIO_URL, after_uid="uid-after")

    batch = EditHistoryBatch.model_validate(
        {
            "schema_version": 1,
            "batch_id": "batch-1",
            "chapter": ev.chapter,
            "saved_at_utc": "2026-08-07T09:15:00Z",
            "operations": [op],
        }
    )

    assert batch.operations[0].targets_after[0]["segment_uid"] == "uid-after"


def test_stamped_delete_event_carries_the_callers_before_uid():
    ev = _delete_event()

    op = stamp_operation(ev, op_id="op-2", audio_url=AUDIO_URL, before_uids=["uid-deleted"])

    assert op["op_type"] == "delete_segment"
    assert op["targets_after"] == []
    assert op["targets_before"][0]["segment_uid"] == "uid-deleted"
    assert op["targets_before"][0]["matched_ref"] == "Basmala"


def test_stamp_operation_rejects_a_before_uid_count_mismatch():
    with pytest.raises(ValueError, match="before_uids"):
        stamp_operation(_waqf_event(), op_id="op-3", audio_url=AUDIO_URL, before_uids=["only-one"])
