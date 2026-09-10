"""Coordinate provenance for a projected segment — ``source_ref`` + support.

The Segments editor works entirely in the delivery edition's coordinates and
knows nothing about Hafs, so the save payload never carries these fields. They
have to be derived, and re-derived on every edit that moves ``matched_ref``:
recognition and MFA only know Hafs, so ``source_ref`` is the span the timestamps
engine actually aligns against. A stale one times the wrong audio; an absent one
makes the engine refuse the delivery outright (see
``qua_timing_engine.timestamps.finalize.assert_projected_segments_are_sourced``),
which is right, but a reviewer correcting a mis-match should not cost the run.

Hafs is the identity projection: neither field is written there, so Hafs
segments keep the exact bytes they have always had.
"""

from __future__ import annotations

import logging

from qua_shared.projection_support import support_for
from qua_shared.riwayat import DEFAULT_SDK_RIWAYAH

log = logging.getLogger("inspector")

#: The provenance pair, written and cleared together.
_FIELDS = ("source_ref", "projection_support")


def stamp_projection(seg: dict, riwayah: str = DEFAULT_SDK_RIWAYAH) -> None:
    """Re-derive this segment's Hafs provenance from its current ``matched_ref``.

    A ref with no word coordinates — a transition token like ``Takbir``, or an
    empty ref on an unmatched segment — has nothing to project, and the engine
    skips those anyway, so it carries no provenance.
    """
    if riwayah == DEFAULT_SDK_RIWAYAH:
        for field in _FIELDS:
            seg.pop(field, None)
        return

    matched_ref = str(seg.get("matched_ref") or "")
    if ":" not in matched_ref:
        for field in _FIELDS:
            seg.pop(field, None)
        return

    from services.reference import editions

    projection = editions.projection(riwayah)
    try:
        reverse = projection.reverse_range(matched_ref)
    except Exception as exc:
        # Refuse rather than write a segment the engine would align as Hafs.
        # Bare ``Exception``: ``reverse_range`` signals a malformed ref with
        # ``InvalidQuranReferenceError`` and an out-of-edition one with a plain
        # ``KeyError``, and the two share no base class.
        raise editions.RefNotInEdition(
            f"{matched_ref!r} is not a word range in {riwayah}"
        ) from exc
    seg["source_ref"] = reverse.source_ref
    seg["projection_support"] = support_for(projection, reverse.source_ref)


__all__ = ["stamp_projection"]
