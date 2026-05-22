"""Unit tests for the structural intake validator (no DB / network)."""

from __future__ import annotations

from scripts.lib.schemas import IntakeSubmission

from services.admin import intake_validation as iv


def _links(n=114):
    return [{"chapter": c, "url": f"https://cdn.example/{c:03d}.mp3"} for c in range(1, n + 1)]


def _new_reciter(**over):
    body = {
        "kind": "new_reciter",
        "proposed_edits": {"name_en": "X", "riwayah": "hafs", "style": "murattal"},
        "source": {"method": "links", "links": _links()},
    }
    body.update(over)
    return IntakeSubmission.model_validate(body)


def test_full_links_clean():
    v = iv.validate_submission(_new_reciter())
    assert v.errors == []
    assert not any("Missing" in w for w in v.warnings)


def test_missing_name_errors():
    sub = _new_reciter(proposed_edits={"riwayah": "hafs", "style": "murattal"})
    v = iv.validate_submission(sub)
    assert any("English name" in e for e in v.errors)


def test_missing_riwayah_style_errors():
    sub = _new_reciter(proposed_edits={"name_en": "X"})
    v = iv.validate_submission(sub)
    assert any("Riwayah" in e for e in v.errors)
    assert any("Style" in e for e in v.errors)


def test_partial_links_warns_missing():
    v = iv.validate_submission(_new_reciter(source={"method": "links", "links": _links(50)}))
    assert v.errors == []
    assert any("Missing 64" in w for w in v.warnings)


def test_malformed_url_errors():
    bad = [{"chapter": 1, "url": "ftp://nope/1.mp3"}, {"chapter": 2, "url": "https://ok/2.mp3"}]
    v = iv.validate_submission(_new_reciter(source={"method": "links", "links": bad}))
    assert any("malformed" in e for e in v.errors)


def test_duplicate_chapter_warns():
    dup = [{"chapter": 1, "url": "https://a/1.mp3"}, {"chapter": 1, "url": "https://b/1.mp3"}]
    v = iv.validate_submission(_new_reciter(source={"method": "links", "links": dup}))
    assert any("Duplicate" in w for w in v.warnings)


def test_no_links_errors():
    v = iv.validate_submission(_new_reciter(source={"method": "links", "links": []}))
    assert any("No valid chapter links" in e for e in v.errors)


def test_playlist_known_host_clean():
    sub = _new_reciter(source={"method": "playlist",
                               "playlist_url": "https://youtube.com/playlist?list=abc"})
    v = iv.validate_submission(sub)
    assert v.errors == []
    assert not any("Unrecognised" in w for w in v.warnings)


def test_playlist_unknown_host_warns():
    sub = _new_reciter(source={"method": "playlist", "playlist_url": "https://random.tld/x"})
    v = iv.validate_submission(sub)
    assert any("Unrecognised" in w for w in v.warnings)


def test_playlist_missing_url_errors():
    sub = _new_reciter(source={"method": "playlist", "playlist_url": None})
    v = iv.validate_submission(sub)
    assert any("playlist URL is required" in e.lower() or "required" in e for e in v.errors)


def test_compact_ranges():
    assert iv._compact([1, 2, 3, 7, 50, 51]) == "1–3, 7, 50–51"
    assert iv._compact([5]) == "5"
    assert iv._compact([]) == ""
