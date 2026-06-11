"""Global announcements — owner-composed broadcasts for the notifications rail.

An owner sends a single announcement (title + optional body); it shows in every
user's Dashboard "My Notifications" rail — including signed-out visitors — until
an owner revokes it. There is no per-user fan-out (the public read route serves
the one global row) and no server-side dismiss state (the browser tracks
dismiss/seen in localStorage).

Flask-free. Writes open their own ``durable_transaction`` (mirrors
``services/notifications/emit.py::notify_flag_reply``); reads go straight to the
repo. The route layer validates request shape via the wire models and gates on
the ``announcements.send`` capability.
"""

from __future__ import annotations

from qua_shared.schemas import Actor
from services.db import repo_announcements
from services.db import sync as _sync

#: Caps mirrored by the wire models / FE inputs; enforced here as a backstop.
TITLE_MAX = 200
BODY_MAX = 2000


class AnnouncementError(ValueError):
    """Invalid announcement input (empty title, over-length)."""


def send(*, title: str, body: str | None, actor: Actor) -> dict:
    """Compose and store one announcement. Returns the stored row dict."""
    title = (title or "").strip()
    body = (body or "").strip() or None
    if not title:
        raise AnnouncementError("title is required")
    if len(title) > TITLE_MAX:
        raise AnnouncementError(f"title must be at most {TITLE_MAX} characters")
    if body and len(body) > BODY_MAX:
        raise AnnouncementError(f"body must be at most {BODY_MAX} characters")

    with _sync.durable_transaction():
        new_id = repo_announcements.create(
            title=title,
            body=body,
            author_hf_user_id=actor.hf_user_id,
            author_login=actor.login_at_time,
        )
    return _by_id(new_id)


def revoke(announcement_id: int, *, actor: Actor) -> bool:
    """Revoke one active announcement (hides it from every rail). Returns False
    if the id is unknown or already revoked."""
    with _sync.durable_transaction():
        return repo_announcements.revoke(announcement_id)


def list_active() -> list[dict]:
    """Active announcements for the public rail (newest-first)."""
    return repo_announcements.list_active()


def list_all() -> list[dict]:
    """Active + revoked announcements for the admin management list."""
    return repo_announcements.list_all()


def _by_id(announcement_id: int) -> dict:
    for row in repo_announcements.list_all():
        if row["id"] == announcement_id:
            return row
    raise AnnouncementError(f"announcement {announcement_id} not found after insert")
