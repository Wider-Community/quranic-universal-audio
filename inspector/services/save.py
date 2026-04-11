"""Save flow: atomic write, backup, history, rebuild_segments_json.

No Flask imports -- all functions accept parameters and return plain dicts.
"""

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from config import RECITATION_SEGMENTS_PATH
from services import cache
from services.data_loader import get_word_counts, load_detailed
from services.validation import chapter_validation_counts
from utils.io import atomic_json_write, backup_file, file_sha256
from utils.references import chapter_from_ref, normalize_ref, seg_sort_key
from utils.uuid7 import uuid7


def normalize_ref_with_wc(ref: str) -> str:
    """Normalize a short ref to canonical form (passes cached word counts)."""
    return normalize_ref(ref, get_word_counts())


def rebuild_segments_json(reciter: str, entries: list[dict]) -> None:
    """Regenerate segments.json from detailed entries (verse-aggregated format)."""
    verse_data: dict[str, list] = defaultdict(list)
    for entry in entries:
        for seg in entry.get("segments", []):
            ref = seg.get("matched_ref", "")
            if not ref:
                continue
            parts = ref.split("-")
            if len(parts) != 2:
                continue
            start_parts = parts[0].split(":")
            end_parts = parts[1].split(":")
            if len(start_parts) != 3 or len(end_parts) != 3:
                continue
            try:
                start_sura = int(start_parts[0])
                start_ayah = int(start_parts[1])
                start_word = int(start_parts[2])
                end_ayah = int(end_parts[1])
                end_word = int(end_parts[2])
            except ValueError:
                continue

            t_from = seg.get("time_start", 0)
            t_to = seg.get("time_end", 0)

            if start_ayah == end_ayah:
                verse_data[f"{start_sura}:{start_ayah}"].append(
                    [start_word, end_word, t_from, t_to]
                )
            else:
                verse_data[ref].append(
                    [start_word, end_word, t_from, t_to]
                )

    segments_path = RECITATION_SEGMENTS_PATH / reciter / "segments.json"
    # Preserve metadata from existing file
    existing_meta = {}
    if segments_path.exists():
        with open(segments_path, "r", encoding="utf-8") as f:
            try:
                existing_doc = json.load(f)
                existing_meta = existing_doc.get("_meta", {})
            except json.JSONDecodeError:
                pass
    seg_doc = {"_meta": existing_meta}
    for key in sorted(verse_data.keys(), key=seg_sort_key):
        seg_doc[key] = verse_data[key]
    with open(segments_path, "w", encoding="utf-8") as f:
        json.dump(seg_doc, f, ensure_ascii=False)


