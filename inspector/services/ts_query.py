"""Query helpers for Timestamps-tab read-only data endpoints.

No Flask imports -- functions accept parameters and return plain dicts/lists.
"""

from constants import TS_AUDIO_CATEGORIES
from services.data_loader import (
    load_audio_urls,
    load_dk,
    load_qpc,
    load_timestamps,
)


def get_verse_data(reciter: str, verse_ref: str) -> dict | None:
    """Return full visualization payload for ``(reciter, verse_ref)``.

    Returns ``None`` when the reciter has no timestamps data or the verse_ref
    is not present — caller converts to HTTP 404 with the appropriate envelope.
    """
    data = load_timestamps(reciter)
    if not data:
        return {"_error": "reciter_not_found"}
    verse = data["verses"].get(verse_ref)
    if verse is None:
        return {"_error": "verse_not_found"}

    qpc = load_qpc()
    dk = load_dk()
    chapter = int(verse_ref.split(":")[0])

    # Build flat intervals list from per-word phones
    words_raw = verse.get("words", []) if isinstance(verse, dict) else verse
    intervals = []
    words_out = []

    is_compound = "-" in verse_ref
    if is_compound:
        start_part, end_part = verse_ref.split("-", 1)
        sp = start_part.split(":")
        ep = end_part.split(":")
        compound_surah = int(sp[0])
        compound_start_ayah = int(sp[1])
        compound_end_ayah = int(ep[1])
    else:
        compound_surah = compound_start_ayah = compound_end_ayah = 0

    cur_ayah = compound_start_ayah if is_compound else 0
    prev_word_idx = -1

    for w in words_raw:
        word_idx = w[0]
        w_start = w[1] / 1000
        w_end = w[2] / 1000
        letters_raw = w[3] if len(w) > 3 else []
        word_phones_raw = w[4] if len(w) > 4 else []

        if is_compound:
            if prev_word_idx >= 0 and word_idx <= prev_word_idx and cur_ayah < compound_end_ayah:
                cur_ayah += 1
            location = f"{compound_surah}:{cur_ayah}:{word_idx}"
            prev_word_idx = word_idx
        else:
            location = f"{verse_ref}:{word_idx}"
        text = qpc.get(location, {}).get("text", "")
        display_text = dk.get(location, {}).get("text", text)

        letters = []
        for lt in letters_raw:
            letters.append({
                "char": lt[0],
                "start": lt[1] / 1000 if lt[1] is not None else None,
                "end": lt[2] / 1000 if lt[2] is not None else None,
            })

        phone_start_idx = len(intervals)
        for ph in word_phones_raw:
            intervals.append({
                "phone": ph[0],
                "start": ph[1] / 1000,
                "end": ph[2] / 1000,
            })
        phoneme_indices = list(range(phone_start_idx, len(intervals)))

        words_out.append({
            "location": location,
            "text": text,
            "display_text": display_text,
            "start": w_start,
            "end": w_end,
            "phoneme_indices": phoneme_indices,
            "letters": letters,
        })

    # Audio URL
    audio_source = data["meta"].get("audio_source", "")
    audio_reciter = data["meta"].get("audio_reciter", reciter)
    audio_url = ""
    if audio_source:
        urls = load_audio_urls(audio_source, audio_reciter)
        audio_url = urls.get(verse_ref, urls.get(str(chapter), ""))

    # TS_AUDIO_CATEGORIES[0] is "by_ayah_audio" — the default/most common category.
    audio_category = data.get("audio_category", TS_AUDIO_CATEGORIES[0])
    time_start_ms = 0
    time_end_ms = 0

    if audio_category == "by_surah_audio":
        if words_raw:
            time_start_ms = words_raw[0][1]
            time_end_ms = words_raw[-1][2]
            offset_s = time_start_ms / 1000
            for word_obj in words_out:
                word_obj["start"] -= offset_s
                word_obj["end"] -= offset_s
                for lt in word_obj["letters"]:
                    if lt["start"] is not None:
                        lt["start"] -= offset_s
                    if lt["end"] is not None:
                        lt["end"] -= offset_s
            for iv in intervals:
                iv["start"] -= offset_s
                iv["end"] -= offset_s
    else:
        if intervals:
            time_end_ms = round(intervals[-1]["end"] * 1000)
        elif words_raw:
            time_end_ms = words_raw[-1][2]

    return {
        "reciter": reciter,
        "chapter": chapter,
        "verse_ref": verse_ref,
        "audio_url": audio_url,
        "audio_category": audio_category,
        "time_start_ms": time_start_ms,
        "time_end_ms": time_end_ms,
        "intervals": intervals,
        "words": words_out,
    }
