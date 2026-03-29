"""
Alignment Inspector Server

Flask server for browsing alignment timestamps, recitation segments, and audio.
"""
import argparse
import concurrent.futures
import hashlib
import json
import random
import re
import shutil
import statistics
import struct
import subprocess
import sys
import tempfile
import threading
import time as _time
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, jsonify, request, send_file, send_from_directory


def _uuid7() -> str:
    """Generate a UUIDv7 (time-ordered, RFC 9562) as a hyphenated string."""
    ts_ms = int(_time.time() * 1000)
    rand_bytes = uuid.uuid4().bytes
    uuid_int = (ts_ms & 0xFFFFFFFFFFFF) << 80
    uuid_int |= 0x7000 << 64  # version 7
    uuid_int |= (int.from_bytes(rand_bytes[:2], "big") & 0x0FFF) << 64
    uuid_int |= 0x8000000000000000  # variant 10
    uuid_int |= int.from_bytes(rand_bytes[2:10], "big") & 0x3FFFFFFFFFFFFFFF
    return str(uuid.UUID(int=uuid_int))


from config import (
    AUDIO_METADATA_PATH, AUDIO_PATH, CACHE_DIR,
    DICTIONARY_PATH, MODEL_PATH,
    RECITATION_SEGMENTS_PATH, SURAH_INFO_PATH, TIMESTAMPS_PATH,
    UNIFIED_DISPLAY_MAX_HEIGHT,
    ANIM_HIGHLIGHT_COLOR, ANIM_WORD_TRANSITION_DURATION,
    ANIM_CHAR_TRANSITION_DURATION, ANIM_TRANSITION_EASING,
    ANIM_WORD_SPACING, ANIM_LINE_HEIGHT, ANIM_FONT_SIZE,
    ANALYSIS_WORD_FONT_SIZE, ANALYSIS_LETTER_FONT_SIZE,
    SEG_FONT_SIZE, SEG_WORD_SPACING,
)

# Word text lookup (qpc_hafs.json: "1:1:1" -> {"text": "...", ...})
_QPC_PATH = Path(__file__).resolve().parent.parent / "quranic_universal_aligner" / "data" / "qpc_hafs.json"
_QPC: dict[str, dict] | None = None

# Digital Khatt display text lookup (digital_khatt_v2_script.json)
_DK_PATH = Path(__file__).resolve().parent.parent / "quranic_universal_aligner" / "data" / "digital_khatt_v2_script.json"
_DK: dict[str, dict] | None = None


_STOP_SIGNS = set('\u06D6\u06D7\u06D8\u06DA')  # sili, qili, small meem, jeem

# ── Validation helper (for auto-revalidation on save) ────────────────────

_VALIDATORS_DIR = Path(__file__).resolve().parent.parent / "validators"
if str(_VALIDATORS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_VALIDATORS_DIR.parent))


def _run_validation_log(reciter_dir: Path):
    """Run segment validation and write validation.log without printing to console."""
    import io as _io
    from datetime import datetime as _dt
    from validators.validate_segments import validate_reciter, load_word_counts

    surah_info_path = Path(__file__).resolve().parent.parent / "data" / "surah_info.json"
    wc = load_word_counts(surah_info_path)
    report_path = reciter_dir / "validation.log"

    buf = _io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf
    try:
        validate_reciter(reciter_dir, wc, verbose=True)
    finally:
        sys.stdout = old_stdout

    content = f"Generated: {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n" + buf.getvalue()
    report_path.write_text(content, encoding="utf-8")


def _word_has_stop(surah, ayah, word_num):
    """Check if a word in qpc_hafs.json contains a waqf stop sign."""
    qpc = _get_qpc()
    entry = qpc.get(f"{surah}:{ayah}:{word_num}")
    if not entry:
        return False
    return bool(_STOP_SIGNS & set(entry.get("text", "")))


def _get_qpc() -> dict[str, dict]:
    global _QPC
    if _QPC is None:
        if _QPC_PATH.exists():
            with open(_QPC_PATH, encoding="utf-8") as f:
                _QPC = json.load(f)
        else:
            _QPC = {}
    return _QPC


def _get_dk() -> dict[str, dict]:
    global _DK
    if _DK is None:
        if _DK_PATH.exists():
            with open(_DK_PATH, encoding="utf-8") as f:
                _DK = json.load(f)
        else:
            _DK = {}
    return _DK


def _dk_text_for_ref(ref: str) -> str:
    """Build Digital Khatt display text for a matched_ref like '1:7:1-1:7:5'."""
    if not ref:
        return ""
    dk = _get_dk()
    if not dk:
        return ""
    parts = ref.split("-")
    if len(parts) != 2:
        return ""
    start_parts = parts[0].split(":")
    end_parts = parts[1].split(":")
    if len(start_parts) != 3 or len(end_parts) != 3:
        return ""
    try:
        s_su, s_ay, s_w = int(start_parts[0]), int(start_parts[1]), int(start_parts[2])
        e_su, e_ay, e_w = int(end_parts[0]), int(end_parts[1]), int(end_parts[2])
    except ValueError:
        return ""
    wc = _get_word_counts()
    words = []
    su, ay, w = s_su, s_ay, s_w
    while (su, ay, w) <= (e_su, e_ay, e_w):
        entry = dk.get(f"{su}:{ay}:{w}")
        if entry:
            words.append(entry["text"])
        w += 1
        if w > wc.get((su, ay), 0):
            w = 1
            ay += 1
            # Handle surah boundary (shouldn't normally happen in a single ref)
            if ay > 300:
                break
    return " ".join(words)


# Import phonemizer (optional — used for reference resolution in segments)
try:
    from quranic_phonemizer import Phonemizer
    _HAS_PHONEMIZER = True
except Exception:
    _HAS_PHONEMIZER = False

app = Flask(__name__, static_folder="static")

# Phonemizer singleton
_phonemizer = None


def get_phonemizer():
    global _phonemizer
    if _phonemizer is None:
        if not _HAS_PHONEMIZER:
            raise RuntimeError("Phonemizer not available")
        _phonemizer = Phonemizer()
    return _phonemizer


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the main HTML page."""
    return send_from_directory("static", "index.html")


@app.route("/static/<path:filename>")
def serve_static(filename):
    """Serve static files."""
    return send_from_directory("static", filename)


# ---------------------------------------------------------------------------
# Timestamps tab (verse-keyed JSONL format)
# ---------------------------------------------------------------------------

_TS_CACHE: dict[str, dict] = {}  # reciter -> {meta, verses, audio_category}
_SEG_VERSES_CACHE: dict[str, tuple] = {}  # reciter -> (verses_dict, pad_ms)
_TS_RECITERS_CACHE: list[dict] | None = None


def _discover_ts_reciters() -> list[dict]:
    """Scan timestamps/{by_ayah_audio,by_surah_audio}/<reciter>/ for reciters.  Cached after first call."""
    global _TS_RECITERS_CACHE
    if _TS_RECITERS_CACHE is not None:
        return _TS_RECITERS_CACHE
    if not TIMESTAMPS_PATH.exists():
        _TS_RECITERS_CACHE = []
        return _TS_RECITERS_CACHE
    result = []
    for category in ("by_ayah_audio", "by_surah_audio"):
        cat_dir = TIMESTAMPS_PATH / category
        if not cat_dir.is_dir():
            continue
        for reciter_dir in sorted(cat_dir.iterdir()):
            if not reciter_dir.is_dir():
                continue
            ts_file = reciter_dir / "timestamps_full.json"
            if not ts_file.exists():
                ts_file = reciter_dir / "timestamps.json"
                if not ts_file.exists():
                    continue
            slug = reciter_dir.name
            name = slug.replace("_", " ").title()
            # Read _meta for audio_source — use _TS_CACHE if already loaded,
            # otherwise read only the first 512 bytes to avoid parsing multi-MB files
            audio_source = ""
            if slug in _TS_CACHE:
                audio_source = _TS_CACHE[slug].get("meta", {}).get("audio_source", "")
            else:
                try:
                    with open(ts_file, encoding="utf-8") as f:
                        head = f.read(512)
                    m = re.search(r'"audio_source"\s*:\s*"([^"]*)"', head)
                    if m:
                        audio_source = m.group(1)
                except OSError:
                    pass
            result.append({
                "slug": slug, "name": name,
                "audio_source": audio_source,
                "audio_category": category,
            })
    _TS_RECITERS_CACHE = result
    return result


def _load_timestamps(reciter: str) -> dict:
    """Load and cache a reciter's verse-keyed timestamps JSON."""
    if reciter in _TS_CACHE:
        return _TS_CACHE[reciter]
    # Find the file by scanning categories (prefer full, fall back to words-only)
    path = None
    for category in ("by_ayah_audio", "by_surah_audio"):
        full = TIMESTAMPS_PATH / category / reciter / "timestamps_full.json"
        basic = TIMESTAMPS_PATH / category / reciter / "timestamps.json"
        if full.exists():
            path = full
            break
        if basic.exists():
            path = basic
            break
    if path is None:
        return {}
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    meta = doc.pop("_meta", {})
    verses = doc  # remaining keys are verse refs
    result = {"meta": meta, "verses": verses, "audio_category": category}
    _TS_CACHE[reciter] = result
    return result


def _load_seg_verses(reciter: str) -> tuple[dict, int]:
    """Load segments.json verse data for boundary mismatch checking. Cached."""
    if reciter in _SEG_VERSES_CACHE:
        return _SEG_VERSES_CACHE[reciter]
    seg_path = RECITATION_SEGMENTS_PATH / reciter / "segments.json"
    if not seg_path.exists():
        return {}, 0
    with open(seg_path, encoding="utf-8") as f:
        doc = json.load(f)
    pad_ms = doc.get("_meta", {}).get("pad_ms", 0)
    verses = {k: v for k, v in doc.items() if k != "_meta"}
    _SEG_VERSES_CACHE[reciter] = (verses, pad_ms)
    return verses, pad_ms


