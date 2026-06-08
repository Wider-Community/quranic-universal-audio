"""Per-reciter bucket readiness probe — a non-blocking warn signal.

The timestamps job is alignment-only: chapter audio (``reciters/<slug>/audio/``)
and waveform peaks (``reciters/<slug>/peaks/``) are populated OFFLINE by katana
extraction, not by the Inspector. This module reports which by-surah chapters
are still missing either artifact so the Releases tab can show a quiet warn
pill. It NEVER blocks an action — a reciter can be generated/published with
audio or peaks still pending.

Cheap by design: the expected chapter set comes from the LRU-cached audio
manifest sidecar (``services/audio/audio_meta``), and presence is two bucket
``list_dir`` calls cached for ~60 s (audio/peaks land out-of-band, so this
can't piggyback on ``db_seq``). On the deployed Space the bucket is mounted →
``list_dir`` is a local ``iterdir`` (cheap); unmounted it falls back to a
network ``list_bucket_tree`` walk, which is why the call is TTL-cached.

Flask-free.
"""

from __future__ import annotations

import logging

from services.audio import audio_meta
from services.storage import cache
from services.storage.hf_bucket import StorageNotFound, get_backend

log = logging.getLogger(__name__)


def _present_stems(prefix: str, suffix: str) -> set[str]:
    """Chapter keys present under ``reciters/<slug>/<dir>`` with ``suffix``.

    Returns the basename with ``suffix`` stripped (e.g. ``audio/1.mp3`` → ``1``).
    A missing dir (or any listing error) is treated as empty — a warn probe must
    never raise into the status route.
    """
    try:
        names = get_backend().list_dir(prefix)
    except StorageNotFound:
        return set()
    except Exception as exc:  # noqa: BLE001 — never break the status route
        log.warning("readiness list_dir(%s) failed: %s", prefix, exc)
        return set()
    out: set[str] = set()
    for n in names:
        s = str(n)
        base = s.rsplit("/", 1)[-1]
        if base.endswith(suffix):
            out.add(base[: -len(suffix)])
    return out


def reciter_bucket_readiness(slug: str) -> dict | None:
    """Which by-surah chapters lack bucket audio / peaks for ``slug``.

    Returns ``{"audio_missing": int, "peaks_missing": int,
    "audio_missing_chapters": list[int], "peaks_missing_chapters": list[int]}``
    or ``None`` when the manifest lists no by-surah chapters (nothing to probe —
    e.g. a by-ayah-only delivery). TTL-cached per slug.

    Expected set = by-surah keys from the audio manifest (peaks + audio are
    by-surah artifacts; by-ayah keys carry a ``:`` and are skipped).
    """
    hit, cached = cache.get_reciter_readiness_cache(slug)
    if hit:
        return cached

    expected = {k for k in audio_meta._chapters(slug) if ":" not in str(k)}
    if not expected:
        cache.set_reciter_readiness_cache(slug, None)
        return None

    audio_present = _present_stems(f"reciters/{slug}/audio", ".mp3")
    peaks_present = _present_stems(f"reciters/{slug}/peaks", ".json.gz")

    def _missing(present: set[str]) -> list[int]:
        miss = expected - present
        out: list[int] = []
        for k in miss:
            try:
                out.append(int(str(k)))
            except (TypeError, ValueError):
                continue
        return sorted(out)

    audio_missing = _missing(audio_present)
    peaks_missing = _missing(peaks_present)
    result = {
        "audio_missing": len(audio_missing),
        "peaks_missing": len(peaks_missing),
        "audio_missing_chapters": audio_missing,
        "peaks_missing_chapters": peaks_missing,
    }
    cache.set_reciter_readiness_cache(slug, result)
    return result
