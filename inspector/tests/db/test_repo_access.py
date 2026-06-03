"""repo_access: users + role_assignments, Member/RolesFile reconstruction."""

from __future__ import annotations

import sqlite3

import pytest

from qua_shared.schemas import Role

from services import db
from services.db import repo_access


def test_grant_resolve_find(fresh_db):
    with db.transaction():
        repo_access.grant_role(
            hf_user_id="u1", login="alice", role=Role.MAINTAINER, granted_by="owner1"
        )
    assert repo_access.resolve_role("u1") == Role.MAINTAINER
    assert repo_access.resolve_role("nobody") == Role.CONTRIBUTOR
    m = repo_access.find_member("u1")
    assert m is not None and m.login == "alice" and m.role == Role.MAINTAINER
    assert m.added_by_hf_id == "owner1" and m.is_active()


def test_revoke_then_regrant(fresh_db):
    with db.transaction():
        repo_access.grant_role(
            hf_user_id="u1", login="alice", role=Role.MAINTAINER, granted_by="o"
        )
    with db.transaction():
        revoked = repo_access.revoke_role(
            hf_user_id="u1", revoked_by="o", reason="left the team"
        )
    assert revoked is not None and not revoked.is_active()
    assert repo_access.resolve_role("u1") == Role.CONTRIBUTOR
    assert repo_access.find_member("u1") is None
    # re-grant after revoke is allowed (partial-unique only blocks active dupes)
    with db.transaction():
        repo_access.grant_role(
            hf_user_id="u1", login="alice", role=Role.OWNER, granted_by="o"
        )
    assert repo_access.resolve_role("u1") == Role.OWNER
    # snapshot keeps both the revoked and the active assignment
    members = repo_access.snapshot().members
    assert len(members) == 2
    assert sum(1 for m in members if m.is_active()) == 1


def test_double_active_grant_blocked(fresh_db):
    with db.transaction():
        repo_access.grant_role(
            hf_user_id="u1", login="alice", role=Role.MAINTAINER, granted_by="o"
        )
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction():
            repo_access.grant_role(
                hf_user_id="u1", login="alice", role=Role.OWNER, granted_by="o"
            )


def test_update_login_and_role(fresh_db):
    with db.transaction():
        repo_access.grant_role(
            hf_user_id="u1", login="alice", role=Role.MAINTAINER, granted_by="o"
        )
    with db.transaction():
        m = repo_access.update_role(hf_user_id="u1", login="alice2", role=Role.OWNER)
    assert m is not None and m.login == "alice2" and m.role == Role.OWNER
    assert repo_access.resolve_role("u1") == Role.OWNER


def test_ensure_user_idempotent_keeps_first_seen(fresh_db):
    with db.transaction():
        repo_access.ensure_user("u1", login="alice")
    first = db.get_conn().execute(
        "SELECT first_seen FROM users WHERE hf_user_id='u1'"
    ).fetchone()[0]
    with db.transaction():
        repo_access.ensure_user("u1", login="alice-renamed")
    row = db.get_conn().execute(
        "SELECT first_seen, login_cache FROM users WHERE hf_user_id='u1'"
    ).fetchone()
    assert row[0] == first              # first_seen preserved
    assert row[1] == "alice-renamed"    # login_cache refreshed
