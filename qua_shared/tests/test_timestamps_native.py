from __future__ import annotations

import gzip
import sys
import types

import orjson
import pytest

from qua_shared.timestamps_native import project_native_shard, select_complete_verses
from qua_shared.timestamps_shards import build_timestamp_shards, gzip_shard


def _reading(reading_id: str, specs: list[tuple[str, tuple[int, int], list[int]]]) -> dict:
    words, units, word_timing, unit_timing, parts = [], [], [], [], []
    for ref, span, indexes in specs:
        ids = []
        width = max(1, (span[1] - span[0]) // len(indexes))
        for offset, index in enumerate(indexes):
            word_id = len(words) + 1
            unit_id = 100 + word_id
            start = span[0] + offset * width
            end = start + width
            ids.append(word_id)
            words.append({"id": word_id, "ref": f"{ref}:{index}"})
            units.append({"id": unit_id, "word_id": word_id, "kind": "letter", "text": "x"})
            word_timing.append({"word_id": word_id, "start_ms": start, "end_ms": end})
            unit_timing.append({"source_unit_id": unit_id, "start_ms": start, "end_ms": end})
        parts.append({"ref": ref, "t": list(span), "word_ids": ids})
    return {
        "id": reading_id,
        "parts": parts,
        "analysis": {"schema_version": 2, "result": {"words": words}},
        "source": {"schema_version": 2, "source": {"units": units}},
        "cells": {"schema_version": 2, "cell_view": {}},
        "timing": {"words": word_timing, "sounds": [], "units": unit_timing, "boundaries": []},
    }


def _shard(readings: list[dict]) -> dict:
    return {
        "_meta": {
            "schema_version": 12,
            "chapter": 1,
            "audio_category": "by_surah",
            "phonemizer_version": "2.14",
            "native_schema_version": 2,
        },
        "readings": readings,
    }


def test_native_projection_keeps_loopback_and_earliest_complete_occasion():
    shard = _shard(
        [
            _reading("r1", [("1:1", (0, 400), [1, 2]), ("1:1", (400, 900), [2, 3])]),
            _reading("r2", [("1:2", (900, 1100), [1])]),
            _reading("r3", [("1:1", (1100, 1600), [1, 2, 3])]),
        ]
    )
    projected = project_native_shard(shard)
    assert [word["index"] for word in projected["1:1"]["words"]] == [1, 2, 2, 3]
    assert projected["1:1"]["verse_start_ms"] == 0
    assert projected["1:1"]["verse_end_ms"] == 900


def test_native_projection_rejects_every_old_schema():
    shard = _shard([])
    shard["_meta"]["schema_version"] = 11
    with pytest.raises(ValueError, match="version 12"):
        project_native_shard(shard)


def test_complete_verse_gate_uses_native_word_indexes():
    projected = project_native_shard(_shard([_reading("r1", [("1:1", (0, 200), [1, 3])])]))
    kept, dropped = select_complete_verses(projected, {(1, 1): 3})
    assert kept == {}
    assert dropped == ["1:1"]


def test_builder_delegates_to_staged_sdk(monkeypatch):
    calls = []

    class FakeShards(types.ModuleType):
        def build_native_shards(self, doc, **kwargs):
            calls.append((doc, kwargs))
            return {1: {}}

    module = FakeShards("qua_sdk.integrations.shards")
    monkeypatch.setitem(sys.modules, "qua_sdk", types.ModuleType("qua_sdk"))
    monkeypatch.setitem(
        sys.modules, "qua_sdk.integrations", types.ModuleType("qua_sdk.integrations")
    )
    monkeypatch.setitem(sys.modules, "qua_sdk.integrations.shards", module)
    assert build_timestamp_shards({"raw": True}, audio_category="by_surah") == {1: {}}
    assert calls == [({"raw": True}, {"audio_category": "by_surah", "src_meta": None})]


def test_native_gzip_is_deterministic():
    shard = _shard([_reading("r1", [("1:1", (0, 100), [1])])])
    first = gzip_shard(shard)
    assert first == gzip_shard(shard)
    assert orjson.loads(gzip.decompress(first)) == shard
