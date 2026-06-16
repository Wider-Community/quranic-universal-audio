"""Email-notification preference wire shapes.

Backs the "My notifications" envelope modal: a signed-in OR anonymous visitor
opts into no-reply emails for catalog + workflow events. Served by
``inspector/routes/auth/email_preferences.py`` (``GET/POST /api/me/email-preferences``).

Storage is keyed by the destination **email address**, so an anonymous visitor
can subscribe without an HF account; the row optionally carries the saver's
``hf_user_id`` when signed in (used to match the ``request_aligned`` event). The
emitter (``inspector/email``) fans the six events out to the matching addresses.

Scope semantics for the two reciter-scoped events:
- ``off``      — never email.
- ``all``      — email for every reciter.
- ``selected`` — email only for the reciters in the shared ``reciters`` list.

The two riwayah events are booleans gated by the shared ``riwayahs`` follow list.
``EmailPreferences`` mirrors the FE ``EmailPrefs`` interface verbatim; codegen
keeps the two in lockstep. ``EmailPreferencesSaved`` is the POST echo — the saved
prefs plus the ``manage_token`` the FE caches for the unsubscribe / re-manage flow.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EmailScope = Literal["off", "all", "selected"]


class EmailPreferences(BaseModel):
    """A subscriber's email-notification preferences (GET response / POST body)."""

    model_config = ConfigDict(extra="forbid")

    email: str = ""
    request_aligned: bool = False
    recitation_published: EmailScope = "off"
    timestamps_regenerated: EmailScope = "off"
    github_release: bool = False
    riwayah_new_recitation: bool = False
    riwayah_first_available: bool = False
    #: Shared reciter_ids powering every ``selected``-mode event.
    reciters: list[str] = Field(default_factory=list)
    #: Shared riwayah slugs powering both riwayah events.
    riwayahs: list[str] = Field(default_factory=list)


class EmailPreferencesSaved(EmailPreferences):
    """POST echo: the persisted prefs plus the stable manage/unsubscribe token.

    The FE caches ``manage_token`` so a returning anonymous visitor can re-fetch
    fresh server state by token, and so the modal stays consistent with an
    out-of-band unsubscribe.
    """

    manage_token: str
