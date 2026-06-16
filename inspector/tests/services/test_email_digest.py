"""Email-digest flush coverage — windowing, batching, dedup, per-event isolation.

Buffering happens via the real ``emit_*`` functions (they write ``email_digest``);
the flush is driven directly through ``digest.flush_due`` with a controlled
``now`` so the 60-min window is exercised without sleeping. Sends are captured at
the ``send`` boundary (no threads, no SMTP).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from services.db import _serde
from services.db import repo_email_digest as repo_digest
from services.db import repo_email_subscriptions as repo_subs
from services.db import sync as _sync
from services.email import digest as email_digest
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

# Past the 60-min window: cutoff (= now - window) lands after the buffered rows.
_AFTER_WINDOW = timedelta(minutes=61)


@pytest.fixture
def captured(monkeypatch):
    """Record (to, subject, html) for every flushed email."""
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        email_send, "send", lambda to, subject, html, text=None: calls.append((to, subject, html))
    )
    return calls


def _sub(email, **prefs):
    blob = {"email": email, **_DEFAULT, **prefs}
    with _sync.durable_transaction():
        repo_subs.upsert(email=email, hf_user_id=None, prefs=blob, new_token=f"tok-{email}")


def _flush_after_window():
    email_digest.flush_due(now=_serde.now() + _AFTER_WINDOW)


def test_buffered_event_not_sent_before_window(captured):
    _sub("a@x.com", recitation_published="all")
    email_emit.emit_recitation_published(
        reciter_id="r1", reciter_name="Reciter One", riwayah=None, is_first_in_riwayah=False
    )
    email_digest.flush_due(now=_serde.now())  # default 60-min window not elapsed
    assert captured == []


def test_single_reciter_flushes_with_singular_template(captured):
    _sub("a@x.com", recitation_published="all")
    email_emit.emit_recitation_published(
        reciter_id="r1", reciter_name="Reciter One", riwayah=None, is_first_in_riwayah=False
    )
    _flush_after_window()
    assert len(captured) == 1
    to, subject, _ = captured[0]
    assert to == "a@x.com"
    assert subject == "Now published: Reciter One"


def test_multiple_reciters_flush_as_one_digest(captured):
    _sub("a@x.com", recitation_published="all")
    for rid, name in [("r1", "Reciter One"), ("r2", "Reciter Two")]:
        email_emit.emit_recitation_published(
            reciter_id=rid, reciter_name=name, riwayah=None, is_first_in_riwayah=False
        )
    _flush_after_window()
    assert len(captured) == 1
    _, subject, html = captured[0]
    assert subject == "2 new recitations published"
    assert "Reciter One" in html and "Reciter Two" in html


def test_repeated_reciter_is_deduped(captured):
    _sub("a@x.com", recitation_published="all")
    for _ in range(2):
        email_emit.emit_recitation_published(
            reciter_id="r1", reciter_name="Reciter One", riwayah=None, is_first_in_riwayah=False
        )
    _flush_after_window()
    assert len(captured) == 1
    # Deduped to one reciter → singular wording, not "1 new recitations".
    assert captured[0][1] == "Now published: Reciter One"


def test_flush_deletes_the_buffer(captured):
    _sub("a@x.com", recitation_published="all")
    email_emit.emit_recitation_published(
        reciter_id="r1", reciter_name="Reciter One", riwayah=None, is_first_in_riwayah=False
    )
    _flush_after_window()
    far = _serde.now() + timedelta(days=1)
    assert repo_digest.due_groups(cutoff=far) == []


def test_timestamps_digest_uses_its_own_template(captured):
    _sub("a@x.com", timestamps_regenerated="all")
    for rid, name in [("r1", "Reciter One"), ("r2", "Reciter Two")]:
        email_emit.emit_timestamps_regenerated(reciter_id=rid, reciter_name=name)
    _flush_after_window()
    assert len(captured) == 1
    _, subject, html = captured[0]
    assert subject == "Timestamps updated for 2 reciters"
    assert "Reciter One" in html and "Reciter Two" in html


def test_two_events_flush_independently_not_merged(captured):
    # One address subscribed to both events → two separate digest emails (max 2),
    # never a single cross-event email.
    _sub("a@x.com", recitation_published="all", timestamps_regenerated="all")
    email_emit.emit_recitation_published(
        reciter_id="r1", reciter_name="Reciter One", riwayah=None, is_first_in_riwayah=False
    )
    email_emit.emit_timestamps_regenerated(reciter_id="r1", reciter_name="Reciter One")
    _flush_after_window()
    subjects = sorted(subj for _, subj, _ in captured)
    assert subjects == ["Now published: Reciter One", "Timestamps updated: Reciter One"]