_AUDIO_URL_CACHE: dict[str, dict] = {}


def _load_audio_urls(audio_source: str, reciter: str) -> dict:
    """Load verse/chapter URL map from data/audio/<audio_source>/<reciter>.json."""
    key = f"{audio_source}/{reciter}"
    if key in _AUDIO_URL_CACHE:
        return _AUDIO_URL_CACHE[key]
    path = AUDIO_METADATA_PATH / audio_source / f"{reciter}.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        urls = json.load(f)
    urls.pop("_meta", None)
    _AUDIO_URL_CACHE[key] = urls
    return urls


@app.route("/api/ts/config")
def ts_config():
    """Return display configuration for Timestamps tab."""
    return jsonify({
        "unified_display_max_height": UNIFIED_DISPLAY_MAX_HEIGHT,
        "anim_highlight_color": ANIM_HIGHLIGHT_COLOR,
        "anim_word_transition_duration": ANIM_WORD_TRANSITION_DURATION,
        "anim_char_transition_duration": ANIM_CHAR_TRANSITION_DURATION,
        "anim_transition_easing": ANIM_TRANSITION_EASING,
        "anim_word_spacing": ANIM_WORD_SPACING,
        "anim_line_height": ANIM_LINE_HEIGHT,
        "anim_font_size": ANIM_FONT_SIZE,
        "analysis_word_font_size": ANALYSIS_WORD_FONT_SIZE,
        "analysis_letter_font_size": ANALYSIS_LETTER_FONT_SIZE,
    })


@app.route("/api/seg/config")
def seg_config():
    """Return display configuration for Segments tab."""
    return jsonify({
        "seg_font_size": SEG_FONT_SIZE,
        "seg_word_spacing": SEG_WORD_SPACING,
    })


_SURAH_INFO_LITE: dict | None = None


