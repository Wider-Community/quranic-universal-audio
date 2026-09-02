"""Re-run word timing for one sample segment on the batch timing Space.

The sample's audio already sits in the bucket (``samples/<id>/audio/<ch>.mp3``),
so the Space is handed a bucket span + the ref grammar string and returns word
rows; they come back as ``DetailedSegment.word_timings`` (audio-absolute ms).
The FE sends the segment as it currently holds it (ref + span) and commits the
result through the normal save path as a ``set_word_timings`` op. Plain Quran
spans only: repetition wraps and specials need the list-ref grammar.
"""

from __future__ import annotations

from services.admin import ts_space_client
from services.db import repo_samples
from services.storage import storage_paths
from services.storage.hf_bucket import resolve_bucket_repo

from . import SampleError, SampleNotFound


class RealignUnsupported(SampleError):
    """The segment's ref cannot be expressed as a single MFA span."""


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


def realign_span(sample_id: str, *, ref: str, start_ms: int, end_ms: int) -> list[dict]:
    """Word timings for ``[start_ms, end_ms]`` of the sample audio against ``ref``."""
    row = repo_samples.get(sample_id)
    if row is None:
        raise SampleNotFound(sample_id)
    if ":" not in ref:
        raise RealignUnsupported("only Quran-ref segments can be realigned")
    if end_ms <= start_ms:
        raise SampleError("time_end must be greater than time_start")
    slug = storage_paths.sample_slug(sample_id)
    result = ts_space_client.align_item(
        ref=ref,
        repo=resolve_bucket_repo(),
        path=storage_paths.prefetched_audio_path(slug, int(row["pseudo_chapter"])),
        start_ms=start_ms,
        end_ms=end_ms,
    )
    if result.get("status") != "ok" or not isinstance(result.get("words"), list):
        raise SampleError(f"timing failed: {result.get('error') or result.get('status')}")
    timings = _rows_to_timings(result["words"], start_ms)
    if not timings:
        raise SampleError("timing returned no words")
    return timings
