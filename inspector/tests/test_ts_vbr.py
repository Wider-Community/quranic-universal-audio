"""Timestamps tab VBR metadata route."""
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
