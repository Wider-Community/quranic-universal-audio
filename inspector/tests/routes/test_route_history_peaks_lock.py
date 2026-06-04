"""POST/GET /api/seg/history-peaks/<reciter> tests.

The POST route is the History on-play write-back. It is **not** edit-lock
gated — it persists derived, idempotent peaks for ops that already exist, so
any same-origin viewer (incl. anonymous) may fill the cache. Guards instead:
``require_same_origin`` (CSRF), op_id-must-exist validation, dedup-by-op_id,
and record/size bounds.

The GET route is public and serves the canonical b64 records.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("INSPECTOR_SESSION_SECRET", "0" * 64)

_HEADERS = {"Content-Type": "application/json", "Origin": "http://localhost"}
_XORIGIN = {"Content-Type": "application/json", "Origin": "http://evil.example"}


def test_history_peaks_post_anonymous_same_origin_ok(flask_client, tmp_reciter_dir):
    """Relaxed gating: an anonymous, same-origin POST is accepted (empty
    records → nothing written)."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    res = flask_client.post(
        f"/api/seg/history-peaks/{reciter}",
        data=json.dumps({"records": []}),
        headers=_HEADERS,
    )
    assert res.status_code == 200
    assert res.get_json() == {"ok": True, "written": 0, "skipped": 0}


def test_history_peaks_post_cross_origin_rejected(flask_client, tmp_reciter_dir):
    """CSRF guard still applies: a cross-origin POST is rejected."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    res = flask_client.post(
        f"/api/seg/history-peaks/{reciter}",
        data=json.dumps({"records": []}),
        headers=_XORIGIN,
    )
    assert res.status_code == 403


def test_history_peaks_post_unknown_op_id_skipped(flask_client, tmp_reciter_dir):
    """A record whose op_id isn't in the reciter's edit history is refused
    (skipped), so a same-origin caller can't persist arbitrary data."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    res = flask_client.post(
        f"/api/seg/history-peaks/{reciter}",
        data=json.dumps(
            {
                "records": [
                    {
                        "op_id": "does-not-exist",
                        "url": "https://cdn/1.mp3",
                        "start_ms": 0,
                        "end_ms": 1000,
                        "bps": 10,
                        "peaks_b64": "AAAA",
                    }
                ]
            }
        ),
        headers=_HEADERS,
    )
    assert res.status_code == 200
    body = res.get_json()
    assert body["written"] == 0
    assert body["skipped"] == 1


def test_history_peaks_post_too_many_records_rejected(flask_client, tmp_reciter_dir):
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    res = flask_client.post(
        f"/api/seg/history-peaks/{reciter}",
        data=json.dumps({"records": [{"op_id": str(i)} for i in range(200)]}),
        headers=_HEADERS,
    )
    assert res.status_code == 413


def test_history_peaks_get_stays_public(flask_client, tmp_reciter_dir):
    """GET is read-only + public so anonymous users see history rows render
    with the persisted (b64) peaks."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    res = flask_client.get(f"/api/seg/history-peaks/{reciter}")
    assert res.status_code == 200
    assert "records" in res.get_json()
