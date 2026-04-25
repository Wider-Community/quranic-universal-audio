"""Per-segment detail-list builder for validate_reciter_segments.

Iterates entries and returns the detail lists (failed, low_confidence,
boundary_adj, cross_verse, audio_bleeding, repetitions, muqattaat,
qalqala) plus the verse_segments coverage map. Each detail item carries a
``classified_issues`` field — the full category list the segment matches
under the unified classifier (forward-compat for multi-category card
indicators on the frontend).
"""

from __future__ import annotations

from collections import defaultdict

from config import BOUNDARY_TAIL_DISPLAY_EXTRA, BOUNDARY_TAIL_K, LOW_CONFIDENCE_DETAIL_THRESHOLD, SHOW_BOUNDARY_PHONEMES
from services.phoneme_matching import get_phoneme_tails
from utils.formatting import format_ms
from utils.references import chapter_from_ref, seg_belongs_to_entry

from services.validation.classifier import (
    classify_flags,
    classify_segment,
)
from services.validation.registry import PER_SEGMENT_CATEGORIES


def _classified_issues_from_flags(flags: dict, *, detail: bool) -> list[str]:
    """Translate a classifier flags dict to a category list (registry order).

    Mirrors the public ``classify_segment`` output so detail items and the
    standalone classifier API agree on the field's contents.
    """
    cats: list[str] = []
    for cat in PER_SEGMENT_CATEGORIES:
        if flags.get(cat):
            cats.append(cat)
    if detail and flags.get("low_confidence_detail") and "low_confidence" not in cats:
        cats.append("low_confidence_detail")
    return cats


