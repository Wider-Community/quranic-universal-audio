"""Re-run word timing for one sample segment on the batch timing Space.

The segment's audio already sits in the bucket (``samples/<id>/audio/<ch>.mp3``),
so the Space is handed a bucket span + the ref grammar string and returns word
rows; they come back as ``DetailedSegment.word_timings`` (audio-absolute ms).
The caller (the FE) commits them through the normal save path so history and
undo see a ``set_word_timings`` op. Plain Quran spans only: repetition wraps
and specials need the list-ref grammar and are refused.
"""

from __future__ import annotations

from services.admin import ts_space_client
from services.db import repo_samples
from services.storage import storage_paths
from services.storage.data_loader import load_detailed
from services.storage.hf_bucket import resolve_bucket_repo
from utils.references import chapter_from_ref

from . import SampleError, SampleNotFound


class RealignUnsupported(SampleError):
    """The segment's ref cannot be expressed as a single MFA span."""


def _find_segment(entries: list[dict], segment_uid: str) -> tuple[int, dict] | None:
    for entry in entries:
        for seg in entry.get("segments", []):
            if seg.get("segment_uid") == segment_uid:
                return chapter_from_ref(entry["ref"]), seg
    return None


def _rows_to_timings(rows: list[dict], origin_ms: int) -> list[dict]:
    return [
        {
            "word": str(w.get("text") or ""),
            "location": str(w["location"]),
            "start_ms": origin_ms + round(float(w["start"]) * 1000),
            "end_ms": origin_ms + round(float(w["end"]) * 1000),
        }
        for w in rows
    ]


def realign_segment(sample_id: str, segment_uid: str) -> list[dict]:
    """Word timings for ``segment_uid`` of sample ``sample_id`` from the Space."""
    if repo_samples.get(sample_id) is None:
        raise SampleNotFound(sample_id)
    slug = storage_paths.sample_slug(sample_id)
    found = _find_segment(load_detailed(slug), segment_uid)
    if found is None:
        raise SampleNotFound(segment_uid)
    chapter, seg = found
    ref = seg.get("matched_ref") or ""
    if ":" not in ref:
        raise RealignUnsupported("only Quran-ref segments can be realigned")
    if seg.get("wrap_word_ranges"):
        raise RealignUnsupported("repetition segments cannot be realigned as one span")
    row = ts_space_client.align_item(
        ref=ref,
        repo=resolve_bucket_repo(),
        path=storage_paths.prefetched_audio_path(slug, chapter),
        start_ms=int(seg["time_start"]),
        end_ms=int(seg["time_end"]),
    )
    if row.get("status") != "ok" or not isinstance(row.get("words"), list):
        raise SampleError(f"timing failed: {row.get('error') or row.get('status')}")
    timings = _rows_to_timings(row["words"], int(seg["time_start"]))
    if not timings:
        raise SampleError("timing returned no words")
    return timings
