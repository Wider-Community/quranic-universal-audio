"""Read VBR detection results from ``<bucket>/catalog/audio_meta.json``.

The artifact is generated offline by ``scripts/probe_audio_meta.py``. The file
maps reciter slug -> {manifest_hash, by_chapter}, where each by_chapter entry
is present only when the chapter is VBR (missing key implies CBR, the safe
default).

The inspector reads this at chapter-load to decide whether to route segment
playback through the server clip endpoint (VBR) or keep the existing direct
``<audio>.currentTime`` path (CBR).

v2: moved from the repo-tracked ``data/.audio_meta.json`` to the bucket. The
Phase 1 stub catalog promotion has NOT yet uploaded this file, so all
lookups return the CBR-default empty result. Phase 6 catalog promotion
populates it from the bulk probe output.

No Flask imports — pure data access.
"""
from __future__ import annotations

import logging

from services import cache
from services import storage_paths
from services.hf_bucket import StorageNotFound, get_backend

logger = logging.getLogger(__name__)


def _load_doc() -> dict | None:
    """Return the parsed audio_meta document from the bucket. Caches the result
    once at first call; ``services.catalog.hydrate()`` does not refresh this
    cache today (the file is rarely written; Inspector boot will drop the
    cache via container restart).
    """
    cached = cache.get_audio_meta_doc()
    if cached is not None:
        return cached[1]
    try:
        doc = get_backend().read_json(storage_paths.audio_meta_path())
        if not isinstance(doc, dict):
            return None
        # ``cache.set_audio_meta_doc(mtime_ns, doc)`` retained — mtime carrying
        # the cache key is irrelevant for the bucket case; pass 0 to satisfy
        # the existing signature.
        cache.set_audio_meta_doc(0, doc)
        return doc
    except StorageNotFound:
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("audio_meta: failed to read from bucket: %s", e)
        return None


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


def vbr_chapters_for_reciter(reciter: str) -> list[int]:
    """Return the sorted list of chapter numbers known VBR for ``reciter``.

    Used by the chapter-load endpoint to ship the per-reciter VBR map to the
    frontend so cross-chapter accordion prefetch can pick the right transport
    (clip URL vs chapter URL) without a per-chapter probe round-trip. Only the
    chapters present under ``by_chapter`` are returned — the artifact omits CBR
    chapters by construction, so set membership is the encoding signal.
    """
    doc = _load_doc()
    if not doc:
        return []
    section = doc.get(reciter)
    if not isinstance(section, dict):
        return []
    by_chapter = section.get("by_chapter") or {}
    out: list[int] = []
    for k, entry in by_chapter.items():
        if not isinstance(entry, dict) or not entry.get("vbr"):
            continue
        try:
            out.append(int(k))
        except (TypeError, ValueError):
            continue
    out.sort()
    return out


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


_SIDECAR_CACHE: dict[str, dict] = {}


def _load_sidecar(slug: str) -> dict | None:
    """Per-delivery audio manifest sidecar lookup, cached per-process.

    Distinct from ``_load_doc()`` (which reads the rolled-up VBR-summary
    artifact). The sidecar at ``catalog/audio_manifest/<slug>.json`` carries
    the full chapter → URL map needed by the prefetch worker + audio-proxy
    short-circuit.
    """
    cached = _SIDECAR_CACHE.get(slug)
    if cached is not None:
        return cached
    try:
        doc = get_backend().read_json(storage_paths.audio_manifest_path(slug))
    except StorageNotFound:
        return None
    except Exception as e:  # noqa: BLE001
        logger.warning("audio_meta: failed to read sidecar for %s: %s", slug, e)
        return None
    if not isinstance(doc, dict):
        return None
    _SIDECAR_CACHE[slug] = doc
    return doc


def chapter_for_url(reciter: str, url: str) -> str | None:
    """Reverse-lookup the chapter key for a URL — used by the audio-proxy
    short-circuit to find the prefetched MP3 path. Returns the raw sidecar
    key (``"1"``..``"114"`` for by_surah, ``"<surah>:<ayah>"`` for by_ayah)
    or None when the URL is unknown to this delivery.
    """
    doc = _load_sidecar(reciter)
    if not doc:
        return None
    for k, entry in (doc.get("chapters") or {}).items():
        if isinstance(entry, dict) and entry.get("url") == url:
            return k
    return None


def chapter_urls(reciter: str) -> dict[str, str]:
    """Full chapter-key → URL map for ``reciter``. Used by the prefetch
    queue to enumerate work. Empty dict when the sidecar is missing.
    """
    doc = _load_sidecar(reciter)
    if not doc:
        return {}
    out: dict[str, str] = {}
    for k, entry in (doc.get("chapters") or {}).items():
        if isinstance(entry, dict) and isinstance(entry.get("url"), str):
            out[k] = entry["url"]
    return out