def _build_detail_lists(
    entries: list[dict],
    is_by_ayah: bool,
    word_counts: dict,
    canonical: dict | None,
    single_word_verses: set,
) -> dict:
    """Iterate entries and build all detail lists + verse_segments map.

    Returns a dict with keys:
      chapter_seg_idx, verse_segments,
      failed, low_confidence, boundary_adj, cross_verse,
      audio_bleeding, repetitions, muqattaat, qalqala.
    """
    failed: list[dict] = []
    low_confidence: list[dict] = []
    boundary_adj: list[dict] = []
    cross_verse: list[dict] = []
    audio_bleeding: list[dict] = []
    repetitions: list[dict] = []
    muqattaat: list[dict] = []
    qalqala: list[dict] = []
    chapter_seg_idx: dict[int, int] = {}
    verse_segments: dict[tuple[int, int], list] = defaultdict(list)

    for entry in entries:
        chapter = chapter_from_ref(entry["ref"])
        entry_ref = entry.get("ref", "")
        for seg in entry.get("segments", []):
            i = chapter_seg_idx.get(chapter, 0)
            chapter_seg_idx[chapter] = i + 1
            matched_ref = seg.get("matched_ref", "")
            confidence = seg.get("confidence", 0.0)
            t_start = seg.get("time_start", 0)
            t_end = seg.get("time_end", 0)

            if not matched_ref:
                failed.append({
                    "chapter": chapter, "seg_index": i,
                    "time": f"{format_ms(t_start)}-{format_ms(t_end)}",
                    "classified_issues": classify_segment(seg),
                })
                continue

            parts = matched_ref.split("-")
            if len(parts) != 2:
                # Malformed structural ref — fall back to a minimal flag check
                # so audio_bleeding / repetitions / low_confidence still surface.
                fallback_issues: list[str] = []
                if is_by_ayah and ":" in entry_ref and not seg_belongs_to_entry(matched_ref, entry_ref):
                    seg_start = matched_ref.split("-")[0]
                    seg_parts = seg_start.split(":")
                    matched_verse = f"{seg_parts[0]}:{seg_parts[1]}" if len(seg_parts) >= 2 else matched_ref
                    audio_bleeding.append({
                        "chapter": chapter, "seg_index": i, "entry_ref": entry_ref,
                        "matched_verse": matched_verse, "ref": matched_ref,
                        "confidence": round(confidence, 4),
                        "time": f"{format_ms(t_start)}-{format_ms(t_end)}",
                        "msg": f"audio {entry_ref} contains segment matching verse {matched_verse}",
                        "classified_issues": ["audio_bleeding"],
                    })
                    fallback_issues.append("audio_bleeding")
                if seg.get("wrap_word_ranges"):
                    repetitions.append({
                        "chapter": chapter, "seg_index": i, "ref": matched_ref,
                        "display_ref": matched_ref, "confidence": round(confidence, 4),
                        "time": f"{format_ms(t_start)}-{format_ms(t_end)}",
                        "text": seg.get("matched_text", ""),
                        "classified_issues": ["repetitions"],
                    })
                    fallback_issues.append("repetitions")
                if confidence < LOW_CONFIDENCE_DETAIL_THRESHOLD:
                    low_confidence.append({
                        "ref": matched_ref, "chapter": chapter, "seg_index": i,
                        "confidence": round(confidence, 4),
                        "classified_issues": ["low_confidence"] + fallback_issues,
                    })
                continue

            start_parts = parts[0].split(":")
            end_parts = parts[1].split(":")
            if len(start_parts) != 3 or len(end_parts) != 3:
                continue
            try:
                surah = int(start_parts[0])
                s_ayah = int(start_parts[1])
                s_word = int(start_parts[2])
                e_ayah = int(end_parts[1])
                e_word = int(end_parts[2])
            except (ValueError, IndexError):
                continue

            flags = classify_flags(
                seg, entry_ref, is_by_ayah,
                surah, s_ayah, e_ayah, s_word, e_word,
                single_word_verses, canonical,
            )
            classified = _classified_issues_from_flags(flags, detail=True)

            if flags["audio_bleeding"]:
                seg_start = matched_ref.split("-")[0]
                sp = seg_start.split(":")
                matched_verse = f"{sp[0]}:{sp[1]}" if len(sp) >= 2 else matched_ref
                audio_bleeding.append({
                    "chapter": chapter, "seg_index": i, "entry_ref": entry_ref,
                    "matched_verse": matched_verse, "ref": matched_ref,
                    "confidence": round(confidence, 4),
                    "time": f"{format_ms(t_start)}-{format_ms(t_end)}",
                    "msg": f"audio {entry_ref} contains segment matching verse {matched_verse}",
                    "classified_issues": classified,
                })

            if flags["repetitions"]:
                display_ref = matched_ref
                rp = matched_ref.split("-")
                if len(rp) == 2:
                    s_rp = rp[0].split(":")
                    e_rp = rp[1].split(":")
                    if len(s_rp) >= 2 and len(e_rp) >= 2 and s_rp[1] == e_rp[1]:
                        display_ref = f"{s_rp[0]}:{s_rp[1]}"
                repetitions.append({
                    "chapter": chapter, "seg_index": i, "ref": matched_ref,
                    "display_ref": display_ref, "confidence": round(confidence, 4),
                    "time": f"{format_ms(t_start)}-{format_ms(t_end)}",
                    "text": seg.get("matched_text", ""),
                    "classified_issues": classified,
                })

            if flags["low_confidence_detail"]:
                lp = matched_ref.split("-")
                display_ref = matched_ref
                if len(lp) == 2:
                    s = lp[0].split(":")
                    e = lp[1].split(":")
                    if len(s) >= 2 and len(e) >= 2:
                        display_ref = f"{s[0]}:{s[1]}" if s[1] == e[1] else f"{s[0]}:{s[1]}-{e[1]}"
                low_confidence.append({
                    "ref": display_ref, "chapter": chapter, "seg_index": i,
                    "confidence": round(confidence, 4),
                    "classified_issues": classified,
                })

            if flags["cross_verse"]:
                cross_verse.append({
                    "chapter": chapter, "seg_index": i, "ref": matched_ref,
                    "classified_issues": classified,
                })

            if flags["boundary_adj"]:
                item: dict = {
                    "chapter": chapter, "seg_index": i, "ref": matched_ref,
                    "verse_key": f"{surah}:{s_ayah}",
                    "classified_issues": classified,
                }
                if SHOW_BOUNDARY_PHONEMES and canonical and seg.get("phonemes_asr"):
                    display_n = BOUNDARY_TAIL_K + BOUNDARY_TAIL_DISPLAY_EXTRA
                    tails = get_phoneme_tails(seg["phonemes_asr"], matched_ref, canonical, display_n)
                    if tails:
                        item["gt_tail"] = " ".join(tails[0])
                        item["asr_tail"] = " ".join(tails[1])
                boundary_adj.append(item)

            if flags["muqattaat"]:
                muqattaat.append({
                    "chapter": chapter, "seg_index": i, "ref": matched_ref,
                    "classified_issues": classified,
                })

            if flags["qalqala"]:
                qalqala.append({
                    "chapter": chapter, "seg_index": i, "ref": matched_ref,
                    "qalqala_letter": flags["qalqala_letter"],
                    "end_of_verse": (e_word == word_counts.get((surah, e_ayah), 0)),
                    "classified_issues": classified,
                })

            # Accumulate verse coverage (3-tuple: word_from, word_to, seg_index)
            if s_ayah != e_ayah:
                for ayah in range(s_ayah, e_ayah + 1):
                    if ayah == s_ayah:
                        wc = word_counts.get((surah, ayah), s_word)
                        verse_segments[(surah, ayah)].append((s_word, wc, i))
                    elif ayah == e_ayah:
                        verse_segments[(surah, ayah)].append((1, e_word, i))
                    else:
                        wc = word_counts.get((surah, ayah), 1)
                        verse_segments[(surah, ayah)].append((1, wc, i))
            else:
                verse_segments[(surah, s_ayah)].append((s_word, e_word, i))

    return {
        "chapter_seg_idx": chapter_seg_idx,
        "verse_segments": verse_segments,
        "failed": failed,
        "low_confidence": low_confidence,
        "boundary_adj": boundary_adj,
        "cross_verse": cross_verse,
        "audio_bleeding": audio_bleeding,
        "repetitions": repetitions,
        "muqattaat": muqattaat,
        "qalqala": qalqala,
    }
