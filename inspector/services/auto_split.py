"""Auto-split: ask MFA where the internal boundaries of a seg are.

Triggered by the Segments tab's accordion "Auto Split" button. Handles two
kinds of segs today:

- **Cross-verse** — one cursor between the last word of verse A and the
  first word of verse B. Produces two ref pieces.
- **Repetition** — N-1 cursors splitting the seg into the forward pass and
  each repeated section recorded in ``wrap_word_ranges``. Produces N ref
  pieces. Needs the MFA Space's list-of-refs support (one ref string per
  reading-sequence section, joined into one audio).

Every failure path (segment not found, ffmpeg error, MFA timeout, malformed
response) returns ``None`` for the absolute cuts so the frontend can fall
back silently to evenly-spaced cursors (no user-facing error).
"""
from __future__ import annotations

import logging
import os
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

# The MFA HTTP client lives in scripts/lib/timestamps_pipeline.py, which
# imports numpy at module load. The inspector deploy image doesn't ship numpy
# (only the offline pipeline needs it) so we must NOT import it at startup —
# do it lazily inside compute_auto_split instead.
#
# Module-level placeholders keep `monkeypatch.setattr(auto_split, "...")` in
# tests working: tests set the attrs before the lazy loader runs, and the
# loader is a no-op when the names are already callable.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

build_mfa_ref = None
mfa_upload_and_submit = None
mfa_wait_result = None


def _ensure_mfa_client() -> None:
    """Import the MFA HTTP client on first use.

    Kept out of module import so the deploy image (no numpy) can still load
    inspector. Tests can pre-bind the three names via monkeypatch to bypass
    the import entirely.
    """
    global build_mfa_ref, mfa_upload_and_submit, mfa_wait_result
    if callable(build_mfa_ref) and callable(mfa_upload_and_submit) \
            and callable(mfa_wait_result):
        return
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from scripts.lib.timestamps_pipeline import (
        build_mfa_ref as _b,
        mfa_upload_and_submit as _u,
        mfa_wait_result as _w,
    )
    if not callable(build_mfa_ref):
        build_mfa_ref = _b
    if not callable(mfa_upload_and_submit):
        mfa_upload_and_submit = _u
    if not callable(mfa_wait_result):
        mfa_wait_result = _w


from services import cache
from services.data_loader import get_word_counts, load_detailed
from utils.references import chapter_from_ref
from utils.repetitions import (
    compute_reading_sequence,
    count_words_in_section,
    section_refs_canonical,
)

logger = logging.getLogger(__name__)

# MFA expects 16 kHz mono. Matches what extract_timestamps feeds the Space.
_MFA_SAMPLE_RATE = 16_000

# Narrower beam than the timestamps-pipeline default (50). One seg,
# interactive UX: tighter beam keeps the per-click latency down.
_MFA_BEAM = 30


# ---------------------------------------------------------------------------
# Segment lookup + audio slicing
# ---------------------------------------------------------------------------

def _find_segment(reciter: str, chapter: int, segment_uid: str) -> Optional[dict]:
    """Return the segment dict for ``segment_uid`` in *chapter*, or None."""
    for entry in load_detailed(reciter):
        if chapter_from_ref(entry.get("ref", "")) != chapter:
            continue
        for seg in entry.get("segments", []):
            if seg.get("segment_uid") == segment_uid:
                return {**seg, "_audio_url": entry.get("audio", "")}
    return None


def _is_cross_verse(matched_ref: str) -> bool:
    parts = matched_ref.split("-")
    if len(parts) != 2:
        return False
    s, e = parts[0].split(":"), parts[1].split(":")
    return len(s) >= 2 and len(e) >= 2 and s[1] != e[1]


def _slice_to_wav(source: str, start_ms: int, end_ms: int, out_path: Path) -> bool:
    """ffmpeg-extract [start, end] from *source* into mono 16 kHz PCM WAV."""
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


