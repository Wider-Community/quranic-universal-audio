"""Round-trip tests for the verse-aggregated ``segments.json`` schema.

Schema lives at ``qua_shared/schemas/bucket/segments_doc.py`` and models the
``reciters/<slug>/segments.json`` artefact: a ``_meta`` block plus dynamic
``"<surah>:<ayah>"`` verse keys mapping to lists of
``[w_start, w_end, ms_start, ms_end, ...optional dict]`` rows.

This is a BACKEND-ONLY artefact (never FE-facing). The schema mirrors the
structural checks in ``services/storage/bucket_audit.py::_audit_segments``.
"""

from __future__ import annotations

import json

import pytest

from qua_shared.schemas import SegmentsDoc


def _sample_doc() -> dict:
    """`_meta` + two verse keys; one row carries an optional annotation dict."""
    return {
        "_meta": {"audio_source": "by_surah/fixture", "created_at": "2026-05-01T00:00:00Z"},
        "1:1": [[0, 3, 100, 540], [4, 6, 540, 900]],
        "1:2": [[0, 2, 900, 1200, {"repeated": [[0, 2]]}]],
    }


def _normalize(obj):
    return json.loads(json.dumps(obj))


def test_segments_doc_parses_dynamic_keys():
    doc = _sample_doc()
    m = SegmentsDoc.model_validate(doc)
    assert set(m.root.keys()) - {"_meta"} == {"1:1", "1:2"}


def test_segments_doc_round_trips():
    doc = _sample_doc()
    m = SegmentsDoc.model_validate(doc)
    assert _normalize(m.model_dump()) == _normalize(doc)


def test_segments_doc_meta_optional_dict_preserved():
    m = SegmentsDoc.model_validate(_sample_doc())
    assert m.root["_meta"]["audio_source"] == "by_surah/fixture"
    # Optional trailing annotation dict on a row survives.
    assert m.root["1:2"][0][4] == {"repeated": [[0, 2]]}


def test_segments_doc_rejects_inverted_ms_range():
    doc = _sample_doc()
    doc["1:1"] = [[0, 3, 900, 100]]  # ms_end < ms_start
    with pytest.raises(ValueError, match="ms_end < ms_start"):
        SegmentsDoc.model_validate(doc)


def test_segments_doc_rejects_short_row():
    doc = _sample_doc()
    doc["1:1"] = [[0, 3, 100]]  # only three cells — need four ints
    with pytest.raises(ValueError, match=r"1:1\[0\]"):
        SegmentsDoc.model_validate(doc)


def test_segments_doc_rejects_non_int_word_range():
    doc = _sample_doc()
    doc["1:1"] = [["a", 3, 100, 540]]
    with pytest.raises(ValueError, match="word range not ints"):
        SegmentsDoc.model_validate(doc)


def test_segments_doc_rejects_bad_verse_key():
    doc = _sample_doc()
    doc["nope"] = [[0, 3, 100, 540]]
    with pytest.raises(ValueError, match="invalid verse key"):
        SegmentsDoc.model_validate(doc)


def test_segments_doc_rejects_non_dict_meta():
    doc = _sample_doc()
    doc["_meta"] = ["not", "a", "dict"]
    with pytest.raises(ValueError, match="_meta must be a dict"):
        SegmentsDoc.model_validate(doc)


def test_segments_doc_rejects_non_dict_row_tail():
    doc = _sample_doc()
    doc["1:1"] = [[0, 3, 100, 540, "not-a-dict"]]
    with pytest.raises(ValueError, match="row tail must be a dict"):
        SegmentsDoc.model_validate(doc)
