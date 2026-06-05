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
        public_activity,
        "_iter_partitions",
        lambda months=2: iter(records),
    )


def _install_catalog(monkeypatch, name_by_slug):
    """Make ``catalog_service.display_name(slug)`` return our mapping."""
    from services import catalog as catalog_service

    monkeypatch.setattr(
        catalog_service,
        "display_name",
        lambda slug: name_by_slug.get(slug),
    )


def _record(
    event,
    *,
    slug="husary_qdc",
    to_state=None,
    ts="2026-05-13T12:00:00+00:00",
    result="ok",
    actor_hf="u-1",
    actor_login="alice",
    actor_role="maintainer",
):
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


def test_classifies_allowlisted_events(monkeypatch):
    from services.public_activity import all_public_cards

    _install_audit(
        monkeypatch,
        [
            _record("catalog.added"),
            _record("reciter.alignment_completed"),
            _record("reciter.claimed"),
            # v2: the public release event is `released` (covers HF push + GH cut).
            # `reciter.published` (TS-gen completion) is HIDDEN now — admin-only.
            _record("released"),
            _record("state.transition", to_state="awaiting_alignment"),
        ],
    )
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    cards = all_public_cards()
    kinds = sorted({c["kind"] for c in cards})
    assert kinds == [
        "added",
        "available_review",
        "released",
        "requested",
        "under_review",
    ]


def test_marked_ready_is_redacted_from_public_feed(monkeypatch):
    """marked_ready is internal-only — never surfaces on the public feed."""
    from services.public_activity import all_public_cards

    _install_audit(monkeypatch, [_record("reciter.marked_ready")])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    assert all_public_cards() == []


def test_redacts_non_allowlisted_events(monkeypatch):
    from services.public_activity import all_public_cards

    _install_audit(
        monkeypatch,
        [
            _record("claim.force_released"),
            _record("claim.reassigned"),
            _record("admin.unlocked_for_revision"),
            _record("reciter.discarded"),
            _record("reciter.unmarked_ready"),
            _record("access.role_granted"),
        ],
    )
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

    # v2: `released` is the public-facing publish event.
    _install_audit(monkeypatch, [_record("released", slug="husary_qdc")])
    _install_catalog(monkeypatch, {"husary_qdc": "Mahmoud Khalil Al-Husary"})

    cards = all_public_cards()
    assert len(cards) == 1
    assert "Mahmoud Khalil Al-Husary" in cards[0]["text"]
    assert "husary_qdc" not in cards[0]["text"]


def test_card_payload_omits_assignee_by_default(monkeypatch):
    """Default (no caller role) keeps the pre-existing redacted shape."""
    from services.public_activity import all_public_cards

    _install_audit(monkeypatch, [_record("reciter.claimed")])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    cards = all_public_cards()
    assert "actor" not in cards[0]
    assert "actor_login" not in cards[0]


def test_owner_caller_sees_actor_login(monkeypatch):
    """include_identity=True surfaces actor identity on the public rail. The
    route resolves the ``identity.see_actor`` capability (default owner-only)
    into this bool; the service stays capability-agnostic."""
    from services.public_activity import all_public_cards

    _install_audit(
        monkeypatch,
        [
            _record("reciter.claimed", actor_login="alice", actor_hf="u-A"),
        ],
    )
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    cards = all_public_cards(include_identity=True)
    assert cards[0]["actor_login"] == "alice"
    assert cards[0]["actor_hf_user_id"] == "u-A"


def test_maintainer_caller_does_not_see_actor(monkeypatch):
    """include_identity=False keeps actor identity redacted (the default for
    non-owner callers without the identity.see_actor capability)."""
    from services.public_activity import all_public_cards

    _install_audit(monkeypatch, [_record("reciter.claimed", actor_login="alice")])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    cards = all_public_cards(include_identity=False)
    assert "actor_login" not in cards[0]


