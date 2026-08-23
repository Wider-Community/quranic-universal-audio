"""Strict round-trip tests for native timestamp shard v12."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from qua_shared.schemas import TsShardDoc


def _doc() -> dict:
    return {
        "_meta": {
            "schema_version": 12,
            "chapter": 1,
            "audio_category": "by_surah",
            "phonemizer_version": "2.14.0",
            "native_schema_version": 2,
            "aligner_model": "mfa-arabic-v3",
        },
        "readings": [
            {
                "id": "r1",
                "parts": [{"ref": "1:3", "t": [100, 500], "word_ids": [0]}],
                "analysis": {"schema_version": 2, "result": {}},
                "source": {"schema_version": 2, "source": {}},
                "cells": {"schema_version": 2, "cell_view": {}},
                "timing": {
                    "words": [{"word_id": 0, "start_ms": 100, "end_ms": 500}],
                    "sounds": [{"sound_id": 0, "start_ms": 100, "end_ms": 500}],
                    "units": [{"source_unit_id": 0, "start_ms": 100, "end_ms": 500}],
                    "boundaries": [],
                },
            }
        ],
    }


def test_native_v12_round_trips_without_projection_fields():
    doc = _doc()
    model = TsShardDoc.model_validate(doc)
    assert model.model_dump(by_alias=True, mode="json") == doc


def test_meta_preserves_generation_provenance():
    model = TsShardDoc.model_validate(_doc())
    assert (model.meta.model_extra or {})["aligner_model"] == "mfa-arabic-v3"


@pytest.mark.parametrize("name", ["analysis", "source", "cells"])
def test_every_embedded_native_document_must_be_schema_two(name: str):
    doc = _doc()
    doc["readings"][0][name]["schema_version"] = 1
    with pytest.raises(ValidationError, match=f"{name} is not native schema 2"):
        TsShardDoc.model_validate(doc)


def test_unknown_top_level_and_reading_fields_are_rejected():
    doc = _doc()
    doc["legacy_segments"] = []
    with pytest.raises(ValidationError):
        TsShardDoc.model_validate(doc)
    doc = _doc()
    doc["readings"][0]["share_group"] = 1
    with pytest.raises(ValidationError):
        TsShardDoc.model_validate(doc)


def test_invalid_timing_and_part_ranges_are_rejected():
    doc = _doc()
    doc["readings"][0]["timing"]["sounds"][0]["end_ms"] = 99
    with pytest.raises(ValidationError, match="timing end precedes start"):
        TsShardDoc.model_validate(doc)
    doc = _doc()
    doc["readings"][0]["parts"][0]["t"] = [500, 100]
    with pytest.raises(ValidationError, match="part end precedes start"):
        TsShardDoc.model_validate(doc)
