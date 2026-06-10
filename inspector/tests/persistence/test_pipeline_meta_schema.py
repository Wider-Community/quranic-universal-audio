"""Round-trip tests for the ``PipelineMeta`` Pydantic schema.

Schema lives at ``qua_shared/schemas/bucket/pipeline_meta.py``. The artefact
is the per-reciter ``reciters/<slug>/pipeline_meta.json`` — immutable facts
emitted by the offline extraction pipeline (currently the set of chapters
whose Basmala was stripped) so Inspector doesn't re-derive them at runtime.

These assert the canonical shape round-trips byte/shape-equal, the required
``generated_at`` provenance, and that ``extra="forbid"`` + the
``strip_and_warn`` pre-validator surface unknown keys with a WARNING + strip
them rather than crashing the read or absorbing them as silent extras.
"""

from __future__ import annotations

import logging

import pytest

from qua_shared.schemas import PipelineMeta


def _canonical_meta() -> dict:
    """Canonical pipeline_meta — generated_at + a couple stripped chapters."""
    return {
        "schema_version": 1,
        "generated_at": "2026-05-16T21:46:39.362Z",
        "deleted_basmala_chapters": [9, 1],
    }


# -- Validation tests ---------------------------------------------------


def test_canonical_meta_validates():
    m = PipelineMeta.model_validate(_canonical_meta())
    assert m.schema_version == 1
    assert m.generated_at == "2026-05-16T21:46:39.362Z"
    assert m.deleted_basmala_chapters == [9, 1]


def test_generated_at_required():
    """``generated_at`` has no default — a record without it is corrupt."""
    raw = _canonical_meta()
    raw.pop("generated_at")
    with pytest.raises(ValueError):
        PipelineMeta.model_validate(raw)


def test_deleted_basmala_defaults_empty():
    """A reciter with no stripped Basmala still validates — the list
    defaults to empty."""
    raw = _canonical_meta()
    raw.pop("deleted_basmala_chapters")
    m = PipelineMeta.model_validate(raw)
    assert m.deleted_basmala_chapters == []
    assert m.model_dump()["deleted_basmala_chapters"] == []


# -- extra="forbid" / strip_and_warn policy ----------------------------


def test_unknown_key_stripped_and_warned(caplog):
    """An unknown key is stripped + surfaces a WARNING (not absorbed as an
    extra, not a crash) — the lean-artefact tolerance policy."""
    caplog.set_level(logging.WARNING, logger="qua_shared.schemas._extras")
    raw = _canonical_meta()
    raw["bogus_field"] = 123
    m = PipelineMeta.model_validate(raw)
    assert (m.model_extra or {}) == {}
    assert not hasattr(m, "bogus_field")
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "bogus_field" in msgs
    assert "UNRECOGNIZED" in msgs


# -- Round-trip emission ------------------------------------------------


def test_round_trip_byte_shape_equal():
    """``model_dump()`` reproduces the canonical artefact shape exactly —
    no field renamed or dropped, no extra key introduced."""
    raw = _canonical_meta()
    m = PipelineMeta.model_validate(raw)
    out = m.model_dump()
    assert out == raw
