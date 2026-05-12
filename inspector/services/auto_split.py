"""Auto-split: ask MFA where the verse boundary inside a cross-verse segment is.

Triggered by the Segments tab's cross-verse accordion "Auto Split" button.
Slices the segment audio, runs it through the MFA Space with the segment's
matched_ref and ``padding="none"``, then picks the midpoint between the last
word of the first verse and the first word of the second.

Any failure (segment not found, not cross-verse, ffmpeg error, MFA timeout,
malformed response) returns ``None`` so the frontend can fall back to the
midpoint cursor without surfacing the error.
"""
from __future__ import annotations

import logging
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from config import (
    AUTO_SPLIT_MFA_TIMEOUT,
    FFMPEG_FULL_TIMEOUT,
    MFA_SPACE_URL,
)

# inspector/ is on sys.path (see pyproject.toml); the MFA HTTP client lives at
# <repo>/scripts/lib/timestamps_pipeline.py. app.py inserts the repo root for
# the live server, but tests import this module directly — mirror the
# bootstrap here so the import works in either path.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.lib.timestamps_pipeline import (  # noqa: E402
    build_mfa_ref,
    mfa_upload_and_submit,
    mfa_wait_result,
)

from services import cache
from services.data_loader import load_detailed
from utils.references import chapter_from_ref

logger = logging.getLogger(__name__)

# MFA expects 16 kHz mono. Matches what extract_timestamps feeds the Space.
_MFA_SAMPLE_RATE = 16_000

# Narrower beam than the timestamps-pipeline default (50). One seg, interactive
# UX: tighter beam keeps the per-click latency down and the word boundaries
# we care about (last word of verse A / first word of verse B) are inside
# the segment by construction, so a beam-50 safety net buys nothing.
_MFA_BEAM = 30


def _find_segment(reciter: str, chapter: int, segment_uid: str) -> Optional[dict]:
    """Return the segment dict for ``segment_uid`` in *chapter*, or None."""
    for entry in load_detailed(reciter):
        if chapter_from_ref(entry.get("ref", "")) != chapter:
            continue
        for seg in entry.get("segments", []):
            if seg.get("segment_uid") == segment_uid:
                # Attach the entry's audio URL so callers don't repeat the walk.
                return {**seg, "_audio_url": entry.get("audio", "")}
    return None


def _is_cross_verse(matched_ref: str) -> bool:
    parts = matched_ref.split("-")
    if len(parts) != 2:
        return False
    s, e = parts[0].split(":"), parts[1].split(":")
    return len(s) >= 2 and len(e) >= 2 and s[1] != e[1]


def _slice_to_wav(source: str, start_ms: int, end_ms: int, out_path: Path) -> bool:
    """ffmpeg-extract [start, end] from *source* into mono 16 kHz PCM WAV.

    *source* is a local path or HTTP(S) URL; the same path the segment-clip
    route uses today, so CBR/VBR handling is identical (ffmpeg decodes the
    stream regardless of the container's seek-table quality).
    """
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start_ms / 1000:.3f}",
        "-i", source,
        "-t", f"{max(0, end_ms - start_ms) / 1000:.3f}",
        "-ac", "1",
        "-ar", str(_MFA_SAMPLE_RATE),
        "-c:a", "pcm_s16le",
        str(out_path),
    ]
    try:
        subprocess.run(cmd, check=True, timeout=FFMPEG_FULL_TIMEOUT,
                       capture_output=True)
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        logger.warning("auto_split ffmpeg failed: %s (cmd=%s)",
                       exc, shlex.join(cmd))
        return False
    return out_path.exists() and out_path.stat().st_size > 0


def _boundary_ms_from_words(words: list[dict], boundary_ayah: int) -> Optional[int]:
    """Return segment-relative midpoint between last word of verse ``A`` and
    first word of verse ``B`` (``B == boundary_ayah``).

    Each MFA word has ``location`` ``"surah:ayah:word"`` and ``start``/``end``
    in seconds.
    """
    boundary_idx = None
    for i, w in enumerate(words):
        loc = w.get("location", "")
        parts = loc.split(":")
        if len(parts) < 2:
            continue
        try:
            ayah = int(parts[1])
        except ValueError:
            continue
        if ayah == boundary_ayah:
            boundary_idx = i
            break
    if boundary_idx is None or boundary_idx == 0:
        return None
    prev_end = words[boundary_idx - 1].get("end")
    next_start = words[boundary_idx].get("start")
    if prev_end is None or next_start is None:
        return None
    return round(((prev_end + next_start) / 2.0) * 1000)


def compute_auto_split_ms(reciter: str, chapter: int,
                          segment_uid: str) -> Optional[int]:
    """Forced-align the cross-verse seg and return its verse-boundary ms.

    Returns the absolute time (within the chapter audio) where the split
    cursor should land, or ``None`` to signal "fall back to midpoint" —
    every error path silently returns ``None`` because the frontend's UX
    is the same on any miss.
    """
    seg = _find_segment(reciter, chapter, segment_uid)
    if not seg:
        return None
    matched_ref = seg.get("matched_ref", "")
    if not _is_cross_verse(matched_ref):
        return None

    boundary_ayah = None
    try:
        boundary_ayah = int(matched_ref.split("-")[1].split(":")[1])
    except (IndexError, ValueError):
        return None

    audio_url = seg.get("_audio_url", "")
    if not audio_url:
        return None
    time_start = int(seg.get("time_start", 0))
    time_end = int(seg.get("time_end", 0))
    if time_end <= time_start:
        return None

    mfa_ref = build_mfa_ref(seg)
    if not mfa_ref:
        return None

    # Prefer the local proxy cache when audio_proxy has it. Same shortcut as
    # routes/segment_clip.py — drops the ffmpeg HTTP fetch when warm.
    local = cache.audio_cache_path(reciter, audio_url)
    source = str(local) if local.exists() else audio_url

    try:
        with tempfile.TemporaryDirectory(prefix="auto_split_") as tmp:
            wav_path = Path(tmp) / "seg.wav"
            if not _slice_to_wav(source, time_start, time_end, wav_path):
                return None
            event_id, headers, base_url = mfa_upload_and_submit(
                [mfa_ref], [wav_path], MFA_SPACE_URL,
                beam=_MFA_BEAM,
                padding="none",
                timeout=AUTO_SPLIT_MFA_TIMEOUT,
            )
            results = mfa_wait_result(event_id, headers, base_url,
                                      timeout=AUTO_SPLIT_MFA_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 — all-paths fallback is intentional
        logger.info("auto_split MFA call failed for %s/%s seg %s: %s",
                    reciter, chapter, segment_uid, exc)
        return None

    # mfa_wait_result returns the "results" array — one item per uploaded audio.
    if not results or not isinstance(results, list):
        return None
    first = results[0] or {}
    words = first.get("words") or []
    rel_ms = _boundary_ms_from_words(words, boundary_ayah)
    if rel_ms is None:
        return None
    return time_start + rel_ms
