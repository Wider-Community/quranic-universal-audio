"""Tests for the standalone release tier sharding helper."""

from __future__ import annotations

from qua_jobs import shard


def test_split_v3_occurrence_rows_preserves_order_and_recomputes_counts():
    doc = {
        "_meta": {"tier": "word", "verse_count": 2, "occurrence_count": 3},
        "rows": [
            ["1:1", 0, 100, False, [[1, 0, 100]]],
            ["1:1", 200, 400, True, [[1, 200, 400]]],
            ["2:1", 0, 300, True, [[1, 0, 300]]],
        ],
    }

    out = shard.split(doc)

    assert out[1]["rows"] == doc["rows"][:2]
    assert out[1]["_meta"]["chapter"] == 1
    assert out[1]["_meta"]["verse_count"] == 1
    assert out[1]["_meta"]["occurrence_count"] == 2
    assert out[2]["rows"] == doc["rows"][2:]


def test_split_legacy_keyed_tier_remains_supported():
    out = shard.split({"_meta": {"tier": "verse"}, "2:2": [5, 9], "2:1": [0, 4]})
    assert list(out[2]) == ["_meta", "2:1", "2:2"]
