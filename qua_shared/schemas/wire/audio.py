"""Audio-tab HTTP wire schemas (``/api/audio/*`` JSON responses).

The audio blueprint serves exactly one JSON-success shape — the rest of its
routes (segment-clip, audio-proxy) stream raw MP3 bytes on success and only
ever return JSON on failure (the canonical ``ErrorEnvelope`` in
``_envelopes.py``). So the only response modelled here is the per-delivery
chapter metadata map returned by ``GET /api/audio/surahs/<category>/<source>/<slug>``
(see ``inspector/routes/audio/metadata.py``).

Mirrors the hand-written FE types ``AudioSurahEntry`` / ``AudioSurahsResponse``
in ``inspector/frontend/src/lib/types/api.ts``; these models replace those
hand-mirrors in a later phase, so they track the shape the route actually
emits exactly:

- every entry always carries ``url`` and ``duration_ms`` (the latter is
  ``None`` when neither the manifest nor the slim-peaks header yields a length);
- ``via`` / ``origin_url`` are added only when Quran.Foundation routing fires
  (``_apply_qf_routing``): a successfully routed chapter gets ``via="qf_api"``
  with the original CDN link preserved as ``origin_url`` (and ``duration_ms``
  reset to ``None`` so the player reads the re-encode's real header), while a
  routing failure tags every chapter ``via="qf_fallback"`` and leaves the
  original link + duration untouched. Un-routed deliveries carry neither key.

Key serialization subtlety: ``duration_ms`` is a *required, nullable* field —
the route always emits the key (its value is ``None`` when no length is known
or when the chapter was QF-routed), whereas ``via``/``origin_url`` are wholly
*absent* on un-routed entries. A blanket ``exclude_none`` would wrongly drop
``duration_ms: null`` too, so the model carries a serializer that omits only
the two optional QF keys when unset and always keeps ``duration_ms``. Dump with
a plain ``model_dump(by_alias=True)`` (no ``exclude_none``) to reproduce the
exact on-the-wire keys.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_serializer

#: How a chapter URL was resolved. ``qf_api`` = served from the
#: Quran.Foundation Content API; ``qf_fallback`` = QF routing was attempted but
#: failed, so the entry keeps our own CDN link. Absent for un-routed deliveries.
AudioVia = Literal["qf_api", "qf_fallback"]


class AudioSurahEntry(BaseModel):
    """One chapter's playback metadata in the ``surahs`` map.

    ``duration_ms`` is ``None`` when no length is known (manifest carried none
    and slim-peaks fallback also missed) or when the chapter was QF-routed
    (``via="qf_api"``), which deliberately drops our manifest duration. ``via``
    and ``origin_url`` are present only on QF-routed/fallback entries.

    ``url`` and ``duration_ms`` are always serialized (matching the route, which
    always emits both keys); ``via``/``origin_url`` are dropped when ``None`` so
    un-routed entries dump to exactly ``{"url", "duration_ms"}``.
    """

    model_config = ConfigDict(extra="forbid")

    url: str
    duration_ms: int | None
    via: AudioVia | None = None
    origin_url: str | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler) -> dict[str, Any]:
        data = handler(self)
        # The two QF-routing keys are absent on un-routed entries; everything
        # else (including ``duration_ms: None``) is always present on the wire.
        for optional_key in ("via", "origin_url"):
            if data.get(optional_key) is None:
                data.pop(optional_key, None)
        return data


class AudioSurahsResponse(BaseModel):
    """``GET /api/audio/surahs/<category>/<source>/<slug>`` success body.

    ``surahs`` is keyed by chapter number as a string (the manifest sidecar's
    ``chapters`` keys pass through verbatim).
    """

    model_config = ConfigDict(extra="forbid")

    surahs: dict[str, AudioSurahEntry]
