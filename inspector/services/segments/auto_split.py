"""Auto-split: look up precomputed cursor positions for a segment.

The actual MFA alignment that produces the cursor positions happens
**offline**, via ``scripts/lib/auto_split_precompute.py``, after segment
extraction. The result is persisted to ``<reciter>/auto_split_v1.json``
keyed by ``segment_uid``. At runtime the Inspector reads that sidecar via
``services.data_loader.load_auto_split`` and serves it in ~10 ms instead of
making a 5–15 s round trip to the MFA Space.

Returns the same shape the frontend has been consuming since the N-cursor
extension::

    {"cursors": list[int] | None,        # absolute ms cuts (N-1 entries)
     "refs":    list[str] | None,        # N per-section refs
     "kind":    "cross_verse" | "repetition" | None,
     "source":  "sidecar" | "miss"}

When the sidecar has no entry for ``segment_uid`` (offline alignment
failed, or this is a post-edit descendant the offline pass never saw) the
response is the ``"miss"`` envelope with all-null payload. The frontend
flips the row's button label from *Auto Split* back to plain *Split* and
falls back to manual single-cursor placement — same UX as a non-candidate
seg has always had.
"""
from __future__ import annotations

import logging
from typing import Optional

from services.storage.data_loader import load_auto_split
from utils.references import chapter_from_ref
from services.storage.data_loader import load_detailed

logger = logging.getLogger(__name__)


def _find_segment_kind(reciter: str, chapter: int,
                       segment_uid: str) -> Optional[str]:
    """Return ``"cross_verse"`` / ``"repetition"`` / ``None``.

    Used only by the response's ``kind`` field when the sidecar reports a
    miss — so we can tell the frontend whether the row was an auto-split
    candidate at all. (Sidecar hits already carry ``kind`` from the offline
    pre-compute, so this lookup is the cold path.)
    """
    for entry in load_detailed(reciter):
        if chapter_from_ref(entry.get("ref", "")) != chapter:
            continue
        for seg in entry.get("segments", []):
            if seg.get("segment_uid") != segment_uid:
                continue
            wrap = seg.get("wrap_word_ranges") or None
            if wrap:
                return "repetition"
            mref = seg.get("matched_ref", "") or ""
            parts = mref.split("-")
            if len(parts) == 2:
                s, e = parts[0].split(":"), parts[1].split(":")
                if len(s) >= 2 and len(e) >= 2 and s[1] != e[1]:
                    return "cross_verse"
            return None
    return None


def compute_auto_split(reciter: str, chapter: int, segment_uid: str) -> dict:
    """Resolve the precomputed Auto Split cursors for a single segment.

    Returns the response envelope described in the module docstring. Reads
    are O(1) against the per-reciter in-memory ``load_auto_split`` cache.
    No MFA, no audio fetch, no ffmpeg — those moved offline.
    """
    by_uid, _meta = load_auto_split(reciter)
    hit = by_uid.get(segment_uid)
    if hit is not None:
        cursors = hit.get("cursors") or None
        refs = hit.get("refs") or None
        kind = hit.get("kind") or None
        # Sanity: a sidecar entry without cursors / refs is meaningless;
        # treat it as a miss rather than ship a half-shape to the FE.
        if cursors and refs and kind:
            return {"cursors": list(cursors), "refs": list(refs),
                    "kind": kind, "source": "sidecar"}

    # Sidecar miss: tell the FE this row has no precomputed cursors. The
    # button falls back to a plain Split. ``kind`` is still useful so the
    # FE can colour-code or telemetry-tag the miss.
    return {"cursors": None, "refs": None,
            "kind": _find_segment_kind(reciter, chapter, segment_uid),
            "source": "miss"}


def load_auto_split_map(reciter: str) -> dict[str, dict]:
    """Return the whole precomputed Auto Split map for *reciter*, filtered.

    The bulk sibling of :func:`compute_auto_split`: instead of one ``uid`` per
    request it returns ``{segment_uid: {"cursors": [...], "refs": [...],
    "kind": ...}}`` for *every* sidecar hit. The FE preloads this once (on
    accordion open) so each Auto Split click is a zero-network O(1) map lookup
    instead of a round trip, and can classify misses ("uid not in map")
    client-side without the O(n) ``_find_segment_kind`` scan.

    Applies the same validity gate ``compute_auto_split`` uses per-uid — an
    entry missing any of ``cursors`` / ``refs`` / ``kind`` is dropped rather
    than shipped half-shaped. Reads the O(1) in-memory ``load_auto_split``
    cache (one bucket read per reciter per process).
    """
    by_uid, _meta = load_auto_split(reciter)
    out: dict[str, dict] = {}
    for uid, hit in by_uid.items():
        if not isinstance(hit, dict):
            continue
        cursors = hit.get("cursors") or None
        refs = hit.get("refs") or None
        kind = hit.get("kind") or None
        if cursors and refs and kind:
            out[uid] = {"cursors": list(cursors), "refs": list(refs),
                        "kind": kind}
    return out