def _run_mfa(reciter: str, audio_url: str, time_start: int, time_end: int,
             ref_or_seq) -> Optional[list[dict]]:
    """Slice audio + call MFA. Returns the per-word list or None on failure."""
    try:
        _ensure_mfa_client()
    except Exception as exc:  # noqa: BLE001
        logger.warning("auto_split MFA client unavailable: %s", exc)
        return None
    local = cache.audio_cache_path(reciter, audio_url)
    source = str(local) if local.exists() else audio_url

    # Deployed inspector configures its bucket token as INSPECTOR_HF_TOKEN;
    # mfa_upload_and_submit reads HF_TOKEN. Mirror the hf_bucket.py fallback.
    if not os.environ.get("HF_TOKEN") and os.environ.get("INSPECTOR_HF_TOKEN"):
        os.environ["HF_TOKEN"] = os.environ["INSPECTOR_HF_TOKEN"]

    try:
        with tempfile.TemporaryDirectory(prefix="auto_split_") as tmp:
            wav_path = Path(tmp) / "seg.wav"
            if not _slice_to_wav(source, time_start, time_end, wav_path):
                return None
            event_id, headers, base_url = mfa_upload_and_submit(
                [ref_or_seq], [wav_path], MFA_SPACE_URL,
                beam=_MFA_BEAM,
                padding="none",
                timeout=AUTO_SPLIT_MFA_TIMEOUT,
            )
            results = mfa_wait_result(event_id, headers, base_url,
                                      timeout=AUTO_SPLIT_MFA_TIMEOUT)
    except Exception as exc:  # noqa: BLE001
        # WARNING because a silent fallback masks a real wiring issue
        # (missing HF_TOKEN, Space asleep, network) that the user almost
        # certainly wants to see. The route response stays unchanged so the
        # UX is still fallback-on-fail.
        logger.warning("auto_split MFA call failed: %s", exc)
        return None

    if not results or not isinstance(results, list):
        return None
    first = results[0] or {}
    return first.get("words") or None


# ---------------------------------------------------------------------------
# Cross-verse path
# ---------------------------------------------------------------------------

def _suggest_cross_verse_refs(matched_ref: str,
                              word_counts: dict[tuple[int, int], int]
                              ) -> Optional[list[str]]:
    """Split the cross-verse ref into two per-verse refs.

    ``"37:151:3-37:152:2"`` →
    ``["37:151:3-37:151:N", "37:152:1-37:152:2"]`` where N is the verse's
    total word count.
    """
    parts = matched_ref.split("-")
    if len(parts) != 2:
        return None
    s = parts[0].split(":")
    e = parts[1].split(":")
    if len(s) != 3 or len(e) != 3:
        return None
    try:
        surah = int(s[0])
        a_ayah, a_word = int(s[1]), int(s[2])
        b_ayah, b_word = int(e[1]), int(e[2])
    except ValueError:
        return None
    a_total = word_counts.get((surah, a_ayah))
    if not a_total:
        return None
    return [
        f"{surah}:{a_ayah}:{a_word}-{surah}:{a_ayah}:{a_total}",
        f"{surah}:{b_ayah}:1-{surah}:{b_ayah}:{b_word}",
    ]


def _boundary_ms_at_ayah(words: list[dict], boundary_ayah: int) -> Optional[int]:
    """Midpoint between last word of verse A and first word of verse B."""
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


# ---------------------------------------------------------------------------
# Repetition path
# ---------------------------------------------------------------------------

def _repetition_sections(matched_ref: str, wrap: list) -> Optional[list[list[str]]]:
    """Return reading-order ``[[from, to], ...]`` from the seg's wrap data."""
    parts = matched_ref.split("-")
    if len(parts) != 2:
        return None
    sections = compute_reading_sequence(parts[0], parts[1], wrap)
    return sections or None