@app.route("/api/surah-info")
def get_surah_info():
    """Return lightweight surah metadata: number -> {name_en, name_ar, num_verses}."""
    global _SURAH_INFO_LITE
    if _SURAH_INFO_LITE is None:
        with open(SURAH_INFO_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        _SURAH_INFO_LITE = {}
        for num, info in raw.items():
            _SURAH_INFO_LITE[num] = {
                "name_en": info.get("name_en", ""),
                "name_ar": info.get("name_ar", ""),
                "num_verses": info["num_verses"],
            }
    return jsonify(_SURAH_INFO_LITE)


@app.route("/api/ts/reciters")
def get_ts_reciters():
    """Return list of reciters with timestamps data."""
    reciters = _discover_ts_reciters()
    return jsonify(reciters)


@app.route("/api/ts/chapters/<reciter>")
def get_ts_chapters(reciter):
    """Return sorted list of chapter numbers derived from verse keys."""
    data = _load_timestamps(reciter)
    if not data:
        return jsonify({"error": "Reciter not found"}), 404
    chapters = sorted(set(int(k.split(":")[0]) for k in data["verses"]))
    return jsonify(chapters)


@app.route("/api/ts/verses/<reciter>/<int:chapter>")
def get_ts_verses(reciter, chapter):
    """Return verse refs and audio URLs for a chapter."""
    data = _load_timestamps(reciter)
    if not data:
        return jsonify({"error": "Reciter not found"}), 404

    prefix = f"{chapter}:"
    verse_refs = sorted(
        (k for k in data["verses"] if k.startswith(prefix)),
        key=lambda k: int(k.split(":")[1]),
    )
    if not verse_refs:
        return jsonify({"error": "Chapter not found"}), 404

    # Resolve audio URLs
    audio_source = data["meta"].get("audio_source", "")
    urls = _load_audio_urls(audio_source, reciter) if audio_source else {}

    verses = []
    for ref in verse_refs:
        verses.append({
            "ref": ref,
            "audio_url": urls.get(ref, urls.get(str(chapter), "")),
        })

    return jsonify({"verses": verses})


@app.route("/api/ts/data/<reciter>/<verse_ref>")
def get_ts_data(reciter, verse_ref):
    """Return full verse data for visualization (converts compact arrays to objects)."""
    data = _load_timestamps(reciter)
    if not data:
        return jsonify({"error": "Reciter not found"}), 404
    verse = data["verses"].get(verse_ref)
    if verse is None:
        return jsonify({"error": "Verse not found"}), 404

    qpc = _get_qpc()
    dk = _get_dk()
    chapter = int(verse_ref.split(":")[0])

    # Build flat intervals list from per-word phones (nested in w[4]).
    # Also build per-word phoneme_indices deterministically.
    # Handle both formats: full (dict with "words" key) and basic (plain array)
    words_raw = verse.get("words", []) if isinstance(verse, dict) else verse
    intervals = []
    words_out = []

    # For compound keys (cross-verse), resolve per-word locations correctly
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

    # Track verse boundary crossings for compound keys
    cur_ayah = compound_start_ayah if is_compound else 0
    prev_word_idx = -1

    for w in words_raw:
        word_idx = w[0]
        w_start = w[1] / 1000
        w_end = w[2] / 1000
        letters_raw = w[3] if len(w) > 3 else []
        word_phones_raw = w[4] if len(w) > 4 else []

        # Resolve word text from qpc_hafs and Digital Khatt
        if is_compound:
            # Detect verse boundary crossing (word_idx drops)
            if prev_word_idx >= 0 and word_idx <= prev_word_idx and cur_ayah < compound_end_ayah:
                cur_ayah += 1
            location = f"{compound_surah}:{cur_ayah}:{word_idx}"
            prev_word_idx = word_idx
        else:
            location = f"{verse_ref}:{word_idx}"
        text = qpc.get(location, {}).get("text", "")
        display_text = dk.get(location, {}).get("text", text)  # fallback to QPC

        # Convert letters
        letters = []
        for lt in letters_raw:
            letters.append({
                "char": lt[0],
                "start": lt[1] / 1000 if lt[1] is not None else None,
                "end": lt[2] / 1000 if lt[2] is not None else None,
            })

        # Build intervals from per-word phones
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
    audio_url = ""
    if audio_source:
        urls = _load_audio_urls(audio_source, reciter)
        audio_url = urls.get(verse_ref, urls.get(str(chapter), ""))

    # time_start/end offset based on audio category
    audio_category = data.get("audio_category", "by_ayah_audio")
    time_start_ms = 0
    time_end_ms = 0

    if audio_category == "by_surah_audio":
        # Timestamps are surah-relative; make them segment-relative
        # by subtracting the first word's start from all timestamps
        if words_raw:
            time_start_ms = words_raw[0][1]
            time_end_ms = words_raw[-1][2]
            offset_s = time_start_ms / 1000
            # Shift all timestamps to be relative to segment start
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
        # by_ayah: verse is the whole file (0 to last phone end)
        if intervals:
            time_end_ms = round(intervals[-1]["end"] * 1000)
        elif words_raw:
            time_end_ms = words_raw[-1][2]  # fallback: last word end_ms

    return jsonify({
        "reciter": reciter,
        "chapter": chapter,
        "verse_ref": verse_ref,
        "audio_url": audio_url,
        "time_start_ms": time_start_ms,
        "time_end_ms": time_end_ms,
        "intervals": intervals,
        "words": words_out,
    })


@app.route("/api/ts/random")
def get_ts_random():
    """Pick a random verse from a random reciter and return full data."""
    reciters = _discover_ts_reciters()
    if not reciters:
        return jsonify({"error": "No timestamps data"}), 500

    for _ in range(10):
        r = random.choice(reciters)
        data = _load_timestamps(r["slug"])
        if not data or not data["verses"]:
            continue
        verse_ref = random.choice(list(data["verses"].keys()))
        return get_ts_data(r["slug"], verse_ref)

    return jsonify({"error": "No verses found"}), 500


@app.route("/api/ts/random/<reciter>")
def get_ts_random_reciter(reciter):
    """Pick a random verse from the specified reciter and return full data."""
    data = _load_timestamps(reciter)
    if not data or not data["verses"]:
        return jsonify({"error": f"No timestamps data for reciter '{reciter}'"}), 404

    verse_ref = random.choice(list(data["verses"].keys()))
    return get_ts_data(reciter, verse_ref)


@app.route("/api/ts/validate/<reciter>")
def validate_ts_reciter(reciter):
    """Validate timestamp data and return categorised issues."""
    data = _load_timestamps(reciter)
    if not data:
        return jsonify({"error": "Reciter not found"}), 404

    meta = data["meta"]
    verses = data["verses"]

    word_counts = _get_word_counts()

    # ── 1. MFA failures (from meta) ──
    mfa_failures = []
    for fail in meta.get("mfa_failures", []):
        vk = fail.get("verse", "")
        chapter = int(vk.split(":")[0]) if vk and ":" in vk else 0
        ref = fail.get("ref", "?")
        mfa_failures.append({
            "verse_key": vk, "chapter": chapter,
            "ref": ref, "seg": fail.get("seg", "?"),
            "error": fail.get("error", "?"),
            "diff_ms": 0,
            "label": f"{vk} [{ref}]",
        })

    # ── 2. Missing word indices ──
    # Accumulate coverage across regular + compound keys, then check
    covered_per_verse: dict[tuple[int, int], set[int]] = {}
    for verse_key, verse_data in verses.items():
        words_list = verse_data.get("words", [])
        if "-" in verse_key:
            # Compound key: walk words detecting verse boundary crossings
            try:
                start_part, end_part = verse_key.split("-", 1)
                sp = start_part.split(":")
                ep = end_part.split(":")
                surah, start_ayah = int(sp[0]), int(sp[1])
                end_ayah = int(ep[1])
            except (ValueError, IndexError):
                continue
            cur_ayah = start_ayah
            prev_idx = -1
            for w in words_list:
                idx = w[0]
                if prev_idx >= 0 and idx <= prev_idx and cur_ayah < end_ayah:
                    cur_ayah += 1
                sa = (surah, cur_ayah)
                if sa not in covered_per_verse:
                    covered_per_verse[sa] = set()
                covered_per_verse[sa].add(idx)
                prev_idx = idx
        else:
            parts = verse_key.split(":")
            if len(parts) != 2:
                continue
            try:
                surah, ayah = int(parts[0]), int(parts[1])
            except ValueError:
                continue
            sa = (surah, ayah)
            if sa not in covered_per_verse:
                covered_per_verse[sa] = set()
            covered_per_verse[sa].update(w[0] for w in words_list)

    missing_words = []
    for (surah, ayah), covered in covered_per_verse.items():
        expected = word_counts.get((surah, ayah))
        if expected is None:
            continue
        missing = sorted(set(range(1, expected + 1)) - covered)
        if missing:
            verse_key_label = f"{surah}:{ayah}"
            missing_words.append({
                "verse_key": verse_key_label, "chapter": surah,
                "missing": missing, "count": len(missing),
                "diff_ms": len(missing) * 1000,
                "label": f"{verse_key_label} [-{len(missing)}w]",
            })
    missing_words.sort(key=lambda x: x["diff_ms"], reverse=True)

    # ── 3. Boundary mismatches ──
    seg_verses, seg_pad_ms = _load_seg_verses(reciter)
    tolerance = 2 * seg_pad_ms if seg_pad_ms > 0 else 500
    boundary_mismatches = []
    for verse_key, verse_data in verses.items():
        if verse_key not in seg_verses:
            continue
        words_raw = verse_data.get("words", [])
        segs = seg_verses[verse_key]
        if not words_raw or not segs:
            continue
        parts = verse_key.split(":")
        chapter = int(parts[0]) if len(parts) >= 1 else 0
        ts_first, ts_last = words_raw[0][1], words_raw[-1][2]
        seg_first, seg_last = segs[0][2], segs[-1][3]

        for side, ts_ms, seg_ms in [("start", ts_first, seg_first), ("end", ts_last, seg_last)]:
            diff = abs(ts_ms - seg_ms)
            if diff > tolerance:
                boundary_mismatches.append({
                    "verse_key": verse_key, "chapter": chapter,
                    "side": side, "diff_ms": round(diff),
                    "ts_ms": round(ts_ms), "seg_ms": round(seg_ms),
                    "label": f"{verse_key} [{round(diff)}ms {side}]",
                })
    boundary_mismatches.sort(key=lambda x: x["diff_ms"], reverse=True)

    return jsonify({
        "mfa_failures": mfa_failures,
        "missing_words": missing_words,
        "boundary_mismatches": boundary_mismatches,
        "meta": {"has_segments": bool(seg_verses), "tolerance_ms": tolerance},
    })


@app.route("/audio/<reciter>/<filename>")
def serve_audio(reciter, filename):
    """Serve audio files."""
    audio_path = AUDIO_PATH / reciter / filename

    if not audio_path.exists():
        return jsonify({"error": "Audio file not found"}), 404

    mime_types = {
        ".flac": "audio/flac",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".ogg": "audio/ogg",
    }
    mime_type = mime_types.get(audio_path.suffix.lower(), "audio/mpeg")
    return send_file(audio_path, mimetype=mime_type)


# ---------------------------------------------------------------------------
# Segment inspector endpoints
# ---------------------------------------------------------------------------

# Cache parsed detailed.json per reciter
_SEG_CACHE: dict[str, list[dict]] = {}
_SEG_META_CACHE: dict[str, dict] = {}
_SEG_RECITERS_CACHE: list[dict] | None = None

# Waveform peaks cache — { reciter: { audio_url: { duration_ms, peaks } } }
_PEAKS_CACHE: dict[str, dict[str, dict]] = {}
_PEAKS_LOCK = threading.Lock()
_PEAKS_COMPUTING: set[str] = set()  # keys currently being computed in background

_PEAKS_DIR = CACHE_DIR / "peaks"


def _compute_audio_peaks(audio_url: str) -> dict | None:
    """Compute waveform peaks for an audio URL. Returns {duration_ms, peaks} or None."""
    url_hash = hashlib.sha256(audio_url.encode()).hexdigest()[:32]
    cache_path = _PEAKS_DIR / f"{url_hash}.json"
    if cache_path.exists():
        try:
            with open(cache_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Decode to raw mono 16-bit PCM at 8kHz via ffmpeg (reads URLs directly)
    try:
        result = subprocess.run(
            ["ffmpeg", "-i", audio_url, "-f", "s16le", "-ac", "1", "-ar", "8000",
             "-v", "quiet", "-"],
            capture_output=True, timeout=300,
        )
        if result.returncode != 0 or len(result.stdout) < 4:
            return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None

    raw = result.stdout
    num_samples = len(raw) // 2
    if num_samples == 0:
        return None
    samples = struct.unpack(f"<{num_samples}h", raw)

    duration_ms = int(num_samples / 8000 * 1000)
    duration_sec = num_samples / 8000
    num_buckets = max(100, int(duration_sec * 10))

    block_size = max(1, num_samples // num_buckets)
    peaks = []
    for i in range(num_buckets):
        start = i * block_size
        end = min(start + block_size, num_samples)
        if start >= num_samples:
            break
        block = samples[start:end]
        mn = min(block) / 32768.0
        mx = max(block) / 32768.0
        peaks.append([round(mn, 4), round(mx, 4)])

    data = {"duration_ms": duration_ms, "peaks": peaks}

    # Write to disk cache
    _PEAKS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(data, f, separators=(",", ":"))
    except OSError:
        pass

    return data


def _get_peaks_for_reciter(reciter: str, chapter_filter: set[int] | None = None) -> dict:
    """Compute and cache peaks for a reciter's audio URLs. Returns {url: peaks_data}."""
    entries = _load_detailed(reciter)
    if not entries:
        return {}

    # Collect unique audio URLs (optionally filtered by chapter)
    urls = {}  # url -> True
    for entry in entries:
        chapter = _chapter_from_ref(entry["ref"])
        if chapter_filter and chapter not in chapter_filter:
            continue
        url = entry.get("audio", "")
        if url and url not in urls:
            urls[url] = True

    # Check what's already cached in memory
    with _PEAKS_LOCK:
        cached = _PEAKS_CACHE.get(reciter, {})

    to_compute = [u for u in urls if u not in cached]
    if not to_compute:
        return {u: cached[u] for u in urls if u in cached}

    # Compute missing peaks in parallel
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        future_to_url = {pool.submit(_compute_audio_peaks, u): u for u in to_compute}
        for future in concurrent.futures.as_completed(future_to_url):
            url = future_to_url[future]
            try:
                data = future.result()
                if data:
                    results[url] = data
            except Exception:
                pass

    # Merge into memory cache
    with _PEAKS_LOCK:
        if reciter not in _PEAKS_CACHE:
            _PEAKS_CACHE[reciter] = {}
        _PEAKS_CACHE[reciter].update(results)
        all_cached = _PEAKS_CACHE[reciter]

    return {u: all_cached[u] for u in urls if u in all_cached}


def _chapter_from_ref(ref: str) -> int:
    """Extract chapter (surah) number from a ref string.

    Handles both surah-level refs (e.g. ``"1"``) and verse-level refs
    (e.g. ``"1:1"``).
    """
    return int(ref.split(":")[0])


def _seg_belongs_to_entry(seg_ref: str, entry_ref: str) -> bool:
    """Check if a segment's matched_ref falls within the verse of an entry's ref.

    For by_ayah, entry_ref is like ``"1:1"`` (surah:verse).
    seg_ref may be ``"1:1:1-1:1:4"`` (cross-word) or ``"1:1"`` etc.
    A segment belongs to an entry if the surah:verse prefix matches.
    """
    if not seg_ref or not entry_ref:
        return False
    # Extract surah:verse from the start of seg_ref
    seg_parts = seg_ref.split("-")[0].split(":")
    entry_parts = entry_ref.split(":")
    if len(entry_parts) >= 2 and len(seg_parts) >= 2:
        return seg_parts[0] == entry_parts[0] and seg_parts[1] == entry_parts[1]
    # Surah-level entry: match by chapter only
    return seg_parts[0] == entry_parts[0]


def _load_detailed(reciter: str) -> list[dict]:
    """Load and cache all entries from a reciter's detailed.json."""
    if reciter in _SEG_CACHE:
        return _SEG_CACHE[reciter]
    path = RECITATION_SEGMENTS_PATH / reciter / "detailed.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    if "_meta" in doc:
        _SEG_META_CACHE[reciter] = doc["_meta"]
    entries = doc.get("entries", [])
    _SEG_CACHE[reciter] = entries
    # Fallback: if detailed.json had no _meta, try segments.json
    if reciter not in _SEG_META_CACHE:
        seg_path = path.parent / "segments.json"
        if seg_path.exists():
            with open(seg_path, encoding="utf-8") as sf:
                try:
                    seg_doc = json.load(sf)
                    if "_meta" in seg_doc:
                        _SEG_META_CACHE[reciter] = seg_doc["_meta"]
                except json.JSONDecodeError:
                    pass
    return entries


@app.route("/api/seg/reciters")
def get_seg_reciters():
    """List reciters that have segment extraction results.

    Returns list of ``{slug, name, audio_source}`` objects.
    ``audio_source`` is read from the ``_meta`` of ``segments.json``.
    """
    global _SEG_RECITERS_CACHE
    if _SEG_RECITERS_CACHE is not None:
        return jsonify(_SEG_RECITERS_CACHE)
    if not RECITATION_SEGMENTS_PATH.exists():
        return jsonify([])
    result = []
    for d in sorted(RECITATION_SEGMENTS_PATH.iterdir(), key=lambda p: p.name):
        if not d.is_dir() or not (d / "detailed.json").exists():
            continue
        slug = d.name
        name = slug.replace("_", " ").title()
        audio_source = ""
        seg_path = d / "segments.json"
        if seg_path.exists():
            with open(seg_path, encoding="utf-8") as f:
                try:
                    seg_doc = json.load(f)
                    audio_source = seg_doc.get("_meta", {}).get("audio_source", "")
                except json.JSONDecodeError:
                    pass
        result.append({"slug": slug, "name": name, "audio_source": audio_source})
    _SEG_RECITERS_CACHE = result
    return jsonify(result)


@app.route("/api/seg/chapters/<reciter>")
def get_seg_chapters(reciter):
    """Return list of chapter numbers available for a reciter."""
    entries = _load_detailed(reciter)
    if not entries:
        return jsonify({"error": "Reciter not found"}), 404
    chapters = sorted(set(_chapter_from_ref(e["ref"]) for e in entries))
    return jsonify(chapters)


@app.route("/api/seg/data/<reciter>/<int:chapter>")
def get_seg_data(reciter, chapter):
    """Return segments, audio URL, summary, and issues for a chapter."""
    entries = _load_detailed(reciter)
    matching = [e for e in entries if _chapter_from_ref(e["ref"]) == chapter]
    if not matching:
        return jsonify({"error": "Chapter not found"}), 404

    # For surah-level data there's one entry; for verse-level, merge all
    audio_url = matching[0].get("audio", "")

    # Build segment list (times are in ms)
    segments = []
    idx = 0
    for entry_idx, entry in enumerate(matching):
        entry_audio = entry.get("audio", "")
        for seg in entry.get("segments", []):
            t_start = seg.get("time_start", 0)
            t_end = seg.get("time_end", 0)
            mref = seg.get("matched_ref", "")
            segments.append({
                "index": idx,
                "entry_idx": entry_idx,
                "time_start": t_start,
                "time_end": t_end,
                "matched_ref": mref,
                "matched_text": seg.get("matched_text", ""),
                "display_text": _dk_text_for_ref(mref),
                "confidence": round(seg.get("confidence", 0.0), 4),
                "audio_url": entry_audio,
            })
            idx += 1

    # Optional verse filter
    verse_filter = request.args.get("verse")
    if verse_filter:
        prefix = f"{chapter}:{verse_filter}:"
        segments = [s for s in segments if s["matched_ref"].startswith(prefix)]

    # Compute summary
    matched = [s for s in segments if s["matched_ref"]]
    failed = [s for s in segments if not s["matched_ref"]]
    confidences = [s["confidence"] for s in matched]

    # Speech / silence stats
    speech_durations = [s["time_end"] - s["time_start"] for s in segments]
    total_speech = sum(speech_durations)
    pad_ms = _SEG_META_CACHE.get(reciter, {}).get("pad_ms", 0)
    silence_durations = []
    for i in range(len(segments) - 1):
        if segments[i]["entry_idx"] == segments[i + 1]["entry_idx"]:
            gap = segments[i + 1]["time_start"] - segments[i]["time_end"] + 2 * pad_ms
            if gap > 0:
                silence_durations.append(gap)
    total_silence = sum(silence_durations)

    # Issue indices
    issue_indices = []
    for s in segments:
        if not s["matched_ref"]:
            issue_indices.append(s["index"])
        elif s["confidence"] < 0.60:
            issue_indices.append(s["index"])

    # Missing verses (compare to surah_info via cached word counts)
    missing_verses = []
    wc = _get_word_counts()
    expected_verses = {v for (s, v) in wc if s == chapter}
    if expected_verses:
        found_verses = set()
        for s in segments:
            ref = s["matched_ref"]
            if ref:
                parts = ref.split("-")
                if len(parts) == 2:
                    start = parts[0].split(":")
                    end = parts[1].split(":")
                    if len(start) >= 2:
                        try:
                            for v in range(int(start[1]), int(end[1]) + 1):
                                found_verses.add(v)
                        except (ValueError, IndexError):
                            pass
        missing_verses = sorted(expected_verses - found_verses)

    summary = {
        "total_segments": len(segments),
        "matched_segments": len(matched),
        "failed_segments": len(failed),
        "conf_min": round(min(confidences), 4) if confidences else 0,
        "conf_median": round(statistics.median(confidences), 4) if confidences else 0,
        "conf_mean": round(statistics.mean(confidences), 4) if confidences else 0,
        "conf_max": round(max(confidences), 4) if confidences else 0,
        "below_60": sum(1 for c in confidences if c < 0.60),
        "below_80": sum(1 for c in confidences if c < 0.80),
        "total_speech_ms": round(total_speech),
        "avg_segment_ms": round(total_speech / len(segments)) if segments else 0,
        "total_silence_ms": round(total_silence),
        "avg_silence_ms": round(total_silence / len(silence_durations)) if silence_durations else 0,
        "issue_indices": issue_indices,
        "missing_verses": [f"{chapter}:{v}" for v in missing_verses],
    }

    # Build verse word counts for display shortening (s:v:1-s:v:N → s:v)
    verse_word_counts = {}
    for (s, v), n in wc.items():
        if s == chapter:
            verse_word_counts[f"{chapter}:{v}"] = n

    return jsonify({
        "audio_url": audio_url,
        "segments": segments,
        "summary": summary,
        "verse_word_counts": verse_word_counts,
    })


@app.route("/api/seg/all/<reciter>")
def get_seg_all(reciter):
    """Return all segments across all chapters for a reciter."""
    entries = _load_detailed(reciter)
    if not entries:
        return jsonify({"error": "Reciter not found"}), 404

    segments = []
    audio_by_chapter = {}
    chapter_seg_idx = {}  # chapter -> next index (running counter)

    for entry_idx, entry in enumerate(entries):
        chapter = _chapter_from_ref(entry["ref"])
        entry_audio = entry.get("audio", "")
        if str(chapter) not in audio_by_chapter:
            audio_by_chapter[str(chapter)] = entry_audio
        for seg in entry.get("segments", []):
            idx = chapter_seg_idx.get(chapter, 0)
            chapter_seg_idx[chapter] = idx + 1
            mref = seg.get("matched_ref", "")
            # Assign stable segment_uid if missing (persists on next save)
            seg_uid = seg.get("segment_uid") or ""
            if not seg_uid:
                seg_uid = _uuid7()
                seg["segment_uid"] = seg_uid
            segments.append({
                "chapter":      chapter,
                "entry_idx":    entry_idx,
                "index":        idx,
                "segment_uid":  seg_uid,
                "time_start":   seg.get("time_start", 0),
                "time_end":     seg.get("time_end", 0),
                "matched_ref":  mref,
                "matched_text": seg.get("matched_text", ""),
                "display_text": _dk_text_for_ref(mref),
                "confidence":   round(seg.get("confidence", 0.0), 4),
                "audio_url":    entry_audio,
            })

    verse_word_counts = {}
    for (surah, ayah), n in _get_word_counts().items():
        verse_word_counts[f"{surah}:{ayah}"] = n

    return jsonify({
        "segments": segments,
        "audio_by_chapter": audio_by_chapter,
        "verse_word_counts": verse_word_counts,
        "pad_ms": _SEG_META_CACHE.get(reciter, {}).get("pad_ms", 0),
    })


@app.route("/api/seg/peaks/<reciter>")
def get_seg_peaks(reciter):
    """Return pre-computed waveform peaks for a reciter's audio files."""
    entries = _load_detailed(reciter)
    if not entries:
        return jsonify({"error": "Reciter not found"}), 404

    # Optional chapter filter
    chapters_param = request.args.get("chapters", "")
    chapter_filter = None
    if chapters_param:
        try:
            chapter_filter = {int(c) for c in chapters_param.split(",") if c.strip()}
        except ValueError:
            pass

    # Collect all target URLs to know total count
    target_urls = set()
    for entry in entries:
        ch = _chapter_from_ref(entry["ref"])
        if chapter_filter and ch not in chapter_filter:
            continue
        url = entry.get("audio", "")
        if url:
            target_urls.add(url)

    # Return whatever is already cached
    with _PEAKS_LOCK:
        cached = _PEAKS_CACHE.get(reciter, {})
    result = {u: cached[u] for u in target_urls if u in cached}
    complete = len(result) >= len(target_urls)

    # Start background computation for missing URLs
    cache_key = f"{reciter}:{chapters_param}"
    if not complete and cache_key not in _PEAKS_COMPUTING:
        _PEAKS_COMPUTING.add(cache_key)

        def _bg():
            try:
                _get_peaks_for_reciter(reciter, chapter_filter)
            finally:
                _PEAKS_COMPUTING.discard(cache_key)

        threading.Thread(target=_bg, daemon=True).start()

    return jsonify({"peaks": result, "complete": complete})


@app.route("/api/seg/resolve_ref")
def resolve_ref():
    """Resolve a word-range reference to its Arabic text via the phonemizer."""
    ref = request.args.get("ref", "").strip()
    if not ref:
        return jsonify({"error": "No ref provided"}), 400
    if not _HAS_PHONEMIZER:
        return jsonify({"error": "Phonemizer not available"}), 503
    try:
        pm = get_phonemizer()
        result = pm.phonemize(ref=ref)
        mapping = result.get_mapping()
        text = " ".join(w.text for w in mapping.words)
        display_text = _dk_text_for_ref(ref)
        return jsonify({"text": text, "display_text": display_text or text})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


def _normalize_ref(ref: str) -> str:
    """Normalize a short ref to canonical surah:ayah:word-surah:ayah:word format.

    Handles: "1:7" -> "1:7:1-1:7:N", "1:7:3" -> "1:7:3-1:7:3",
             "1:7-1:8" -> "1:7:1-1:8:N"
    """
    if not ref:
        return ref
    # Load word counts lazily
    wc = _get_word_counts()
    parts = ref.split("-")
    if len(parts) == 2:
        start = parts[0].split(":")
        end = parts[1].split(":")
        if len(start) == 3 and len(end) == 3:
            return ref  # Already canonical
        if len(start) == 2 and len(end) == 2:
            # "1:7-1:8" -> "1:7:1-1:8:N"
            try:
                e_surah, e_ayah = int(end[0]), int(end[1])
                e_wc = wc.get((e_surah, e_ayah), 1)
                return f"{start[0]}:{start[1]}:1-{end[0]}:{end[1]}:{e_wc}"
            except ValueError:
                return ref
    elif len(parts) == 1:
        colons = ref.split(":")
        if len(colons) == 2:
            # "1:7" -> "1:7:1-1:7:N"
            try:
                surah, ayah = int(colons[0]), int(colons[1])
                n = wc.get((surah, ayah), 1)
                return f"{surah}:{ayah}:1-{surah}:{ayah}:{n}"
            except ValueError:
                return ref
        elif len(colons) == 3:
            # "1:7:3" -> "1:7:3-1:7:3"
            return f"{ref}-{ref}"
    return ref


_WORD_COUNTS_CACHE: dict[tuple[int, int], int] | None = None


def _get_word_counts() -> dict[tuple[int, int], int]:
    """Load and cache word counts from surah_info.json."""
    global _WORD_COUNTS_CACHE
    if _WORD_COUNTS_CACHE is not None:
        return _WORD_COUNTS_CACHE
    wc: dict[tuple[int, int], int] = {}
    sip = SURAH_INFO_PATH
    if not sip.exists():
        sip = RECITATION_SEGMENTS_PATH.parent / "surah_info.json"
    if sip.exists():
        with open(sip, encoding="utf-8") as f:
            si = json.load(f)
        for surah_str, data in si.items():
            for v in data["verses"]:
                wc[(int(surah_str), v["verse"])] = v["num_words"]
    _WORD_COUNTS_CACHE = wc
    return wc


@app.route("/api/seg/save/<reciter>/<int:chapter>", methods=["POST"])
def save_seg_data(reciter, chapter):
    """Save edited segments back to detailed.json and segments.json."""
    updates = request.get_json()
    if not updates or "segments" not in updates:
        return jsonify({"error": "Missing segments in request body"}), 400

    entries = _load_detailed(reciter)
    if not entries:
        return jsonify({"error": "Reciter not found"}), 404

    matching = [e for e in entries if _chapter_from_ref(e["ref"]) == chapter]
    if not matching:
        return jsonify({"error": "Chapter not found"}), 404

    # Build lookup of existing segments by (time_start, time_end) for phonemes_asr preservation
    existing_by_time = {}
    for e in matching:
        for seg in e.get("segments", []):
            key = (seg.get("time_start", 0), seg.get("time_end", 0))
            existing_by_time[key] = seg

    def _make_seg(s):
        existing = existing_by_time.get((s.get("time_start", 0), s.get("time_end", 0)), {})
        phonemes = s.get("phonemes_asr", "") or existing.get("phonemes_asr", "")
        seg_uid = s.get("segment_uid", "") or existing.get("segment_uid", "")
        return {
            "segment_uid": seg_uid,
            "time_start": s.get("time_start", 0),
            "time_end": s.get("time_end", 0),
            "matched_ref": _normalize_ref(s.get("matched_ref", "")),
            "matched_text": s.get("matched_text", ""),
            "confidence": s.get("confidence", 0.0),
            "phonemes_asr": phonemes,
        }

    # Edit history: snapshot validation counts before mutation
    meta = _SEG_META_CACHE.get(reciter, {})
    val_before = _chapter_validation_counts(entries, chapter, meta)

    if updates.get("full_replace"):
        if len(matching) == 1:
            # by_surah: single entry, replace directly
            matching[0]["segments"] = [_make_seg(s) for s in updates["segments"]]
        else:
            # by_ayah: preserve segment ownership by source audio entry.
            # Never redistribute by matched_ref, which can silently "move"
            # segments across verse audio files and mask audio-bleeding issues.
            entry_by_audio: dict[str, list[dict]] = defaultdict(list)
            for e in matching:
                audio = e.get("audio", "")
                if audio:
                    entry_by_audio[audio].append(e)
                e["segments"] = []

            for s in updates["segments"]:
                seg_audio = s.get("audio_url", "")
                if not seg_audio:
                    return jsonify({
                        "error": (
                            "Rejected structural save for by_ayah: segment payload is "
                            "missing audio_url. Reload Inspector and try again."
                        )
                    }), 400

                candidates = entry_by_audio.get(seg_audio, [])
                if len(candidates) != 1:
                    if len(candidates) == 0:
                        return jsonify({
                            "error": (
                                "Rejected structural save for by_ayah: segment audio_url "
                                "does not belong to this chapter."
                            )
                        }), 400
                    return jsonify({
                        "error": (
                            "Rejected structural save for by_ayah: ambiguous audio_url "
                            "matched multiple chapter entries."
                        )
                    }), 400

                candidates[0]["segments"].append(_make_seg(s))
    else:
        # Patch mode: update individual segments by running index across all entries
        flat_segments = []
        for e in matching:
            for pos, s in enumerate(e.get("segments", [])):
                flat_segments.append(s)

        for upd in updates["segments"]:
            idx = upd.get("index")
            if idx is not None and 0 <= idx < len(flat_segments):
                flat_segments[idx]["matched_ref"] = _normalize_ref(upd.get("matched_ref", ""))
                flat_segments[idx]["matched_text"] = upd.get("matched_text", "")
                if "confidence" in upd:
                    flat_segments[idx]["confidence"] = upd["confidence"]

    # Backup before writing (single-level undo)
    detailed_path = RECITATION_SEGMENTS_PATH / reciter / "detailed.json"
    segments_path = RECITATION_SEGMENTS_PATH / reciter / "segments.json"
    if detailed_path.exists():
        shutil.copy2(detailed_path, detailed_path.with_suffix(".json.bak"))
    if segments_path.exists():
        shutil.copy2(segments_path, segments_path.with_suffix(".json.bak"))

    # Write detailed.json
    with open(detailed_path, "w", encoding="utf-8") as f:
        json.dump({"_meta": meta, "entries": entries}, f, ensure_ascii=False)

    # Compute file hash for tamper detection
    file_hash = "sha256:" + hashlib.sha256(detailed_path.read_bytes()).hexdigest()

    # Rebuild segments.json
    _rebuild_segments_json(reciter, entries)

    # Edit history: snapshot validation counts after mutation and write batch record
    val_after = _chapter_validation_counts(entries, chapter, meta)
    operations = updates.get("operations", [])
    batch = {
        "schema_version": 1,
        "batch_id": _uuid7(),
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
    global _SEG_RECITERS_CACHE
    _SEG_CACHE.pop(reciter, None)
    _SEG_META_CACHE.pop(reciter, None)
    _SEG_VERSES_CACHE.pop(reciter, None)
    _SEG_RECITERS_CACHE = None

    # Auto-revalidate in background thread so save returns immediately
    threading.Thread(
        target=lambda: _run_validation_log(RECITATION_SEGMENTS_PATH / reciter),
        daemon=True,
    ).start()

    return jsonify({"ok": True})


@app.route("/api/seg/undo/<reciter>", methods=["POST"])
def undo_seg_save(reciter):
    """Restore detailed.json and segments.json from .bak files (single-level undo)."""
    detailed_bak = RECITATION_SEGMENTS_PATH / reciter / "detailed.json.bak"
    segments_bak = RECITATION_SEGMENTS_PATH / reciter / "segments.json.bak"

    if not detailed_bak.exists():
        return jsonify({"error": "No undo backup available"}), 404

    detailed_path = RECITATION_SEGMENTS_PATH / reciter / "detailed.json"
    segments_path = RECITATION_SEGMENTS_PATH / reciter / "segments.json"

    # Read last edit_history record to link the revert
    history_path = RECITATION_SEGMENTS_PATH / reciter / "edit_history.jsonl"
    last_batch_id = None
    last_chapter = None
    if history_path.exists():
        try:
            lines = history_path.read_text(encoding="utf-8").strip().splitlines()
            if lines:
                last_record = json.loads(lines[-1])
                last_batch_id = last_record.get("batch_id")
                last_chapter = last_record.get("chapter")
        except (json.JSONDecodeError, OSError):
            pass

    # Restore from backup
    shutil.copy2(detailed_bak, detailed_path)
    if segments_bak.exists():
        shutil.copy2(segments_bak, segments_path)

    # Compute file hash of restored file
    file_hash = "sha256:" + hashlib.sha256(detailed_path.read_bytes()).hexdigest()

    # Append revert record to edit history (append-only, never mutates old records)
    revert = {
        "schema_version": 1,
        "batch_id": _uuid7(),
        "reverts_batch_id": last_batch_id,
        "reciter": reciter,
        "chapter": last_chapter,
        "saved_at_utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "file_hash_after": file_hash,
        "operations": [],
    }
    with open(history_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(revert, ensure_ascii=False) + "\n")

    # Remove backup files (single-level undo only)
    detailed_bak.unlink()
    if segments_bak.exists():
        segments_bak.unlink()

    # Invalidate caches
    global _SEG_RECITERS_CACHE
    _SEG_CACHE.pop(reciter, None)
    _SEG_META_CACHE.pop(reciter, None)
    _SEG_VERSES_CACHE.pop(reciter, None)
    _SEG_RECITERS_CACHE = None

    # Re-validate in background
    threading.Thread(
        target=lambda: _run_validation_log(RECITATION_SEGMENTS_PATH / reciter),
        daemon=True,
    ).start()

    return jsonify({"ok": True})


def _seg_sort_key(k):
    """Sort key for segments.json: regular 'sura:ayah' and cross-verse 'sura:ayah:word-sura:ayah:word'."""
    parts = k.split("-")
    start = parts[0].split(":")
    return tuple(int(x) for x in start)


def _rebuild_segments_json(reciter: str, entries: list[dict]):
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
                # Cross-verse: store under full matched_ref key
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
    for key in sorted(verse_data.keys(), key=_seg_sort_key):
        seg_doc[key] = verse_data[key]
    with open(segments_path, "w", encoding="utf-8") as f:
        json.dump(seg_doc, f, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Validation constants and helpers (shared by validate endpoint and edit history)
# ---------------------------------------------------------------------------
import unicodedata as _ud

_MUQATTAAT_VERSES = {
    (2,1),(3,1),(7,1),(10,1),(11,1),(12,1),(13,1),(14,1),(15,1),
    (19,1),(20,1),(26,1),(27,1),(28,1),(29,1),(30,1),(31,1),(32,1),
    (36,1),(38,1),(40,1),(41,1),(42,1),(42,2),(43,1),(44,1),(45,1),
    (46,1),(50,1),(68,1),
}
_STANDALONE_REFS = {
    (9,13,13),(16,16,1),(43,35,1),(70,11,1),(79,27,6),
    (37,9,1),(37,24,1),(44,37,9),(46,35,22),(44,28,1),
}
_STANDALONE_WORDS = {"كلا", "ذلك", "سبحنهۥ"}
_STRIP_CHARS = set("\u0640\u06de\u06e6\u06e9\u200f")


def _strip_quran_deco(text):
    """Strip Quranic decoration and diacritics for bare-skeleton comparison."""
    text = _ud.normalize("NFD", text)
    out = []
    for ch in text:
        if ch in _STRIP_CHARS:
            continue
        if _ud.category(ch) == "Mn":
            continue
        out.append(ch)
    return "".join(out).strip()


def _chapter_validation_counts(entries: list, chapter: int, meta: dict) -> dict:
    """Count validation issues for a single chapter. Returns {category: count}."""
    word_counts = _get_word_counts()
    single_word_verses = {k for k, v in word_counts.items() if v == 1}
    is_by_ayah = "by_ayah" in meta.get("audio_source", "")

    counts = {
        "failed": 0, "low_confidence": 0, "oversegmented": 0,
        "cross_verse": 0, "missing_words": 0, "audio_bleeding": 0,
    }
    verse_segments: dict[tuple, list] = defaultdict(list)

    for entry in entries:
        ch = _chapter_from_ref(entry["ref"])
        if ch != chapter:
            continue
        entry_ref = entry.get("ref", "")
        for seg in entry.get("segments", []):
            matched_ref = seg.get("matched_ref", "")
            confidence = seg.get("confidence", 0.0)

            if not matched_ref:
                counts["failed"] += 1
                continue

            if is_by_ayah and ":" in entry_ref and not _seg_belongs_to_entry(matched_ref, entry_ref):
                counts["audio_bleeding"] += 1

            if confidence < 0.80:
                counts["low_confidence"] += 1

            parts = matched_ref.split("-")
            if len(parts) != 2:
                continue
            sp = parts[0].split(":")
            ep = parts[1].split(":")
            if len(sp) != 3 or len(ep) != 3:
                continue
            try:
                surah, s_ayah, s_word = int(sp[0]), int(sp[1]), int(sp[2])
                e_ayah, e_word = int(ep[1]), int(ep[2])
            except (ValueError, IndexError):
                continue

            if s_ayah != e_ayah:
                if confidence < 1.0:
                    counts["cross_verse"] += 1
                for ayah in range(s_ayah, e_ayah + 1):
                    if ayah == s_ayah:
                        wc = word_counts.get((surah, ayah), s_word)
                        verse_segments[(surah, ayah)].append((s_word, wc))
                    elif ayah == e_ayah:
                        verse_segments[(surah, ayah)].append((1, e_word))
                    else:
                        wc = word_counts.get((surah, ayah), 1)
                        verse_segments[(surah, ayah)].append((1, wc))
            else:
                verse_segments[(surah, s_ayah)].append((s_word, e_word))
                if (s_word == e_word
                    and confidence < 1.0
                    and (surah, s_ayah) not in _MUQATTAAT_VERSES
                    and (surah, s_ayah) not in single_word_verses
                    and (surah, s_ayah, s_word) not in _STANDALONE_REFS
                    and _strip_quran_deco(seg.get("matched_text", "")) not in _STANDALONE_WORDS):
                    counts["oversegmented"] += 1

    # Missing words
    for (surah, ayah), seg_list in verse_segments.items():
        expected = word_counts.get((surah, ayah))
        if not expected:
            continue
        covered = set()
        for wf, wt in seg_list:
            covered.update(range(wf, wt + 1))
        missing = set(range(1, expected + 1)) - covered
        if missing:
            counts["missing_words"] += len(missing)

    return counts


@app.route("/api/seg/validate/<reciter>")
def validate_reciter_segments(reciter):
    """Validate all chapters for a reciter, returning issues grouped by category."""
    entries = _load_detailed(reciter)
    if not entries:
        return jsonify({"error": "Reciter not found"}), 404

    word_counts = _get_word_counts()

    errors = []
    missing_verses = []
    missing_words = []
    failed = []
    low_confidence = []
    oversegmented = []
    cross_verse = []
    audio_bleeding = []
    chapter_seg_idx = {}  # chapter -> next index (running counter)

    _single_word_verses = {k for k, v in word_counts.items() if v == 1}

    # Detect audio_source to know if by_ayah (bleeding only applies there)
    meta = _SEG_META_CACHE.get(reciter, {})
    audio_source = meta.get("audio_source", "")
    is_by_ayah = "by_ayah" in audio_source

    # Global verse coverage across all entries (for missing word pair detection)
    # (surah, ayah) -> [(word_from_in_verse, word_to_in_verse, seg_index)]
    verse_segments: dict[tuple[int, int], list] = defaultdict(list)

    for entry in entries:
        chapter = _chapter_from_ref(entry["ref"])
        entry_ref = entry.get("ref", "")
        raw_segments = entry.get("segments", [])

        for seg in raw_segments:
            i = chapter_seg_idx.get(chapter, 0)
            chapter_seg_idx[chapter] = i + 1
            matched_ref = seg.get("matched_ref", "")
            confidence = seg.get("confidence", 0.0)
            t_start = seg.get("time_start", 0)
            t_end = seg.get("time_end", 0)

            # Failed alignment
            if not matched_ref:
                failed.append({
                    "chapter": chapter,
                    "seg_index": i,
                    "time": f"{_format_ms(t_start)}-{_format_ms(t_end)}",
                })
                continue

            # Audio bleeding: segment matched to a different verse than
            # its entry's audio file (only meaningful for by_ayah sources)
            if is_by_ayah and ":" in entry_ref and not _seg_belongs_to_entry(matched_ref, entry_ref):
                # Extract the verse the segment actually matched to
                seg_start = matched_ref.split("-")[0]
                seg_parts = seg_start.split(":")
                matched_verse = f"{seg_parts[0]}:{seg_parts[1]}" if len(seg_parts) >= 2 else matched_ref
                audio_bleeding.append({
                    "chapter": chapter,
                    "seg_index": i,
                    "entry_ref": entry_ref,
                    "matched_verse": matched_verse,
                    "ref": matched_ref,
                    "confidence": round(confidence, 4),
                    "time": f"{_format_ms(t_start)}-{_format_ms(t_end)}",
                    "msg": f"audio {entry_ref} contains segment matching verse {matched_verse}",
                })

            # Low confidence
            if confidence < 0.80:
                parts = matched_ref.split("-")
                display_ref = matched_ref
                if len(parts) == 2:
                    s = parts[0].split(":")
                    e = parts[1].split(":")
                    if len(s) >= 2 and len(e) >= 2:
                        if s[1] == e[1]:
                            display_ref = f"{s[0]}:{s[1]}"
                        else:
                            display_ref = f"{s[0]}:{s[1]}-{e[1]}"
                low_confidence.append({
                    "ref": display_ref,
                    "chapter": chapter,
                    "seg_index": i,
                    "confidence": round(confidence, 4),
                })

            # Parse ref for cross-verse detection and word coverage
            parts = matched_ref.split("-")
            if len(parts) != 2:
                continue
            start_parts = parts[0].split(":")
            end_parts = parts[1].split(":")
            if len(start_parts) != 3 or len(end_parts) != 3:
                continue
            try:
                s_ayah = int(start_parts[1])
                e_ayah = int(end_parts[1])
                s_word = int(start_parts[2])
                e_word = int(end_parts[2])
                surah = int(start_parts[0])
            except (ValueError, IndexError):
                continue

            # Cross-verse detection (skip if already ignored / confidence=1.0)
            if s_ayah != e_ayah and confidence < 1.0:
                cross_verse.append({
                    "chapter": chapter,
                    "seg_index": i,
                    "ref": matched_ref,
                })
                # Coverage for cross-verse: start verse from s_word to end, end verse from 1 to e_word
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

                # Potentially oversegmented: 1-word segment, not muqattaat, not single-word verse,
                # not a known standalone word (by ref or matched_text).
                # Skip if already ignored (confidence=1.0).
                if (s_word == e_word
                    and confidence < 1.0
                    and (surah, s_ayah) not in _MUQATTAAT_VERSES
                    and (surah, s_ayah) not in _single_word_verses
                    and (surah, s_ayah, s_word) not in _STANDALONE_REFS
                    and _strip_quran_deco(seg.get("matched_text", "")) not in _STANDALONE_WORDS):
                    oversegmented.append({
                        "chapter": chapter,
                        "seg_index": i,
                        "ref": matched_ref,
                        "verse_key": f"{surah}:{s_ayah}",
                    })

    # Detect missing word pairs from detailed.json segments (global across all entries)
    for (surah, ayah), seg_list in verse_segments.items():
        expected = word_counts.get((surah, ayah))
        if not expected:
            continue
        seg_list.sort(key=lambda x: x[0])  # sort by word_from
        covered = set()
        for wf, wt, _ in seg_list:
            covered.update(range(wf, wt + 1))
        missing = set(range(1, expected + 1)) - covered
        if not missing:
            continue

        # Find which segment indices border the gap
        gap_indices = set()
        for j in range(len(seg_list)):
            wf, wt, idx = seg_list[j]
            if j + 1 < len(seg_list):
                next_wf, _, next_idx = seg_list[j + 1]
                if next_wf > wt + 1:  # gap between these two
                    gap_indices.add(idx)
                    gap_indices.add(next_idx)
            # Last segment doesn't reach end of verse
            if j == len(seg_list) - 1 and wt < expected:
                gap_indices.add(idx)
            # First segment doesn't start at word 1
            if j == 0 and wf > 1:
                gap_indices.add(idx)

        # Compute auto_fix only when exactly 1 word is missing
        auto_fix = None
        if len(missing) == 1:
            mw = next(iter(missing))
            first_wf, first_wt, first_idx = seg_list[0]
            last_wf, last_wt, last_idx = seg_list[-1]

            if mw == 1 and first_wf > 1:
                # Missing word 1 (verse start) → prepend to first segment
                auto_fix = {"target_seg_index": first_idx,
                            "new_ref_start": f"{surah}:{ayah}:1",
                            "new_ref_end": f"{surah}:{ayah}:{first_wt}"}
            elif mw == expected and last_wt < expected:
                # Missing last word (verse end) → append to last segment
                auto_fix = {"target_seg_index": last_idx,
                            "new_ref_start": f"{surah}:{ayah}:{last_wf}",
                            "new_ref_end": f"{surah}:{ayah}:{expected}"}
            else:
                # Gap between two segments — check stop signs
                for j in range(len(seg_list) - 1):
                    wf, wt, idx = seg_list[j]
                    next_wf, next_wt, next_idx = seg_list[j + 1]
                    if wt + 1 == mw and mw + 1 == next_wf:
                        if _word_has_stop(surah, ayah, wt):
                            # Stop at end of prev seg → missing word to next seg
                            auto_fix = {"target_seg_index": next_idx,
                                        "new_ref_start": f"{surah}:{ayah}:{mw}",
                                        "new_ref_end": f"{surah}:{ayah}:{next_wt}"}
                        elif _word_has_stop(surah, ayah, mw):
                            # Stop on missing word → missing word to prev seg
                            auto_fix = {"target_seg_index": idx,
                                        "new_ref_start": f"{surah}:{ayah}:{wf}",
                                        "new_ref_end": f"{surah}:{ayah}:{mw}"}
                        break

        issue = {
            "verse_key": f"{surah}:{ayah}",
            "chapter": surah,
            "msg": f"missing words: {sorted(missing)}",
            "seg_indices": sorted(gap_indices),
        }
        if auto_fix:
            issue["auto_fix"] = auto_fix
        missing_words.append(issue)

    # Structural errors + stats from segments.json validation (use cache)
    stats = None
    verses, pad_ms = _load_seg_verses(reciter)
    if verses:
        total_segments = 0
        single_seg = 0
        multi_seg_verses = 0
        multi_seg_segs = 0
        max_segs = 0
        cross_verse_count = 0
        seg_durations = []
        pause_durations = []

        for verse_key, segs in verses.items():
            is_cross_verse = "-" in verse_key
            if is_cross_verse:
                cross_verse_count += 1

            n_segs = len(segs)
            total_segments += n_segs
            max_segs = max(max_segs, n_segs)
            if n_segs == 1:
                single_seg += 1
            elif n_segs > 1:
                multi_seg_verses += 1
                multi_seg_segs += n_segs

            if is_cross_verse:
                kparts = verse_key.split("-")
                start_kparts = kparts[0].split(":")
                try:
                    surah = int(start_kparts[0])
                except (ValueError, IndexError):
                    continue
            else:
                parts = verse_key.split(":")
                if len(parts) != 2:
                    continue
                surah = int(parts[0])

            # Time/word validity checks + duration/pause collection
            for idx, seg in enumerate(segs):
                if len(seg) < 4:
                    continue
                w_from, w_to, t_from, t_to = seg[0], seg[1], seg[2], seg[3]
                seg_durations.append(t_to - t_from)

                if t_from >= t_to:
                    errors.append({
                        "verse_key": verse_key, "chapter": surah,
                        "msg": "time_from >= time_to",
                    })
                if w_from < 1:
                    errors.append({
                        "verse_key": verse_key, "chapter": surah,
                        "msg": "word_from < 1",
                    })
                if not is_cross_verse and w_to < w_from:
                    errors.append({
                        "verse_key": verse_key, "chapter": surah,
                        "msg": "word_to < word_from",
                    })
                elif is_cross_verse and w_to < 1:
                    errors.append({
                        "verse_key": verse_key, "chapter": surah,
                        "msg": "word_to < 1",
                    })

                # Time overlap / pause with next segment in same key
                if idx + 1 < len(segs) and len(segs[idx + 1]) >= 4:
                    next_t_from = segs[idx + 1][2]
                    if next_t_from < t_to:
                        errors.append({
                            "verse_key": verse_key, "chapter": surah,
                            "msg": "time overlap",
                        })
                    else:
                        true_pause = (next_t_from - t_to) + 2 * pad_ms
                        pause_durations.append(true_pause)

        # Missing verses: verses in word_counts but not covered at all
        all_verse_keys_in_file = set()
        for verse_key in verses:
            if "-" in verse_key:
                kparts = verse_key.split("-")
                start_kparts = kparts[0].split(":")
                end_kparts = kparts[1].split(":")
                try:
                    s = int(start_kparts[0])
                    for a in range(int(start_kparts[1]), int(end_kparts[1]) + 1):
                        all_verse_keys_in_file.add((s, a))
                except (ValueError, IndexError):
                    pass
            else:
                parts = verse_key.split(":")
                if len(parts) == 2:
                    all_verse_keys_in_file.add((int(parts[0]), int(parts[1])))

        for (surah, ayah) in sorted(word_counts):
            if (surah, ayah) not in all_verse_keys_in_file:
                missing_verses.append({
                    "verse_key": f"{surah}:{ayah}", "chapter": surah,
                    "msg": "missing verse",
                })

        # Build stats
        stats = {
            "segments": total_segments,
            "single": single_seg,
            "multi_verses": multi_seg_verses,
            "multi_segs": multi_seg_segs,
            "cross_verse": cross_verse_count,
            "max_segs": max_segs,
            "seg_dur_min": min(seg_durations) if seg_durations else 0,
            "seg_dur_med": statistics.median(seg_durations) if seg_durations else 0,
            "seg_dur_mean": statistics.mean(seg_durations) if seg_durations else 0,
            "seg_dur_max": max(seg_durations) if seg_durations else 0,
            "pause_dur_min": min(pause_durations) if pause_durations else 0,
            "pause_dur_med": statistics.median(pause_durations) if pause_durations else 0,
            "pause_dur_mean": statistics.mean(pause_durations) if pause_durations else 0,
            "pause_dur_max": max(pause_durations) if pause_durations else 0,
        }

    return jsonify({
        "errors": errors,
        "missing_verses": missing_verses,
        "missing_words": missing_words,
        "failed": failed,
        "low_confidence": low_confidence,
        "oversegmented": oversegmented,
        "cross_verse": cross_verse,
        "audio_bleeding": audio_bleeding,
        "stats": stats,
    })


def _format_ms(ms):
    """Format milliseconds as m:ss."""
    total_sec = ms / 1000
    mins = int(total_sec // 60)
    secs = int(total_sec % 60)
    return f"{mins}:{secs:02d}"


def _histogram(values: list, bin_size: float, lo: float, hi: float, *, cap: bool = True) -> dict:
    """Build a histogram with fixed bin edges.

    When *cap* is True (default), values >= hi are clamped into the last bin.
    When *cap* is False, the upper bound is extended to cover the actual data
    range so no values are clamped.

    Returns ``{"bins": [...], "counts": [...]}``.
    """
    if not cap and values:
        actual_max = max(values)
        if actual_max > hi:
            import math
            hi = math.ceil(actual_max / bin_size) * bin_size + bin_size
    n_bins = int((hi - lo) / bin_size)
    counts = [0] * (n_bins + 1)  # +1 for overflow bin
    bins = [lo + i * bin_size for i in range(n_bins)] + [hi]
    for v in values:
        idx = int((v - lo) / bin_size)
        if idx < 0:
            idx = 0
        elif idx >= len(counts):
            idx = len(counts) - 1
        counts[idx] += 1
    return {"bins": bins, "counts": counts}


def _percentile(sorted_values: list, pct: float) -> float:
    """Return the *pct*-th percentile from an already-sorted list."""
    if not sorted_values:
        return 0
    k = (len(sorted_values) - 1) * pct / 100
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_values) else f
    return round(sorted_values[f] + (k - f) * (sorted_values[c] - sorted_values[f]), 1)


@app.route("/api/seg/stats/<reciter>")
def get_seg_stats(reciter):
    """Return segmentation statistics and histogram distributions for a reciter."""
    verses, pad_ms = _load_seg_verses(reciter)
    if not verses:
        return jsonify({"error": "Reciter not found"}), 404

    # Collect raw data
    seg_durations = []     # ms
    pause_durations = []   # ms (true pause = gap + 2*pad)
    words_per_seg = []
    segs_per_verse = {}    # verse_key -> count (excluding cross-verse keys)

    for verse_key, segs in verses.items():
        is_cross = "-" in verse_key
        if not is_cross:
            segs_per_verse[verse_key] = len(segs)

        for idx, seg in enumerate(segs):
            if len(seg) < 4:
                continue
            w_from, w_to, t_from, t_to = seg[0], seg[1], seg[2], seg[3]
            seg_durations.append(t_to - t_from)
            words_per_seg.append(w_to - w_from + 1)

    # Compute pauses from detailed.json (flat chronological order per audio
    # entry) so stats match the client-side silence filter, which also iterates
    # consecutive segments across verse boundaries.
    entries = _load_detailed(reciter)
    meta = _SEG_META_CACHE.get(reciter, {})
    for entry in entries:
        entry_segs = entry.get("segments", [])
        for i in range(len(entry_segs) - 1):
            t_to = entry_segs[i].get("time_end", 0)
            next_t_from = entry_segs[i + 1].get("time_start", 0)
            if next_t_from > t_to:
                true_pause = (next_t_from - t_to) + 2 * pad_ms
                pause_durations.append(true_pause)

    spv_values = list(segs_per_verse.values())

    # Confidence from detailed.json
    confidences = []
    for entry in entries:
        for seg in entry.get("segments", []):
            conf = seg.get("confidence", 0.0)
            if seg.get("matched_ref"):
                confidences.append(round(conf * 100, 1))

    # Summary
    total_segments = len(seg_durations)
    total_verses = len(spv_values)
    single_word = sum(1 for w in words_per_seg if w == 1)
    multi_seg = sum(1 for v in spv_values if v > 1)

    summary = {
        "total_segments": total_segments,
        "total_verses": total_verses,
        "single_word_segs": single_word,
        "single_word_pct": round(single_word / total_segments * 100, 1) if total_segments else 0,
        "multi_seg_verses": multi_seg,
        "multi_seg_pct": round(multi_seg / total_verses * 100, 1) if total_verses else 0,
        "segs_per_verse_mean": round(statistics.mean(spv_values), 2) if spv_values else 0,
        "segs_per_verse_max": max(spv_values) if spv_values else 0,
        "seg_dur_median_ms": round(statistics.median(seg_durations)) if seg_durations else 0,
        "pause_dur_median_ms": round(statistics.median(pause_durations)) if pause_durations else 0,
    }

    # Distributions
    distributions = {
        "pause_duration_ms": _histogram(pause_durations, 50, 0, 3000),
        "seg_duration_ms": _histogram(seg_durations, 500, 0, 15000, cap=False),
        "words_per_seg": _histogram(words_per_seg, 1, 1, 15, cap=False),
        "segs_per_verse": _histogram(spv_values, 1, 1, 8),
        "confidence": _histogram(confidences, 5, 0, 100),
    }

    # Attach percentile lines to distributions
    for key, values in [
        ("pause_duration_ms", pause_durations),
        ("seg_duration_ms", seg_durations),
        ("words_per_seg", words_per_seg),
        ("confidence", confidences),
    ]:
        if values and key in distributions:
            sv = sorted(values)
            distributions[key]["percentiles"] = {
                "p25": _percentile(sv, 25),
                "p50": _percentile(sv, 50),
                "p75": _percentile(sv, 75),
            }

    vad_params = {
        "min_silence_ms": meta.get("min_silence_ms", 0),
        "min_speech_ms": meta.get("min_speech_ms", 0),
        "pad_ms": pad_ms,
    }

    return jsonify({
        "vad_params": vad_params,
        "summary": summary,
        "distributions": distributions,
    })


@app.route("/api/seg/stats/<reciter>/save-chart", methods=["POST"])
def save_stat_chart(reciter):
    """Save a chart PNG to data/recitation_segments/<reciter>/analysis/."""
    seg_dir = RECITATION_SEGMENTS_PATH / reciter
    if not seg_dir.exists():
        return jsonify({"error": "Reciter not found"}), 404

    name = request.form.get("name", "chart")
    # Sanitise filename
    name = "".join(c for c in name if c.isalnum() or c in "-_").strip() or "chart"

    f = request.files.get("image")
    if not f:
        return jsonify({"error": "No image provided"}), 400

    out_dir = seg_dir / "analysis"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{name}.png"
    f.save(str(out_path))
    return jsonify({"ok": True, "path": str(out_path)})


# ---------------------------------------------------------------------------
# Edit history endpoint
# ---------------------------------------------------------------------------

@app.route("/api/seg/edit-history/<reciter>")
def get_seg_edit_history(reciter):
    """Return edit history batches and summary stats for the reciter."""
    history_path = RECITATION_SEGMENTS_PATH / reciter / "edit_history.jsonl"
    if not history_path.exists():
        return jsonify({"batches": [], "summary": None})

    batches = []
    op_counts: Counter = Counter()
    fix_kind_counts: Counter = Counter()
    chapters_edited: set[int] = set()
    total_batches = 0

    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        if record.get("record_type") == "genesis":
            continue

        is_revert = bool(record.get("reverts_batch_id"))
        ops = record.get("operations", [])

        batch = {
            "batch_id": record.get("batch_id"),
            "saved_at_utc": record.get("saved_at_utc"),
            "chapter": record.get("chapter"),
            "chapters": record.get("chapters"),
            "save_mode": record.get("save_mode"),
            "is_revert": is_revert,
            "reverts_batch_id": record.get("reverts_batch_id"),
            "validation_summary_before": record.get("validation_summary_before"),
            "validation_summary_after": record.get("validation_summary_after"),
            "operations": ops,
        }
        batches.append(batch)

        if ops:
            total_batches += 1
            ch = record.get("chapter")
            if ch is not None:
                chapters_edited.add(ch)
            for mch in record.get("chapters") or []:
                chapters_edited.add(mch)
            for op in ops:
                op_counts[op.get("op_type", "unknown")] += 1
                fix_kind_counts[op.get("fix_kind", "unknown")] += 1

    total_operations = sum(op_counts.values())
    summary = {
        "total_operations": total_operations,
        "total_batches": total_batches,
        "chapters_edited": len(chapters_edited),
        "op_counts": dict(op_counts),
        "fix_kind_counts": dict(fix_kind_counts),
    } if total_operations > 0 else None

    return jsonify({"batches": batches, "summary": summary})


# ---------------------------------------------------------------------------
# Audio tab endpoints
# ---------------------------------------------------------------------------

_AUDIO_SOURCES: dict | None = None


def _load_audio_sources() -> dict:
    """Walk ``data/audio/by_surah/<source>/`` and ``by_ayah/<source>/`` to build
    a hierarchical reciter index.

    Returns::

        {"by_surah": {"qul": [{"slug": "...", "name": "..."}, ...], ...},
         "by_ayah": {"everyayah": [...]}}
    """
    global _AUDIO_SOURCES
    if _AUDIO_SOURCES is not None:
        return _AUDIO_SOURCES

    result: dict[str, dict[str, list[dict]]] = {}
    if not AUDIO_METADATA_PATH.exists():
        _AUDIO_SOURCES = result
        return result

    for category in ("by_surah", "by_ayah"):
        cat_dir = AUDIO_METADATA_PATH / category
        if not cat_dir.exists():
            continue
        cat_data: dict[str, list[dict]] = {}
        for source_dir in sorted(cat_dir.iterdir()):
            if not source_dir.is_dir():
                continue
            source = source_dir.name
            reciters = []
            for p in sorted(source_dir.glob("*.json")):
                slug = p.stem
                name = slug.replace("_", " ").title()
                reciters.append({"slug": slug, "name": name})
            if reciters:
                cat_data[source] = reciters
        if cat_data:
            result[category] = cat_data

    _AUDIO_SOURCES = result
    return result


@app.route("/api/audio/sources")
def get_audio_sources():
    """Return hierarchical audio source structure."""
    return jsonify(_load_audio_sources())


@app.route("/api/audio/surahs/<category>/<source>/<slug>")
def get_audio_surahs(category, source, slug):
    """Return surah/ayah URLs for a reciter within a specific source."""
    key = f"{category}/{source}/{slug}"
    if key in _AUDIO_URL_CACHE:
        return jsonify({"surahs": _AUDIO_URL_CACHE[key]})
    path = AUDIO_METADATA_PATH / category / source / f"{slug}.json"
    if not path.exists():
        return jsonify({"error": "Reciter not found"}), 404
    with open(path, encoding="utf-8") as f:
        surahs = json.load(f)
    surahs.pop("_meta", None)
    # Normalize: entries may be plain URL strings or {"url": ..., "timing": ...} dicts
    surahs = {k: (v["url"] if isinstance(v, dict) else v) for k, v in surahs.items()}
    _AUDIO_URL_CACHE[key] = surahs
    return jsonify({"surahs": surahs})


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Alignment Inspector Server")
    parser.add_argument("--port", type=int, default=5000, help="Port to run on")
    args = parser.parse_args()

    # Create cache directory if needed
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Eagerly initialize phonemizer for reference resolution
    if _HAS_PHONEMIZER:
        print("Initializing phonemizer...")
        get_phonemizer()
        print("Phonemizer ready.")
    else:
        print("Phonemizer not available (reference resolution disabled)")

    # Eagerly discover timestamp reciters (fast — reads only _meta headers)
    reciters = _discover_ts_reciters()
    print(f"Discovered {len(reciters)} timestamp reciter(s).")

    # Preload all timestamp data in background threads
    if reciters:
        import concurrent.futures
        def _preload(slug):
            _load_timestamps(slug)
            return slug
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(reciters)) as pool:
            for slug in pool.map(_preload, [r["slug"] for r in reciters]):
                print(f"  Preloaded timestamps: {slug}")
        print("All timestamp data cached.")

    # Run server
    print(f"Starting server at http://localhost:{args.port}")
    app.run(host="0.0.0.0", port=args.port, debug=True, use_reloader=False)
