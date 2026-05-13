"""Single audio-source resolver for a (reciter, chapter URL) pair.

Every consumer that needs audio bytes — the audio-proxy route, peaks decode,
auto_split slicing — goes through here. The resolver answers: "where do this
chapter's bytes live right now (bucket prefetch, disk cache, or only at the
CDN)?" and "is this chapter VBR?", reading both signals from the per-slug
audio_manifest sidecar in the bucket (single source of truth).

No Flask. No I/O beyond what ``audio_fetch`` and ``cache`` already do.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from services import audio_fetch, audio_meta, cache


@dataclass(frozen=True)
class AudioSource:
    """Resolved location + metadata for one chapter URL.

    Exactly one of ``data`` / ``path`` is populated when the chapter is on
    the bucket or on local disk; both are ``None`` for CDN-only chapters.
    Callers prefer ``data`` (bucket bytes — already in memory after the read)
    over ``path`` (disk, ffmpeg can mmap), and fall back to ``cdn_url`` only
    when ffmpeg can be given a network handle (it cannot, in the stripped
    inspector image — see ``Dockerfile`` ``--disable-network``).
    """

    cdn_url: str
    data: Optional[bytes]
    path: Optional[Path]
    vbr: bool
    bitrate_kbps: Optional[int]
    chapter_key: Optional[str]

    @property
    def has_local_bytes(self) -> bool:
        """True when ffmpeg can read the audio without network (bucket or disk)."""
        return self.data is not None or self.path is not None


def resolve(reciter: str, url: str) -> AudioSource:
    """Return the best available source for ``url`` under ``reciter``.

    Priority: bucket prefetched bytes → disk-cached file → CDN URL.
    """
    chapter_key = audio_meta.chapter_for_url(reciter, url)
    meta = audio_meta.chapter_meta_for_url(reciter, url)
    vbr = bool(meta and (meta.get("bitrate_mode") or "").lower() == "vbr")
    bitrate_kbps = meta.get("bitrate_kbps") if isinstance(meta, dict) else None

    # Prefer a real local path so callers can stream via send_file/sendfile
    # (Range, ETag, 304). The bytes fallback is only for local-dev when no
    # mount or disk shadow is available.
    local = audio_fetch.read_prefetched_audio_local_path(reciter, url)
    if local is not None:
        return AudioSource(
            cdn_url=url, data=None, path=local,
            vbr=vbr, bitrate_kbps=bitrate_kbps, chapter_key=chapter_key,
        )

    disk = cache.audio_cache_path(reciter, url)
    if disk.exists():
        return AudioSource(
            cdn_url=url, data=None, path=disk,
            vbr=vbr, bitrate_kbps=bitrate_kbps, chapter_key=chapter_key,
        )

    data = audio_fetch.read_prefetched_audio_bytes(reciter, url)
    if data is not None:
        return AudioSource(
            cdn_url=url, data=data, path=None,
            vbr=vbr, bitrate_kbps=bitrate_kbps, chapter_key=chapter_key,
        )

    return AudioSource(
        cdn_url=url, data=None, path=None,
        vbr=vbr, bitrate_kbps=bitrate_kbps, chapter_key=chapter_key,
    )


def resolve_chapter_peaks(reciter: str, url: str) -> dict | None:
    """Return the prefetched chapter peaks JSON for ``url`` if present.

    Thin pass-through to ``audio_fetch.read_prefetched_peaks`` — kept here so
    callers depend on one module for all audio-resolution questions.
    """
    return audio_fetch.read_prefetched_peaks(reciter, url)
