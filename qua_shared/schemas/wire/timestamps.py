"""Timestamps-tab HTTP wire schemas (``/api/ts/*`` + the verse payload the
FE assembles from a shard).

Models the shape the ``/api/ts/*`` routes **actually emit** (the producer is
the source of truth).

What is modelled here, by source route/service:

- ``GET /api/ts/config`` → :class:`TsConfigResponse`. Built by
  ``routes/timestamps/timestamps.py::ts_config``. The route always emits
  ``catalog_url`` and does NOT emit a ``mode`` field.
- ``GET /api/ts/manifest`` (decompressed) → :class:`TsManifestResponse` +
  :class:`TsManifestReciter`. Built by ``services/reference/timestamps.py``.
  The route never emits a build-internal ``_build`` block (see the model
  docstring).
- ``GET /api/static/catalog.json`` → the Timestamps tab reads it as the slim
  projection :class:`TsCatalogResponse` (+ :class:`TsCatalogReciter` /
  :class:`TsCatalogDelivery`). The route actually serves the FULL
  ``ReciterCatalog`` dump, so these projection models use ``extra="ignore"``
  (NOT ``forbid``) — they describe the subset the FE consumes, not the whole
  wire body. See the class docstrings.
- ``GET /api/ts/vbr/<reciter>`` → :class:`TsVbrResponse`. Built inline by
  ``ts_vbr``.
- the per-chapter shard (``GET /api/ts/shard/<reciter>/<chapter>``,
  decompressed) reuses :class:`~qua_shared.schemas.bucket.ts_shard.TsShardDoc`
  / ``TsShardSegment`` / ``TsShardWord`` — imported, never redefined.
- the verse payload the FE ``ts_client`` assembles from a shard (the legacy
  ``/api/ts/data`` shape, no live route today) → :class:`TsVerseData` +
  :class:`TsWord` / :class:`Letter` / :class:`PhonemeInterval`.
- ``TsRecitersResponse`` = ``list[TsReciter]`` (deprecated reciter list).

FE-facing: re-exported from ``fe_types.py`` and code-generated into
``inspector/frontend/src/lib/types/generated/schemas.ts``.

json2ts caveat (the typed-tuple limitation): ``TsShardWord`` and the ``t``
spans here are positional tuples. Pydantic v2 emits JSON-Schema-2020-12
``prefixItems`` for them (correctly typed), but the pinned json2ts (15.0.4)
only understands the Draft-07 ``items: [...]`` tuple form and renders
``prefixItems`` as ``[unknown, ...]``. The models below are correct; the FE
narrows them with positional projections in ``ts-client.ts``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..bucket.catalog import AudioCategory
from ..bucket.ts_shard import TsShardDoc, TsShardSegment, TsShardWord

__all__ = [
    "TsConfigResponse",
    "TsManifestReciter",
    "TsManifestResponse",
    "TsCatalogReciter",
    "TsCatalogDelivery",
    "TsCatalogResponse",
    "TsVbrResponse",
    "TsReciter",
    "TsRecitersResponse",
    "Letter",
    "PhonemeInterval",
    "TsWord",
    "TsVerseData",
    # Re-exported shard shapes (single source of truth — imported, not redefined).
    "TsShardDoc",
    "TsShardSegment",
    "TsShardWord",
]


# ---------------------------------------------------------------------------
# GET /api/ts/config
# ---------------------------------------------------------------------------


class TsConfigResponse(BaseModel):
    """``GET /api/ts/config`` — display constants + read-path URLs.

    Built by ``routes/timestamps/timestamps.py::ts_config`` from ``config.py``
    tunables. Pure constants; the route caches it for 5 min.

    The route always emits ``catalog_url`` (``"/api/static/catalog.json"``) and
    does NOT emit a ``mode`` field. ``anim_word_spacing`` / ``anim_font_size`` /
    ``analysis_word_font_size`` / ``analysis_letter_font_size`` are **CSS
    strings** (``"0.2em"`` / ``"44px"`` / ``"1.5rem"`` / ``"1.75rem"`` — they go
    straight into a ``style``), not numbers. The genuinely-numeric tunables
    (``anim_word_transition_duration`` / ``anim_char_transition_duration`` /
    ``anim_line_height`` / ``unified_display_max_height``) stay numbers.
    """

    model_config = ConfigDict(extra="forbid")

    manifest_url: str
    shard_url_template: str
    catalog_url: str
    unified_display_max_height: int
    anim_highlight_color: str
    anim_word_transition_duration: float
    anim_char_transition_duration: float
    anim_transition_easing: str
    #: CSS length string (``"0.2em"``) — NOT a number.
    anim_word_spacing: str
    anim_line_height: float
    #: CSS length string (``"44px"``) — NOT a number.
    anim_font_size: str
    #: CSS length string (``"1.5rem"``) — NOT a number.
    analysis_word_font_size: str
    #: CSS length string (``"1.75rem"``) — NOT a number.
    analysis_letter_font_size: str


# ---------------------------------------------------------------------------
# GET /api/ts/manifest  (gzipped on the wire; this is the decompressed body)
# ---------------------------------------------------------------------------


class TsManifestReciter(BaseModel):
    """One reciter block inside the decompressed ``manifest`` body.

    Composed by ``services/reference/timestamps.py::_bucket_reciter_block``.
    Per-chapter audio URLs are deliberately NOT here — the FE resolves them
    from ``/api/audio/surahs`` (the audio-manifest sidecar).

    The route never emits a build-internal ``_build`` block on this read path.
    ``name_ar`` is emitted as ``null`` when the catalog has no Arabic name,
    ``source`` is emitted as ``""`` when unknown.
    """

    model_config = ConfigDict(extra="forbid")

    name_en: str
    name_ar: str | None = None
    riwayah: str
    style: str
    source: str
    #: Short form ``by_surah`` / ``by_ayah`` (NOT ``*_audio``).
    audio_category: AudioCategory
    ts_chapters: list[int] = Field(default_factory=list)
    vbr_chapters: list[int] = Field(default_factory=list)


class TsManifestResponse(BaseModel):
    """Decompressed body of ``GET /api/ts/manifest``.

    Built by ``_build_manifest_dict``. ``dataset_base_url`` is ``""`` in the
    Inspector (resources resolve as absolute Flask paths); ``commit`` is ``""``.
    ``resources`` maps a purpose key (``qpc_hafs`` / ``digital_khatt`` / …) to
    a ``/api/ts/resource/<key>`` URL. ``reciters`` is keyed by delivery slug.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: int
    generated_at: str
    commit: str = ""
    dataset_base_url: str
    shard_url_template: str
    resources: dict[str, str] = Field(default_factory=dict)
    reciters: dict[str, TsManifestReciter] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# GET /api/static/catalog.json  (the Timestamps-tab slim projection)
