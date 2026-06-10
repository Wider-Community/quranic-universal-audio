"""Round-trip tests for the shared ``EditHistoryBatch`` / ``EditOperation``
schema — focused on the dead-field fix (TASK A of the schema-unify refactor).

Two fields that the live save flow WRITES and the undo / resolved-by-edit
paths READ — ``patch`` and ``op_context_category`` — used to sit in
``_OP_DEAD_FIELDS`` and were silently stripped on every ``model_validate``.
They are now promoted to declared fields (``patch`` typed as ``EditOpPatch``)
and must survive a round-trip.

Conversely ``save_mode`` is a wire-only presentation hint: the save flow no
longer persists it, but legacy batches that carry it still read (it stays in
``_BATCH_DEAD_FIELDS``), and the History-panel wire shape re-derives it.

The genuinely-dead op fields (``command`` / ``snapshots`` / ``type`` / …)
still strip at INFO via the ``qua_shared.schemas._extras`` logger.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from qua_shared.schemas import EditOperation, EditOpPatch, parse_edit_history_line

_FIXTURE = (
    Path(__file__).parents[2] / "tests" / "fixtures" / "segments" / "112-ikhlas.edit_history.jsonl"
)


def _fixture_lines() -> list[str]:
    return [ln for ln in _FIXTURE.read_text(encoding="utf-8").splitlines() if ln.strip()]


# -- (a) live fields survive ------------------------------------------------


def test_committed_fixture_patch_and_context_survive_round_trip():
    """The committed batch carries a real ``patch`` + ``op_context_category``
    on its op; both must survive ``parse_edit_history_line`` → ``model_dump``.

    The fixture op also carries ``op_context_category`` only implicitly — add
    it here by parsing a synthesized batch that mirrors the live save shape so
    the assertion exercises the promoted field directly.
    """
    [line] = _fixture_lines()
    batch = parse_edit_history_line(line)
    assert batch is not None
    assert len(batch.operations) == 1
    op = batch.operations[0]

    # The fixture op carries a real (non-empty) patch — it must be typed and
    # round-trip with its payload intact, not stripped.
    assert isinstance(op.patch, EditOpPatch)
    assert op.patch.before and op.patch.before[0]["segment_uid"] == (
        "019d5c88-f55f-7ee0-81d1-d99f423e8dd5"
    )
    assert op.patch.affectedChapterIds == [112]

    dumped = batch.model_dump(exclude_none=True)
    dumped_op = dumped["operations"][0]
    assert "patch" in dumped_op, "patch was stripped on round-trip"
    assert dumped_op["patch"]["affectedChapterIds"] == [112]
    assert dumped_op["patch"]["before"][0]["segment_uid"] == (
        "019d5c88-f55f-7ee0-81d1-d99f423e8dd5"
    )


def test_op_context_category_survives_round_trip():
    """``op_context_category`` (read by build_resolved_by_edit_index) is a
    declared field now — it must NOT be stripped."""
    op = EditOperation.model_validate(
        {
            "op_id": "op-ctx-1",
            "op_type": "trim_segment",
            "op_context_category": "boundary_adj",
            "targets_before": [],
            "targets_after": [],
        }
    )
    assert op.op_context_category == "boundary_adj"
    out = op.model_dump(exclude_none=True)
    assert out["op_context_category"] == "boundary_adj"
    assert (op.model_extra or {}) == {}


# -- (b) freshly-built batch does not persist save_mode ---------------------


def test_fresh_batch_model_dump_has_no_save_mode():
    """A batch built the way the save flow builds it (no ``save_mode`` key)
    must NOT gain one through the schema — it's a wire-only hint.

    Also asserts a legacy batch that DOES carry ``save_mode`` still reads
    (the key is tolerated + stripped), proving the field stays in
    ``_BATCH_DEAD_FIELDS``.
    """
    fresh = {
        "schema_version": 1,
        "batch_id": "fresh-batch-1",
        "chapter": 112,
        "saved_at_utc": "2026-06-10T00:00:00.000Z",
        "operations": [
            {
                "op_id": "fresh-op-1",
                "op_type": "trim_segment",
                "op_context_category": "boundary_adj",
                "patch": {
                    "before": [],
                    "after": [],
                    "removedIds": [],
                    "insertedIds": [],
                    "affectedChapterIds": [112],
                },
            }
        ],
    }
    batch = parse_edit_history_line(json.dumps(fresh))
    assert batch is not None
    dumped = batch.model_dump(exclude_none=True)
    assert "save_mode" not in dumped, "save_mode leaked into persisted batch shape"


def test_legacy_batch_with_save_mode_still_reads_and_strips_it(caplog):
    """Legacy on-disk batches carry ``save_mode`` — it must parse (stripped)
    and never reappear in the emitted shape."""
    caplog.set_level(logging.INFO, logger="qua_shared.schemas._extras")
    [line] = _fixture_lines()
    obj = json.loads(line)
    assert obj.get("save_mode") == "full_replace"  # the fixture carries it

    batch = parse_edit_history_line(line)
    assert batch is not None
    assert "save_mode" not in batch.model_dump(exclude_none=True)
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "save_mode" in msgs  # stripped + logged at INFO (legacy class)


# -- (c) genesis lines → None ----------------------------------------------


def test_genesis_lines_parse_to_none():
    """v0 (``type=="genesis"``), v1 (``record_type=="genesis"``), and a
    structurally-pre-batch_id record all parse to ``None``."""
    assert parse_edit_history_line('{"type": "genesis", "audio_source": "qul"}') is None
    assert parse_edit_history_line('{"record_type": "genesis", "extraction_params": {}}') is None
    assert parse_edit_history_line('{"saved_at_utc": "2026-01-01T00:00:00Z"}') is None
    assert parse_edit_history_line("") is None
    assert parse_edit_history_line("   ") is None


# -- (d) genuinely-dead op fields still strip at INFO -----------------------


def test_genuinely_dead_op_fields_still_strip_at_info(caplog):
    """``command`` / ``snapshots`` / ``type`` etc. remain in
    ``_OP_DEAD_FIELDS`` and strip at INFO — they were NOT promoted."""
    caplog.set_level(logging.INFO, logger="qua_shared.schemas._extras")
    op = EditOperation.model_validate(
        {
            "op_id": "dead-op-1",
            "op_type": "trim_segment",
            "type": "trim",  # v0 alias — dead
            "command": {"type": "trim"},  # v1 envelope — dead
            "snapshots": {"before": {}, "after": {}},  # singular form — dead
            "merge_direction": "prev",  # dead
            "applied_at_utc": "2026-01-01T00:00:00Z",  # dead
            "op_context_category": "boundary_adj",  # LIVE — must survive
            "targets_before": [],
            "targets_after": [],
        }
    )
    # Dead fields gone — no typed attribute, no extra.
    for dead in ("type", "command", "snapshots", "merge_direction", "applied_at_utc"):
        assert not hasattr(op, dead)
    assert (op.model_extra or {}) == {}
    # The live promoted field survived alongside the strips.
    assert op.op_context_category == "boundary_adj"
    assert isinstance(op.patch, type(None))  # absent in input → default None

    msgs = " ".join(r.getMessage() for r in caplog.records)
    for dead in ("command", "snapshots", "type", "merge_direction", "applied_at_utc"):
        assert dead in msgs
    # The promoted fields must NOT show up in the stripped-field log.
    assert "op_context_category" not in msgs
    # Confirm the INFO (legacy-class) severity, not WARNING (unknown).
    info_records = [
        r
        for r in caplog.records
        if r.name == "qua_shared.schemas._extras" and r.levelno == logging.INFO
    ]
    assert info_records, "expected an INFO-level legacy-strip log record"


# -- WIRE: _load_edit_history_from_records derives save_mode + is_revert -----


def test_wire_history_batch_derives_save_mode_and_is_revert():
    """Feed records through the History-panel wire builder and assert the
    emitted batch dict still carries a derived ``save_mode`` (the save flow no
    longer persists it) plus ``is_revert``."""
    from services.activity.history_query import _load_edit_history_from_records

    records = [
        {
            "schema_version": 1,
            "batch_id": "wire-batch-1",
            "chapter": 112,
            "saved_at_utc": "2026-06-10T00:00:00.000Z",
            # No save_mode persisted — must be derived. A merge op → structural.
            "operations": [
                {
                    "op_id": "wire-op-1",
                    "op_type": "merge_segments",
                    "op_context_category": "boundary_adj",
                    "targets_before": [],
                    "targets_after": [],
                }
            ],
        },
        {
            "schema_version": 1,
            "batch_id": "wire-batch-2",
            "chapter": 112,
            "saved_at_utc": "2026-06-10T00:01:00.000Z",
            # Field-only edit → patch.
            "operations": [
                {
                    "op_id": "wire-op-2",
                    "op_type": "edit_reference",
                    "targets_before": [],
                    "targets_after": [],
                }
            ],
        },
    ]

    result = _load_edit_history_from_records("wire_reciter", records, cache_result=False)
    batches = {b["batch_id"]: b for b in result["batches"]}

    assert batches["wire-batch-1"]["save_mode"] == "full_replace"
    assert batches["wire-batch-1"]["is_revert"] is False
    assert batches["wire-batch-2"]["save_mode"] == "patch"
    assert batches["wire-batch-2"]["is_revert"] is False
