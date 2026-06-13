"""Unit tests for the release ``download_audio.py`` helper — pure parsing,
chapter-window derivation, and the friendly missing-tool error path. The actual
yt-dlp / ffmpeg downloads are not exercised here."""

from __future__ import annotations

import pytest

from qua_jobs import download_audio as da


def _reciter(slug: str, urls: dict, offsets: dict | None = None) -> dict:
    audio: dict = {"chapter_urls": urls}
    if offsets:
        audio["chapter_offsets_ms"] = offsets
    return {"slug": slug, "audio": audio}


def test_reciters_in_handles_release_level_and_single():
    rec = _reciter("a", {"1": "u"})
    assert da._reciters_in({"recitations": [rec]}) == [rec]
    assert da._reciters_in([rec]) == [rec]
    assert da._reciters_in(rec) == [rec]  # bare per-reciter object


def test_pick_reciter_requires_slug_when_ambiguous():
    catalog = {"recitations": [_reciter("a", {"1": "u"}), _reciter("b", {"1": "u"})]}
    with pytest.raises(ValueError, match="pass --reciter"):
        da._pick_reciter(catalog, None)
    assert da._pick_reciter(catalog, "b")["slug"] == "b"


def test_pick_reciter_defaults_to_sole_entry():
    catalog = {"recitations": [_reciter("only", {"1": "u"})]}
    assert da._pick_reciter(catalog, None)["slug"] == "only"


def test_needs_ytdlp_routes_by_url():
    assert da._needs_ytdlp("https://www.youtube.com/watch?v=x") is True
    assert da._needs_ytdlp("https://drive.google.com/file/d/x/view") is True
    assert da._needs_ytdlp("https://cdn.example/001.mp3") is False
    assert da._needs_ytdlp("https://cdn.example/001.mp3?token=abc") is False


def test_chapter_windows_splits_combined_file_at_next_offset():
    # Two chapters share one file at 130 ms and 67795 ms → ch1 ends where ch2
    # begins; ch2 runs to end-of-file (None).
    windows = da._chapter_windows({"1": 130, "2": 67795}, ["1", "2"])
    assert windows == {"1": (130, 67795), "2": (67795, None)}


def test_chapter_windows_single_file_trims_lead_in_to_eof():
    windows = da._chapter_windows({"36": 4200}, ["36"])
    assert windows == {"36": (4200, None)}


def test_missing_tool_message_names_install_command():
    with pytest.raises(da.MissingTool, match="pip install yt-dlp"):
        da._require("yt-dlp-definitely-not-installed", "pip install yt-dlp")
