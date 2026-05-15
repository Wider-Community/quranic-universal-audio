"""Per-chapter audio fetch + Xing-TOC remux + bucket persistence.

The prefetch worker (``services.audio_prefetch``) drives this module across a
thread pool. Each call:

1. HTTP-fetches the upstream chapter URL to a temp file.
2. For VBR chapters, runs ``ffmpeg -bsf:a mp3_to_xing`` so the browser's
   ``<audio>.currentTime`` seek lands on the correct frame — the inspector
   then serves the remuxed file directly with no clip-route involvement.
3. Uploads the (possibly remuxed) MP3 to ``wip/<slug>/audio/<chapter>.mp3``.
4. Computes waveform peaks from the local temp file and uploads the JSON to
   ``wip/<slug>/peaks/<chapter>.json``.

No Flask imports. The module is callable from any thread that holds neither
a per-slug nor the global write-lock; the bucket backend serializes its own
writes internally.
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass

from config import FFMPEG_FULL_TIMEOUT
from . import audio_meta
from .peaks import compute_audio_peaks
from services.storage import storage_paths
from services.storage.hf_bucket import get_backend

logger = logging.getLogger(__name__)

# Global ffmpeg gate. mp3_to_xing is CPU-bound; letting the prefetch fan-out
# spawn one ffmpeg per chapter pegs small Space CPU and starves the request
# path. Cap to a single concurrent remux process; downloads + uploads still
# parallelize via the prefetch thread pool.
_FFMPEG_SEM = threading.Semaphore(1)


@dataclass(frozen=True)
class ChapterArtifact:
    """Result of one chapter prefetch — feeds the audit payload."""

    chapter: str
    audio_path: str
    peaks_path: str | None
    bytes_written: int
    duration_ms: int | None
    ffmpeg_remuxed: bool


class ChapterFetchError(Exception):
    """Raised when a chapter cannot be prefetched. Carries a short tag so the
    audit event can record *why* (network / decode / upload)."""

    def __init__(self, stage: str, detail: str) -> None:
        super().__init__(f"{stage}: {detail}")
        self.stage = stage
        self.detail = detail


def _download_to_temp(url: str, tmp_dir: str) -> str:
    fd, tmp = tempfile.mkstemp(suffix=".mp3", dir=tmp_dir)
    os.close(fd)
    try:
        urllib.request.urlretrieve(url, tmp)
    except Exception as e:  # noqa: BLE001
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise ChapterFetchError("download", f"{type(e).__name__}: {e}") from e
    return tmp


def _remux_mp3_to_xing(src: str, tmp_dir: str) -> str | None:
    """Re-wrap ``src`` adding a Xing TOC header. Returns the new path on
    success or ``None`` when ffmpeg is missing / errors — caller falls back
    to the un-remuxed file (still serves correctly, just keeps the legacy
    VBR mis-seek issue for that chapter).
    """
    fd, tmp = tempfile.mkstemp(suffix=".mp3", dir=tmp_dir)
    os.close(fd)
    try:
        with _FFMPEG_SEM:
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    src,
                    "-c:a",
                    "copy",
                    "-bsf:a",
                    "mp3_to_xing",
                    "-v",
                    "error",
                    tmp,
                ],
                capture_output=True,
                timeout=FFMPEG_FULL_TIMEOUT,
            )
        if result.returncode != 0 or os.path.getsize(tmp) == 0:
            logger.warning(
                "mp3_to_xing remux failed (rc=%s): %s",
                result.returncode,
                result.stderr.decode("utf-8", errors="replace")[:200],
            )
            os.unlink(tmp)
            return None
        return tmp
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning("mp3_to_xing skipped: %s", e)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return None


def fetch_and_persist_chapter(
    slug: str, chapter: str, url: str, *, force: bool = False
) -> ChapterArtifact:
    """Prefetch one chapter end-to-end. Idempotent against existing artifacts
    unless ``force`` is true — saves work on resumed jobs and on the lazy
    fallback path after a Space restart.
    """
    backend = get_backend()
    audio_path = storage_paths.prefetched_audio_path(slug, chapter)
    peaks_path = storage_paths.prefetched_peaks_path(slug, chapter)

    if not force and backend.exists(audio_path) and backend.exists(peaks_path):
        size = len(backend.read_bytes(audio_path))
        return ChapterArtifact(
            chapter=chapter,
            audio_path=audio_path,
            peaks_path=peaks_path,
            bytes_written=size,
            duration_ms=None,
            ffmpeg_remuxed=False,
        )

    tmp_dir = tempfile.mkdtemp(prefix=f"prefetch_{slug}_")
    raw_path: str | None = None
    remux_path: str | None = None
    try:
        raw_path = _download_to_temp(url, tmp_dir)

        is_vbr = audio_meta.is_vbr_for_url(slug, url)
        if is_vbr:
            remux_path = _remux_mp3_to_xing(raw_path, tmp_dir)
        upload_src = remux_path or raw_path

        with open(upload_src, "rb") as fh:
            data = fh.read()
        try:
            backend.write_bytes_atomic(audio_path, data)
        except Exception as e:  # noqa: BLE001
            raise ChapterFetchError("upload_audio", f"{type(e).__name__}: {e}") from e

        peaks = compute_audio_peaks(upload_src)
        duration_ms = peaks.get("duration_ms") if peaks else None
        if peaks:
            try:
                backend.write_json_atomic(peaks_path, peaks)
            except Exception as e:  # noqa: BLE001
                # Audio is up; peaks failure is recoverable on first /peaks request.
                logger.warning("peaks upload failed for %s/%s: %s", slug, chapter, e)
                peaks_path = None  # signal "not persisted"

        return ChapterArtifact(
            chapter=chapter,
            audio_path=audio_path,
            peaks_path=peaks_path if peaks else None,
            bytes_written=len(data),
            duration_ms=duration_ms,
            ffmpeg_remuxed=remux_path is not None,
        )
    finally:
        for p in (raw_path, remux_path):
            if p:
                try:
                    os.unlink(p)
                except OSError:
                    pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


def write_done_marker(slug: str, *, total_chapters: int, completed_at_ms: int) -> None:
    """Atomic last-write that signals "fully prefetched". Presence of this
    file is the *only* signal ``audio_prefetch.is_prefetched`` consults — the
    audio files alone are not enough because a Space restart mid-job can leave
    a partial set on the bucket.
    """
    get_backend().write_json_atomic(
        storage_paths.prefetch_done_marker_path(slug),
        {
            "schema_version": 1,
            "total_chapters": total_chapters,
            "completed_at_ms": completed_at_ms,
        },
    )


def clear_prefetch(slug: str) -> None:
    """Delete every artifact under ``wip/<slug>/audio/`` and ``wip/<slug>/peaks/``.
    Called by the post-RELEASED sweeper and by the admin re-trigger route.
    """
    backend = get_backend()
    for d in (storage_paths.prefetched_audio_dir(slug), storage_paths.prefetched_peaks_dir(slug)):
        try:
            backend.delete(d)
        except Exception as e:  # noqa: BLE001
            logger.warning("clear_prefetch: failed deleting %s: %s", d, e)


def now_ms() -> int:
    return int(time.time() * 1000)


# ----------------------------------------------------------------------
# Read paths (used by the audio-proxy + peaks routes for short-circuits)
# ----------------------------------------------------------------------


def read_prefetched_audio_bytes(slug: str, url: str) -> bytes | None:
    """Return the prefetched MP3 bytes for ``url`` if present in the bucket.

    Resolves URL → chapter key through the catalog sidecar. Returns ``None``
    when either the URL isn't in this delivery's sidecar or the prefetch
    artifact hasn't been written yet — the caller then falls back to its
    existing path (local disk cache or CDN redirect).
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
    """Return a real local ``Path`` to the prefetched chapter when the
    backend can expose one (deployed bucket mount or local-disk backend).

    Lets the audio-proxy hand ``send_file`` a path instead of a BytesIO —
    Werkzeug then handles Range/304 via OS sendfile and we avoid pulling
    the whole 4–5 MB MP3 into Flask memory on every surah switch.
    Returns ``None`` for local-dev no-mount (callers fall back to bytes).
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
    """Return the prefetched peaks JSON for ``url`` if present in the bucket.

    Same fallthrough semantics as ``read_prefetched_audio_bytes``.
    """
    chapter = audio_meta.chapter_for_url(slug, url)
    if chapter is None:
        return None
    path = storage_paths.prefetched_peaks_path(slug, chapter)
    backend = get_backend()
    try:
        return backend.read_json(path)  # type: ignore[return-value]
    except Exception:  # noqa: BLE001
        return None
