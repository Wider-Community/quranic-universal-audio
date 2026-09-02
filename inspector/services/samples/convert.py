"""Aligner export <-> bucket ``detailed.json`` conversion for uploaded samples.

Three upload shapes are accepted, sniffed from the JSON:

- ``alignment`` — the aligner ``Alignment`` contract: ``{segments:[MatchedSegment], chapter?}``
  with seconds-based ``region`` and ``wrap_ranges`` objects.
- ``alignment_resource`` — the same wrapped in the API envelope ``{alignment: {...}, ...}``.
- ``legacy`` — the aligner app's file export: ``{_meta, segments:[{segment, time_from,
  time_to, ref_from, ref_to, special_type, confidence, ...}]}``.

Import produces one ``DetailedEntry`` per sample (one audio = one pseudo-chapter)
plus a sidecar that remembers the shape, the pseudo-chapter, and the segments
that were not live spans (``filtered`` / ``merged_into``). Per-segment
``words`` timings become ``DetailedSegment.word_timings`` (audio-absolute ms)
so every edit and undo carries them. Export reverses that: originals are
copied back with their edited fields overridden (``words`` rewritten
segment-relative, or removed when the edits dropped them), new segments get
fresh ids, dropped originals are re-appended, and everything outside
``segments`` is preserved.

Pure functions, no I/O.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any, Literal

from qua_shared.schemas.bucket.segment import DetailedSegment, WordTiming
from utils.uuid7 import uuid7

EnvelopeKind = Literal["alignment", "alignment_resource", "legacy"]

SIDECAR_SCHEMA_VERSION = 1


class SampleConvertError(ValueError):
    """The uploaded JSON is not an aligner export we can ingest."""


def sniff_envelope(doc: Any) -> tuple[EnvelopeKind, dict]:
    """Return ``(kind, container)`` where ``container["segments"]`` is the list."""
    if not isinstance(doc, dict):
        raise SampleConvertError("JSON root must be an object")
    inner = doc.get("alignment")
    if isinstance(inner, dict) and isinstance(inner.get("segments"), list):
        return "alignment_resource", inner
    segments = doc.get("segments")
    if not isinstance(segments, list):
        raise SampleConvertError("JSON has no `segments` list (expected an aligner export)")
    first = next((s for s in segments if isinstance(s, dict)), None)
    if first is not None and "time_from" in first and "region" not in first:
        return "legacy", doc
    return "alignment", doc


def _chapter_of_ref(ref: str | None) -> int | None:
    if not ref or ":" not in ref:
        return None
    try:
        return int(ref.split("-")[0].split(":")[0])
    except ValueError:
        return None


def resolve_pseudo_chapter(kind: EnvelopeKind, container: dict) -> int:
    """The single chapter key every segment of the sample is filed under."""
    ch = container.get("chapter")
    if isinstance(ch, int) and 1 <= ch <= 114:
        return ch
    for seg in container.get("segments", []):
        if not isinstance(seg, dict):
            continue
        found = _chapter_of_ref(_read_ref(kind, seg))
        if found is not None and 1 <= found <= 114:
            return found
    return 1


# ---------------------------------------------------------------------------
# Per-shape readers
# ---------------------------------------------------------------------------


def _read_id(kind: EnvelopeKind, seg: dict) -> Any:
    return seg.get("segment") if kind == "legacy" else seg.get("id")


def _is_live(kind: EnvelopeKind, seg: dict) -> bool:
    if kind == "legacy":
        return True
    return not seg.get("filtered") and seg.get("merged_into") is None


def _read_span_s(kind: EnvelopeKind, seg: dict) -> tuple[float, float]:
    if kind == "legacy":
        start, end = seg.get("time_from"), seg.get("time_to")
    else:
        region = seg.get("region")
        if not isinstance(region, dict):
            raise SampleConvertError(f"segment {_read_id(kind, seg)!r} has no region")
        start, end = region.get("start_s"), region.get("end_s")
    if start is None or end is None:
        raise SampleConvertError(f"segment {_read_id(kind, seg)!r} has no time span")
    try:
        return float(start), float(end)
    except (TypeError, ValueError) as exc:
        raise SampleConvertError(
            f"segment {_read_id(kind, seg)!r} has a malformed time span"
        ) from exc


def _read_ref(kind: EnvelopeKind, seg: dict) -> str:
    if kind != "legacy":
        return seg.get("matched_ref") or ""
    ref_from, ref_to = seg.get("ref_from") or "", seg.get("ref_to") or ""
    if ref_from and ref_to:
        return f"{ref_from}-{ref_to}"
    return seg.get("special_type") or ""


def _read_wraps(kind: EnvelopeKind, seg: dict) -> list[list[str]] | None:
    if kind == "legacy":
        return None  # the legacy export carries only a has_repeated_words flag
    wrap_ranges = seg.get("wrap_ranges")
    if not wrap_ranges:
        return None
    out: list[list[str]] = []
    for wr in wrap_ranges:
        if not isinstance(wr, dict) or "jump_to" not in wr or "jump_from" not in wr:
            raise SampleConvertError("wrap_ranges entries need jump_to and jump_from")
        tup = [str(wr["jump_to"]), str(wr["jump_from"])]
        if wr.get("repeat_end"):
            tup.append(str(wr["repeat_end"]))
        out.append(tup)
    return out


def _read_words(seg: dict, start_ms: int) -> list[WordTiming] | None:
    """Word timings as audio-absolute ms; the upload stores them relative to
    the segment start in seconds. ``None`` when the segment carries none."""
    raw = seg.get("words")
    if not isinstance(raw, list) or not raw:
        return None
    out: list[WordTiming] = []
    for w in raw:
        if not isinstance(w, dict) or w.get("start") is None or w.get("end") is None:
            continue
        try:
            start, end = float(w["start"]), float(w["end"])
        except (TypeError, ValueError):
            continue
        out.append(
            WordTiming(
                word=str(w.get("word") or ""),
                location=str(w.get("location") or ""),
                start_ms=start_ms + round(start * 1000),
                end_ms=start_ms + round(end * 1000),
            )
        )
    return out or None


def _region_ms(kind: EnvelopeKind, seg: dict) -> tuple[int, int]:
    start_s, end_s = _read_span_s(kind, seg)
    start, end = round(start_s * 1000), round(end_s * 1000)
    if end <= start or start < 0:
        raise SampleConvertError(
            f"segment {_read_id(kind, seg)!r} has an empty or inverted time span"
        )
    return start, end


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def alignment_to_detailed(
    kind: EnvelopeKind, container: dict, *, pseudo_chapter: int
) -> tuple[dict, dict]:
    """Convert one upload into ``(detailed_doc, sidecar)``."""
    raw_segments = container.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise SampleConvertError("upload has no segments")

    originals: dict[str, dict] = {}
    dropped: list[dict] = []
    live: list[tuple[int, dict]] = []
    for raw in raw_segments:
        if not isinstance(raw, dict):
            raise SampleConvertError("every segment must be an object")
        if not _is_live(kind, raw):
            dropped.append(raw)
            continue
        start, end = _region_ms(kind, raw)
        uid = uuid7()
        seg = DetailedSegment(
            time_start=start,
            time_end=end,
            matched_ref=_read_ref(kind, raw),
            confidence=float(raw.get("confidence") or 0.0),
            wrap_word_ranges=_read_wraps(kind, raw),
            segment_uid=uid,
            word_timings=_read_words(raw, start),
        )
        originals[uid] = raw
        live.append((start, seg.model_dump(exclude_none=True)))

    if not live:
        raise SampleConvertError("upload has no live segments (all filtered or merged)")
    live.sort(key=lambda item: item[0])
    entries = [{"ref": str(pseudo_chapter), "segments": [seg for _, seg in live]}]
    meta = {
        "created_at": datetime.now(UTC).isoformat(),
        "audio_source": "sample",
        "pad_left_ms": 0,
        "pad_right_ms": 0,
        "min_silence_floor_ms": 0,
    }
    sidecar = {
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "kind": kind,
        "pseudo_chapter": pseudo_chapter,
        "originals": originals,
        "dropped": dropped,
    }
    return {"_meta": meta, "entries": entries}, sidecar


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _tuples_to_wrap_ranges(wrap_word_ranges: Any) -> list[dict] | None:
    if not wrap_word_ranges:
        return None
    out = []
    for tup in wrap_word_ranges:
        entry = {"jump_to": tup[0], "jump_from": tup[1]}
        entry["repeat_end"] = tup[2] if len(tup) > 2 else None
        out.append(entry)
    return out


def _next_id_allocator(kind: EnvelopeKind, originals: dict[str, dict], dropped: list[dict]):
    ids = [_read_id(kind, s) for s in [*originals.values(), *dropped]]
    ints = [i for i in ids if isinstance(i, int)]
    counter = (max(ints) if ints else -1) + 1

    def _next() -> int:
        nonlocal counter
        value = counter
        counter += 1
        return value

    return _next


def _infer_kind(matched_ref: str) -> str | None:
    if not matched_ref:
        return None
    return "quran" if ":" in matched_ref else "special"


def _write_words(out: dict, seg: dict) -> None:
    """Rewrite ``words`` segment-relative from ``word_timings``; drop a stale
    upload ``words`` list when the edits left the segment without timings."""
    timings = seg.get("word_timings")
    if not timings:
        out.pop("words", None)
        return
    origin = seg["time_start"]
    out["words"] = [
        {
            "word": w.get("word", ""),
            "location": w["location"],
            "start": round((w["start_ms"] - origin) / 1000, 3),
            "end": round((w["end_ms"] - origin) / 1000, 3),
        }
        for w in timings
    ]


def _write_segment(kind: EnvelopeKind, base: dict | None, seg: dict, next_id) -> dict:
    matched_ref = seg.get("matched_ref") or ""
    start_s, end_s = seg["time_start"] / 1000, seg["time_end"] / 1000
    confidence = float(seg.get("confidence") or 0.0)
    if kind == "legacy":
        out = (
            copy.deepcopy(base)
            if base is not None
            else {
                "segment": next_id(),
                "matched_text": "",
                "has_missing_words": False,
                "has_repeated_words": False,
                "error": None,
            }
        )
        out["time_from"], out["time_to"] = start_s, end_s
        if ":" in matched_ref:
            ref_from, _, ref_to = matched_ref.partition("-")
            out["ref_from"], out["ref_to"] = ref_from, ref_to or ref_from
            out["special_type"] = None
        else:
            out["ref_from"], out["ref_to"] = "", ""
            out["special_type"] = matched_ref or None
        out["confidence"] = confidence
        out["kind"] = _infer_kind(matched_ref)
        _write_words(out, seg)
        return out
    out = copy.deepcopy(base) if base is not None else {"id": next_id(), "matched_text": ""}
    out["region"] = {"start_s": start_s, "end_s": end_s}
    out["matched_ref"] = matched_ref or None
    out["confidence"] = confidence
    out["wrap_ranges"] = _tuples_to_wrap_ranges(seg.get("wrap_word_ranges"))
    if base is None:
        out["kind"] = _infer_kind(matched_ref)
    if (base is not None and "words" in base) or seg.get("word_timings"):
        _write_words(out, seg)
    return out


def detailed_to_alignment(entries: list[dict], sidecar: dict, original_doc: dict) -> dict:
    """Rebuild the uploaded document with the edited segments swapped in."""
    kind, _ = sniff_envelope(original_doc)
    originals: dict[str, dict] = sidecar.get("originals") or {}
    dropped: list[dict] = sidecar.get("dropped") or []
    next_id = _next_id_allocator(kind, originals, dropped)

    rebuilt: list[dict] = []
    for entry in entries:
        for seg in entry.get("segments", []):
            uid = seg.get("segment_uid")
            base = originals.get(uid) if uid else None
            rebuilt.append(_write_segment(kind, base, seg, next_id))
    rebuilt.extend(copy.deepcopy(d) for d in dropped)
    rebuilt.sort(key=lambda s: _read_span_s(kind, s)[0])

    doc = copy.deepcopy(original_doc)
    target = doc["alignment"] if kind == "alignment_resource" else doc
    target["segments"] = rebuilt
    if kind != "legacy" and target.get("chapter") is None and sidecar.get("pseudo_chapter"):
        target["chapter"] = sidecar["pseudo_chapter"]
    return doc
