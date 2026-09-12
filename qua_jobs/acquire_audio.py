#!/usr/bin/env python3
"""Persist a delivery's chapter audio + peaks to the bucket — the align pipeline's first stage.

Runs as a CPU HF Job launched by ``services/admin/align_pipeline/stage_acquire.py``.
Reads the delivery's audio manifest (``catalog/audio_manifest/<slug>.json``),
fetches every chapter URL, re-encodes it to the canonical chapter mp3
(192 kbps CBR, 44.1 kHz, source channel count preserved) and bakes the slim
peaks blob beside it — the same bytes ``inspector/services/audio`` would produce,
via ``qua_shared.audio.peaks``.

Chapters run **concurrently** on a thread pool (default: one worker per vCPU,
capped by ``MAX_WORKERS``). Every per-chapter step releases the GIL — the fetch
waits on a socket, ffprobe/ffmpeg/peaks are subprocesses — so the pool overlaps
network latency with encode work instead of leaving a multi-core flavor idle on a
single serial chain. Override with ``ACQUIRE_WORKERS``.

Idempotent per chapter: a chapter whose mp3 AND peaks already exist is skipped, so
a retried run only pays for what the previous attempt did not finish. Writes:

    reciters/<slug>/audio/<ch>.mp3
    reciters/<slug>/peaks/<ch>.json.gz
    reciters/<slug>/chapter_sources.json      {"<ch>": {"url", "offset_ms": 0}}
    staging/<slug>/<run_id>/acquire.json      per-chapter outcome + failures

Exits non-zero when any chapter failed, so the Inspector marks the run failed with
the failure list instead of aligning a partial delivery. Only single-file-per-chapter
(``by_surah``) manifests are supported; a URL claimed by two chapters is refused.

Env:
  SLUG                    (required) delivery slug
  RUN_ID                  (required) align run id (names the staging dir)
  INSPECTOR_BUCKET_MOUNT  bucket mount root (default ``/data``)
  CHANNELS                optional 1|2 override; default = probe the source
  ACQUIRE_WORKERS         optional concurrent chapter count (default = vCPUs, max 8)
  HF_TOKEN                HF auth (secret) — only for yt-dlp-free direct fetches, unused otherwise
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, os.environ.get("PYTHONPATH", "/aux/code"))

from qua_shared.audio.peaks import compute_audio_peaks, pack_slim  # noqa: E402

log = logging.getLogger("acquire_audio")

CANONICAL_BITRATE = "192k"
CANONICAL_SAMPLE_RATE = "44100"
_DIRECT_AUDIO_EXTS = frozenset({".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".aac"})
_USER_AGENT = "Mozilla/5.0 (quranic-universal-audio acquire)"
_HTTP_TIMEOUT_S = 120
_FFMPEG_TIMEOUT_S = 1800
_YTDLP_FORMAT = "bestaudio/best"
_YTDLP_EXTRACTOR_ARGS = "youtube:player_client=android,web"
#: Beyond this the source CDN, not the flavor, is the limit — and each worker
#: holds a raw + an encoded copy of its chapter in the job's ephemeral disk.
MAX_WORKERS = 8

_log_lock = threading.Lock()


def _bucket_root() -> Path:
    return Path(os.environ.get("INSPECTOR_BUCKET_MOUNT", "/data"))


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _worker_count(chapters: int) -> int:
    """Concurrent chapters: the env override, else one per vCPU within the cap."""
    override = os.environ.get("ACQUIRE_WORKERS", "").strip()
    if override.isdigit() and int(override) > 0:
        return min(int(override), chapters)
    return max(1, min(os.cpu_count() or 1, MAX_WORKERS, chapters))


def _atomic_write(dest: Path, src: Path) -> None:
    """Move ``src`` onto ``dest`` through a same-directory temp so a reader never
    sees a half-written file on the bucket mount."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    shutil.copyfile(src, tmp)
    os.replace(tmp, dest)


def _atomic_write_bytes(dest: Path, data: bytes) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, dest)


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def _read_manifest(slug: str) -> dict[int, str]:
    """``{chapter: url}`` from the by_surah audio manifest sidecar."""
    path = _bucket_root() / "catalog" / "audio_manifest" / f"{slug}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    chapters: dict[int, str] = {}
    for key, entry in (doc.get("chapters") or {}).items():
        if ":" in str(key):
            raise ValueError(f"{slug}: by_ayah manifests are not supported by acquire_audio")
        chapters[int(key)] = entry["url"]
    if not chapters:
        raise ValueError(f"{slug}: audio manifest lists no chapters")
    by_url: dict[str, list[int]] = {}
    for ch, url in chapters.items():
        by_url.setdefault(url, []).append(ch)
    shared = {url: chs for url, chs in by_url.items() if len(chs) > 1}
    if shared:
        raise ValueError(f"{slug}: one url maps to several chapters (combined files): {shared}")
    return chapters


# ---------------------------------------------------------------------------
# Fetch + encode
# ---------------------------------------------------------------------------


def _needs_ytdlp(url: str) -> bool:
    suffix = Path(url.split("?")[0]).suffix.lower()
    return suffix not in _DIRECT_AUDIO_EXTS


