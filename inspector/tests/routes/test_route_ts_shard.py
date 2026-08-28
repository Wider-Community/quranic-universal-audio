"""Timestamps shard route — byte pass-through + cache policy."""

from __future__ import annotations


def test_ts_shard_passes_bytes_through_with_no_store(flask_client, monkeypatch):
    """A shard mutates in place at a stable URL (re-stamp / edit), so it must NOT
    be HTTP-cached — the FE already holds the active chapter in an in-memory LRU,
    so `no-store` costs nothing and prevents the browser serving a stale shard
    (the long max-age this replaced silently pinned pre-re-stamp cells)."""
    from routes.timestamps import timestamps as ts_routes

    body = b"brotli-shard-bytes"
    monkeypatch.setattr(ts_routes.ts_serve, "shard_bytes", lambda *a, **k: body)

    res = flask_client.get("/api/ts/shard/reciter_a/2")

    assert res.status_code == 200
    assert res.data == body
    assert res.headers["Cache-Control"] == "no-store"
    assert res.headers["Content-Encoding"] == "br"
    assert res.mimetype == "application/json"


def test_ts_shard_missing_is_404(flask_client, monkeypatch):
    from routes.timestamps import timestamps as ts_routes

    monkeypatch.setattr(ts_routes.ts_serve, "shard_bytes", lambda *a, **k: None)

    res = flask_client.get("/api/ts/shard/reciter_a/2")

    assert res.status_code == 404
