"""Tests for ``services/public_activity``.

Exercises the six-event allowlist + name-resolution + redaction surface
without writing real audit partitions.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _install_audit(monkeypatch, records):
    """Patch ``_iter_partitions`` to yield the supplied test records."""
    from services import public_activity

    monkeypatch.setattr(
        public_activity, "_iter_partitions", lambda months=2: iter(records),
    )


def _install_catalog(monkeypatch, name_by_slug):
    """Make ``catalog_service.display_name(slug)`` return our mapping."""
    from services import catalog as catalog_service

    monkeypatch.setattr(
        catalog_service, "display_name", lambda slug: name_by_slug.get(slug),
    )


def _record(event, *, slug="husary_qdc", to_state=None,
            ts="2026-05-13T12:00:00+00:00", result="ok"):
    return {
        "event": event,
        "slug": slug,
        "to_state": to_state,
        "ts": ts,
        "result": result,
        "actor": {"hf_user_id": "u-1", "login_at_time": "alice", "role": "maintainer"},
    }


def test_classifies_six_allowlisted_events(monkeypatch):
    from services.public_activity import all_public_cards

    _install_audit(monkeypatch, [
        _record("catalog.added"),
        _record("reciter.alignment_completed"),
        _record("reciter.claimed"),
        _record("reciter.marked_ready"),
        _record("reciter.timestamps_completed"),
        _record("state.transition", to_state="awaiting_alignment"),
    ])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    cards = all_public_cards()
    kinds = sorted({c["kind"] for c in cards})
    assert kinds == [
        "added",
        "available_review",
        "published",
        "publishing",
        "requested",
        "under_review",
    ]


def test_redacts_non_allowlisted_events(monkeypatch):
    from services.public_activity import all_public_cards

    _install_audit(monkeypatch, [
        _record("claim.force_released"),
        _record("claim.reassigned"),
        _record("admin.force_set_state"),
        _record("reciter.discarded"),
        _record("reciter.unmarked_ready"),
        _record("access.role_granted"),
    ])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    cards = all_public_cards()
    assert cards == []


def test_skips_records_with_unresolved_name(monkeypatch):
    from services.public_activity import all_public_cards

    _install_audit(monkeypatch, [_record("reciter.claimed", slug="unknown_slug")])
    _install_catalog(monkeypatch, {})

    cards = all_public_cards()
    assert cards == []


def test_skips_failed_audit_records(monkeypatch):
    from services.public_activity import all_public_cards

    _install_audit(monkeypatch, [_record("reciter.claimed", result="error")])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    cards = all_public_cards()
    assert cards == []


def test_card_text_uses_display_name_not_slug(monkeypatch):
    from services.public_activity import all_public_cards

    _install_audit(monkeypatch, [_record("reciter.timestamps_completed", slug="husary_qdc")])
    _install_catalog(monkeypatch, {"husary_qdc": "Mahmoud Khalil Al-Husary"})

    cards = all_public_cards()
    assert len(cards) == 1
    assert "Mahmoud Khalil Al-Husary" in cards[0]["text"]
    assert "husary_qdc" not in cards[0]["text"]


def test_card_payload_omits_assignee(monkeypatch):
    from services.public_activity import all_public_cards

    _install_audit(monkeypatch, [_record("reciter.claimed")])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    cards = all_public_cards()
    assert "actor" not in cards[0]
    assert "assignee" not in repr(cards[0])


def test_feed_paginates(monkeypatch):
    from services.public_activity import feed

    _install_audit(monkeypatch, [
        _record("reciter.claimed", ts=f"2026-05-{day:02d}T00:00:00+00:00")
        for day in range(1, 11)
    ])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    page = feed(cursor=0, limit=3)
    assert page["total"] == 10
    assert len(page["cards"]) == 3
    assert page["next_cursor"] == 3

    page2 = feed(cursor=9, limit=3)
    assert len(page2["cards"]) == 1
    assert page2["next_cursor"] is None
