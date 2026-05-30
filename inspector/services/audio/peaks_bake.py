"""Bake slim 10bps chapter peaks for a reciter — Flask-free, bucket-first.

Single source of truth for "ensure ``reciters/<slug>/peaks/<ch>.json.gz``
exists". Used by the one-shot backfill CLI (``inspector/scripts/
backfill_released_peaks.py``) and (going forward) the publish/job path.

Released reciters' ``audio/`` is swept post-release, so peaks are computed from
the per-chapter CDN URL in the audio_manifest sidecar via ffmpeg (the same
``ffmpeg -i URL`` path the bench proved decodes https directly) → ``pack_slim``
to the canonical 10bps int8 envelope → bucket write. Reuses the config-free,
parity-tested ``scripts/lib/peaks_compute`` so the bytes match the extractor.
"""
from __future__ import annotations

import logging

from scripts.lib.peaks_compute import compute_audio_peaks, pack_slim
from services.audio import audio_meta
from services.storage import storage_paths
from services.storage.data_dir import get_backend

log = logging.getLogger("peaks_bake")


def bake_chapter_peaks(slug: str, chapter: str | int, url: str,
                       *, overwrite: bool = False) -> str:
    """Ensure ``peaks/<chapter>.json.gz`` exists for one chapter.

    Returns ``"skip"`` (already present), ``"baked"`` (written), or
    ``"fail"`` (ffmpeg/decode error — caller continues).
    """
    backend = get_backend()
    path = storage_paths.prefetched_peaks_path(slug, chapter)
    if not overwrite and backend.exists(path):
        return "skip"
    hd = compute_audio_peaks(url)
    if not hd:
        return "fail"
    backend.write_bytes_atomic(path, pack_slim(hd))
    return "baked"


def bake_missing_peaks(slug: str, *, chapters=None, overwrite: bool = False) -> dict:
    """Bake every (missing) by_surah chapter's slim peaks for ``slug``.

    Iterates the audio_manifest sidecar (NOT swept) for chapter→URL. by_ayah
    deliveries key the sidecar by ``"<surah>:<ayah>"`` — those are NOT handled
    here (per-verse peaks would be needed); when the sidecar has no by_surah
    keys the result carries ``by_ayah=True`` so the caller can abort loudly
    instead of silently writing zero files.

    Serial (one ffmpeg full-chapter decode at a time). The CLI parallelises
    across chapters via ``bake_chapter_peaks``; this convenience form is for the
    publish-time missing-only backstop. Returns outcome counts.
    """
    urls = audio_meta.chapter_urls(slug)
    by_surah = {k: u for k, u in urls.items() if ":" not in k and u}
    if not by_surah:
        return {"by_ayah": True, "baked": 0, "skipped": 0, "failed": 0}
    want = {str(c) for c in chapters} if chapters else None
    out = {"by_ayah": False, "baked": 0, "skipped": 0, "failed": 0}
    for key, url in sorted(by_surah.items(), key=lambda kv: int(kv[0])):
        if want is not None and key not in want:
            continue
        try:
            r = bake_chapter_peaks(slug, key, url, overwrite=overwrite)
        except Exception as exc:  # noqa: BLE001
            log.warning("[%s] ch%s bake error: %s", slug, key, exc)
            r = "fail"
        out["baked" if r == "baked" else "skipped" if r == "skip" else "failed"] += 1
    return out
