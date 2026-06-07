"""GitHub release artifact and Releases-tab wire schemas.

These models cover two surfaces:

- public GitHub release assets produced by ``qua_jobs/cut_release.py``;
- admin Releases-tab payloads code-generated to the Inspector frontend.

Release files are consumer-facing, so artifact models use ``extra="forbid"``
where keys are fixed. Timestamp tier docs use dynamic verse keys and validate
those extra keys explicitly.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, model_validator

SCHEMA_VERSION = 1
VERSE_KEY_RE = re.compile(r"^[1-9]\d{0,2}:[1-9]\d{0,2}$")
LOCATION_KEY_RE = re.compile(r"^[1-9]\d{0,2}:[1-9]\d{0,2}:[1-9]\d{0,2}$")

ChangeKind = Literal["added", "refresh", "unchanged"]
AudioCategory = Literal["by_surah", "by_ayah"]
TimestampTier = Literal["verse", "word", "letter"]


# ---------------------------------------------------------------------------
# Public release assets.
# ---------------------------------------------------------------------------


class FileDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sha256: str = Field(..., min_length=1)
    bytes: int = Field(..., ge=0)


class ReleaseManifestRecitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zip: str
    zip_url: str
    sha256: str
    bytes: int = Field(..., ge=0)
    coverage_ayahs: int = Field(..., ge=0)
    content_hash: str
    change_kind: ChangeKind
    ts_version: str


class ReleaseManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    release_version: str
    created_at: str
    previous_version: str | None = None
    recitation_count: int = Field(..., ge=0)
    static_refs: dict[str, FileDigest] = Field(default_factory=dict)
    recitations: dict[str, ReleaseManifestRecitation] = Field(default_factory=dict)
    license: str = "CC-BY-4.0"


class ReleaseCatalogAudio(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_urls: dict[str, str] = Field(default_factory=dict)
    sample_rate_hz: int | None = None
    channels: int | None = None
    bitrate_mode: str | None = None
    bitrate_kbps_nominal: int | None = None


class ReleaseCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    surahs: int = Field(..., ge=0)
    ayahs: int = Field(..., ge=0)


class ReleaseRecitationCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    slug: str
    reciter_id: str | None = None
    name_en: str | None = None
    name_ar: str | None = None
    riwayah: str | None = None
    style: str | None = None
    country: str | None = None
    channel: str | None = None
    audio_category: AudioCategory | str | None = None
    recording_context: str | None = None
    recording_year: int | None = None
    variant_label: str | None = None
    audio: ReleaseCatalogAudio = Field(default_factory=ReleaseCatalogAudio)
    coverage: ReleaseCoverage


class ReleaseCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    recitations: list[ReleaseRecitationCatalog] = Field(default_factory=list)


class RecitationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    release_version: str
    slug: str
    created_at: str
    files: dict[str, FileDigest] = Field(default_factory=dict)


class TimestampMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    slug: str
    audio_category: str | None = None
    verse_count: int = Field(..., ge=0)
    tier: TimestampTier
    layout: str


class _TimestampDoc(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    meta: TimestampMeta = Field(alias="_meta")

    @model_validator(mode="after")
    def _validate_verse_entries(self):
        extras = self.model_extra or {}
        for key, value in extras.items():
            if key.startswith("_"):
                continue
            if not VERSE_KEY_RE.match(key):
                raise ValueError(f"invalid verse key: {key!r}")
            self._validate_value(value)
        return self

    def _validate_value(self, value: Any) -> None:
        raise NotImplementedError


class VerseTimestampsDoc(_TimestampDoc):
    def _validate_value(self, value: Any) -> None:
        if not _is_ms_pair(value):
            raise ValueError("verse timestamp must be [start_ms, end_ms]")


class WordTimestampsDoc(_TimestampDoc):
    def _validate_value(self, value: Any) -> None:
        if not (
            isinstance(value, list)
            and len(value) == 2
            and _is_ms_pair(value[0])
            and isinstance(value[1], list)
            and all(_is_word(w) for w in value[1])
        ):
            raise ValueError("word timestamp must be [[start_ms,end_ms], words]")


class LetterTimestampsDoc(_TimestampDoc):
    def _validate_value(self, value: Any) -> None:
        if not (
            isinstance(value, list)
            and len(value) == 3
            and _is_ms_pair(value[0])
            and isinstance(value[1], list)
            and all(_is_word(w) for w in value[1])
            and isinstance(value[2], list)
            and all(_is_letter(letter) for letter in value[2])
        ):
            raise ValueError("letter timestamp must be [[start_ms,end_ms], words, letters]")


class QpcHafsWord(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int | None = None
    surah: str
    ayah: str
    word: str
    location: str
    text: str


class QpcHafsDoc(RootModel[dict[str, QpcHafsWord]]):
    @model_validator(mode="after")
    def _validate_locations(self):
        for key, word in self.root.items():
            if not LOCATION_KEY_RE.match(key):
                raise ValueError(f"invalid QPC location key: {key!r}")
            if word.location != key:
                raise ValueError(f"QPC location mismatch: {key!r} != {word.location!r}")
        return self


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_ms_pair(v: Any) -> bool:
    return isinstance(v, list) and len(v) == 2 and _is_int(v[0]) and _is_int(v[1])


def _is_word(v: Any) -> bool:
    return isinstance(v, list) and len(v) == 3 and _is_int(v[0]) and _is_int(v[1]) and _is_int(v[2])


def _is_letter(v: Any) -> bool:
    return (
        isinstance(v, list)
        and len(v) == 4
        and _is_int(v[0])
        and isinstance(v[1], str)
        and _is_int(v[2])
        and _is_int(v[3])
    )


# ---------------------------------------------------------------------------
# Admin Releases-tab wire payloads.
# ---------------------------------------------------------------------------


class AdminReleaseRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    version: str
    produced_at: str
    stale_since: str | None = None


class AdminGhReleaseMember(BaseModel):
    model_config = ConfigDict(extra="allow")

    change_kind: ChangeKind
    stale_since: str | None = None
    release_id: int | None = None
    ts_version: str | None = None


class AdminPublishError(BaseModel):
    """A reciter's failure in the most recent batch publish. Surfaced on the
    row so the FE can re-bucket it into "Failed to publish" until a retry
    supersedes it with a successful HF release."""

    model_config = ConfigDict(extra="allow")

    message: str
    job_id: str
    at: str | None = None


class AdminReleaseStatusRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    slug: str
    name_en: str | None = None
    name_ar: str | None = None
    state: str | None = None
    riwayah: str
    style: str
    channel: str
    ts: AdminReleaseRow | None
    hf: AdminReleaseRow | None
    gh: AdminGhReleaseMember | None
    publish_error: AdminPublishError | None = None


class AdminLatestGhRelease(BaseModel):
    model_config = ConfigDict(extra="allow")

    version: str
    produced_at: str
    external_uri: str | None = None


class AdminReleasesSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    version: str | None
    produced_at: str | None
    external_uri: str | None
    member_count: int
    total_bytes: int
    days_since_cut: int | None


class AdminInFlightJob(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: Literal["hf_publish", "hf_publish_batch", "cut_release", "timestamps"]
    slug: str | None
    job_id: str
    started_at: str | None
    url: str | None = None


class AdminLastBatch(BaseModel):
    """Summary of the most recent batch publish, for the dismissable banner."""

    model_config = ConfigDict(extra="allow")

    job_id: str
    at: str | None = None
    published_count: int
    failed_count: int


class AdminReleasesStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    latest_gh_release: AdminLatestGhRelease | None
    summary: AdminReleasesSummary | None
    in_flight: list[AdminInFlightJob]
    recitations: list[AdminReleaseStatusRow]
    last_batch: AdminLastBatch | None = None


class AdminReleasePreviewRow(BaseModel):
    model_config = ConfigDict(extra="allow")

    slug: str
    name_en: str | None = None
    name_ar: str | None = None
    riwayah: str
    style: str
    channel: str
    coverage_surahs: int | None = None
    change_kind: ChangeKind
    ts_version: str


class AdminReleasePreviewCounts(BaseModel):
    model_config = ConfigDict(extra="allow")

    added: int
    refresh: int
    unchanged: int


class AdminReleaseLinks(BaseModel):
    model_config = ConfigDict(extra="allow")

    repo: str
    hf_dataset: str


class AdminReleasePreviewResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    computed_version: str | None
    needs_manual_version: bool
    previous_version: str | None
    change_counts: AdminReleasePreviewCounts
    added: list[AdminReleasePreviewRow]
    refreshed: list[AdminReleasePreviewRow]
    release_date: str
    license: str
    links: AdminReleaseLinks
    changelog_preview_md: str
    expected_version_at_preview: str | None


class AdminCutReleaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str | None = None
    expected_version_at_preview: str | None = None


class AdminPublishBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slugs: list[str] = Field(..., min_length=1)


class AdminLaunchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    job_id: str
    url: str | None
