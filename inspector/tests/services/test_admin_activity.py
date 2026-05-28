"""Tests for ``services/admin_activity`` — admin-only activity feed.

Mirrors the public feed but consumes ``ADMIN_ONLY_EVENTS`` from the
classifier and supports tier-aware redaction:

- Owner callers see the actor's HF login on each card.
- Maintainer callers see the same cards with the actor identity redacted.

Per-user dismissals (read from ``services/activity_state``) hide cards
from the live feed; ``archived=True`` returns them so the rail can render
a collapsible archive section.
"""

from __future__ import annotations

import pytest

from scripts.lib.schemas import Role


def _record(event, *, slug="husary_qdc", to_state=None,
            ts="2026-05-13T12:00:00+00:00", result="ok",
            actor_hf="u-1", actor_login="alice", actor_role="maintainer"):
    return {
        "event": event,
        "slug": slug,
        "to_state": to_state,
        "ts": ts,
        "result": result,
        "actor": {
            "hf_user_id": actor_hf,
            "login_at_time": actor_login,
            "role": actor_role,
        },
    }


def _install_audit(monkeypatch, records):
    from services import public_activity
    monkeypatch.setattr(
        public_activity, "_iter_partitions", lambda months=2: iter(records),
    )


def _install_catalog(monkeypatch, name_by_slug):
    from services import catalog as catalog_service
    monkeypatch.setattr(
        catalog_service, "display_name", lambda slug: name_by_slug.get(slug),
    )
    # Force the delivery-descriptor path to None so tests stay focused on
    # the name fallback path; specific tests that need richer descriptors
    # patch _install_delivery_descriptor directly.
    monkeypatch.setattr(
        catalog_service, "find_delivery", lambda slug: None,
    )


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def test_feed_includes_admin_only_events(monkeypatch):
    from services.admin_activity import feed

    _install_audit(monkeypatch, [
        _record("reciter.marked_ready"),
        _record("claim.force_released"),
        _record("admin.unlocked_for_revision"),
    ])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    page = feed(caller_role=Role.MAINTAINER, caller_hf_id="u-X")
    kinds = sorted({c["kind"] for c in page["cards"]})
    assert kinds == ["force_released", "marked_ready", "unlocked_for_revision"]


def test_feed_excludes_public_events(monkeypatch):
    """Public events stay on the public rail; never appear in the admin feed."""
    from services.admin_activity import feed

    _install_audit(monkeypatch, [
        _record("catalog.added"),
        _record("reciter.alignment_completed"),
        _record("reciter.claimed"),
        _record("reciter.published"),
    ])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    page = feed(caller_role=Role.MAINTAINER, caller_hf_id="u-X")
    assert page["cards"] == []


def test_feed_excludes_hidden_events(monkeypatch):
    from services.admin_activity import feed

    _install_audit(monkeypatch, [
        _record("admin.batch_timestamps_refresh"),
        _record("reciter.timestamps_completed"),
        _record("published.edited"),
        _record("access.role_granted"),
    ])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    page = feed(caller_role=Role.OWNER, caller_hf_id="u-O")
    assert page["cards"] == []


def test_feed_skips_failed_audit_records(monkeypatch):
    from services.admin_activity import feed

    _install_audit(monkeypatch, [_record("reciter.marked_ready", result="error")])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    page = feed(caller_role=Role.OWNER, caller_hf_id="u-O")
    assert page["cards"] == []


# ---------------------------------------------------------------------------
# Tier-aware actor redaction
# ---------------------------------------------------------------------------


def test_owner_sees_actor_login(monkeypatch):
    from services.admin_activity import feed

    _install_audit(monkeypatch, [
        _record("reciter.marked_ready", actor_login="alice", actor_hf="u-A"),
    ])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    page = feed(caller_role=Role.OWNER, caller_hf_id="u-O")
    assert len(page["cards"]) == 1
    card = page["cards"][0]
    assert card["actor_login"] == "alice"
    assert card["actor_hf_user_id"] == "u-A"


def test_maintainer_sees_redacted_actor(monkeypatch):
    from services.admin_activity import feed

    _install_audit(monkeypatch, [
        _record("reciter.marked_ready", actor_login="alice", actor_hf="u-A"),
    ])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    page = feed(caller_role=Role.MAINTAINER, caller_hf_id="u-X")
    assert len(page["cards"]) == 1
    card = page["cards"][0]
    assert "actor_login" not in card
    assert "actor_hf_user_id" not in card


