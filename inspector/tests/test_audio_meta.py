"""Smoke + unit tests for ``services.audio_meta``.

Covers the per-reciter VBR chapter listing used by the chapter-data API to
ship the encoding map down to the frontend (driving cross-chapter accordion
prefetch routing).
"""
from __future__ import annotations

import json

import pytest


@pytest.fixture
def tmp_audio_meta(tmp_path, monkeypatch):
    """Point ``services.audio_meta`` and the cache at a tmp file we control.

    Yields a ``write(doc)`` helper so each test can stage its own audio_meta
    payload and exercise the loader against it.
    """
    from services import audio_meta as audio_meta_mod
    from services import cache as cache_mod

    path = tmp_path / ".audio_meta.json"
    monkeypatch.setattr(audio_meta_mod, "AUDIO_META_PATH", path, raising=True)
    # Reset the singleton mtime cache so the new path is read fresh each test.
    cache_mod._audio_meta_doc.clear()

    def _write(doc: dict) -> None:
        path.write_text(json.dumps(doc), encoding="utf-8")

    yield type("Helper", (), {"write": staticmethod(_write), "path": path})

    cache_mod._audio_meta_doc.clear()


def test_vbr_chapters_for_reciter_returns_sorted_chapter_numbers(tmp_audio_meta):
    from services.audio_meta import vbr_chapters_for_reciter

    tmp_audio_meta.write({
        "_schema": 1,
        "alghazali": {
            "by_chapter": {
                "76": {"vbr": True, "url": "u76"},
                "1": {"vbr": True, "url": "u1"},
                "100": {"vbr": True, "url": "u100"},
            },
        },
    })
    assert vbr_chapters_for_reciter("alghazali") == [1, 76, 100]


def test_vbr_chapters_for_reciter_skips_non_vbr_entries(tmp_audio_meta):
    from services.audio_meta import vbr_chapters_for_reciter

    # Only chapters with ``vbr: True`` should be reported. The artifact may
    # in principle carry CBR entries (e.g. for legacy reasons) — defensively
    # filter them out so the frontend's ``Set`` membership check is exact.
    tmp_audio_meta.write({
        "alghazali": {
            "by_chapter": {
                "1": {"vbr": True, "url": "u1"},
                "2": {"vbr": False, "url": "u2"},
                "3": {"url": "u3"},
            },
        },
    })
    assert vbr_chapters_for_reciter("alghazali") == [1]


def test_vbr_chapters_for_reciter_unknown_reciter_returns_empty(tmp_audio_meta):
    from services.audio_meta import vbr_chapters_for_reciter

    tmp_audio_meta.write({"alghazali": {"by_chapter": {"1": {"vbr": True}}}})
    assert vbr_chapters_for_reciter("nonexistent_reciter") == []


def test_vbr_chapters_for_reciter_missing_artifact_returns_empty(tmp_audio_meta, monkeypatch):
    from services import audio_meta as audio_meta_mod
    from services.audio_meta import vbr_chapters_for_reciter

    # Repoint at a non-existent path; loader hits FileNotFoundError and
    # returns None, the helper degrades gracefully to an empty list.
    monkeypatch.setattr(
        audio_meta_mod, "AUDIO_META_PATH", tmp_audio_meta.path.parent / "nope.json",
        raising=True,
    )
    assert vbr_chapters_for_reciter("alghazali") == []
