"""Timestamp-tab VBR metadata routes and local manifest wiring."""
from __future__ import annotations


def test_ts_vbr_route_returns_chapters(flask_client, monkeypatch):
    from routes import timestamps as ts_routes

    monkeypatch.setattr(
        ts_routes,
        "vbr_chapters_for_reciter",
        lambda reciter: [2, 7] if reciter == "reciter_a" else [],
    )

    res = flask_client.get("/api/ts/vbr/reciter_a")

    assert res.status_code == 200
    assert res.get_json() == {"vbr_chapters": [2, 7]}


def test_ts_local_reciter_block_includes_vbr_chapters(monkeypatch):
    from services import ts_local

    monkeypatch.setattr(ts_local, "_load_ts_doc", lambda slug, audio_category: {
        "_meta": {},
        "1:1": {"words": []},
    })
    monkeypatch.setattr(ts_local, "_find_audio_manifest", lambda slug: {
        "_meta": {"name_en": "Reciter A"},
        "1": "https://example.test/001.mp3",
    })
    monkeypatch.setattr(ts_local, "derive_url_template", lambda manifest, audio_cat: "")
    monkeypatch.setattr(ts_local, "split_to_shards", lambda *args, **kwargs: {
        1: {"_meta": {"chapter": 1}, "1:1": {"words": []}},
    })
    monkeypatch.setattr(ts_local, "gzip_shard", lambda shard: b"gz")
    monkeypatch.setattr(ts_local, "vbr_chapters_for_reciter", lambda slug: [1])

    block, shards = ts_local._build_reciter_block("reciter_a", "by_surah_audio")

    assert shards == {1: b"gz"}
    assert block["vbr_chapters"] == [1]
    assert block["ts_chapters"] == [1]
