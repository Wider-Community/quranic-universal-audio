"""Tests for QF Content-API word-by-word translations.

Covers:
- ``content.word_by_word`` parsing (location→gloss), ``end``-glyph filtering,
  required browser User-Agent + headers, per-(verse,language) caching, and
  unknown-language fallback to English;
- the ``/api/qf/content/wbw/...`` routes.
"""

from __future__ import annotations

import pytest


class _FakeResp:
    def __init__(self, payload, ok=True, status=200):
        self._payload = payload
        self.ok = ok
        self.status_code = status
        self.text = ""

    def json(self):
        return self._payload


def _verse_payload():
    """Minimal /verses/by_key shape: 3 real words + 1 ayah-end glyph."""
    return {
        "verse": {
            "verse_key": "2:255",
            "words": [
                {
                    "location": "2:255:1",
                    "char_type_name": "word",
                    "translation": {"text": "Allah", "language_name": "english"},
                },
                {
                    "location": "2:255:2",
                    "char_type_name": "word",
                    "translation": {"text": "(there is) no", "language_name": "english"},
                },
                {
                    "location": "2:255:3",
                    "char_type_name": "word",
                    "translation": {"text": None, "language_name": "english"},
                },
                {
                    "location": "2:255:4",
                    "char_type_name": "end",
                    "translation": {"text": "(255)", "language_name": "english"},
                },
            ],
        }
    }


@pytest.fixture
def _clear_qf_cache():
    from services.storage import cache

    cache._qf_content_token.clear()
    cache._qf_wbw.clear()
    cache._qf_token_cooldown.clear()
    yield
    cache._qf_content_token.clear()
    cache._qf_wbw.clear()
    cache._qf_token_cooldown.clear()


def test_word_by_word_parses_filters_and_caches(monkeypatch, _clear_qf_cache):
    from services.quran_foundation import content
    from services.storage import cache

    cache.set_qf_content_token({"access_token": "tok", "expires_at": 2**31})
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return _FakeResp(_verse_payload())

    monkeypatch.setattr(content.requests, "get", fake_get)
    out = content.word_by_word("2:255", "en")

    # end-glyph filtered; missing gloss coerced to "".
    assert out == {"2:255:1": "Allah", "2:255:2": "(there is) no", "2:255:3": ""}
    assert "2:255:4" not in out
    # Correct switch param + headers.
    assert captured["params"]["language"] == "en"
    assert captured["params"]["words"] == "true"
    assert captured["headers"]["User-Agent"].startswith("Mozilla/")
    assert captured["headers"]["x-auth-token"] == "tok"
    assert captured["url"].endswith("/verses/by_key/2:255")

    # Second call served from cache (no request).
    monkeypatch.setattr(content.requests, "get", lambda *a, **k: pytest.fail("should be cached"))
    assert content.word_by_word("2:255", "en") == out


def test_word_by_word_unknown_language_falls_back_to_en(monkeypatch, _clear_qf_cache):
    from services.quran_foundation import content
    from services.storage import cache

    cache.set_qf_content_token({"access_token": "tok", "expires_at": 2**31})
    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen["language"] = params["language"]
        return _FakeResp(_verse_payload())

    monkeypatch.setattr(content.requests, "get", fake_get)
    content.word_by_word("2:255", "klingon")
    assert seen["language"] == "en"


def test_word_by_word_rejects_bad_verse_key(_clear_qf_cache):
    from services.quran_foundation import content

    with pytest.raises(content.QfContentError):
        content.word_by_word("not-a-key", "en")


def test_word_by_word_raises_on_http_error(monkeypatch, _clear_qf_cache):
    from services.quran_foundation import content
    from services.storage import cache

    cache.set_qf_content_token({"access_token": "tok", "expires_at": 2**31})
    monkeypatch.setattr(
        content.requests,
        "get",
        lambda *a, **k: _FakeResp({}, ok=False, status=502),
    )
    with pytest.raises(content.QfContentError):
        content.word_by_word("2:255", "en")


def test_token_failure_trips_cooldown_and_fast_fails(monkeypatch, _clear_qf_cache):
    """After a token-mint failure, the next call fast-fails from the cooldown
    without hitting the network again — so an outage can't make every
    concurrent request hang on the timeout."""
    from services.quran_foundation import content

    monkeypatch.setattr(content.config, "content_client_id", lambda: "cid")
    monkeypatch.setattr(content.config, "content_client_secret", lambda: "sec")
    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        raise content.requests.RequestException("token endpoint down")

    monkeypatch.setattr(content.requests, "post", boom)

    with pytest.raises(content.QfContentError):
        content.get_content_token()
    assert calls["n"] == 1

    # Second call within the cooldown window must not touch the network.
    with pytest.raises(content.QfContentError):
        content.get_content_token()
    assert calls["n"] == 1


# ---- routes ----


def test_route_wbw_languages(flask_client):
    resp = flask_client.get("/api/qf/content/wbw/languages")
    assert resp.status_code == 200
    langs = resp.get_json()
    assert len(langs) == 15
    by_code = {x["code"]: x for x in langs}
    assert by_code["en"]["label"] == "English"
    # Completeness flags (full-Quran measured): English/Urdu complete, Tamil/Hindi not.
    assert by_code["en"]["complete"] is True
    assert by_code["ur"]["complete"] is True
    assert by_code["ta"]["complete"] is False
    assert by_code["hi"]["complete"] is False


def test_route_wbw_returns_words(flask_client, monkeypatch, _clear_qf_cache):
    from routes import qf_content as route

    from services.quran_foundation import content

    monkeypatch.setattr(route.qf_config, "content_is_configured", lambda: True)
    monkeypatch.setattr(content, "word_by_word", lambda vk, lang: {"2:255:1": "Allah"})
    resp = flask_client.get("/api/qf/content/wbw/2/255?language=en")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["verse_key"] == "2:255"
    assert body["language"] == "en"
    assert body["words"] == {"2:255:1": "Allah"}


def test_route_wbw_503_when_not_configured(flask_client, monkeypatch):
    from routes import qf_content as route

    monkeypatch.setattr(route.qf_config, "content_is_configured", lambda: False)
    resp = flask_client.get("/api/qf/content/wbw/2/255")
    assert resp.status_code == 503
