"""Read VBR detection results from data/.audio_meta.json.

The artifact is generated offline by scripts/probe_audio_meta.py and committed
to the repo. The file maps reciter slug -> {manifest_hash, by_chapter}, where
each by_chapter entry is present only when the chapter is VBR (missing key
implies CBR, the safe default).

The inspector reads this at chapter-load to decide whether to route segment
playback through the server clip endpoint (VBR) or keep the existing direct
<audio>.currentTime path (CBR). Loaded once and cached; reloaded automatically
when the file mtime changes.

No Flask imports — pure data access.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from config import AUDIO_META_PATH
from services import cache

logger = logging.getLogger(__name__)


def _load_doc() -> dict | None:
    """Return the parsed audio_meta document, refreshing the cache on mtime change."""
    try:
        st = AUDIO_META_PATH.stat()
    except FileNotFoundError:
        return None
    cached = cache.get_audio_meta_doc()
    if cached is not None and cached[0] == st.st_mtime_ns:
        return cached[1]
    try:
        with open(AUDIO_META_PATH, encoding="utf-8") as f:
            doc = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("audio_meta: failed to parse %s: %s", AUDIO_META_PATH, e)
        return None
    cache.set_audio_meta_doc(st.st_mtime_ns, doc)
    return doc


def is_vbr(reciter: str, chapter: int | str) -> bool:
    """Return True if the (reciter, chapter) pair is known VBR.

    Falls back to False (CBR / unknown) when the reciter section is missing,
    when the chapter is absent (default-CBR convention), or when the artifact
    is missing entirely. This is intentional — the existing <audio> path is the
    no-regression default; only confirmed-VBR chapters take the slower clip
    route.
    """
    doc = _load_doc()
    if not doc:
        return False
    section = doc.get(reciter)
    if not isinstance(section, dict):
        return False
    by_chapter = section.get("by_chapter") or {}
    entry = by_chapter.get(str(chapter))
    if not isinstance(entry, dict):
        return False
    return bool(entry.get("vbr"))


def chapter_meta(reciter: str, chapter: int | str) -> dict | None:
    """Return the per-chapter audio_meta entry, or None when missing."""
    doc = _load_doc()
    if not doc:
        return None
    section = doc.get(reciter)
    if not isinstance(section, dict):
        return None
    by_chapter = section.get("by_chapter") or {}
    entry = by_chapter.get(str(chapter))
    return entry if isinstance(entry, dict) else None


def is_vbr_for_url(reciter: str, url: str) -> bool:
    """Reverse-lookup VBR status from a URL alone.

    Used by callers that have a URL but not a chapter number (notably the
    peaks endpoint, where the request body is keyed by URL). Linear scan over
    the reciter's by_chapter dict — O(n) where n is the chapter count for the
    reciter (typically ≤ 114) and the document itself is in-memory cached.
    """
    doc = _load_doc()
    if not doc:
        return False
    section = doc.get(reciter)
    if not isinstance(section, dict):
        return False
    for entry in (section.get("by_chapter") or {}).values():
        if isinstance(entry, dict) and entry.get("url") == url:
            return bool(entry.get("vbr"))
    return False
