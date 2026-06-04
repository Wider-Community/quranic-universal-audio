"""Bookmarks + QF-auth route tests.

Covers the dormant-but-real proxy surface:
- anonymous callers get an empty list (not 401) so the FE stays local;
- mutations require a session + same-origin;
- the dev-stub session drives the in-memory store end to end.
"""

from __future__ import annotations

import os
import secrets

import pytest


@pytest.fixture
def _session_secret(monkeypatch):
    if not os.environ.get("INSPECTOR_SESSION_SECRET"):
        monkeypatch.setenv("INSPECTOR_SESSION_SECRET", secrets.token_hex(32))


def _dev_cookie() -> str:
    from services.quran_foundation import session

    return session.encode_session(
        {
            "access_token": "",
            "refresh_token": "",
            "expires_at": 2**31,
            "login": "dev-qf-user",
            "dev": True,
        }
    )


def test_status_anonymous(flask_client):
    resp = flask_client.get("/api/qf/status")
    assert resp.status_code == 200
    assert resp.get_json() == {"connected": False}


def test_bookmarks_list_anonymous_empty(flask_client):
    resp = flask_client.get("/api/bookmarks")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["connected"] is False
    assert body["bookmarks"] == []


def test_add_requires_session(flask_client):
    resp = flask_client.post(
        "/api/bookmarks",
        json={"surah": 2, "ayah": 255},
        headers={"Origin": "http://localhost"},
    )
    assert resp.status_code == 401


def test_add_requires_same_origin(flask_client):
    # No Origin/Referer on a mutating request → 403 before any session check.
    resp = flask_client.post("/api/bookmarks", json={"surah": 2, "ayah": 255})
    assert resp.status_code == 403


def test_dev_session_round_trip(flask_client, _session_secret):
    from services.quran_foundation import bookmarks as bm
    from services.quran_foundation import session

    bm._DEV_STORE.clear()
    flask_client.set_cookie(session.QF_SESSION_COOKIE_NAME, _dev_cookie(), path="/")

    # Connected status.
    status = flask_client.get("/api/qf/status").get_json()
    assert status["connected"] is True and status["dev"] is True

    # Empty to start.
    assert flask_client.get("/api/bookmarks").get_json()["bookmarks"] == []

    # Add → appears.
    add = flask_client.post(
        "/api/bookmarks", json={"surah": 2, "ayah": 255}, headers={"Origin": "http://localhost"}
    )
    assert add.status_code == 200
    listed = flask_client.get("/api/bookmarks").get_json()["bookmarks"]
    assert {"surah": 2, "ayah": 255, "key": "2:255"} in listed

    # Remove → gone.
    rm = flask_client.delete("/api/bookmarks/2:255", headers={"Origin": "http://localhost"})
    assert rm.status_code == 200
    assert flask_client.get("/api/bookmarks").get_json()["bookmarks"] == []


def test_dev_login_gated_off_when_not_dev(flask_client, monkeypatch):
    monkeypatch.setenv("INSPECTOR_DEV_MODE", "0")
    resp = flask_client.post("/api/qf/dev-login", headers={"Origin": "http://localhost"})
    assert resp.status_code == 404