# ---------------------------------------------------------------------------
#
# The route serves the FULL ``ReciterCatalog`` dump (``model_dump(by_alias)``),
# carrying ``generated_at`` / ``vocab`` / ``aliases`` / ``derived`` and many
# more delivery fields. The Timestamps tab reads only the slim subset modelled
# below — so these projection models use ``extra="ignore"`` (the FE-read
# contract), NOT ``extra="forbid"`` (which would reject the real wire body).


class TsCatalogReciter(BaseModel):
    """Reciter entry as the Timestamps tab reads it from ``catalog.json``.

    Slim projection of ``ReciterEntry`` (extra catalog fields ignored).
    """

    model_config = ConfigDict(extra="ignore")

    reciter_id: str
    name_en: str
    name_ar: str | None = None
    country: str | None = None
    notes: str | None = None


class TsCatalogDelivery(BaseModel):
    """Delivery entry as the Timestamps tab reads it from ``catalog.json``.

    Slim projection of ``Delivery`` (extra catalog fields ignored). ``slug``
    uniquely identifies a delivery (the legacy manifest's "reciter slug").
    """

    model_config = ConfigDict(extra="ignore")

    slug: str
    reciter_id: str
    riwayah: str
    style: str
    source: str
    audio_category: AudioCategory


class TsCatalogResponse(BaseModel):
    """``GET /api/static/catalog.json`` as the Timestamps tab consumes it.

    The route emits the whole ``ReciterCatalog``; this models the slim subset
    the FE reads (``schema_version`` + ``reciters[]`` + ``deliveries[]``), so it
    uses ``extra="ignore"`` to tolerate the rest of the real wire body.
    """

    model_config = ConfigDict(extra="ignore")

    schema_version: int
    reciters: list[TsCatalogReciter] = Field(default_factory=list)
    deliveries: list[TsCatalogDelivery] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# GET /api/ts/vbr/<reciter>
