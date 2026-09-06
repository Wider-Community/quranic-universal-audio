"""GET /api/seg/audio-proxy/<reciter> — bucket-mounted path branch.

Exercises ``routes/audio/range_file.send_range_file`` end-to-end through the
proxy: full body, single Range (closed / open-ended / suffix), ``If-Range``
freshness, unsatisfiable → 416, ``If-None-Match`` → 304, and the invariant
that the body is produced in large reads (the whole point — Werkzeug's
``send_file`` Range path reads 8 KB at a time, which over the Space's NFS
bucket mount throttles playback to ~100-200 KB/s).
"""

from __future__ import annotations

import pytest
from routes.audio import proxy as proxy_mod
from routes.audio import range_file

from services.audio.audio_source import AudioSource

SIZE = 3 * 1024 * 1024 + 123  # spans several 1 MB chunks + a tail


@pytest.fixture
def mp3_path(tmp_path):
    p = tmp_path / "002.mp3"
    p.write_bytes(bytes(i % 251 for i in range(SIZE)))
    return p


@pytest.fixture
def client(flask_client, monkeypatch, mp3_path):
    src = AudioSource(
        cdn_url="https://cdn.local/002.mp3",
        data=None,
        path=mp3_path,
        vbr=False,
        bitrate_kbps=128,
        chapter_key="2",
    )
    monkeypatch.setattr(proxy_mod.audio_source, "resolve", lambda *a, **k: src)
    return flask_client


def _get(client, **headers):
    return client.get(
        "/api/seg/audio-proxy/husary",
        query_string={"url": "https://cdn.local/002.mp3"},
        headers=headers,
    )


def test_full_body(client, mp3_path):
    res = _get(client)
    assert res.status_code == 200
    assert res.headers["Content-Length"] == str(SIZE)
    assert res.headers["Accept-Ranges"] == "bytes"
    assert res.headers["ETag"] == range_file.file_etag(mp3_path)
    assert "immutable" in res.headers["Cache-Control"]
    assert res.headers["Access-Control-Allow-Origin"] == "*"
    assert res.get_data() == mp3_path.read_bytes()


def test_closed_range(client, mp3_path):
    res = _get(client, Range="bytes=100-199")
    assert res.status_code == 206
    assert res.headers["Content-Range"] == f"bytes 100-199/{SIZE}"
    assert res.headers["Content-Length"] == "100"
    assert res.get_data() == mp3_path.read_bytes()[100:200]


def test_open_ended_range_streams_to_eof(client, mp3_path):
    start = SIZE - 2_000_000
    res = _get(client, Range=f"bytes={start}-")
    assert res.status_code == 206
    assert res.headers["Content-Range"] == f"bytes {start}-{SIZE - 1}/{SIZE}"
    assert res.get_data() == mp3_path.read_bytes()[start:]


def test_suffix_range(client, mp3_path):
    res = _get(client, Range="bytes=-500")
    assert res.status_code == 206
    assert res.headers["Content-Range"] == f"bytes {SIZE - 500}-{SIZE - 1}/{SIZE}"
    assert res.get_data() == mp3_path.read_bytes()[-500:]


def test_unsatisfiable_range_416(client):
    res = _get(client, Range=f"bytes={SIZE + 10}-")
    assert res.status_code == 416
    assert res.headers["Content-Range"] == f"bytes */{SIZE}"


def test_if_range_matching_etag_honours_range(client, mp3_path):
    etag = range_file.file_etag(mp3_path)
    res = _get(client, **{"Range": "bytes=0-9", "If-Range": etag})
    assert res.status_code == 206
    assert res.headers["Content-Length"] == "10"


def test_if_range_stale_etag_falls_back_to_full_body(client):
    res = _get(client, **{"Range": "bytes=0-9", "If-Range": '"stale"'})
    assert res.status_code == 200
    assert res.headers["Content-Length"] == str(SIZE)


def test_if_none_match_304(client, mp3_path):
    etag = range_file.file_etag(mp3_path)
    res = _get(client, **{"If-None-Match": etag})
    assert res.status_code == 304
    assert res.get_data() == b""


def test_body_read_in_large_chunks(mp3_path, monkeypatch):
    """The regression guard: reads must be ~1 MB, never 8 KB."""
    expected = mp3_path.read_bytes()  # before the spy — read_bytes() goes through Path.open too
    sizes: list[int] = []
    real_open = range_file.Path.open

    def spy_open(self, *a, **k):
        fh = real_open(self, *a, **k)
        real_read = fh.read

        def read(n=-1):
            sizes.append(n)
            return real_read(n)

        fh.read = read
        return fh

    monkeypatch.setattr(range_file.Path, "open", spy_open)
    body = b"".join(range_file._iter_file(mp3_path, 0, SIZE))
    assert body == expected
    assert sizes[:-1] == [range_file._CHUNK_BYTES] * 3
    assert sizes[-1] == 123
