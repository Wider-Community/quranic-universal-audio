"""Round-trip tests for the ``PipelineMeta`` Pydantic schema.

Schema lives at ``qua_shared/schemas/bucket/pipeline_meta.py``. The artefact
is the per-reciter ``reciters/<slug>/pipeline_meta.json`` — immutable facts
emitted by the offline extraction pipeline (currently the set of chapters
whose Basmala was stripped) so Inspector doesn't re-derive them at runtime.

These assert the canonical shape round-trips byte/shape-equal, the required
``generated_at`` provenance, and that the artefact is pure ``extra="forbid"``
— any unknown key raises ``ValidationError`` rather than being stripped.
"""

from __future__ import annotations

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


# -- pure extra="forbid" policy ----------------------------------------


def test_unknown_key_rejected():
    """An unknown key raises ``ValidationError`` under pure ``extra="forbid"``
    — no silent strip, no absorbed extra, no crash-on-read tolerance."""
    raw = _canonical_meta()
    raw["bogus_field"] = 123
    with pytest.raises(ValueError):
        PipelineMeta.model_validate(raw)


# -- Round-trip emission ------------------------------------------------


def test_round_trip_byte_shape_equal():
    """``model_dump()`` reproduces the canonical artefact shape exactly —
    no field renamed or dropped, no extra key introduced."""
    raw = _canonical_meta()
    m = PipelineMeta.model_validate(raw)
    out = m.model_dump()
    assert out == raw