# ---------------------------------------------------------------------------


class TsVbrResponse(BaseModel):
    """``GET /api/ts/vbr/<reciter>`` — VBR-chapter fallback for older HF manifests.

    Built inline by ``ts_vbr`` as ``{"vbr_chapters": [...]}``. The route never
    populates ``error`` on this path (it is a 200-only endpoint); the field
    stays optional for parity with the generic error envelope.
    """

    model_config = ConfigDict(extra="forbid")

    vbr_chapters: list[int] = Field(default_factory=list)
    error: str | None = None


# ---------------------------------------------------------------------------
# Reciter list (deprecated) — list[TsReciter]
# ---------------------------------------------------------------------------


class TsReciter(BaseModel):
    """One reciter in the (deprecated) ``TsRecitersResponse`` list.

    Mirrors ``TsReciter`` in ``ts-client.ts``. The reciter list is read from
    the manifest / catalog; this remains for the legacy list endpoint shape.
    """

    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    audio_source: str | None = None
    audio_reciter: str | None = None
    has_data: bool | None = None


#: ``list[TsReciter]`` — the legacy ``/api/ts/reciters`` body. A bare list has
#: no wrapping model; consumers validate with ``TypeAdapter(TsRecitersResponse)``.
TsRecitersResponse = list[TsReciter]


# ---------------------------------------------------------------------------
# Verse payload (legacy /api/ts/data shape; FE assembles it from a shard today)
# ---------------------------------------------------------------------------


class Letter(BaseModel):
    """One letter with optional per-letter timing (seconds). Mirrors ``Letter``
    in ``ts-client.ts``. ``start``/``end`` are ``null`` when the aligner couldn't
    place the letter."""

    model_config = ConfigDict(extra="forbid")

    char: str
    start: float | None = None
    end: float | None = None


class PhonemeInterval(BaseModel):
    """One phoneme interval in a verse's flat ``intervals`` list (seconds).

    Mirrors ``PhonemeInterval`` in ``ts-client.ts``. ``geminate_*`` mark the two
    halves of an MFA-split geminate; ``bridge`` carries a cross-word tajweed
    bridge rule (idgham) when this phone fuses with the previous word.
    """

    model_config = ConfigDict(extra="forbid")

    phone: str
    start: float
    end: float
    geminate_start: bool | None = None
    geminate_end: bool | None = None
    bridge: str | None = None


class TsWord(BaseModel):
    """One word with text + timing (seconds) + letters + phoneme indices.

    Mirrors ``TsWord`` in ``ts-client.ts``. ``start`` may be negative for
    ``by_surah`` mode after the chapter-offset subtraction. ``phoneme_indices``
    index into the verse's flat ``intervals`` list.
    """

    model_config = ConfigDict(extra="forbid")

    location: str
    text: str
    display_text: str
    start: float
    end: float
    phoneme_indices: list[int] = Field(default_factory=list)
    letters: list[Letter] = Field(default_factory=list)


class TsVerseData(BaseModel):
    """Full verse payload for the Timestamps tab (legacy ``/api/ts/data`` shape).

    Mirrors ``TsVerseData`` in ``ts-client.ts``. Assembled client-side from a
    chapter shard (no live route). ``audio_category`` here is the ``*_audio``
    long form (drives URL-rewrite + offset handling), distinct from the
    shard/manifest short form.

    ``time_start_ms`` deliberately has NO ``ge=0`` bound: in ``by_surah`` mode
    the per-verse start is offset relative to the chapter audio and can be
    negative. ``time_end_ms`` is likewise unbounded for symmetry.
    """

    model_config = ConfigDict(extra="forbid")

    reciter: str
    chapter: int
    verse_ref: str
    audio_url: str
    audio_category: Literal["by_ayah_audio", "by_surah_audio"]
    #: NOT ``ge=0`` — negative in by_surah mode (chapter-offset relative).
    time_start_ms: int
    time_end_ms: int
    intervals: list[PhonemeInterval] = Field(default_factory=list)
    words: list[TsWord] = Field(default_factory=list)
