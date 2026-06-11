"""Announcement wire shapes (admin compose + public read).

Backs the global-announcements feature: an owner composes one announcement that
shows in every user's "My Notifications" rail (signed-in or anonymous) until
revoked. Served by ``inspector/routes/announcements.py`` (public read) and
``inspector/routes/admin/announcements.py`` (owner compose / revoke / list).

- ``AnnouncementCreate`` — the POST body (request; tolerant of a missing body).
- ``Announcement`` — the public read shape (``GET /api/announcements``); the
  minimal fields the rail renders. No author/provenance.
- ``AnnouncementAdmin`` — the management shape (``GET /api/admin/announcements``
  + the create ack), adding author + revoked_at. Mirrors the
  ``repo_announcements`` row dict exactly.

Request model is ``extra="forbid"`` (reject unknown input keys); response models
own their producer so they are ``extra="forbid"`` too.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AnnouncementCreate(BaseModel):
    """POST body for composing an announcement."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=2000)


class Announcement(BaseModel):
    """Public read shape — the fields the notifications rail renders."""

    model_config = ConfigDict(extra="forbid")

    id: int
    title: str
    body: str | None = None
    created_at: str


class AnnouncementAdmin(BaseModel):
    """Management shape — public fields plus author + revoked_at provenance.

    Mirrors ``repo_announcements._row_to_dict`` exactly so the admin routes can
    ``model_validate`` a row dict directly.
    """

    model_config = ConfigDict(extra="forbid")

    id: int
    title: str
    body: str | None = None
    author_login: str | None = None
    created_at: str
    revoked_at: str | None = None
