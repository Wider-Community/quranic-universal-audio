"""POST /api/seg/history-peaks/<reciter> tests — confirms the edit-lock
guard added in Phase 3.

The route appends to ``edit_history_peaks.jsonl`` in the bucket, so it
shares the writer policy with save/undo: signed-in + active reviewer
(or admin via admin_bypass) only.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("INSPECTOR_SESSION_SECRET", "0" * 64)

_HEADERS = {"Content-Type": "application/json", "Origin": "http://localhost"}


def test_history_peaks_post_anonymous_returns_401(flask_client, tmp_reciter_dir):
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    res = flask_client.post(
        f"/api/seg/history-peaks/{reciter}",
        data=json.dumps({"records": []}),
        headers=_HEADERS,
    )
    assert res.status_code == 401


def test_history_peaks_post_non_assignee_returns_403(signed_in_client, tmp_reciter_dir):
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="other-user")
    client, _ = signed_in_client(hf_user_id="test-user-1", login="alice")
    res = client.post(
        f"/api/seg/history-peaks/{reciter}",
        data=json.dumps({"records": []}),
        headers=_HEADERS,
    )
    assert res.status_code == 403


def test_history_peaks_post_assignee_happy_path(signed_in_client, tmp_reciter_dir):
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="u-1")
    client, _ = signed_in_client(hf_user_id="u-1", login="alice")
    res = client.post(
        f"/api/seg/history-peaks/{reciter}",
        data=json.dumps({"records": []}),
        headers=_HEADERS,
    )
    assert res.status_code == 200


def test_history_peaks_get_stays_public(flask_client, tmp_reciter_dir):
    """The GET route is read-only and stays public so anonymous users can
    still see history rows render with cached peaks."""
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="test-user-1")
    res = flask_client.get(f"/api/seg/history-peaks/{reciter}")
    assert res.status_code == 200
    assert "records" in res.get_json()


def test_history_peaks_post_maintainer_can_override(signed_in_client, tmp_reciter_dir):
    reciter = "fixture_reciter"
    tmp_reciter_dir.install(reciter, "112-ikhlas", under_review_for="other-user")
    client, _ = signed_in_client(hf_user_id="mod-1", login="mod", role="maintainer")
    res = client.post(
        f"/api/seg/history-peaks/{reciter}",
        data=json.dumps({"records": []}),
        headers=_HEADERS,
    )
    assert res.status_code == 200
