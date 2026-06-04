"""Admin Users read path: list aggregations + detail + no-N+1 guard."""

from __future__ import annotations

from datetime import UTC

from services import db
from services.admin import users as users_service
from services.db import _serde, repo_admin_users


def _ins_transition(conn, *, tid, actor, event, slug=None, ts=None):
    conn.execute(
        "INSERT INTO transitions(id, ts, slug, event, actor_id) VALUES (?,?,?,?,?)",
        (tid, ts or _serde.to_iso(_serde.now()), slug, event, actor),
    )


def _ins_request(conn, *, rid, requester, status, kind="existing_combo_edit", slug=None):
    conn.execute(
        "INSERT INTO requests(id, kind, slug, requester_id, submitted_at, status) "
        "VALUES (?,?,?,?,?,?)",
        (rid, kind, slug, requester, _serde.to_iso(_serde.now()), status),
    )


def test_list_users_aggregates(seed_role, seed_state):
    seed_role("m1", login="maint", role="maintainer")
    seed_role("c1", login="contrib", role="contributor")
    # c1 holds an open, marked-ready claim on slugA.
    seed_state(
        "slugA",
        state="under_review",
        assignee_hf_id="c1",
        assignee_login="contrib",
        marked_ready=True,
    )

    with db.transaction() as conn:
        _ins_transition(conn, tid="t1", actor="m1", event="reciter.marked_ready")
        _ins_transition(conn, tid="t2", actor="m1", event="reciter.marked_ready")
        _ins_transition(conn, tid="t3", actor="c1", event="reciter.claimed")
        _ins_request(conn, rid="r1", requester="c1", status="pending")
        _ins_request(conn, rid="r2", requester="c1", status="accepted")

    payload = users_service.list_users()
    by_id = {u["hf_user_id"]: u for u in payload["users"]}

    assert by_id["m1"]["role"] == "maintainer"
    assert by_id["m1"]["reviews"] == 2
    assert by_id["m1"]["requests"] == 0
    assert by_id["m1"]["active_claim"] is None

    assert by_id["c1"]["role"] == "contributor"
    assert by_id["c1"]["reviews"] == 0
    assert by_id["c1"]["requests"] == 2
    assert by_id["c1"]["last_activity"] is not None
    claim = by_id["c1"]["active_claim"]
    assert claim is not None and claim["slug"] == "slugA"
    assert claim["marked_ready"] is True

    # >= 2: granting m1's maintainer role also creates the "test-seed" granter
    # user row, which legitimately counts as a registered user.
    assert payload["summary"]["registered"] >= 2
    assert payload["summary"]["active_this_week"] >= 1


def test_zero_action_user_still_listed(seed_role):
    # A user who logged in but never acted (Tier-1) must still appear.
    seed_role("lurker", login="lurker", role="contributor")
    payload = users_service.list_users()
    ids = {u["hf_user_id"] for u in payload["users"]}
    assert "lurker" in ids
    row = next(u for u in payload["users"] if u["hf_user_id"] == "lurker")
    assert row["reviews"] == 0 and row["requests"] == 0 and row["active_claim"] is None


def test_detail_outcome_and_stats(seed_role, seed_state):
    from datetime import datetime, timezone

    from tests.conftest import _seed_delivery_chain

    from services.db import repo_claims

    seed_role("rev", login="rev", role="contributor")
    # open claim → "claimed, open now". Not marked-ready so it doesn't add a
    # ~0-turnaround pair and skew the avg (the only turnaround pair is pubS).
    seed_state(
        "openS",
        state="under_review",
        assignee_hf_id="rev",
        assignee_login="rev",
        marked_ready=False,
    )
    # a closed-as-published claim row for history/turnaround
    claimed_at = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    marked_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    released_at = datetime(2026, 1, 2, 0, 0, 0, tzinfo=UTC)
    with db.transaction() as conn:
        _seed_delivery_chain(conn, "pubS")
        repo_claims.open_claim(
            slug="pubS",
            assignee_id="rev",
            assignee_login="rev",
            claimed_at=claimed_at,
        )
        repo_claims.set_marked_ready("pubS", ready=True, at=marked_at)
        repo_claims.close_claim(
            slug="pubS",
            close_reason="reciter.published",
            released_at=released_at,
        )
        _ins_request(conn, rid="rq1", requester="rev", status="accepted")
        _ins_request(conn, rid="rq2", requester="rev", status="returned")

    detail = users_service.get_user_detail("rev")
    assert detail is not None
    assert detail["stats"]["lifetime_claims"] == 2
    assert detail["stats"]["requests_by_status"] == {"accepted": 1, "returned": 1}
    # turnaround: 12h on the published claim
    assert detail["stats"]["avg_turnaround_seconds"] == 12 * 3600

    outcomes = {c["slug"]: c["outcome"] for c in detail["claims_history"]}
    assert outcomes["openS"] == "claimed, open now"
    assert outcomes["pubS"] == "published"


def test_detail_unknown_user_returns_none():
    assert users_service.get_user_detail("nobody") is None


def test_list_users_no_n_plus_1(seed_role, monkeypatch):
    """The list path issues a constant number of repo queries regardless of
    user count (5 aggregations), never per-user."""
    calls = {"n": 0}
    real_get_conn = repo_admin_users.get_conn

    class _CountingConn:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, *a, **k):
            calls["n"] += 1
            return self._conn.execute(*a, **k)

    monkeypatch.setattr(repo_admin_users, "get_conn", lambda: _CountingConn(real_get_conn()))

    for i in range(3):
        seed_role(f"u{i}", login=f"u{i}", role="contributor")
    calls["n"] = 0
    users_service.list_users()
    three = calls["n"]

    for i in range(3, 9):
        seed_role(f"u{i}", login=f"u{i}", role="contributor")
    calls["n"] = 0
    users_service.list_users()
    nine = calls["n"]

    assert three == nine
    # Pin the exact aggregation count: base_rows, last_activity_by_actor,
    # requests_count_by_user, reviews_count_by_actor, open_claims_by_user.
    assert three == 5
