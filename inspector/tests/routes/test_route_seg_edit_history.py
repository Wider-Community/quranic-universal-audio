"""The edit-history route merges the TS-generation timeline onto the cached
``{batches, summary}`` blob so the FE can render the history tier filter.
"""

from __future__ import annotations


def test_edit_history_merges_generations(flask_client, monkeypatch):
    from routes.segments import validation

    monkeypatch.setattr(
        validation, "load_edit_history", lambda _r: {"batches": [], "summary": None}
    )
    monkeypatch.setattr(
        validation,
        "generation_timeline",
        lambda _r: [
            {
                "version": "g1",
                "produced_at": "2026-01-01T00:00:00Z",
                "published": True,
                "published_at": "2026-01-02T00:00:00Z",
            },
        ],
    )

    resp = flask_client.get("/api/seg/edit-history/ar.some")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["batches"] == []
    assert body["summary"] is None
    assert body["generations"][0]["version"] == "g1"
    assert body["generations"][0]["published"] is True
