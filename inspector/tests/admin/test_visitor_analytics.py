"""Visitor analytics (Tier 2/3): counters, hourly flush, classification, cookie."""
from __future__ import annotations

import pytest

from services import db
from services.admin import visitors


@pytest.fixture(autouse=True)
def _reset_bucket():
    visitors._reset_for_test()
    yield
    visitors._reset_for_test()


# ---- counters + flush ----


def test_record_hit_and_flush_upserts():
    visitors.record_hit({"hf_user_id": "u1"})
    visitors.record_hit({"hf_user_id": "u1"})      # same id → 2 hits, 1 unique
    visitors.record_hit(None, anon_id="a1")
    visitors.record_hit(None, anon_id="a2")

    before = db.current_db_seq()
    assert visitors.flush() is True
    after = db.current_db_seq()
    assert after == before + 1  # exactly one committed write per flush

    from services.db import repo_visitors
    day = visitors._today()
    row = repo_visitors.get_day(day)
    assert row["signed_in_hits"] == 2
    assert row["unique_signed_in"] == 1
    assert row["anon_hits"] == 2
    assert row["unique_anon"] == 2
    # bucket drained
    assert visitors.live_counts()["signed_in_hits"] == 0


def test_flush_empty_is_noop():
    before = db.current_db_seq()
    assert visitors.flush() is False
    assert db.current_db_seq() == before  # no write, no bucket upload


def test_flush_accumulates_same_day():
    visitors.record_hit(None, anon_id="a1")
    visitors.flush()
    visitors.record_hit(None, anon_id="a2")
    visitors.flush()
    from services.db import repo_visitors
    row = repo_visitors.get_day(visitors._today())
    assert row["anon_hits"] == 2
    assert row["unique_anon"] == 2


def test_get_visitor_stats_includes_live():
    visitors.record_hit(None, anon_id="a1")
    visitors.flush()                       # 1 persisted
    visitors.record_hit(None, anon_id="a2")  # 1 live, un-flushed
    stats = visitors.get_visitor_stats()
    assert stats["today"]["anon_hits"] == 2  # persisted + live


# ---- request classification + anon cookie (Flask hooks) ----


def test_anonymous_request_counts_and_sets_cookie(flask_client, monkeypatch):
    monkeypatch.setenv("INSPECTOR_VISITOR_ANALYTICS", "1")
    resp = flask_client.get("/api/me")
    assert resp.status_code == 200
    assert visitors.live_counts()["anon_hits"] >= 1
    set_cookie = resp.headers.get("Set-Cookie", "")
    assert "inspector_anon" in set_cookie


def test_signed_in_request_counts_as_signed_in(signed_in_client, monkeypatch):
    monkeypatch.setenv("INSPECTOR_VISITOR_ANALYTICS", "1")
    client, user = signed_in_client(hf_user_id="vu", login="vu", role="contributor")
    resp = client.get("/api/me")
    assert resp.status_code == 200
    counts = visitors.live_counts()
    assert counts["signed_in_hits"] >= 1
    assert counts["anon_hits"] == 0


def test_static_assets_skipped(flask_client, monkeypatch):
    monkeypatch.setenv("INSPECTOR_VISITOR_ANALYTICS", "1")
    flask_client.get("/assets/app.js")  # 404, but must not be counted
    assert visitors.live_counts()["anon_hits"] == 0


def test_disabled_by_default_no_count(flask_client):
    # Env var unset → analytics off → no counting, no cookie.
    resp = flask_client.get("/api/me")
    assert visitors.live_counts()["anon_hits"] == 0
    assert "inspector_anon" not in resp.headers.get("Set-Cookie", "")