def _repetition_cuts(words: list[dict], section_word_counts: list[int]
                     ) -> Optional[list[int]]:
    """Return N-1 segment-relative ms cuts between consecutive sections.

    Walks ``words`` in input order, consuming ``section_word_counts[i]``
    words per section, and emits the midpoint between the last word of
    section *i* and the first of section *i+1*. Any short slice or missing
    start/end aborts (returns None) so the caller can fall back.
    """
    if not section_word_counts or not words:
        return None
    cuts: list[int] = []
    cursor = 0
    for i, count in enumerate(section_word_counts[:-1]):
        cursor += count
        if cursor <= 0 or cursor >= len(words):
            return None
        prev_end = words[cursor - 1].get("end")
        next_start = words[cursor].get("start")
        if prev_end is None or next_start is None:
            return None
        cuts.append(round(((prev_end + next_start) / 2.0) * 1000))
    return cuts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_auto_split(reciter: str, chapter: int, segment_uid: str) -> dict:
    """Compute the auto-split cursors + per-section refs for a segment.

    Returns a JSON-serializable dict in the shape:

      ``{"cursors": list[int] | None,   # absolute ms cuts (N-1 entries)
         "refs":    list[str] | None,   # N per-section refs
         "kind":    "cross_verse" | "repetition" | None,
         "source":  "mfa" | "fallback"}``

    Cross-verse fallback drops one cursor at the seg midpoint. Repetition
    fallback drops N-1 evenly-spaced cursors. Either fallback still
    populates ``refs`` from the seg metadata so the FE confirm-walk has
    text to load even when MFA was unreachable.
    """
    seg = _find_segment(reciter, chapter, segment_uid)
    if not seg:
        return {"cursors": None, "refs": None, "kind": None, "source": "fallback"}

    matched_ref = seg.get("matched_ref", "")
    wrap = seg.get("wrap_word_ranges") or None
    time_start = int(seg.get("time_start", 0))
    time_end = int(seg.get("time_end", 0))
    if time_end <= time_start or not matched_ref:
        return {"cursors": None, "refs": None, "kind": None, "source": "fallback"}

    audio_url = seg.get("_audio_url", "")
    word_counts = get_word_counts()

    if wrap:
        return _compute_repetition(seg, audio_url, time_start, time_end,
                                   matched_ref, wrap, word_counts, reciter)
    if _is_cross_verse(matched_ref):
        return _compute_cross_verse(seg, audio_url, time_start, time_end,
                                    matched_ref, word_counts, reciter)
    return {"cursors": None, "refs": None, "kind": None, "source": "fallback"}


def _compute_cross_verse(seg, audio_url, time_start, time_end, matched_ref,
                         word_counts, reciter) -> dict:
    refs = _suggest_cross_verse_refs(matched_ref, word_counts)
    midpoint = (time_start + time_end) // 2

    if not audio_url:
        return {"cursors": [midpoint], "refs": refs, "kind": "cross_verse",
                "source": "fallback"}

    try:
        boundary_ayah = int(matched_ref.split("-")[1].split(":")[1])
    except (IndexError, ValueError):
        return {"cursors": [midpoint], "refs": refs, "kind": "cross_verse",
                "source": "fallback"}

    mfa_ref = None
    try:
        _ensure_mfa_client()
        mfa_ref = build_mfa_ref(seg) if callable(build_mfa_ref) else None
    except Exception:  # noqa: BLE001
        mfa_ref = None
    if not mfa_ref:
        return {"cursors": [midpoint], "refs": refs, "kind": "cross_verse",
                "source": "fallback"}

    words = _run_mfa(reciter, audio_url, time_start, time_end, mfa_ref)
    if not words:
        return {"cursors": [midpoint], "refs": refs, "kind": "cross_verse",
                "source": "fallback"}
    rel_ms = _boundary_ms_at_ayah(words, boundary_ayah)
    if rel_ms is None:
        return {"cursors": [midpoint], "refs": refs, "kind": "cross_verse",
                "source": "fallback"}
    return {"cursors": [time_start + rel_ms], "refs": refs,
            "kind": "cross_verse", "source": "mfa"}


def _compute_repetition(seg, audio_url, time_start, time_end, matched_ref,
                        wrap, word_counts, reciter) -> dict:
    sections = _repetition_sections(matched_ref, wrap)
    if not sections or len(sections) < 2:
        return {"cursors": None, "refs": None, "kind": "repetition",
                "source": "fallback"}
    refs = section_refs_canonical(sections)
    n = len(sections)
    duration = time_end - time_start
    even_cuts = [time_start + round(duration * (i + 1) / n) for i in range(n - 1)]

    section_word_counts = [
        count_words_in_section(s[0], s[1], word_counts) for s in sections
    ]
    if not all(c > 0 for c in section_word_counts):
        return {"cursors": even_cuts, "refs": refs, "kind": "repetition",
                "source": "fallback"}

    if not audio_url:
        return {"cursors": even_cuts, "refs": refs, "kind": "repetition",
                "source": "fallback"}

    # MFA Space sequence support: pass list[str] as the ref entry.
    words = _run_mfa(reciter, audio_url, time_start, time_end, refs)
    if not words or len(words) != sum(section_word_counts):
        # Tolerate small mismatches? For now, conservative fallback.
        return {"cursors": even_cuts, "refs": refs, "kind": "repetition",
                "source": "fallback"}
    rel_cuts = _repetition_cuts(words, section_word_counts)
    if rel_cuts is None:
        return {"cursors": even_cuts, "refs": refs, "kind": "repetition",
                "source": "fallback"}
    return {"cursors": [time_start + c for c in rel_cuts], "refs": refs,
            "kind": "repetition", "source": "mfa"}
