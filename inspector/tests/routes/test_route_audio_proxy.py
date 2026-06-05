"""GET /api/seg/audio-proxy/<reciter> — download-disposition behaviour.

The proxy normally streams a chapter inline (playback). With ``?download=1``
it must emit ``Content-Disposition: attachment`` so the browser saves the
file instead — this drives the dashboard footer's download button. The
``?chapter=<n>`` param only shapes the filename ``<reciter>-<NNN>.mp3``.

These tests mock ``audio_source.resolve`` to the in-memory (BytesIO) branch
so no bucket/CDN setup is needed; the disposition is computed once and shared
across all three serve branches, so the bytes branch exercises the logic.
"""

from __future__ import annotations


def _fake_source(chapter_key: str | None = "2"):
    from services.audio.audio_source import AudioSource

    return AudioSource(
        cdn_url="https://cdn.local/002.mp3",
        data=b"ID3\x00\x00\x00\x00\x00\x00fake-mp3-bytes",
        path=None,
        vbr=False,
        bitrate_kbps=None,
        chapter_key=chapter_key,
    )


def _patch_resolve(monkeypatch):
    from routes.audio import proxy as proxy_mod

    monkeypatch.setattr(proxy_mod.audio_source, "resolve", lambda *a, **k: _fake_source())


def test_download_sets_attachment_disposition(flask_client, monkeypatch):
    _patch_resolve(monkeypatch)
    res = flask_client.get(
        "/api/seg/audio-proxy/abdul-basit",
        query_string={"url": "https://cdn.local/002.mp3", "download": "1", "chapter": "2"},
    )
    assert res.status_code == 200, res.get_data()
    assert res.headers.get("Content-Disposition") == 'attachment; filename="abdul-basit-002.mp3"'


def test_no_download_param_streams_inline(flask_client, monkeypatch):
    """Normal playback request — no attachment header, still seekable."""
    _patch_resolve(monkeypatch)
    res = flask_client.get(
        "/api/seg/audio-proxy/abdul-basit",
        query_string={"url": "https://cdn.local/002.mp3"},
    )
    assert res.status_code == 200
    assert "Content-Disposition" not in res.headers
    assert res.headers.get("Accept-Ranges") == "bytes"


def test_download_without_chapter_falls_back_to_reciter_name(flask_client, monkeypatch):
    _patch_resolve(monkeypatch)
    res = flask_client.get(
        "/api/seg/audio-proxy/abdul-basit",
        query_string={"url": "https://cdn.local/002.mp3", "download": "1"},
    )
    assert res.status_code == 200
    assert res.headers.get("Content-Disposition") == 'attachment; filename="abdul-basit.mp3"'


def test_download_name_sanitizes_and_pads():
    from routes.audio.proxy import _download_name

    assert _download_name("abdul-basit", "2") == "abdul-basit-002.mp3"
    assert _download_name("abdul-basit", "112") == "abdul-basit-112.mp3"
    # Path-traversal / quote chars stripped from the header value.
    assert _download_name('ab/../"sit', "5") == "absit-005.mp3"
    # Non-numeric / missing chapter → bare reciter name.
    assert _download_name("husary", "") == "husary.mp3"
    assert _download_name("husary", "abc") == "husary.mp3"
    # Empty slug → safe default.
    assert _download_name("", "2") == "surah-002.mp3"
