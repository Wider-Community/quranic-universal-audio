"""repo_state + repo_claims: the delivery_states ⟕ open-claim → ReciterRow JOIN."""

from __future__ import annotations

from datetime import datetime

from qua_shared.schemas import ReciterState, Visibility
from services import db
from services.db import repo_claims, repo_state

from ._helpers import seed_delivery, seed_user


def _dt(s="2026-01-01T00:00:00+00:00") -> datetime:
    return datetime.fromisoformat(s)


def test_catalogued_row_has_no_assignee(fresh_db):
    seed_delivery("d1")
    with db.transaction():
        repo_state.upsert_state("d1", state=ReciterState.CATALOGUED, state_since=_dt())
    row = repo_state.get_row("d1")
    assert row is not None
    assert row.state == ReciterState.CATALOGUED
    assert row.assignee_hf_id is None
    assert row.marked_ready is False
    assert row.visibility == Visibility.PUBLIC


def test_under_review_assignee_from_open_claim(fresh_db):
    seed_user("rev1", "reviewer")
    seed_delivery("d1")
    with db.transaction():
        repo_state.upsert_state("d1", state=ReciterState.UNDER_REVIEW, state_since=_dt())
        repo_claims.open_claim(
            slug="d1",
            assignee_id="rev1",
            assignee_login="reviewer",
            claimed_at=_dt("2026-02-02T00:00:00+00:00"),
        )
    row = repo_state.get_row("d1")
    assert row.state == ReciterState.UNDER_REVIEW
    assert row.assignee_hf_id == "rev1"
    assert row.assignee_login == "reviewer"
    assert row.assignee_since == _dt("2026-02-02T00:00:00+00:00")
    assert row.marked_ready is False


def test_marked_ready_derived_from_claim(fresh_db):
    seed_user("rev1", "reviewer")
    seed_delivery("d1")
    with db.transaction():
        repo_state.upsert_state("d1", state=ReciterState.UNDER_REVIEW, state_since=_dt())
        repo_claims.open_claim(slug="d1", assignee_id="rev1", assignee_login="reviewer")
    with db.transaction():
        repo_claims.set_marked_ready("d1", ready=True)
    assert repo_state.get_row("d1").marked_ready is True
    with db.transaction():
        repo_claims.set_marked_ready("d1", ready=False)
    assert repo_state.get_row("d1").marked_ready is False


def test_release_clears_assignee(fresh_db):
    seed_user("rev1", "reviewer")
    seed_delivery("d1")
    with db.transaction():
        repo_state.upsert_state("d1", state=ReciterState.UNDER_REVIEW, state_since=_dt())
        repo_claims.open_claim(slug="d1", assignee_id="rev1", assignee_login="reviewer")
    # release: close claim + move state out of under_review (publish → released)
    with db.transaction():
        repo_claims.close_claim(slug="d1", close_reason="released")
        repo_state.update_state("d1", state=ReciterState.RELEASED, state_since=_dt())
    # Directly assert the open claim was actually closed — the assembled
    # ReciterRow only fills assignee_* when state == UNDER_REVIEW, so checking
    # `row.assignee_hf_id is None` alone passes for the wrong reason.
    assert repo_claims.get_open_claim("d1") is None
    row = repo_state.get_row("d1")
    assert row.state == ReciterState.RELEASED
    assert row.assignee_hf_id is None


def test_retained_columns_roundtrip(fresh_db):
    seed_delivery("d1")
    with db.transaction():
        repo_state.upsert_state(
            "d1",
            state=ReciterState.RELEASED,
            state_since=_dt(),
            last_save_at=_dt("2026-03-03T00:00:00+00:00"),
            timestamps_job_ids=["job-1", "job-2"],
        )
    row = repo_state.get_row("d1")
    assert row.timestamps_job_ids == ["job-1", "job-2"]
    assert row.last_save_at == _dt("2026-03-03T00:00:00+00:00")


def test_all_rows_and_open_claim_for_user(fresh_db):
    seed_user("rev1", "reviewer")
    seed_delivery("d1")
    seed_delivery("d2")
    with db.transaction():
        repo_state.upsert_state("d1", state=ReciterState.UNDER_REVIEW, state_since=_dt())
        repo_state.upsert_state("d2", state=ReciterState.CATALOGUED, state_since=_dt())
        repo_claims.open_claim(slug="d1", assignee_id="rev1", assignee_login="reviewer")
    rows = {r.slug: r for r in repo_state.all_rows()}
    assert set(rows) == {"d1", "d2"}
    assert rows["d1"].assignee_hf_id == "rev1"
    assert rows["d2"].assignee_hf_id is None
    # one-claim-per-user lookup (O(1) index, replaces all_rows scan)
    assert repo_claims.open_claim_for_user("rev1") == "d1"
    assert repo_claims.open_claim_for_user("nobody") is None


def test_visibility_discarded_with_reason(fresh_db):
    seed_delivery("d1")
    with db.transaction():
        repo_state.upsert_state(
            "d1",
            state=ReciterState.CATALOGUED,
            state_since=_dt(),
            visibility=Visibility.DISCARDED,
            visibility_reason="spam submission",
        )
    row = repo_state.get_row("d1")
    assert row.visibility == Visibility.DISCARDED
    assert row.visibility_reason == "spam submission"
