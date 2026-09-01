"""Aligner ``Alignment`` contract <-> bucket ``detailed.json`` conversion.

A sample upload is the aligner app's export: either a bare ``Alignment``
(``{segments: [...], chapter?}``) or an ``AlignmentResource`` envelope
(``{alignment: {...}, ...}``). Each ``MatchedSegment`` carries a seconds-based
``region`` and ``wrap_ranges`` objects; the Inspector edits millisecond
``time_start``/``time_end`` and ``wrap_word_ranges`` tuples.

Import produces one ``DetailedEntry`` per sample (one audio = one pseudo-chapter)
plus a sidecar that remembers the pseudo-chapter, every original segment keyed
by the ``segment_uid`` it became, and the segments that were not live spans
(``filtered`` / ``merged_into``). Export reverses that: originals are copied
back with their edited fields overridden, new segments get fresh ids, dropped
originals are re-appended, and the envelope is preserved in every field except
``segments``.

Pure functions, no I/O.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any, Literal

from qua_shared.schemas.bucket.segment import DetailedSegment
from utils.uuid7 import uuid7

EnvelopeKind = Literal["alignment", "alignment_resource"]

SIDECAR_SCHEMA_VERSION = 1


class SampleConvertError(ValueError):
    """The uploaded JSON is not an aligner export we can ingest."""


def sniff_envelope(doc: Any) -> tuple[EnvelopeKind, dict]:
    """Return ``(kind, alignment_dict)`` for a bare Alignment or a resource envelope."""
    if not isinstance(doc, dict):
        raise SampleConvertError("JSON root must be an object")
    inner = doc.get("alignment")
    if isinstance(inner, dict) and isinstance(inner.get("segments"), list):
        return "alignment_resource", inner
    if isinstance(doc.get("segments"), list):
        return "alignment", doc
    raise SampleConvertError("JSON has no `segments` list (expected an aligner Alignment export)")


def _chapter_of_ref(ref: str | None) -> int | None:
    if not ref or ":" not in ref:
        return None
    try:
        return int(ref.split("-")[0].split(":")[0])
    except ValueError:
        return None


def resolve_pseudo_chapter(alignment: dict) -> int:
    """The single chapter key every segment of the sample is filed under."""
    ch = alignment.get("chapter")
    if isinstance(ch, int) and 1 <= ch <= 114:
        return ch
    for seg in alignment.get("segments", []):
        found = _chapter_of_ref(seg.get("matched_ref")) if isinstance(seg, dict) else None
        if found is not None and 1 <= found <= 114:
            return found
    return 1


def _is_live(seg: dict) -> bool:
    return not seg.get("filtered") and seg.get("merged_into") is None


def _region_ms(seg: dict) -> tuple[int, int]:
    region = seg.get("region")
    if not isinstance(region, dict):
        raise SampleConvertError(f"segment {seg.get('id')!r} has no region")
    try:
        start = round(float(region["start_s"]) * 1000)
        end = round(float(region["end_s"]) * 1000)
    except (KeyError, TypeError, ValueError) as exc:
        raise SampleConvertError(f"segment {seg.get('id')!r} has a malformed region") from exc
    if end <= start or start < 0:
        raise SampleConvertError(f"segment {seg.get('id')!r} has an empty or inverted region")
    return start, end


def _wrap_ranges_to_tuples(wrap_ranges: Any) -> list[list[str]] | None:
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


def _tuples_to_wrap_ranges(wrap_word_ranges: Any) -> list[dict] | None:
    if not wrap_word_ranges:
        return None
    out = []
    for tup in wrap_word_ranges:
        entry = {"jump_to": tup[0], "jump_from": tup[1]}
        entry["repeat_end"] = tup[2] if len(tup) > 2 else None
        out.append(entry)
    return out


def alignment_to_detailed(alignment: dict, *, pseudo_chapter: int) -> tuple[dict, dict]:
    """Convert one Alignment into ``(detailed_doc, sidecar)``."""
    raw_segments = alignment.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise SampleConvertError("alignment has no segments")

    originals: dict[str, dict] = {}
    dropped: list[dict] = []
    live: list[tuple[int, dict]] = []
    for raw in raw_segments:
        if not isinstance(raw, dict):
            raise SampleConvertError("every segment must be an object")
        if not _is_live(raw):
            dropped.append(raw)
            continue
        start, end = _region_ms(raw)
        uid = uuid7()
        seg = DetailedSegment(
            time_start=start,
            time_end=end,
            matched_ref=raw.get("matched_ref") or "",
            confidence=float(raw.get("confidence") or 0.0),
            wrap_word_ranges=_wrap_ranges_to_tuples(raw.get("wrap_ranges")),
            segment_uid=uid,
        )
        originals[uid] = raw
        live.append((start, seg.model_dump(exclude_none=True)))

    if not live:
        raise SampleConvertError("alignment has no live segments (all filtered or merged)")
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
        "pseudo_chapter": pseudo_chapter,
        "originals": originals,
        "dropped": dropped,
    }
    return {"_meta": meta, "entries": entries}, sidecar


def _next_id_allocator(originals: dict[str, dict], dropped: list[dict]):
    ids = [s.get("id") for s in [*originals.values(), *dropped]]
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


def detailed_to_alignment(entries: list[dict], sidecar: dict, original_doc: dict) -> dict:
    """Rebuild the uploaded document with the edited segments swapped in."""
    kind, _ = sniff_envelope(original_doc)
    originals: dict[str, dict] = sidecar.get("originals") or {}
    dropped: list[dict] = sidecar.get("dropped") or []
    next_id = _next_id_allocator(originals, dropped)

    rebuilt: list[dict] = []
    for entry in entries:
        for seg in entry.get("segments", []):
            uid = seg.get("segment_uid")
            base = originals.get(uid) if uid else None
            out = copy.deepcopy(base) if base is not None else {"id": next_id(), "matched_text": ""}
            out["region"] = {
                "start_s": seg["time_start"] / 1000,
                "end_s": seg["time_end"] / 1000,
            }
            out["matched_ref"] = seg.get("matched_ref") or None
            out["confidence"] = float(seg.get("confidence") or 0.0)
            out["wrap_ranges"] = _tuples_to_wrap_ranges(seg.get("wrap_word_ranges"))
            if base is None:
                out["kind"] = _infer_kind(seg.get("matched_ref") or "")
            rebuilt.append(out)
    rebuilt.extend(copy.deepcopy(d) for d in dropped)
    rebuilt.sort(key=lambda s: (s.get("region") or {}).get("start_s", 0.0))

    doc = copy.deepcopy(original_doc)
    target = doc["alignment"] if kind == "alignment_resource" else doc
    target["segments"] = rebuilt
    if target.get("chapter") is None and sidecar.get("pseudo_chapter"):
        target["chapter"] = sidecar["pseudo_chapter"]
    return doc
