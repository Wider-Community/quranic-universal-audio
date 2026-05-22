"""Bucket-resident audio read primitives + cleanup.

Used by:
- ``audio_source.resolve`` — picks bucket vs CDN path for the audio proxy.
- ``routes/segments/peaks.py`` — slim-envelope peaks reader.
- ``audio_prefetch.sweep_due`` — post-release cleanup.

No background worker. No CDN downloads. Bucket audio is written by the
katana extraction pipeline (``.local/extraction/upload_to_bucket.py`` +
``.local/extraction/segments/audio_persist.py``); the inspector only reads
and (via the sweeper) deletes.

No Flask imports — callable from any thread.
"""

from __future__ import annotations

import logging

from . import audio_meta
from .peaks_slim import unpack_slim_envelope
from services.storage import storage_paths
from services.storage.hf_bucket import get_backend

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Read paths (used by the audio-proxy + peaks routes)
# ----------------------------------------------------------------------


def read_prefetched_audio_bytes(slug: str, url: str) -> bytes | None:
    """Return the chapter MP3 bytes for ``url`` if present in the bucket.

    Resolves URL → chapter key through the catalog sidecar. Returns ``None``
    when either the URL isn't in this delivery's sidecar or the chapter file
    isn't on the bucket — the caller then falls back to a CDN redirect.
    """
    chapter = audio_meta.chapter_for_url(slug, url)
    if chapter is None:
        return None
    path = storage_paths.prefetched_audio_path(slug, chapter)
    backend = get_backend()
    try:
        return backend.read_bytes(path)
    except Exception:  # noqa: BLE001
        return None


def read_prefetched_audio_local_path(slug: str, url: str):
    """Return a real local ``Path`` to the chapter file when the backend can
    expose one (deployed bucket mount or local-disk backend).

    Lets the audio-proxy hand ``send_file`` a path instead of a BytesIO —
    Werkzeug then handles Range/304 via OS sendfile and we avoid pulling the
    whole 4–5 MB MP3 into Flask memory on every surah switch. Returns
    ``None`` for local-dev no-mount (callers fall back to bytes or CDN).
    """
    chapter = audio_meta.chapter_for_url(slug, url)
    if chapter is None:
        return None
    path = storage_paths.prefetched_audio_path(slug, chapter)
    try:
        return get_backend().local_path(path)
    except Exception:  # noqa: BLE001
        return None


def read_prefetched_peaks(slug: str, url: str) -> dict | None:
    """Return the chapter-overview peaks for ``url`` in the slim int8 envelope.

    Reads ``<wip|published>/<slug>/peaks/<chapter>.json.gz`` and returns the
    packed envelope verbatim: ``{schema_version:3, duration_ms, q:'int8',
    bps, n, peaks_b64}``. No dequant, no ``.tolist()`` — the FE-facing route
    sends this through unchanged and the browser inflates b64 → ``Int8Array``
    once on receive (see ``the inspector-audio skill``).

    Returns ``None`` for:
    - Unknown URL (not in the catalog manifest).
    - Missing file (extraction didn't bake peaks for that chapter, or backfill
      not yet run).
    - Pre-v3 file or corrupt blob — caller treats this as a cache miss and
      falls back to ``/segment-peaks`` per-card.

    Companion ``unpack_slim`` (returns dequantized float-list) exists in
    ``peaks_slim.py`` for the offline extraction history-JSONL writer.
    Runtime inspector code uses only this envelope reader.
    """
    chapter = audio_meta.chapter_for_url(slug, url)
    if chapter is None:
        return None
    path = storage_paths.prefetched_peaks_path(slug, chapter)
    backend = get_backend()
    try:
        blob = backend.read_bytes(path)
    except Exception:  # noqa: BLE001
        return None
    return unpack_slim_envelope(blob)


def clear_prefetch(slug: str) -> None:
    """Delete every artifact under ``wip/<slug>/audio/`` and ``wip/<slug>/peaks/``.

    Called by the post-RELEASED sweeper. The ``_done.json`` sentinel is
    deleted separately by the sweeper itself so it can survive a partial
    failure here.
    """
    backend = get_backend()
    for d in (storage_paths.prefetched_audio_dir(slug), storage_paths.prefetched_peaks_dir(slug)):
        try:
            backend.delete(d)
        except Exception as e:  # noqa: BLE001
            logger.warning("clear_prefetch: failed deleting %s: %s", d, e)