def test_tombstoned_audit_id_excluded(monkeypatch):
    """Records whose audit_id is in the global tombstone list disappear."""
    from qua_shared.schemas import Actor, Role
    from services import activity_classification as ac
    from services import activity_state as activity_state_service
    from services.public_activity import all_public_cards

    rec = _record("reciter.claimed")
    _install_audit(monkeypatch, [rec])
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    actor = Actor(hf_user_id="u-O", login_at_time="owen", role=Role.OWNER)
    # Tombstone the synthetic record's audit_id (no content_hash on it → the
    # card falls back to ac.audit_id, matching this key).
    activity_state_service.delete(ac.audit_id(rec), actor=actor, reason="ten chars or more here")

    assert all_public_cards() == []


class _StubDelivery:
    def __init__(self, slug, reciter_id, riwayah, style):
        self.slug = slug
        self.reciter_id = reciter_id
        self.riwayah = riwayah
        self.style = style


class _StubReciter:
    def __init__(self, reciter_id, name_en):
        self.reciter_id = reciter_id
        self.name_en = name_en


def _install_delivery_descriptor(monkeypatch, deliveries, reciters):
    """Patch catalog lookups used by ``_delivery_descriptor``."""
    from services import catalog as catalog_service

    monkeypatch.setattr(
        catalog_service,
        "find_delivery",
        lambda slug: deliveries.get(slug),
    )
    monkeypatch.setattr(
        catalog_service,
        "find_reciter",
        lambda rid: reciters.get(rid),
    )
    # display_name is still the fallback path; keep it consistent.
    monkeypatch.setattr(
        catalog_service,
        "display_name",
        lambda slug: (
            reciters[deliveries[slug].reciter_id].name_en
            if slug in deliveries and deliveries[slug].reciter_id in reciters
            else None
        ),
    )


def test_card_carries_riwayah_and_style(monkeypatch):
    """Cards include the delivery's riwayah and style slugs for rich rendering."""
    from services.public_activity import all_public_cards

    deliveries = {
        "husary_qdc": _StubDelivery(
            slug="husary_qdc",
            reciter_id="husary",
            riwayah="hafs_an_asim",
            style="murattal",
        ),
    }
    reciters = {"husary": _StubReciter("husary", "Mahmoud Khalil Al-Husary")}

    _install_audit(monkeypatch, [_record("reciter.claimed", slug="husary_qdc")])
    _install_delivery_descriptor(monkeypatch, deliveries, reciters)

    cards = all_public_cards()
    assert len(cards) == 1
    card = cards[0]
    assert card["name"] == "Mahmoud Khalil Al-Husary"
    assert card["riwayah"] == "hafs_an_asim"
    assert card["style"] == "murattal"
    # Text fallback still emitted for older clients.
    assert "Mahmoud Khalil Al-Husary" in card["text"]


def test_card_falls_back_when_slug_missing_from_catalog(monkeypatch):
    """When the catalog no longer has the delivery, riwayah/style are null
    but the card still renders via the display_name fallback."""
    from services.public_activity import all_public_cards

    _install_audit(monkeypatch, [_record("reciter.claimed", slug="husary_qdc")])
    # No delivery/reciter rows — only display_name resolves.
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    cards = all_public_cards()
    assert len(cards) == 1
    card = cards[0]
    assert card["name"] == "Husary"
    assert card["riwayah"] is None
    assert card["style"] is None
    assert "Husary" in card["text"]


def test_feed_paginates(monkeypatch):
    from services.public_activity import feed

    _install_audit(
        monkeypatch,
        [
            _record("reciter.claimed", ts=f"2026-05-{day:02d}T00:00:00+00:00")
            for day in range(1, 11)
        ],
    )
    _install_catalog(monkeypatch, {"husary_qdc": "Husary"})

    page = feed(cursor=0, limit=3)
    assert page["total"] == 10
    assert len(page["cards"]) == 3
    assert page["next_cursor"] == 3

    page2 = feed(cursor=9, limit=3)
    assert len(page2["cards"]) == 1
    assert page2["next_cursor"] is None
