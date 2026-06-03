"""Reviewed playlist → chapter map — the YouTube / yt-dlp intake convention.

A playlist (YouTube, SoundCloud set, archive item, …) is mapped to the 114
chapters by an LLM-assisted review step in the segments-extraction skill: it
reads every entry's title via yt-dlp and matches it — by playlist index +
English/Arabic surah name — against ground-truth ``data/surah_info.json``,
surfacing anything ambiguous (entry count ≠ 114, unclear/duplicate naming,
unmatched extras) for human confirmation. The confirmed result is this map: an
explicit, audited ``chapter → media URL`` mapping the offline driver
(``ingest_intake.py --chapter-map``) consumes in place of positional
enumeration.

It reduces to ``IntakeSource.links`` for extraction (chapter + URL) while
preserving the matched title + confidence as provenance. ``ConfigDict(extra=
"allow")`` per the schema convention. Not FE-facing (offline/ops artefact), so
it is not re-exported from ``fe_types.py``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .intake_requests import normalize_url

#: How the chapter was assigned. ``exact``/``high`` come from title matching;
#: ``low`` flags an entry the reviewer should eyeball; ``manual`` is a
#: human-supplied mapping (no confident automatic match).
MatchConfidence = Literal["exact", "high", "low", "manual"]


class PlaylistChapterEntry(BaseModel):
    """One reviewed ``chapter → URL`` row. ``url`` is a per-entry media/page URL
    (e.g. a YouTube watch URL) — normalised to an absolute https URL."""

    model_config = ConfigDict(extra="allow")

    chapter: int = Field(ge=1, le=114)
    url: str
    title: str = ""              # the playlist entry title (provenance)
    matched_name: str = ""       # the surah name_en it was matched to (audit)
    confidence: MatchConfidence = "manual"

    @field_validator("url")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return normalize_url(v)


class PlaylistChapterMap(BaseModel):
    """The skill's reviewed map. ``entries`` reduce to ``IntakeSource.links``;
    ``playlist_url`` is the originating playlist (→ ``Delivery.source_url``)."""

    model_config = ConfigDict(extra="allow")

    playlist_url: str
    entries: list[PlaylistChapterEntry] = Field(default_factory=list)

    @field_validator("playlist_url")
    @classmethod
    def _normalize_playlist(cls, v: str) -> str:
        return normalize_url(v)
