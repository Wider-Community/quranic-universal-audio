"""Round-trip tests for the per-chapter Timestamps shard schema.

Schema lives at ``qua_shared/schemas/bucket/ts_shard.py`` and models the
decompressed body of ``reciters/<slug>/timestamps/<ch>.json.gz`` — the
temporal segment-array shape produced by
``qua_shared/timestamps_shards.py::build_segment_shards``.

The FE consumes this document, so the word payload is a positional tuple
(``TsShardWord``) that must survive parse → ``model_dump`` byte/shape-equal
(modulo JSON having no tuple type — tuples serialise as lists).
"""

from __future__ import annotations

import json

import pytest

from qua_shared.schemas import TsShardDoc, TsShardWord


def _sample_word() -> list:
    """One 5-slot word tuple: [word_idx, start_ms, end_ms, letters, phones].

    ``letters`` mixes a 4-slot row carrying the v4 ``silent`` flag with legacy
    3-slot triples (one null timing to exercise the optional slot); ``phones``
    carries a 3-cell row and a 4-cell bridge-tagged row (slot 5 = cross-word
    tajweed bridge rule).
    """
    return [
        1,
        100,
        540,
        [["ب", 100, 180, False], ["س", 180, None], ["م", 280, 540]],
        [["b", 100, 180], ["s", 180, 280, "bridge:idgham"]],
    ]


def _sample_doc() -> dict:
    """Minimal but representative shard doc with `_meta` + two segments."""
    return {
        "_meta": {
            "schema_version": 3,
            "chapter": 1,
            "audio_category": "by_surah",
            "aligner_model": "mfa-arabic-v3",
            "created_at": "2026-05-01T00:00:00Z",
        },
        "segments": [
            {"ref": "1:1", "t": [100, 540], "words": [_sample_word()]},
            {
                "ref": "1:2",
                "t": [600, 900],
                "words": [[2, 600, 900, [["ا", 600, 900]], [["a", 600, 900]]]],
            },
        ],
    }


def _normalize(obj):
    """JSON round-trip to coerce tuples → lists for shape comparison."""
    return json.loads(json.dumps(obj))


def test_shard_doc_parses_and_round_trips():
    doc = _sample_doc()
    m = TsShardDoc.model_validate(doc)
    # exclude_defaults mirrors the writer: optional additive fields (the v10
    # ``wasl`` flag) are emitted only when set, so a pre-v10 shard round-trips
    # byte-stable instead of gaining ``wasl: False`` on every segment.
    out = m.model_dump(by_alias=True, exclude_defaults=True)
    assert _normalize(out) == _normalize(doc)


def test_shard_segment_wasl_flag_round_trips():
    doc = _sample_doc()
    doc["_meta"]["schema_version"] = 10
    doc["segments"][0]["wasl"] = True  # this occurrence continues into the next
    m = TsShardDoc.model_validate(doc)
    out = m.model_dump(by_alias=True, exclude_defaults=True)
    assert _normalize(out) == _normalize(doc)
    assert out["segments"][0]["wasl"] is True
    assert "wasl" not in out["segments"][1]  # default False stays omitted


def test_shard_word_tuple_round_trips():
    word = _sample_word()
    m = TsShardWord.model_validate(word)
    # RootModel.root holds the tuple; serialised it is the same positional shape.
    assert _normalize(m.model_dump()) == _normalize(word)
    assert isinstance(m.root, tuple)
    assert m.root[0] == 1 and m.root[1] == 100 and m.root[2] == 540


def test_shard_word_arity_is_five():
    """A word with the wrong number of positional slots is rejected — this is
    the contract the FE positional tuple relies on."""
    too_short = [1, 100, 540, [["ب", 100, 180]]]  # missing phones slot
    with pytest.raises(ValueError):
        TsShardWord.model_validate(too_short)


def test_shard_doc_requires_meta():
    doc = _sample_doc()
    doc.pop("_meta")
    with pytest.raises(ValueError):
        TsShardDoc.model_validate(doc)


def test_shard_meta_passes_provenance_through():
    """`_meta` is ``extra="allow"`` so optional aligner provenance the writer
    copies through stays on the model rather than being dropped."""
    m = TsShardDoc.model_validate(_sample_doc())
    assert m.meta.audio_category == "by_surah"
    assert (m.meta.model_extra or {}).get("aligner_model") == "mfa-arabic-v3"


def test_shard_doc_strips_unknown_top_level_field(caplog):
    """An unrecognised top-level key (not ``_meta``/``segments``) is stripped
    with a WARNING via ``strip_and_warn`` — surfaces writer/schema drift."""
    import logging

    caplog.set_level(logging.WARNING, logger="qua_shared.schemas._extras")
    doc = _sample_doc()
    doc["bogus"] = {"junk": 1}
    m = TsShardDoc.model_validate(doc)
    assert (m.model_extra or {}) == {}
    assert "bogus" in " ".join(r.getMessage() for r in caplog.records)