# ---------------------------------------------------------------------------
# Dismissals + archive view
# ---------------------------------------------------------------------------


def test_dismissed_cards_excluded_by_default(monkeypatch, tmp_path):
    from services import activity_state as activity_state_service
    from services import hf_bucket as _hf_bucket
    from services.admin_activity import feed
    from scripts.lib.schemas import Actor

    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)
    activity_state_service.hydrate()

    _install_audit(monkeypatch, [_record("reciter.marked_ready")])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})
    monkeypatch.setattr(
        "services.audit.append", lambda **kw: None,
    )

    # Compute the audit_id for the only record and dismiss it for user M.
    from services import activity_classification as ac
    rec = _record("reciter.marked_ready")
    audit_id = ac.audit_id(rec)
    actor_M = Actor(hf_user_id="u-M", login_at_time="mod", role=Role.MAINTAINER)
    activity_state_service.dismiss(audit_id, actor=actor_M)

    page = feed(caller_role=Role.MAINTAINER, caller_hf_id="u-M")
    assert page["cards"] == []
    assert page["archived_count"] == 1

    # Other admin still sees it.
    page_other = feed(caller_role=Role.OWNER, caller_hf_id="u-O")
    assert len(page_other["cards"]) == 1
    assert page_other["archived_count"] == 0

    _hf_bucket.reset_backend()


def test_archived_param_returns_dismissed(monkeypatch, tmp_path):
    from services import activity_state as activity_state_service
    from services import hf_bucket as _hf_bucket
    from services.admin_activity import feed
    from scripts.lib.schemas import Actor

    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)
    activity_state_service.hydrate()

    _install_audit(monkeypatch, [_record("reciter.marked_ready")])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})
    monkeypatch.setattr("services.audit.append", lambda **kw: None)

    from services import activity_classification as ac
    audit_id = ac.audit_id(_record("reciter.marked_ready"))
    actor_M = Actor(hf_user_id="u-M", login_at_time="mod", role=Role.MAINTAINER)
    activity_state_service.dismiss(audit_id, actor=actor_M)

    page = feed(caller_role=Role.MAINTAINER, caller_hf_id="u-M", archived=True)
    assert len(page["cards"]) == 1

    _hf_bucket.reset_backend()


# ---------------------------------------------------------------------------
# Card shape
# ---------------------------------------------------------------------------


def test_card_carries_audit_id(monkeypatch):
    """Each card must carry the audit_id so the rail can dismiss/undismiss it."""
    from services import activity_classification as ac
    from services.admin_activity import feed

    rec = _record("reciter.marked_ready")
    _install_audit(monkeypatch, [rec])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    page = feed(caller_role=Role.OWNER, caller_hf_id="u-O")
    card = page["cards"][0]
    assert card["audit_id"] == ac.audit_id(rec)


def test_card_uses_display_name(monkeypatch):
    from services.admin_activity import feed

    _install_audit(monkeypatch, [_record("reciter.marked_ready", slug="husary_qdc")])
    _install_catalog(monkeypatch, {"husary_qdc": "Mahmoud Khalil Al-Husary"})

    page = feed(caller_role=Role.OWNER, caller_hf_id="u-O")
    card = page["cards"][0]
    assert "Mahmoud Khalil Al-Husary" in card["text"]
    assert "husary_qdc" not in card["text"]


def test_pagination(monkeypatch):
    from services.admin_activity import feed

    _install_audit(monkeypatch, [
        _record("reciter.marked_ready",
                ts=f"2026-05-{day:02d}T00:00:00+00:00")
        for day in range(1, 8)
    ])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    page = feed(caller_role=Role.OWNER, caller_hf_id="u-O",
                cursor=0, limit=3)
    assert page["total"] == 7
    assert len(page["cards"]) == 3
    assert page["next_cursor"] == 3

    page_last = feed(caller_role=Role.OWNER, caller_hf_id="u-O",
                     cursor=6, limit=3)
    assert len(page_last["cards"]) == 1
    assert page_last["next_cursor"] is None
