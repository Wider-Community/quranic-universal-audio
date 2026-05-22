"""Submit-recitation **intake** request schemas (new-combo / new-reciter).

The existing per-delivery request flow (``pending_requests.py``) is *slug-based*:
it edits an already-catalogued delivery. The Submit-recitation wizard adds two
**slugless** intake types that contribute audio not yet in the catalog:

- ``existing_reciter_new_combo`` — reciter exists, the (riwayah, style) combo does not.
- ``new_reciter`` — neither reciter nor delivery exists.

Both carry an audio **source** (direct per-chapter links, or a single playlist
URL — a dropped CSV/JSON file is normalised into ``links`` client-side). They
land in the unified ``requests`` table with ``slug = NULL`` and everything below
parked in the row's ``payload`` JSON. On owner **accept** the catalog entry is
minted and ``requests.slug`` is back-filled with the new delivery slug.

Wire-only models (request bodies + probe response). ``ConfigDict(extra="allow")``
per the schema convention; FE-facing subset re-exported from ``fe_types.py``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .pending_requests import ProposedEdits

IntakeKind = Literal["existing_reciter_new_combo", "new_reciter"]
SourceMethod = Literal["links", "playlist"]


class SourceLink(BaseModel):
    """One per-chapter direct audio URL."""

    model_config = ConfigDict(extra="allow")

    chapter: int = Field(ge=1, le=114)
    url: str


class IntakeSource(BaseModel):
    """Normalised audio source. Typed links and dropped CSV/JSON files both feed
    ``links``; ``playlist`` carries a single URL we enumerate offline (yt-dlp)."""

    model_config = ConfigDict(extra="allow")

    method: SourceMethod
    links: list[SourceLink] = Field(default_factory=list)
    playlist_url: str | None = None


class IntakeAttestations(BaseModel):
    """Contributor confirmations recorded with the submission (audit trail).

    All three must be true to submit — gated client-side and re-checked server-
    side. Rights to *share* (distribution / reciter permission) and rights to
    *store* (QUA download + permanent retention) are deliberately separate."""

    model_config = ConfigDict(extra="allow")

    distribution_rights: bool = False
    links_verified: bool = False
    storage_rights: bool = False

    def all_true(self) -> bool:
        return self.distribution_rights and self.links_verified and self.storage_rights


class IntakeSubmission(BaseModel):
    """Body of ``POST /api/requests/intake``.

    ``proposed_edits`` reuses :class:`ProposedEdits` — its fields already are the
    combination (riwayah/style/recording_context/recording_year) plus, for
    ``new_reciter``, identity (name_en/name_ar/country)."""

    model_config = ConfigDict(extra="allow")

    kind: IntakeKind
    reciter_id: str | None = None  # required for existing_reciter_new_combo
    proposed_edits: ProposedEdits = Field(default_factory=ProposedEdits)
    source: IntakeSource
    comments: str | None = Field(default=None, max_length=1000)
    auto_claim: bool = False
    attestations: IntakeAttestations = Field(default_factory=IntakeAttestations)


class IntakeValidation(BaseModel):
    """Structural validation outcome (submit-time). ``errors`` block submission;
    ``warnings`` (missing chapters, duplicates, unrecognised playlist host,
    likely-duplicate request) are advisory — the admin adjudicates."""

    model_config = ConfigDict(extra="allow")

    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProbeResult(BaseModel):
    """Reachability of one URL. ``status`` is the HTTP status (``None`` when the
    connection itself failed); ``reachable`` is the rolled-up verdict."""

    model_config = ConfigDict(extra="allow")

    chapter: int | None = None
    url: str
    status: int | None = None
    reachable: bool = False


class ProbeResponse(BaseModel):
    """Body of ``POST /api/admin/requests/<id>/probe``. Also cached onto the
    request row's ``payload.probe`` so the panel shows the last result."""

    model_config = ConfigDict(extra="allow")

    at: str  # ISO-8601 UTC
    results: list[ProbeResult] = Field(default_factory=list)
