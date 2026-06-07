"""Title→surah matching + chapter-map guard.

The guard exists because a positional playlist map (chapter = playlist position)
once shipped stamped ``confidence:"exact"`` for mohammed_burhaji_yt: the playlist
is out of mushaf order at positions 94-102, so 9 chapters got the wrong surah's
audio. ``validate_chapter_map`` must REJECT such a map by cross-checking each
entry's title against its declared chapter.
"""

from __future__ import annotations

import json
from pathlib import Path

from qua_shared.playlist_match import (
    build_surah_matchers,
    match_title_to_surah,
    validate_chapter_map,
)

_SURAH_INFO = json.loads(
    (Path(__file__).resolve().parents[2] / "data" / "surah_info.json").read_text(encoding="utf-8")
)


def _entry(chapter, title, matched_name="", url="https://www.youtube.com/watch?v=x"):
    return {
        "chapter": chapter,
        "url": url,
        "title": title,
        "matched_name": matched_name,
        "confidence": "exact",
    }


def test_match_title_resolves_english_suffix_and_arabic():
    m = build_surah_matchers(_SURAH_INFO)
    # English '| Surah X' suffix
    assert match_title_to_surah("سورة الزلزلة كاملة | Surah Al-Zalzalah", m)[0] == 99
    assert match_title_to_surah("Surah Al-'Alaq", m)[0] == 96
    # Arabic-only name chunk before كاملة
    assert match_title_to_surah("سورة الشرح كاملة للشيخ", m)[0] == 94


def test_burhaji_positional_map_is_rejected():
    # The exact bad shape: chapter 94 with the CORRECT matched_name (Ash-Sharh)
    # but the WRONG title (Az-Zalzalah's video) — stamped exact. Must be caught.
    bad = {
        "playlist_url": "https://www.youtube.com/playlist?list=X",
        "entries": [
            _entry(94, "سورة الزلزلة كاملة | Surah Al-Zalzalah", matched_name="Ash-Sharh"),
            _entry(96, "سورة الشرح كاملة | Surah Al-Sharh", matched_name="Al-Alaq"),
        ],
    }
    rep = validate_chapter_map(bad, _SURAH_INFO, expect_count=None)
    assert not rep.ok
    assert any("TITLE CONTRADICTION" in e for e in rep.errors)
    # both entries contradict
    assert sum("TITLE CONTRADICTION" in e for e in rep.errors) == 2


def test_correct_title_matched_map_passes():
    good = {
        "playlist_url": "https://www.youtube.com/playlist?list=X",
        "entries": [
            _entry(94, "سورة الشرح كاملة | Surah Al-Sharh", matched_name="Ash-Sharh"),
            _entry(96, "سورة العلق كاملة | Surah Al-'Alaq", matched_name="Al-Alaq"),
            _entry(99, "سورة الزلزلة كاملة | Surah Al-Zalzalah", matched_name="Az-Zalzala"),
        ],
    }
    rep = validate_chapter_map(good, _SURAH_INFO, expect_count=None)
    assert rep.ok, rep.errors


def test_duplicate_chapter_is_rejected():
    dup = {
        "playlist_url": "u",
        "entries": [
            _entry(5, "Surah Al-Ma'idah", matched_name="Al-Maaida"),
            _entry(5, "Surah Al-An'am", matched_name="Al-An'aam"),
        ],
    }
    rep = validate_chapter_map(dup, _SURAH_INFO, expect_count=None)
    assert not rep.ok
    assert any("assigned to >1 entry" in e for e in rep.errors)


def test_matched_name_mismatch_is_rejected():
    m = {
        "playlist_url": "u",
        "entries": [
            _entry(2, "Surah Al-Baqarah", matched_name="An-Nisaa"),  # wrong matched_name
        ],
    }
    rep = validate_chapter_map(m, _SURAH_INFO, expect_count=None)
    assert not rep.ok
    assert any("matched_name" in e for e in rep.errors)


def test_incomplete_cover_flagged_when_full_expected():
    m = {"playlist_url": "u", "entries": [_entry(1, "Surah Al-Fatihah", matched_name="Al-Faatiha")]}
    rep = validate_chapter_map(m, _SURAH_INFO, expect_count=114)
    assert not rep.ok
    assert any("missing chapters" in e or "expected 114" in e for e in rep.errors)


def test_unresolvable_title_warns_not_errors():
    m = {
        "playlist_url": "u",
        "entries": [
            _entry(1, "intro nasheed — recitation montage", matched_name="Al-Faatiha"),
        ],
    }
    rep = validate_chapter_map(m, _SURAH_INFO, expect_count=None)
    # matched_name is correct for ch1, title unresolvable → warning, not error
    assert rep.ok, rep.errors
    assert any("not resolvable" in w for w in rep.warnings)
