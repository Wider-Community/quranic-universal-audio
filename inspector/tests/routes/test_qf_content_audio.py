"""Tests for QF Content-API audio routing in the dashboard player.

Covers:
- the ``(reciter_id, style)`` → QF id map;
- ``content.chapter_audio_urls`` parsing + required browser User-Agent;
- the ``/api/audio/surahs`` route swapping QuranicAudio links for API URLs,
  leaving other sources untouched, and falling back on API failure.
"""

from __future__ import annotations

import types

import pytest


# ---- reciter_map ----


def test_qf_id_for_known_and_unknown():
    from services.quran_foundation.reciter_map import qf_id_for

    assert qf_id_for("abdulbasit_abdulsamad", "murattal") == 2
    assert qf_id_for("abdulbasit_abdulsamad", "mujawwad") == 1
    assert qf_id_for("saad_al_ghamdi", "murattal") == 13
    assert qf_id_for("saad_al_ghamdi", "mujawwad") is None  # unmapped style
    assert qf_id_for("nobody_here", "murattal") is None
    assert qf_id_for("abdulbasit_abdulsamad", None) is None


# ---- content.chapter_audio_urls ----


class _FakeResp:
    def __init__(self, payload, ok=True, status=200):
        self._payload = payload
        self.ok = ok
        self.status_code = status
        self.text = ""

    def json(self):
        return self._payload


@pytest.fixture
def _clear_qf_cache():
    from services.storage import cache

    cache._qf_content_token.clear()
    cache._qf_chapter_urls.clear()
    yield
    cache._qf_content_token.clear()
    cache._qf_chapter_urls.clear()


def test_chapter_audio_urls_parses_and_sets_ua(monkeypatch, _clear_qf_cache):
    from services.quran_foundation import content
    from services.storage import cache

    # Seed a valid token so no token request fires.
    cache.set_qf_content_token({"access_token": "tok", "expires_at": 2**31})

    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResp(
            {
                "audio_files": [
                    {"chapter_id": 1, "audio_url": "https://cdn/1.mp3"},
                    {"chapter_id": 2, "audio_url": "https://cdn/2.mp3"},
                    {"chapter_id": 3, "audio_url": None},  # skipped
                ]
            }
        )

    monkeypatch.setattr(content.requests, "get", fake_get)
    out = content.chapter_audio_urls(7)
    assert out == {"1": "https://cdn/1.mp3", "2": "https://cdn/2.mp3"}
    assert captured["headers"]["User-Agent"].startswith("Mozilla/")
    assert captured["headers"]["x-auth-token"] == "tok"
    # Second call is served from cache (no second request).
    monkeypatch.setattr(
        content.requests, "get", lambda *a, **k: pytest.fail("should be cached")
    )
    assert content.chapter_audio_urls(7) == out


def test_chapter_audio_urls_raises_on_http_error(monkeypatch, _clear_qf_cache):
    from services.quran_foundation import content
    from services.storage import cache

    cache.set_qf_content_token({"access_token": "tok", "expires_at": 2**31})
    monkeypatch.setattr(
        content.requests, "get", lambda *a, **k: _FakeResp({}, ok=False, status=502)
    )
    with pytest.raises(content.QfContentError):
        content.chapter_audio_urls(7)


# ---- /api/audio/surahs route ----


def _stub_route(monkeypatch, *, reciter_id, style, api_urls=None, raise_err=False):
    """Wire the route's collaborators: bucket manifest read, config, catalog,
    and the content fetch."""
    from routes.audio import metadata
    from services.quran_foundation import content as qf_content
    from services.storage import cache

    cache._audio_url.clear()
    cache._qf_chapter_urls.clear()

    backend = types.SimpleNamespace(
        read_json=lambda path: {
            "chapters": {
                "1": {"url": "https://download.quranicaudio.com/quran/x/001.mp3",
                      "duration_sec": 47},
                "2": {"url": "https://download.quranicaudio.com/quran/x/002.mp3",
                      "duration_sec": 90},
            }
        }
    )
    monkeypatch.setattr(metadata, "get_backend", lambda: backend)
    monkeypatch.setattr(metadata.qf_config, "content_is_configured", lambda: True)
    monkeypatch.setattr(
        metadata.catalog,
        "find_delivery",
        lambda slug: types.SimpleNamespace(reciter_id=reciter_id, style=style),
    )

    def fake_urls(qf_id):
        if raise_err:
            raise qf_content.QfContentError("boom")
        return api_urls or {}

    monkeypatch.setattr(metadata.qf_content, "chapter_audio_urls", fake_urls)


def test_route_swaps_mapped_quranicaudio_delivery(flask_client, monkeypatch):
    _stub_route(
        monkeypatch,
        reciter_id="saad_al_ghamdi",
        style="murattal",
        api_urls={"1": "https://download.quranicaudio.com/quran/sa3d/complete/001.mp3"},
    )
    resp = flask_client.get("/api/audio/surahs/by_surah/quranicaudio/saad_al_ghamdi_qdc")
    assert resp.status_code == 200
    surahs = resp.get_json()["surahs"]
    assert surahs["1"]["via"] == "qf_api"
    assert surahs["1"]["url"].endswith("/complete/001.mp3")
    assert surahs["1"]["origin_url"].endswith("/quran/x/001.mp3")
    assert surahs["1"]["duration_ms"] is None
    # Chapter 2 not in the API map → untouched.
    assert "via" not in surahs["2"]
    assert surahs["2"]["url"].endswith("/quran/x/002.mp3")


def test_route_leaves_non_quranicaudio_source_untouched(flask_client, monkeypatch):
    _stub_route(
        monkeypatch,
        reciter_id="saad_al_ghamdi",
        style="murattal",
        api_urls={"1": "https://api/1.mp3"},
    )
    resp = flask_client.get("/api/audio/surahs/by_surah/mp3quran/saad_al_ghamdi_mp3quran")
    surahs = resp.get_json()["surahs"]
    assert "via" not in surahs["1"]
    assert surahs["1"]["url"].endswith("/quran/x/001.mp3")


def test_route_falls_back_on_api_error(flask_client, monkeypatch):
    _stub_route(
        monkeypatch, reciter_id="saad_al_ghamdi", style="murattal", raise_err=True
    )
    resp = flask_client.get("/api/audio/surahs/by_surah/quranicaudio/saad_al_ghamdi_qdc")
    surahs = resp.get_json()["surahs"]
    assert surahs["1"]["via"] == "qf_fallback"
    assert surahs["1"]["url"].endswith("/quran/x/001.mp3")  # our link retained
