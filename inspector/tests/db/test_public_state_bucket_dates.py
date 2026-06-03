"""``_bucket_dates_for_slug`` transition replay — non-linear progression.

The modal's delivery timeline replays the ``transitions`` log into per-bucket
entry timestamps. The interesting cases are NON-linear: internal states that
collapse onto one bucket (no double-counting) and buckets re-entered after a
regression (a fresh timestamp each visit).
"""

from __future__ import annotations

from qua_shared.schemas import Actor, Role

from services.db import repo_transitions
from services.public_state import _bucket_dates_for_slug
from tests.db._helpers import seed_delivery


def _actor() -> Actor:
    return Actor(hf_user_id="u1", login_at_time="alice", role=Role.OWNER)


def _step(slug: str, from_state: str | None, to_state: str) -> None:
    repo_transitions.append(
        event="reciter.test_step",
        actor=_actor(),
        slug=slug,
        from_state=from_state,
        to_state=to_state,
    )


def test_bucket_dates_collapse_and_reentry(fresh_db):
    seed_delivery("d1")
    # A non-linear lifecycle, including a now-removed legacy state in the
    # historical log:
    #   catalogued → awaiting_alignment → awaiting_review → under_review
    #   → awaiting_timestamps  (LEGACY state, removed from the enum → the replay
    #                           skips it; prev bucket stays "under_review", so it
    #                           does not add an entry — same net effect as the old
    #                           same-bucket collapse)
    #   → awaiting_review      (regression: re-enter "available_for_review")
    #   → under_review         (re-enter "under_review")
    seq = [
        (None, "catalogued"),
        ("catalogued", "awaiting_alignment"),
        ("awaiting_alignment", "awaiting_review"),
        ("awaiting_review", "under_review"),
        ("under_review", "awaiting_timestamps"),
        ("awaiting_timestamps", "awaiting_review"),
        ("awaiting_review", "under_review"),
    ]
    for frm, to in seq:
        _step("d1", frm, to)

    dates = _bucket_dates_for_slug("d1")

    # One entry each for the buckets visited exactly once.
    assert len(dates["available_for_request"]) == 1
    assert len(dates["requested"]) == 1
    # awaiting_review entered twice (initial + regression) → two timestamps.
    assert len(dates["available_for_review"]) == 2
    # under_review entered twice; the legacy awaiting_timestamps step in between
    # is skipped (unknown state) and must NOT add a third entry.
    assert len(dates["under_review"]) == 2
    assert "published" not in dates

    # Per-bucket entries are chronological.
    afr = dates["available_for_review"]
    assert afr == sorted(afr)


def test_bucket_dates_admin_jump_skips_intermediate(fresh_db):
    """An admin override that jumps states records only the buckets actually
    entered — skipped buckets are simply absent (timeline renders them blank)."""
    seed_delivery("d2")
    _step("d2", None, "awaiting_alignment")
    _step("d2", "awaiting_alignment", "released")  # jump straight to published

    dates = _bucket_dates_for_slug("d2")
    assert set(dates) == {"requested", "published"}
    assert "available_for_review" not in dates
    assert "under_review" not in dates


def test_bucket_dates_empty_for_unknown_slug(fresh_db):
    assert _bucket_dates_for_slug("nonexistent") == {}
