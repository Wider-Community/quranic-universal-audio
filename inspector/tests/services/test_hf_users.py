"""Tests for ``inspector/services/hf_users.py`` — HF user-lookup proxy."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests


def _mock_response(status: int, json_body: dict | None = None):
    resp = MagicMock()
    resp.status_code = status
    resp.ok = 200 <= status < 300
    resp.json.return_value = json_body or {}
    return resp


def test_lookup_returns_parsed_user(monkeypatch):
    from services import hf_users

    body = {
        "id": "abc123",
        "user": "Hetchyy",
        "fullname": "Ahmed Ibrahim",
        "avatarUrl": "https://huggingface.co/avatars/hetchyy.png",
    }
    monkeypatch.setattr(
        hf_users.requests,
        "get",
        lambda url, timeout: _mock_response(200, body),
    )
    user = hf_users.lookup("hetchyy")
    assert user is not None
    assert user.hf_user_id == "abc123"
    assert user.login == "Hetchyy"
    assert user.fullname == "Ahmed Ibrahim"
    assert user.avatar_url == "https://huggingface.co/avatars/hetchyy.png"


def test_lookup_falls_back_to_underscore_id(monkeypatch):
    from services import hf_users

    body = {"_id": "legacy42", "user": "old_user"}
    monkeypatch.setattr(
        hf_users.requests,
        "get",
        lambda url, timeout: _mock_response(200, body),
    )
    user = hf_users.lookup("old_user")
    assert user is not None
    assert user.hf_user_id == "legacy42"


def test_lookup_returns_none_on_404(monkeypatch):
    from services import hf_users

    monkeypatch.setattr(
        hf_users.requests,
        "get",
        lambda url, timeout: _mock_response(404),
    )
    assert hf_users.lookup("ghost") is None


def test_lookup_raises_on_5xx(monkeypatch):
    from services import hf_users

    monkeypatch.setattr(
        hf_users.requests,
        "get",
        lambda url, timeout: _mock_response(503),
    )
    with pytest.raises(hf_users.HfUserLookupError):
        hf_users.lookup("alice")


def test_lookup_raises_on_timeout(monkeypatch):
    from services import hf_users

    def _raise(url, timeout):
        raise requests.Timeout("read timeout")

    monkeypatch.setattr(hf_users.requests, "get", _raise)
    with pytest.raises(hf_users.HfUserLookupError):
        hf_users.lookup("alice")


def test_lookup_raises_when_id_missing(monkeypatch):
    from services import hf_users

    monkeypatch.setattr(
        hf_users.requests,
        "get",
        lambda url, timeout: _mock_response(200, {"user": "alice"}),
    )
    with pytest.raises(hf_users.HfUserLookupError):
        hf_users.lookup("alice")


def test_lookup_returns_none_for_blank_login(monkeypatch):
    from services import hf_users

    # Should short-circuit; no HTTP call.
    called = []
    monkeypatch.setattr(
        hf_users.requests,
        "get",
        lambda url, timeout: called.append(1) or _mock_response(404),
    )
    assert hf_users.lookup("") is None
    assert hf_users.lookup("   ") is None
    assert called == []
