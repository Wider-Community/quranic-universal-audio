"""Strict round-trip tests for compact timestamp shard v12."""

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
            "renderer_codec_version": 1,
            "native_profile": {
                "riwayah": "hafs",
                "script": "uthmani",
                "variant": {},
                "extra_phonemes": ["emphatic_fatha"],
            },
            "aligner_model": "mfa-arabic-v3",
        },
        "readings": [
            {
                "id": "r1",
                "parts": [["1:3", 100, 500, 0, 1]],
                "render": {
                    "v": 1,
                    "m": ["1:3:1", "canon", "native"],
                    "p": ["b"],
                    "r": [],
                    "w": [["1:3:1", "ب", [], [[0, [], []]], [], [], []]],
                    "b": [[3, [], [], [], 3, None]],
                },
                "timing": {
                    "w": [[100, 500]],
                    "s": [[100, 500]],
                    "l": [[0, 0, "ب", 100, 500, 0]],
                    "c": [],
                },
            }
        ],
    }


def test_native_v12_round_trips_compact_storage():
    doc = _doc()
    model = TsShardDoc.model_validate(doc)
    assert model.model_dump(by_alias=True, mode="json") == doc


def test_meta_preserves_generation_provenance():
    model = TsShardDoc.model_validate(_doc())
    assert (model.meta.model_extra or {})["aligner_model"] == "mfa-arabic-v3"


def test_renderer_codec_version_is_guarded():
    doc = _doc()
    doc["readings"][0]["render"]["v"] = 2
    with pytest.raises(ValidationError):
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
    doc["readings"][0]["timing"]["s"][0] = [100, 99]
    with pytest.raises(ValidationError, match="timing end precedes start"):
        TsShardDoc.model_validate(doc)
    doc = _doc()
    doc["readings"][0]["parts"][0] = ["1:3", 500, 100, 0, 1]
    with pytest.raises(ValidationError, match="invalid compact part"):
        TsShardDoc.model_validate(doc)
