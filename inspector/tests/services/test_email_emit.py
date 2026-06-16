"""Email emitter recipient-resolution + dedupe coverage.

Captures dispatches at the ``send`` boundary (the seam to external SMTP) so the
tests are deterministic — no threads, no network. Asserts WHICH addresses get
WHICH email per event, the scope filtering, and the single-email-per-publish
precedence (first_available > new_recitation > recitation_published).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from services.db import _serde
from services.db import repo_email_digest as repo_digest
from services.db import repo_email_subscriptions as repo_subs
from services.db import sync as _sync
from services.email import emit as email_emit
from services.email import send as email_send

_DEFAULT = {
    "request_aligned": False,
    "recitation_published": "off",
    "timestamps_regenerated": "off",
    "github_release": False,
    "riwayah_new_recitation": False,
    "riwayah_first_available": False,
    "reciters": [],
    "riwayahs": [],
}


@pytest.fixture
def captured(monkeypatch):
    """Replace the SMTP dispatch with a synchronous recorder of (to, subject)."""
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        email_send, "send", lambda to, subject, html, text=None: calls.append((to, subject))
    )
    return calls


def _sub(email, *, hf_user_id=None, **prefs):
    blob = {"email": email, **_DEFAULT, **prefs}
    with _sync.durable_transaction():
        repo_subs.upsert(email=email, hf_user_id=hf_user_id, prefs=blob, new_token=f"tok-{email}")


def _by_email(calls):
    return {to: subj for to, subj in calls}


def _buffered(event_kind):
    """Addresses with a buffered digest row for ``event_kind`` (any age)."""
    far = _serde.now() + timedelta(days=1)
    return {g["email"] for g in repo_digest.due_groups(cutoff=far) if g["event_kind"] == event_kind}


def test_recitation_published_all_buffers_subscriber(captured):
    # The plain recitation_published scope buffers into the digest — no immediate send.
    _sub("all@x.com", recitation_published="all")
    _sub("off@x.com", recitation_published="off")
    email_emit.emit_recitation_published(
        reciter_id="r1", reciter_name="Reciter One", riwayah=None, is_first_in_riwayah=False
    )
    assert captured == []
    assert _buffered("recitation_published") == {"all@x.com"}


def test_recitation_published_selected_buffers_only_chosen_reciter(captured):
    _sub("match@x.com", recitation_published="selected", reciters=["r1"])
    _sub("nomatch@x.com", recitation_published="selected", reciters=["r2"])
    email_emit.emit_recitation_published(
        reciter_id="r1", reciter_name="Reciter One", riwayah=None, is_first_in_riwayah=False
    )
    assert captured == []
    assert _buffered("recitation_published") == {"match@x.com"}


def test_publish_precedence_first_available_wins(captured):
    # All three opt-ins match; the address gets ONE email — the first-available one.
    _sub(
        "follow@x.com",
        recitation_published="all",
        riwayah_new_recitation=True,
        riwayah_first_available=True,
        riwayahs=["hafs"],
    )
    email_emit.emit_recitation_published(
        reciter_id="r1", reciter_name="Reciter One", riwayah="hafs", is_first_in_riwayah=True
    )
    assert len(captured) == 1
    assert captured[0][1].endswith("is now available")


def test_publish_new_recitation_when_not_first(captured):
    _sub(
        "follow@x.com",
        recitation_published="all",
        riwayah_new_recitation=True,
        riwayah_first_available=True,
        riwayahs=["hafs"],
    )
    email_emit.emit_recitation_published(
        reciter_id="r1", reciter_name="Reciter One", riwayah="hafs", is_first_in_riwayah=False
    )
    assert len(captured) == 1
    assert captured[0][1].startswith("New recitation in")


def test_timestamps_regenerated_scope_filtering(captured):
    _sub("all@x.com", timestamps_regenerated="all")
    _sub("sel@x.com", timestamps_regenerated="selected", reciters=["r1"])
    _sub("selno@x.com", timestamps_regenerated="selected", reciters=["r9"])
    email_emit.emit_timestamps_regenerated(reciter_id="r1", reciter_name="Reciter One")
    assert captured == []
    assert _buffered("timestamps_regenerated") == {"all@x.com", "sel@x.com"}


def test_github_release_emails_only_subscribers(captured):
    _sub("yes@x.com", github_release=True)
    _sub("no@x.com", github_release=False)
    email_emit.emit_github_release(version="v1.2.0")
    by = _by_email(captured)
    assert by == {"yes@x.com": "New release: v1.2.0"}


def test_request_aligned_only_matches_associated_user(captured):
    _sub("u1@x.com", hf_user_id="u-1", request_aligned=True)
    _sub("u2@x.com", hf_user_id="u-2", request_aligned=False)
    email_emit.emit_request_aligned(hf_user_id="u-1", reciter_name="Reciter One")
    email_emit.emit_request_aligned(hf_user_id="u-2", reciter_name="Reciter One")
    by = _by_email(captured)
    assert "u1@x.com" in by and by["u1@x.com"].startswith("Your request is ready")
    assert "u2@x.com" not in by
