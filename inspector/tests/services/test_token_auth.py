"""Tests for the bearer-token OWNER auth helper (services/auth/token_auth.py).

``whoami`` is monkeypatched so no network is hit. Covers: bearer owner → Actor,
authenticated non-owner → NotOwner, bad/blank token + whoami error → fail-closed
TokenAuthError, and the Bearer-header parser.
"""

from __future__ import annotations

import pytest

from scripts.lib.schemas import Role
from services.auth import token_auth
from tests.conftest import _seed_role


@pytest.fixture(autouse=True)
def _clear_token_cache():
    token_auth._clear_cache_for_test()
    yield
    token_auth._clear_cache_for_test()


def _patch_whoami(monkeypatch, mapping: dict[str, dict]):
    """Map ``token -> whoami(...) dict``. Unknown tokens raise (like a bad HF
    token would)."""
    import huggingface_hub

    def _fake(token=None, **_kw):
        if token in mapping:
            return mapping[token]
        raise RuntimeError("401 invalid token")

    monkeypatch.setattr(huggingface_hub, "whoami", _fake)


def test_bearer_owner_resolves_actor(monkeypatch):
    _seed_role("owner-1", login="owneruser", role="owner")
    _patch_whoami(monkeypatch, {"tok-owner": {"id": "owner-1", "name": "owneruser"}})

    actor = token_auth.resolve_owner_from_token("tok-owner")
    assert actor.hf_user_id == "owner-1"
    assert actor.login_at_time == "owneruser"
    assert actor.role == Role.OWNER


def test_bearer_owner_via_underscore_id(monkeypatch):
    """HF API may return the id under ``_id`` — the fallback must work."""
    _seed_role("owner-2", login="owner2", role="owner")
    _patch_whoami(monkeypatch, {"tok-2": {"_id": "owner-2", "name": "owner2"}})

    actor = token_auth.resolve_owner_from_token("tok-2")
    assert actor.hf_user_id == "owner-2"


def test_non_owner_token_rejected(monkeypatch):
    # A real user but not an owner (contributor is implicit / maintainer).
    _seed_role("maint-1", login="maint", role="maintainer")
    _patch_whoami(monkeypatch, {"tok-maint": {"id": "maint-1", "name": "maint"}})

    with pytest.raises(token_auth.NotOwner):
        token_auth.resolve_owner_from_token("tok-maint")


def test_unknown_user_is_contributor_not_owner(monkeypatch):
    """A valid token for a user with no role assignment resolves CONTRIBUTOR →
    rejected, never bypassed."""
    _patch_whoami(monkeypatch, {"tok-x": {"id": "nobody", "name": "nobody"}})
    with pytest.raises(token_auth.NotOwner):
        token_auth.resolve_owner_from_token("tok-x")


def test_bad_token_fails_closed(monkeypatch):
    _patch_whoami(monkeypatch, {"tok-good": {"id": "owner-1", "name": "o"}})
    with pytest.raises(token_auth.TokenAuthError):
        token_auth.resolve_owner_from_token("tok-bad")


def test_blank_token_fails_closed():
    with pytest.raises(token_auth.TokenAuthError):
        token_auth.resolve_owner_from_token("")
    with pytest.raises(token_auth.TokenAuthError):
        token_auth.resolve_owner_from_token(None)


def test_whoami_missing_id_fails_closed(monkeypatch):
    _patch_whoami(monkeypatch, {"tok-noid": {"name": "x"}})
    with pytest.raises(token_auth.TokenAuthError):
        token_auth.resolve_owner_from_token("tok-noid")


def test_token_cache_avoids_second_whoami(monkeypatch):
    """Second call within TTL must not re-hit whoami (id is cached; role is
    still resolved fresh)."""
    _seed_role("owner-1", login="o", role="owner")
    calls = {"n": 0}
    import huggingface_hub

    def _fake(token=None, **_kw):
        calls["n"] += 1
        return {"id": "owner-1", "name": "o"}

    monkeypatch.setattr(huggingface_hub, "whoami", _fake)

    token_auth.resolve_owner_from_token("tok-c")
    token_auth.resolve_owner_from_token("tok-c")
    assert calls["n"] == 1


def test_bearer_header_parser():
    assert token_auth.bearer_token_from_header("Bearer abc123") == "abc123"
    assert token_auth.bearer_token_from_header("bearer abc123") == "abc123"
    assert token_auth.bearer_token_from_header("Bearer   spaced  ") == "spaced"
    assert token_auth.bearer_token_from_header("Token abc") is None
    assert token_auth.bearer_token_from_header("abc") is None
    assert token_auth.bearer_token_from_header("") is None
    assert token_auth.bearer_token_from_header(None) is None
    assert token_auth.bearer_token_from_header("Bearer ") is None