def _fetch(url: str, dest: Path) -> None:
    if not _needs_ytdlp(url):
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp, dest.open("wb") as fh:
            shutil.copyfileobj(resp, fh)
        return
    if shutil.which("yt-dlp") is None:
        raise RuntimeError("yt-dlp is not installed in the job image")
    subprocess.run(
        [
            "yt-dlp",
            "-f",
            _YTDLP_FORMAT,
            "--no-playlist",
            "--extractor-args",
            _YTDLP_EXTRACTOR_ARGS,
            "--retries",
            "5",
            "--fragment-retries",
            "5",
            "--retry-sleep",
            "5",
            "--socket-timeout",
            "30",
            "-o",
            str(dest),
            "--force-overwrites",
            url,
        ],  # fmt: skip
        check=True,
        timeout=_FFMPEG_TIMEOUT_S,
    )


def _probe_channels(src: Path) -> int:
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=channels",
            "-of",
            "csv=p=0",
            str(src),
        ],  # fmt: skip
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    ).stdout.strip()
    channels = int(out.splitlines()[0]) if out else 1
    return 2 if channels >= 2 else 1


def _encode(src: Path, dest: Path, channels: int) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(src),
            "-vn",
            "-c:a",
            "libmp3lame",
            "-b:a",
            CANONICAL_BITRATE,
            "-ar",
            CANONICAL_SAMPLE_RATE,
            "-ac",
            str(channels),
            "-f",
            "mp3",
            "-v",
            "error",
            str(dest),
        ],  # fmt: skip
        check=True,
        timeout=_FFMPEG_TIMEOUT_S,
    )
    if not dest.is_file() or dest.stat().st_size == 0:
        raise RuntimeError("ffmpeg produced an empty mp3")


def _acquire_chapter(slug: str, chapter: int, url: str, channels_override: int | None) -> dict:
    """Fetch, encode and bake one chapter. Returns the outcome record."""
    reciter = _bucket_root() / "reciters" / slug
    mp3_dest = reciter / "audio" / f"{chapter}.mp3"
    peaks_dest = reciter / "peaks" / f"{chapter}.json.gz"
    if mp3_dest.is_file() and peaks_dest.is_file():
        log.info("chapter %d: already persisted, skipped", chapter)
        return {"url": url, "skipped": True, "bytes": mp3_dest.stat().st_size}

    with tempfile.TemporaryDirectory(prefix=f"acq_{chapter}_") as tmp:
        work = Path(tmp)
        raw = work / ("src" + (Path(url.split("?")[0]).suffix or ".bin"))
        _fetch(url, raw)
        channels = channels_override or _probe_channels(raw)
        encoded = work / f"{chapter}.mp3"
        _encode(raw, encoded, channels)
        hd = compute_audio_peaks(str(encoded))
        if hd is None:
            raise RuntimeError("ffmpeg produced no peaks for the encoded chapter")
        blob = pack_slim(hd)
        _atomic_write(mp3_dest, encoded)
        _atomic_write_bytes(peaks_dest, blob)
        return {
            "url": url,
            "skipped": False,
            "bytes": encoded.stat().st_size,
            "channels": channels,
            "duration_ms": hd["duration_ms"],
        }


def _acquire_all(
    slug: str, chapters: dict[int, str], channels_override: int | None, workers: int
) -> tuple[dict[str, dict], dict[str, str]]:
    """Run every chapter on the pool. Returns ``(outcomes, failures)`` keyed by chapter."""
    outcomes: dict[str, dict] = {}
    failures: dict[str, str] = {}
    total = len(chapters)
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="acq") as pool:
        futures = {
            pool.submit(_acquire_chapter, slug, ch, chapters[ch], channels_override): ch
            for ch in sorted(chapters)
        }
        for future in as_completed(futures):
            chapter = futures[future]
            try:
                outcomes[str(chapter)] = future.result()
                message = f"chapter {chapter}: ok ({chapters[chapter]})"
            except Exception as exc:  # noqa: BLE001 — recorded per chapter, run continues
                failures[str(chapter)] = f"{type(exc).__name__}: {exc}"
                message = f"chapter {chapter}: FAILED {failures[str(chapter)]}"
            with _log_lock:
                done = len(outcomes) + len(failures)
                log.info("[%d/%d] %s", done, total, message)
    return outcomes, failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    slug = os.environ.get("SLUG", "").strip()
    run_id = os.environ.get("RUN_ID", "").strip()
    if not slug or not run_id:
        log.error("SLUG and RUN_ID are required")
        return 2
    channels_env = os.environ.get("CHANNELS", "").strip()
    channels_override = int(channels_env) if channels_env in ("1", "2") else None

    chapters = _read_manifest(slug)
    workers = _worker_count(len(chapters))
    log.info(
        "%s: %d chapter(s) to acquire on %d worker(s) (run %s)",
        slug,
        len(chapters),
        workers,
        run_id,
    )

    outcomes, failures = _acquire_all(slug, chapters, channels_override, workers)

    reciter = _bucket_root() / "reciters" / slug
    sources = {str(ch): {"url": chapters[ch], "offset_ms": 0} for ch in sorted(chapters)}
    _atomic_write_bytes(
        reciter / "chapter_sources.json",
        json.dumps(sources, ensure_ascii=False, indent=1).encode("utf-8"),
    )
    report = {
        "slug": slug,
        "run_id": run_id,
        "created_at": _now(),
        "chapters": {ch: outcomes[ch] for ch in sorted(outcomes, key=int)},
        "failures": failures,
    }
    _atomic_write_bytes(
        _bucket_root() / "staging" / slug / run_id / "acquire.json",
        json.dumps(report, ensure_ascii=False, indent=1).encode("utf-8"),
    )
    if failures:
        log.error("%s: %d chapter(s) failed: %s", slug, len(failures), sorted(failures))
        return 1
    log.info("%s: all %d chapter(s) persisted", slug, len(outcomes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