def save_seg_data(reciter: str, chapter: int, updates: dict) -> dict:
    """Save edited segments.  Returns ``{"ok": True}`` or ``{"error": ...}``
    with an HTTP status code as a second element in a tuple.
    """
    entries = load_detailed(reciter)
    if not entries:
        return {"error": "Reciter not found"}, 404

    matching = [e for e in entries if chapter_from_ref(e["ref"]) == chapter]
    if not matching:
        return {"error": "Chapter not found"}, 404

    # Build lookups of existing segments by time and by uid for field preservation
    existing_by_time = {}
    existing_by_uid = {}
    for e in matching:
        for seg in e.get("segments", []):
            key = (seg.get("time_start", 0), seg.get("time_end", 0))
            existing_by_time[key] = seg
            uid = seg.get("segment_uid", "")
            if uid:
                existing_by_uid[uid] = seg

    def _make_seg(s):
        existing = existing_by_time.get((s.get("time_start", 0), s.get("time_end", 0)), {})
        if not existing:
            uid = s.get("segment_uid", "")
            if uid:
                existing = existing_by_uid.get(uid, {})
        phonemes = s.get("phonemes_asr", "") or existing.get("phonemes_asr", "")
        seg_uid = s.get("segment_uid", "") or existing.get("segment_uid", "")
        result = {
            "segment_uid": seg_uid,
            "time_start": s.get("time_start", 0),
            "time_end": s.get("time_end", 0),
            "matched_ref": normalize_ref_with_wc(s.get("matched_ref", "")),
            "matched_text": s.get("matched_text", ""),
            "confidence": s.get("confidence", 0.0),
            "phonemes_asr": phonemes,
        }
        wrap = s.get("wrap_word_ranges") or existing.get("wrap_word_ranges")
        if wrap:
            result["wrap_word_ranges"] = wrap
        if s.get("has_repeated_words") or existing.get("has_repeated_words"):
            result["has_repeated_words"] = True
        ic = s.get("ignored_categories") or existing.get("ignored_categories")
        if ic:
            result["ignored_categories"] = list(ic)
        elif s.get("ignored") or existing.get("ignored"):
            result["ignored_categories"] = ["_all"]
        return result

    # Snapshot validation counts before mutation
    meta = cache.get_seg_meta(reciter)
    val_before = chapter_validation_counts(entries, chapter, meta)

    if updates.get("full_replace"):
        if len(matching) == 1:
            matching[0]["segments"] = [_make_seg(s) for s in updates["segments"]]
        else:
            entry_by_audio: dict[str, list[dict]] = defaultdict(list)
            for e in matching:
                audio = e.get("audio", "")
                if audio:
                    entry_by_audio[audio].append(e)
                e["segments"] = []

            for s in updates["segments"]:
                seg_audio = s.get("audio_url", "")
                if not seg_audio:
                    return {"error": (
                        "Rejected structural save for by_ayah: segment payload is "
                        "missing audio_url. Reload Inspector and try again."
                    )}, 400

                candidates = entry_by_audio.get(seg_audio, [])
                if len(candidates) != 1:
                    if len(candidates) == 0:
                        return {"error": (
                            "Rejected structural save for by_ayah: segment audio_url "
                            "does not belong to this chapter."
                        )}, 400
                    return {"error": (
                        "Rejected structural save for by_ayah: ambiguous audio_url "
                        "matched multiple chapter entries."
                    )}, 400

                candidates[0]["segments"].append(_make_seg(s))
    else:
        flat_segments = []
        for e in matching:
            for seg in e.get("segments", []):
                flat_segments.append(seg)

        for upd in updates["segments"]:
            idx = upd.get("index")
            if idx is not None and 0 <= idx < len(flat_segments):
                flat_segments[idx]["matched_ref"] = normalize_ref_with_wc(upd.get("matched_ref", ""))
                flat_segments[idx]["matched_text"] = upd.get("matched_text", "")
                if "confidence" in upd:
                    flat_segments[idx]["confidence"] = upd["confidence"]
                if upd.get("ignored_categories"):
                    flat_segments[idx]["ignored_categories"] = upd["ignored_categories"]

    # Backup before writing
    detailed_path = RECITATION_SEGMENTS_PATH / reciter / "detailed.json"
    segments_path = RECITATION_SEGMENTS_PATH / reciter / "segments.json"
    backup_file(detailed_path)
    backup_file(segments_path)

    # Write detailed.json atomically
    atomic_json_write(detailed_path, {"_meta": meta, "entries": entries})
    file_hash = file_sha256(detailed_path)

    # Rebuild segments.json
    rebuild_segments_json(reciter, entries)

    # Snapshot validation counts after mutation and write batch record
    val_after = chapter_validation_counts(entries, chapter, meta)
    operations = updates.get("operations", [])
    batch = {
        "schema_version": 1,
        "batch_id": uuid7(),
        "reciter": reciter,
        "chapter": chapter,
        "saved_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "save_mode": "full_replace" if updates.get("full_replace") else "patch",
        "file_hash_after": file_hash,
        "validation_summary_before": val_before,
        "validation_summary_after": val_after,
        "operations": operations,
    }
    history_path = RECITATION_SEGMENTS_PATH / reciter / "edit_history.jsonl"
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(batch, ensure_ascii=False) + "\n")

    # Invalidate cache
    cache.invalidate_seg_caches(reciter)

    return {"ok": True}
