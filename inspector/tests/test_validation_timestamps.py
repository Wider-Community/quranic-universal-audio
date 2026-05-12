"""Tests for ``inspector.services.validation.timestamps``.

The Phase-3 refactor moved the former ``validators.validate_timestamps`` CLI
into the validation package. These tests cover the public entrypoint
end-to-end (a tiny on-disk timestamps tree → reshape into the route's wire
shape) plus the helpers in ``_temporal`` / ``_coverage``.
"""
from __future__ import annotations

import json


# ── _temporal helpers ──────────────────────────────────────────────────────


def test_ms_to_hms_under_one_hour():
    from services.validation._temporal import _ms_to_hms
    assert _ms_to_hms(0) == "0:00.0"
    assert _ms_to_hms(1500) == "0:01.5"
    assert _ms_to_hms(125_400) == "2:05.4"


def test_ms_to_hms_over_one_hour():
    from services.validation._temporal import _ms_to_hms
    assert _ms_to_hms(3_661_500) == "1:01:01.5"


def test_check_per_word_temporal_collects_errors_and_durations():
    from services.validation._temporal import check_per_word_temporal

    errors: list[dict] = []
    warnings: list[dict] = []
    durations: list[float] = []
    words = [
        [1, 100, 500],     # ok → duration 400
        [2, -10, 50],      # negative → error
        [3, 200, 200],     # zero duration → warning
        [4, 800, 700],     # inverted → error (no duration)
    ]
    zero, neg = check_per_word_temporal(words, "1:1", errors, warnings, durations)

    assert zero == 1
    assert neg == 1
    assert durations == [400]
    assert len(errors) == 2
    assert len(warnings) == 1


# ── _coverage helpers ──────────────────────────────────────────────────────


def test_parse_verse_key_handles_valid_and_invalid():
    from services.validation._coverage import parse_verse_key
    assert parse_verse_key("1:1") == (1, 1)
    assert parse_verse_key("114:6") == (114, 6)
    assert parse_verse_key("1:bad") is None
    assert parse_verse_key("not-a-key") is None
    assert parse_verse_key("1:2:3") is None  # too many parts


def test_parse_compound_key():
    from services.validation._coverage import parse_compound_key
    assert parse_compound_key("37:151:3-37:152:2") == (37, 151, 152)
    assert parse_compound_key("malformed") is None


def test_collect_verse_keys_handles_mixed_shapes():
    from services.validation._coverage import collect_verse_keys

    verses = {
        "1:1": [],
        "1:2": [],
        "37:151:3-37:152:2": [],
        "broken:key:thing:format": [],
    }
    errors: list[dict] = []
    keys = collect_verse_keys(verses, errors)

    assert (1, 1) in keys
    assert (37, 151) in keys and (37, 152) in keys
    assert any("invalid" in e["msg"] for e in errors)


def test_check_forward_gaps_flags_skips():
    from services.validation._coverage import check_forward_gaps

    warnings: list[dict] = []
    # 1, 2, 5 → gap from 2 to 5
    flagged = check_forward_gaps("1:1", [[1, 0, 1], [2, 1, 2], [5, 5, 6]],
                                  False, warnings)
    assert flagged is True
    assert "forward gaps" in warnings[0]["msg"]


def test_check_forward_gaps_clean_sequence():
    from services.validation._coverage import check_forward_gaps

    warnings: list[dict] = []
    flagged = check_forward_gaps("1:1", [[1, 0, 1], [2, 1, 2], [3, 2, 3]],
                                  False, warnings)
    assert flagged is False
    assert warnings == []


# ── validate_reciter_timestamps end-to-end ─────────────────────────────────


def _make_ts_tree(tmp_path, slug: str, doc: dict, *, audio_type: str = "by_surah_audio"):
    """Build ``<tmp>/<audio_type>/<slug>/timestamps.json`` and return ``tmp/<audio_type>``."""
    base = tmp_path / audio_type / slug
    base.mkdir(parents=True)
    (base / "timestamps.json").write_text(json.dumps(doc), encoding="utf-8")
    return tmp_path


def test_validate_reciter_timestamps_returns_none_for_missing(tmp_path, monkeypatch):
    from services.validation import timestamps as ts_mod

    monkeypatch.setattr(ts_mod, "TIMESTAMPS_PATH", tmp_path)
    assert ts_mod.validate_reciter_timestamps("nobody") is None


def test_validate_reciter_timestamps_wire_shape(tmp_path, monkeypatch):
    """Drop a tiny timestamps.json + force a known word-count → wire-shape check."""
    from services.validation import timestamps as ts_mod

    doc = {
        "_meta": {
            "created_at": "2025-01-01",
            "aligner_model": "test",
            "audio_source": "by_surah",
            "method": "test",
            "beam": 10,
            "shared_cmvn": False,
            "padding": "forward",
        },
        "1:1": [[1, 0, 500], [2, 500, 1000]],
    }
    _make_ts_tree(tmp_path, "test_reciter", doc)

    monkeypatch.setattr(ts_mod, "TIMESTAMPS_PATH", tmp_path)
    monkeypatch.setattr(
        ts_mod,
        "_load_word_counts_from_surah_info",
        lambda: {(1, 1): 2},
    )

    result = ts_mod.validate_reciter_timestamps("test_reciter")

    assert result is not None
    # Wire-shape contract — keys consumed by the frontend.
    for key in ("mfa_failures", "missing_verses", "missing_words",
                "verse_overlaps", "boundary_mismatches", "large_gaps",
                "meta"):
        assert key in result, f"missing key: {key}"
    # Two of two expected words present → no missing_words flagged.
    assert result["missing_words"] == []
    # No mfa failures in fixture meta.
    assert result["mfa_failures"] == []


def test_validate_reciter_timestamps_flags_missing_words(tmp_path, monkeypatch):
    """Word_counts says verse has 3 words; fixture covers indices 1 + 3 → flag idx 2."""
    from services.validation import timestamps as ts_mod

    doc = {
        "_meta": {
            "created_at": "2025-01-01",
            "aligner_model": "test",
            "audio_source": "by_surah",
            "method": "test",
            "beam": 10,
            "shared_cmvn": False,
            "padding": "forward",
        },
        "1:1": [[1, 0, 200], [3, 400, 600]],
    }
    _make_ts_tree(tmp_path, "test_reciter", doc)

    monkeypatch.setattr(ts_mod, "TIMESTAMPS_PATH", tmp_path)
    monkeypatch.setattr(
        ts_mod,
        "_load_word_counts_from_surah_info",
        lambda: {(1, 1): 3},
    )

    result = ts_mod.validate_reciter_timestamps("test_reciter")
    assert result is not None
    assert len(result["missing_words"]) == 1
    assert result["missing_words"][0]["missing"] == [2]
    assert result["missing_words"][0]["verse_key"] == "1:1"
