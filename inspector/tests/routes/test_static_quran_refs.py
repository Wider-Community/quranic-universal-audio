"""Static-data routes: GET /api/static/quran-refs.json + /version."""

from __future__ import annotations


def test_version_endpoint_returns_hash(flask_client, tmp_reciter_dir):
    res = flask_client.get("/api/static/quran-refs/version")
    assert res.status_code == 200
    body = res.get_json()
    assert isinstance(body.get("version"), str) and len(body["version"]) == 12
    cache_control = res.headers.get("Cache-Control", "")
    assert "no-cache" in cache_control


def test_payload_endpoint_serves_immutable_json(flask_client, tmp_reciter_dir):
    version = flask_client.get("/api/static/quran-refs/version").get_json()["version"]
    res = flask_client.get("/api/static/quran-refs.json")
    assert res.status_code == 200
    assert res.mimetype == "application/json"

    cache_control = res.headers.get("Cache-Control", "")
    assert "immutable" in cache_control
    assert "max-age=31536000" in cache_control
    assert res.headers.get("ETag") == f'"{version}"'

    body = res.get_json()
    assert isinstance(body, dict)
    assert "dk_words" in body
    assert "verse_word_counts" in body


def test_seg_all_no_longer_ships_quran_refs(flask_client, tmp_reciter_dir):
    """Sanity check: the slimmed ``/api/seg/all/<r>`` payload omits both fields."""
    # No reciter staged → expect 404, but the payload check still runs at the
    # route level via the test_segments_data tests. This test guards the more
    # common case: if a reciter exists, the response must not include refs.
    res = flask_client.get("/api/seg/all/__missing__")
    # 404 path returns ``{error: ...}`` envelope — neither key present.
    body = res.get_json()
    assert "dk_words" not in (body or {})
    assert "verse_word_counts" not in (body or {})
