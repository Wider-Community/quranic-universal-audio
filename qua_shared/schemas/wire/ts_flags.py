"""Timestamps-tab verse-flag wire shapes.

Backs the public "Report" flow on the Timestamps tab: any visitor (incl.
anonymous) flags the verse currently playing on a published recitation and
leaves an optional comment describing the timestamps issue. Multiple users flag
the same verse, so a verse carries multiple globally-viewable comments.

Served by ``inspector/routes/timestamps/flags.py``:
- ``GET  /api/ts/<slug>/flags``              → ``TsReciterFlags`` (accordion pills + counts)
- ``GET  /api/ts/<slug>/flags/<verse_key>``  → ``TsVerseFlags`` (the modal's comment list)
- ``POST /api/ts/<slug>/flags``              ← ``TsFlagCreateRequest`` → ``TsFlagComment``
- ``DELETE /api/ts/<slug>/flags/<verse_key>``

``author`` on a comment is populated only when the caller holds
``timestamps.see_flagger_identity`` (owner-default); everyone else sees the
comment text but no author. ``mine`` marks the caller's own comment (matched by
``hf_user_id`` when signed in, else by the ``anon_token`` query param).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TsFlagAuthor(BaseModel):
    """Comment author identity — only disclosed to identity-capable callers."""

    model_config = ConfigDict(extra="forbid")

    hf_user_id: str | None = None
    login: str | None = None
    role: str | None = None


class TsFlagComment(BaseModel):
    """One user's comment on a flagged verse (modal list item / POST echo)."""

    model_config = ConfigDict(extra="forbid")

    comment: str | None = None
    created_at: datetime
    updated_at: datetime
    #: True when this is the caller's own comment (editable / deletable).
    mine: bool = False
    #: Author identity, present only when the caller can see flagger identity.
    author: TsFlagAuthor | None = None


class TsVerseFlags(BaseModel):
    """All comments on a single verse (``GET .../flags/<verse_key>``)."""

    model_config = ConfigDict(extra="forbid")

    verse_key: str
    comments: list[TsFlagComment] = Field(default_factory=list)


class TsFlagVerseCount(BaseModel):
    """A flagged verse + how many comments it carries (accordion pill)."""

    model_config = ConfigDict(extra="forbid")

    verse_key: str
    count: int


class TsReciterFlags(BaseModel):
    """Every flagged verse for a reciter (``GET .../flags``)."""

    model_config = ConfigDict(extra="forbid")

    flags: list[TsFlagVerseCount] = Field(default_factory=list)


class TsFlagCreateRequest(BaseModel):
    """Create/update the caller's flag on a verse (``POST .../flags``)."""

    model_config = ConfigDict(extra="forbid")

    verse_key: str
    comment: str | None = None
    #: Anonymous browser token (omitted/ignored when the caller is signed in).
    anon_token: str | None = None
