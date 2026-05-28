"""Coverage for fixes/additions from the milestone review:
reassign, resolve-miss, undismiss no-op, get_by_content_hash, extra_payload
guard, has_any_active, add_reciter/add_delivery + refresh_derived, serde tz,
and transaction-failure lock release."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.lib.schemas import Actor, Delivery, ReciterEntry, Role
from scripts.lib.schemas.catalog import Riwayah, Style, Source, Channel, Vocab

from services import db
from services.db import (
    _serde,
    errors,
    repo_access,
    repo_activity,
    repo_catalog,
    repo_claims,
    repo_requests,
    repo_transitions,
)
from ._helpers import seed_user, seed_delivery


def _actor(hf="u1", login="alice", role=Role.OWNER) -> Actor:
    return Actor(hf_user_id=hf, login_at_time=login, role=role)


# ---- connection: failure still releases the writer lock ----


def test_transaction_failure_releases_lock(fresh_db):
    seed_user("u1")
    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            conn.execute("INSERT INTO users(hf_user_id) VALUES ('x')")
            raise RuntimeError("boom")
    # if the lock had leaked, this second writer would deadlock/raise
    with db.transaction() as conn:
        conn.execute("INSERT INTO users(hf_user_id) VALUES ('y')")
    assert db.get_conn().execute(
        "SELECT COUNT(*) FROM users WHERE hf_user_id IN ('x','y')"
    ).fetchone()[0] == 1  # only 'y' committed


# ---- serde tz handling ----


def test_from_iso_forces_utc_on_naive():
    aware = _serde.from_iso("2026-01-01T00:00:00+00:00")
    naive = _serde.from_iso("2026-01-01T00:00:00")
    assert aware.tzinfo is not None
    assert naive.tzinfo == timezone.utc
    assert _serde.from_iso(None) is None


# ---- repo_claims.reassign ----


def test_reassign_closes_old_opens_new(fresh_db):
    seed_user("rev1", "r1")
    seed_user("rev2", "r2")
    seed_delivery("d1")
    with db.transaction():
        repo_claims.open_claim(slug="d1", assignee_id="rev1", assignee_login="r1")
    with db.transaction():
        repo_claims.reassign(slug="d1", new_assignee_id="rev2", new_assignee_login="r2")
    assert repo_claims.open_claim_for_user("rev1") is None
    assert repo_claims.open_claim_for_user("rev2") == "d1"
    # old claim closed with reason 'reassigned'
    closed = db.get_conn().execute(
        "SELECT close_reason FROM claims WHERE assignee_id='rev1'"
    ).fetchone()
    assert closed["close_reason"] == "reassigned"


# ---- repo_requests: resolve-miss + extra_payload guard ----


def test_resolve_missing_pending_returns_false(fresh_db):
    seed_delivery("d1")
    with db.transaction():
        assert repo_requests.resolve(
            slug="d1", status="accepted", transitioned_by=_actor()
        ) is False


def test_extra_payload_cannot_override_reserved(fresh_db):
    with pytest.raises(ValueError):
        with db.transaction():
            repo_requests.submit(
                slug=None, requester=_actor(), kind="new_reciter",
                extra_payload={"requester": {"evil": True}},
            )


# ---- repo_activity: undelete no-op + get_by_content_hash ----


def test_undelete_missing_is_noop(fresh_db):
    """Per-user dismiss/undismiss were removed with the admin notifications
    rail (migration 0006). Only the global tombstone path remains — verify
    its undelete is still a safe no-op on an unknown hash."""
    seed_user("u1")
    with db.transaction():
        repo_activity.undelete("nonexistent")  # must not raise
    assert repo_activity.is_deleted("nonexistent") is False


def test_get_by_content_hash(fresh_db):
    seed_user("u1")
    rec = repo_transitions.append(event="reciter.released", actor=_actor())
    got = repo_transitions.get(rec.request_id)
    found = repo_transitions.get_by_content_hash(got["content_hash"])
    assert found is not None and found["id"] == rec.request_id
    assert repo_transitions.get_by_content_hash("deadbeef") is None


# ---- repo_access.has_any_active ----


def test_has_any_active(fresh_db):
    assert repo_access.has_any_active() is False
    with db.transaction():
        repo_access.grant_role(
            hf_user_id="u1", login="alice", role=Role.OWNER, granted_by="boot"
        )
    assert repo_access.has_any_active() is True
    with db.transaction():
        repo_access.revoke_role(hf_user_id="u1", revoked_by="u1")
    assert repo_access.has_any_active() is False


# ---- repo_catalog: add_* duplicate contract + refresh_derived ----


def _seed_vocab_for_catalog():
    with db.transaction():
        repo_catalog.load_vocab(Vocab(
            riwayat=[Riwayah(slug="hafs", short="h", name="Hafs")],
            styles=[Style(slug="mur", short="m", name="Mur")],
            sources=[Source(slug="src", name="Src")],
            channels=[Channel(slug="ch", short="c", name="Ch")],
        ))


def _delivery(slug, src="src", ch="ch"):
    return Delivery(
        slug=slug, reciter_id="rid", riwayah="hafs", style="mur", source=src, channel=ch,
        audio_category="by_surah", chapter_count=114,
        added_at=datetime(2026, 1, 1, tzinfo=timezone.utc), added_by_hf_id="seed",
    )


def test_add_reciter_duplicate_raises(fresh_db):
    with db.transaction():
        repo_catalog.add_reciter(ReciterEntry(reciter_id="rid", name_en="R"))
    with pytest.raises(errors.Duplicate):
        with db.transaction():
            repo_catalog.add_reciter(ReciterEntry(reciter_id="rid", name_en="R2"))


def test_add_delivery_duplicate_and_refresh_derived(fresh_db):
    _seed_vocab_for_catalog()
    with db.transaction():
        repo_catalog.add_reciter(ReciterEntry(reciter_id="rid", name_en="R"))
    with db.transaction():
        repo_catalog.add_delivery(_delivery("d1"))
    # derived rollup updated by add_delivery
    derived = repo_catalog.snapshot().derived.source_channels
    assert len(derived) == 1
    assert derived[0].source == "src" and derived[0].delivery_count == 1
    # duplicate slug → Duplicate
    with pytest.raises(errors.Duplicate):
        with db.transaction():
            repo_catalog.add_delivery(_delivery("d1"))
