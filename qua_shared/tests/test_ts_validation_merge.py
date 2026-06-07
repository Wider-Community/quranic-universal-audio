"""``_merge_ts_validation`` must not clobber untouched chapters' flags.

A partial (affected-only) regeneration rebuilds ``ts_validation.json`` from only
the processed chapters' results. The merge keeps the prior file's flags for every
non-refreshed chapter and replaces the refreshed ones — the key guard against a
chapter-5 regen silently dropping chapter-37's low-confidence flags.
"""

from __future__ import annotations

import json

from qua_shared.timestamps_pipeline import _merge_ts_validation


def _write(tmp_path, verses):
    p = tmp_path / "ts_validation.json"
    p.write_text(json.dumps({"_meta": {"beams": [2, 50]}, "verses": verses}), encoding="utf-8")
    return p


def test_merge_preserves_untouched_chapter_flags(tmp_path):
    path = _write(tmp_path, {"37:151": {"flag": "old"}, "5:3": {"flag": "old"}})
    fresh = {"_meta": {"beams": [2, 50]}, "verses": {"5:3": {"flag": "new"}}}

    merged = _merge_ts_validation(path, fresh, {5})

    # Chapter 37's prior flag survives; chapter 5's is replaced with the fresh one.
    assert merged["verses"]["37:151"] == {"flag": "old"}
    assert merged["verses"]["5:3"] == {"flag": "new"}


def test_merge_drops_refreshed_chapter_flag_that_no_longer_applies(tmp_path):
    # Chapter 5 had a flag before; the regen produced none for it → it's cleared.
    path = _write(tmp_path, {"5:3": {"flag": "old"}, "12:1": {"flag": "old"}})
    fresh = {"_meta": {"beams": [2, 50]}, "verses": {}}

    merged = _merge_ts_validation(path, fresh, {5})

    assert "5:3" not in merged["verses"]
    assert merged["verses"]["12:1"] == {"flag": "old"}


def test_merge_with_no_prior_file_returns_fresh(tmp_path):
    fresh = {"_meta": {"beams": [50]}, "verses": {"5:3": {"flag": "new"}}}
    merged = _merge_ts_validation(tmp_path / "absent.json", fresh, {5})
    assert merged is fresh
