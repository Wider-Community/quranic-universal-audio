#!/usr/bin/env python3
"""
Build and upload a reciter config to the HuggingFace dataset.

Usage:
    python scripts/release/build_reciter.py <slug>              # Upload one reciter
    python scripts/release/build_reciter.py --all               # Upload all eligible
    python scripts/release/build_reciter.py --delete <slug>     # Delete a reciter's data
    python scripts/release/build_reciter.py --update-readme     # Update dataset card only

Environment:
    HF_TOKEN       — HuggingFace API token
    SAMPLE_PCT     — Sample percentage for dev (0=full, default=0)
"""

import argparse
import io
import json
import logging
import os
import re
import sys
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from datasets import Audio, Dataset, Features, Sequence, Value
from huggingface_hub import HfApi

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# Non-recited Quranic markers to strip from text (stop signs, hizb, sajdah)
_QURAN_MARKERS = set("\u06D6\u06D7\u06D8\u06D9\u06DA\u06DB\u06DE\u06E9")

SURAH_DOWNLOAD_WORKERS = 4
AYAH_DOWNLOAD_WORKERS = 64

def _strip_quran_markers(text: str) -> str:
    """Strip non-recited markers (waqf signs, hizb, sajdah) from Uthmani text."""
    return "".join(ch for ch in text if ch not in _QURAN_MARKERS)


def _text_for_ref(matched_ref: str, dk_words: dict, surah_info: dict) -> str:
    """Derive the Arabic text for a canonical ``surah:ayah:word-surah:ayah:word``
    matched_ref from the Digital Khatt word map.

    Mirror of ``inspector/services/reference/quran_refs.py::dk_text_for_ref``
    so the HF dataset rebuild produces byte-equivalent text to what the
    Inspector renders from the same ref. As of Migration #5 the extractor
    no longer writes ``matched_text`` to ``detailed.json``; this helper is
    the canonical replacement.

    ``dk_words`` is the flat ``{"<surah>:<ayah>:<word>": {"text": "...", ...}}``
    map from ``data/qpc_hafs.json``. ``surah_info`` carries the per-verse
    ``num_words`` count used to wrap to the next ayah.

    Returns ``""`` for malformed input so callers can short-circuit on falsy.
    """
    if not matched_ref or "-" not in matched_ref:
        return ""
    start, _, end = matched_ref.partition("-")
    s_parts = start.split(":")
    e_parts = end.split(":")
    if len(s_parts) != 3 or len(e_parts) != 3:
        return ""
    try:
        s_su, s_ay, s_w = int(s_parts[0]), int(s_parts[1]), int(s_parts[2])
        e_su, e_ay, e_w = int(e_parts[0]), int(e_parts[1]), int(e_parts[2])
    except ValueError:
        return ""

    # Segments don't cross surahs in practice; mirror the FE / inspector
    # assumption.
    su = s_su
    su_key = str(su)
    surah_meta = surah_info.get(su_key)
    if not surah_meta:
        return ""
    verses = surah_meta.get("verses", [])

    words: list[str] = []
    ay, w = s_ay, s_w
    # Guard against malformed refs that would loop forever.
    max_iters = 1000
    while (su, ay, w) <= (e_su, e_ay, e_w) and max_iters > 0:
        entry = dk_words.get(f"{su}:{ay}:{w}")
        if entry:
            text = entry.get("text") if isinstance(entry, dict) else entry
            if text:
                words.append(text)
        w += 1
        # Wrap to next ayah when we've exhausted this one's words.
        verse_idx = ay - 1
        max_w = (
            verses[verse_idx].get("num_words", 0)
            if 0 <= verse_idx < len(verses)
            else 0
        )
        if w > max_w:
            w = 1
            ay += 1
        max_iters -= 1
    return " ".join(words)


def _cross_verse_text(matched_ref: str, full_text: str,
                      target_ayah: int, surah_info: dict, surah_num: str) -> str:
    """Slice only the target verse's words from a cross-verse segment's text.

    For ref '37:151:3-37:152:2' with 5 words of text, target_ayah=152
    returns the last 2 words (37:152's portion).

    ``full_text`` is the FULL text spanned by the matched_ref — typically
    produced by ``_text_for_ref(matched_ref, dk_words, surah_info)``.
    The legacy code path passed ``det_seg["matched_text"]`` here; after
    Migration #5 the caller derives it from dk_words instead.
    """
    parts = matched_ref.split("-")
    if len(parts) != 2:
        return full_text
    try:
        sp = parts[0].split(":")
        ep = parts[1].split(":")
        s_ayah, s_word = int(sp[1]), int(sp[2])
        e_ayah, e_word = int(ep[1]), int(ep[2])
    except (ValueError, IndexError):
        return full_text

    words = full_text.split()
    if target_ayah == s_ayah:
        # Target is the starting verse — take first N words
        total = surah_info[surah_num]["verses"][s_ayah - 1]["num_words"]
        n = total - s_word + 1
        return " ".join(words[:n])
    elif target_ayah == e_ayah:
        # Target is the ending verse — take last N words
        return " ".join(words[-e_word:]) if e_word > 0 else ""
    return full_text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "qua_shared"))
from config_loader import repo_config  # noqa: E402
from reciter_eligibility import (  # noqa: E402
    compute_coverage,
    find_eligible_reciters,
    has_tracked_timestamps,
)
from timestamps_shards import derive_url_template as _derive_url_template  # noqa: E402

REPO_ID = repo_config()["hf_dataset"]
SAMPLE_PCT = int(os.environ.get("SAMPLE_PCT", "0"))
HF_TOKEN = os.environ.get("HF_TOKEN", "")

# Load .env fallback
if not HF_TOKEN:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("HF_TOKEN="):
                HF_TOKEN = line.split("=", 1)[1].strip()
                break


# ---------------------------------------------------------------------------
# Audio source detection
# ---------------------------------------------------------------------------
def detect_audio_source(slug):
    """Detect audio source type from segments.json _meta."""
    seg_file = ROOT / "data" / "recitation_segments" / slug / "segments.json"
    if not seg_file.exists():
        return None
    try:
        first_line = seg_file.read_text().split("\n", 1)[0]
        meta = json.loads(first_line).get("_meta", {})
        source = meta.get("audio_source", "")
        if "by_ayah" in source:
            return "by_ayah_audio"
        elif "by_surah" in source:
            return "by_surah_audio"
    except Exception:
        pass
    return None


def get_riwayah(slug):
    """Get riwayah slug for a reciter from its audio manifest _meta."""
    audio_dir = ROOT / "data" / "audio"
    for category in ("by_surah", "by_ayah"):
        cat_dir = audio_dir / category
        if not cat_dir.is_dir():
            continue
        for source_dir in cat_dir.iterdir():
            if not source_dir.is_dir():
                continue
            manifest = source_dir / f"{slug}.json"
            if manifest.exists():
                try:
                    meta = json.loads(manifest.read_text()).get("_meta", {})
                    return meta.get("riwayah", "hafs_an_asim")
                except (json.JSONDecodeError, OSError):
                    pass
    return "hafs_an_asim"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_data(slug, audio_type):
    """Load all data files for a reciter.

    Loads timestamps.json (word-level) and derives verse boundaries from the
    word array (verse_start_ms = first word start, verse_end_ms = last word
    end). Optionally loads timestamps_full.json for letter-level data.
    """
    ts_path = ROOT / "data" / "timestamps" / audio_type / slug / "timestamps.json"
    ts_full_path = ROOT / "data" / "timestamps" / audio_type / slug / "timestamps_full.json"
    detailed_path = ROOT / "data" / "recitation_segments" / slug / "detailed.json"
    segments_path = ROOT / "data" / "recitation_segments" / slug / "segments.json"
    surah_info_path = ROOT / "data" / "surah_info.json"
    qpc_hafs_path = ROOT / "data" / "qpc_hafs.json"

    log.info("Loading data for %s...", slug)
    with open(ts_path) as f:
        ts_raw = json.load(f)
    with open(detailed_path) as f:
        detailed = json.load(f)
    with open(segments_path) as f:
        segments = json.load(f)
    with open(surah_info_path) as f:
        surah_info = json.load(f)
    # dk_words is the Digital Khatt word map keyed by "surah:ayah:word".
    # Used by _text_for_ref to derive per-segment Arabic text from matched_ref
    # — replaces reading the now-dropped (Migration #5) det_seg["matched_text"].
    with open(qpc_hafs_path) as f:
        dk_words = json.load(f)

    # timestamps_full.json carries per-verse `verse_start_ms` / `verse_end_ms`
    # derived from accepted home segs (incl. leading/trailing silence captured
    # by the segmenter). Prefer those for clip boundaries; fall back to MFA
    # word bounds if the field is absent (older ts data without seg-based
    # bounds). Letter-level data also comes from this file.
    ts_full_raw: dict = {}
    if ts_full_path.exists():
        log.info("Loading letter timestamps from %s...", ts_full_path.name)
        with open(ts_full_path) as f:
            ts_full_raw = json.load(f)

    # Reshape timestamps.json ([[word_idx, start, end], ...]) into the
    # structure build_rows expects: {ref: {"words": [...], "verse_start_ms",
    # "verse_end_ms"}}
    timestamps = {}
    for ref, words in ts_raw.items():
        if ref == "_meta":
            continue
        if not words:
            timestamps[ref] = {"words": [], "verse_start_ms": 0, "verse_end_ms": 0}
            continue
        full_entry = ts_full_raw.get(ref) if isinstance(ts_full_raw, dict) else None
        verse_start_ms = None
        verse_end_ms = None
        if isinstance(full_entry, dict):
            verse_start_ms = full_entry.get("verse_start_ms")
            verse_end_ms = full_entry.get("verse_end_ms")
        if verse_start_ms is None or verse_end_ms is None:
            verse_start_ms = words[0][1]
            verse_end_ms = max(w[2] for w in words)
        timestamps[ref] = {
            "words": words,
            "verse_start_ms": verse_start_ms,
            "verse_end_ms": verse_end_ms,
        }

    letter_data = {}
    for ref, verse in ts_full_raw.items():
        if ref == "_meta":
            continue
        words = verse.get("words") if isinstance(verse, dict) else verse
        if not words:
            letter_data[ref] = []
            continue
        word_letters = []
        for word in words:
            word_idx = word[0]
            letters = word[3] if len(word) > 3 else []
            word_letters.append((word_idx, letters))
        letter_data[ref] = word_letters
    ts_full_raw.clear()

    # Build verse-level lookup: by_ayah entries have ref="surah:ayah",
    # by_surah entries have ref="chapter_num" (one entry per whole surah).
    # Normalize both to "surah:ayah" keys for uniform lookup in build_rows.
    detailed_by_ref = {}
    for entry in detailed["entries"]:
        ref = entry["ref"]
        if ":" in str(ref):
            # by_ayah: ref is already "surah:ayah"
            detailed_by_ref[ref] = entry
        else:
            # by_surah: ref is chapter number — map each verse to this entry
            for seg in entry.get("segments", []):
                mref = seg.get("matched_ref", "")
                if not mref:
                    continue
                # Extract all verses covered by this segment's ref range
                parts = mref.split("-")
                start = parts[0].split(":")
                s_surah, s_ayah = int(start[0]), int(start[1])
                if len(parts) > 1:
                    end = parts[1].split(":")
                    e_ayah = int(end[1])
                else:
                    e_ayah = s_ayah
                for a in range(s_ayah, e_ayah + 1):
                    vref = f"{s_surah}:{a}"
                    if vref not in detailed_by_ref:
                        detailed_by_ref[vref] = entry

    return timestamps, detailed_by_ref, segments, surah_info, letter_data, dk_words


# ---------------------------------------------------------------------------
# Row building
# ---------------------------------------------------------------------------
def build_rows(timestamps, detailed_by_ref, segments, surah_info,
               letter_data=None, dk_words=None):
    """Build row metadata (without audio bytes) in canonical verse order.

    Clip boundaries are defined by word timestamps (deduplicated, canonical).
    Segments and text are filtered to only those within the clip range so
    the HF dataset row is internally consistent.  Content outside the clip
    (repetitions, cross-verse bleed) is preserved in the raw files but not
    included in the dataset row.
    """
    rows = []
    for surah_num in sorted(surah_info.keys(), key=int):
        surah = surah_info[surah_num]
        for verse_info in surah["verses"]:
            ayah = verse_info["verse"]
            ref = f"{surah_num}:{ayah}"

            entry = detailed_by_ref.get(ref)
            if not entry:
                log.warning("No detailed entry for %s, skipping", ref)
                continue

            # Clip boundaries from word timestamps (canonical, deduplicated)
            if ref in timestamps and ref != "_meta":
                verse_data = timestamps[ref]
                clip_start = verse_data["verse_start_ms"]
                clip_end = verse_data["verse_end_ms"]
            elif ref in segments and ref != "_meta":
                seg_list = segments[ref]
                clip_start = seg_list[0][2]
                clip_end = seg_list[-1][3]
            else:
                log.warning("No timing data for %s, skipping", ref)
                continue

            # Inspector edits can leave fractional-ms timestamps in the
            # source JSON (linear-interpolated word/letter boundaries).
            # Schema is int32, so coerce every ms field at row-build time.
            def _i(x):
                return int(round(x)) if isinstance(x, float) else int(x)

            # Filter segments to those overlapping the clip range
            verse_segments = []
            if ref in segments and ref != "_meta":
                for seg in segments[ref]:
                    if seg[3] <= clip_start or seg[2] >= clip_end:
                        continue  # segment fully outside clip
                    verse_segments.append([
                        _i(seg[0]), _i(seg[1]),
                        _i(max(0, seg[2] - clip_start)),
                        _i(min(seg[3], clip_end) - clip_start),
                    ])

            # Text from detailed.json segments that overlap the clip range.
            # For cross-verse segments, extract only this verse's words.
            filtered_text_parts = []
            for det_seg in entry["segments"]:
                t_start = det_seg.get("time_start", 0)
                t_end = det_seg.get("time_end", 0)
                if t_end <= clip_start or t_start >= clip_end:
                    continue  # outside clip
                mref = det_seg.get("matched_ref", "")
                # Migration #5: derive seg text from dk_words via matched_ref
                # instead of reading det_seg["matched_text"] (which the
                # extractor no longer writes). Fall back to the legacy
                # field for pre-#5 on-disk data that still carries it —
                # so the rebuild stays correct across the transition.
                if dk_words:
                    seg_text = _text_for_ref(mref, dk_words, surah_info)
                    if not seg_text:
                        seg_text = det_seg.get("matched_text", "")
                else:
                    seg_text = det_seg.get("matched_text", "")
                if "-" in mref:
                    rp = mref.split("-")
                    if len(rp) == 2:
                        sa = rp[0].split(":")
                        ea = rp[1].split(":")
                        if len(sa) >= 2 and len(ea) >= 2:
                            s_ayah = int(sa[1])
                            e_ayah = int(ea[1])
                            if ayah < s_ayah or ayah > e_ayah:
                                continue  # segment doesn't cover this ayah
                            if s_ayah != e_ayah:
                                # Cross-verse: extract only this ayah's words
                                seg_text = _cross_verse_text(
                                    mref, seg_text, ayah, surah_info,
                                    surah_num)
                filtered_text_parts.append(seg_text)
            text = " ".join(filtered_text_parts)
            text = _strip_quran_markers(text)

            verse_words = []
            if ref in timestamps and ref != "_meta":
                for word in timestamps[ref]["words"]:
                    verse_words.append([
                        _i(word[0]),
                        _i(word[1] - clip_start),
                        _i(word[2] - clip_start),
                    ])

            # Synthesize segments for cross-verse words not covered by
            # segments.json (they precede or follow the home segments,
            # or segments.json has no entry for this verse at all).
            if verse_words and not verse_segments:
                # No segments.json entry — synthesize one from all words
                verse_segments.append([
                    verse_words[0][0], verse_words[-1][0],
                    verse_words[0][1], verse_words[-1][2],
                ])
            elif verse_words and verse_segments:
                first_seg_start = verse_segments[0][2]  # clip-relative ms
                xv_words = [w for w in verse_words if w[2] <= first_seg_start]
                if xv_words:
                    verse_segments.insert(0, [
                        xv_words[0][0], xv_words[-1][0],
                        xv_words[0][1], xv_words[-1][2],
                    ])
                last_seg_end = verse_segments[-1][3]
                xv_after = [w for w in verse_words if w[1] >= last_seg_end]
                if xv_after:
                    verse_segments.append([
                        xv_after[0][0], xv_after[-1][0],
                        xv_after[0][1], xv_after[-1][2],
                    ])

            # Flat letter timestamps: one entry per letter (not per word)
            verse_letters = []
            if letter_data and ref in letter_data:
                for word_idx, letters in letter_data[ref]:
                    for ch, s, e in letters:
                        verse_letters.append({
                            "word_idx": _i(word_idx),
                            "char": ch,
                            "start_ms": _i(s - clip_start),
                            "end_ms": _i(e - clip_start),
                        })

            rows.append({
                "surah": int(surah_num),
                "ayah": ayah,
                "duration_ms": _i(clip_end - clip_start),
                "text_uthmani": text,
                "segments": verse_segments,
                "word_timestamps": verse_words,
                "letter_timestamps": verse_letters,
                "audio_url": entry["audio"],
                "clip_start": clip_start,
                "clip_end": clip_end,
            })

    return rows


# ---------------------------------------------------------------------------
# Audio download
# ---------------------------------------------------------------------------
def _lazy_import_pydub():
    from pydub import AudioSegment as AS
    return AS


def download_and_slice(url, clip_start_ms, clip_end_ms, retries=3):
    """Download audio and slice at clip boundaries, return MP3 bytes."""
    AS = _lazy_import_pydub()

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                audio_data = resp.read()
            audio = AS.from_file(io.BytesIO(audio_data))
            clip = audio[clip_start_ms:clip_end_ms]

            buf = io.BytesIO()
            clip.export(buf, format="mp3", bitrate="128k")
            return buf.getvalue()
        except Exception as e:
            if attempt == retries - 1:
                raise
            log.warning("Retry %d for %s: %s", attempt + 1, url, e)
    return None


def download_all_audio(rows, is_surah=False):
    """Download and slice audio for all rows in parallel."""
    audio_bytes_list = [None] * len(rows)
    failed = []

    if is_surah:
        # For by_surah: download a few surahs in parallel, slice, then free.
        # Decoded PCM for all 114 surahs can exceed 17 GB (44.1kHz stereo),
        # which OOM-kills GitHub Actions runners (7 GB RAM).  We limit to 4
        # concurrent downloads — peak memory ~2-3 GB, well within limits.
        AS = _lazy_import_pydub()

        # Group row indices by audio URL
        url_to_indices = defaultdict(list)
        for i, row in enumerate(rows):
            url_to_indices[row["audio_url"]].append(i)

        unique_urls = list(url_to_indices.keys())
        log.info("Downloading and slicing %d surah audio files (%d parallel)...", len(unique_urls), SURAH_DOWNLOAD_WORKERS)
        completed_surahs = 0

        def _process_surah(url):
            """Download one surah, slice all its verses, return (url, results, errors)."""
            results = {}  # idx -> mp3 bytes
            errors = []
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=120) as resp:
                    raw_data = resp.read()
                audio = AS.from_file(io.BytesIO(raw_data))
                del raw_data
            except Exception as e:
                for idx in url_to_indices[url]:
                    ref = f"{rows[idx]['surah']}:{rows[idx]['ayah']}"
                    errors.append(ref)
                return url, results, errors

            for idx in url_to_indices[url]:
                row = rows[idx]
                try:
                    clip = audio[row["clip_start"]:row["clip_end"]]
                    buf = io.BytesIO()
                    clip.export(buf, format="mp3", bitrate="128k")
                    results[idx] = buf.getvalue()
                except Exception as e:
                    ref = f"{row['surah']}:{row['ayah']}"
                    errors.append(ref)

            del audio
            return url, results, errors

        with ThreadPoolExecutor(max_workers=SURAH_DOWNLOAD_WORKERS) as pool:
            for url, results, errors in pool.map(_process_surah, unique_urls):
                for idx, mp3 in results.items():
                    audio_bytes_list[idx] = mp3
                failed.extend(errors)
                completed_surahs += 1
                if completed_surahs % 10 == 0:
                    log.info("Progress: %d/%d surahs processed", completed_surahs, len(unique_urls))
    else:
        # For by_ayah: parallel individual downloads
        def process(idx):
            row = rows[idx]
            return idx, download_and_slice(row["audio_url"], row["clip_start"], row["clip_end"])

        log.info("Downloading and slicing %d audio files (64 workers)...", len(rows))
        completed = 0
        with ThreadPoolExecutor(max_workers=AYAH_DOWNLOAD_WORKERS) as pool:
            futures = {pool.submit(process, i): i for i in range(len(rows))}
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    _, mp3 = future.result()
                    audio_bytes_list[idx] = mp3
                except Exception as e:
                    ref = f"{rows[idx]['surah']}:{rows[idx]['ayah']}"
                    log.error("Failed to download %s: %s", ref, e)
                    failed.append(ref)
                completed += 1
                if completed % 500 == 0:    
                    log.info("Progress: %d/%d downloaded", completed, len(rows))

    log.info("Downloads complete. %d succeeded, %d failed.", len(rows) - len(failed), len(failed))
    if failed:
        log.warning("Failed verses: %s", failed)

    return audio_bytes_list, failed


# ---------------------------------------------------------------------------
# Smart audio reuse
# ---------------------------------------------------------------------------
def _try_load_existing(slug):
    """Load existing parquet from HF via pyarrow (raw bytes, no audio decode).

    Returns a pyarrow Table or None if the split doesn't exist yet.
    """
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    riwayah = get_riwayah(slug)
    api = HfApi(token=HF_TOKEN)
    try:
        tree = list(api.list_repo_tree(
            REPO_ID, repo_type="dataset", path_in_repo=riwayah))
        files = [f.rfilename for f in tree
                 if f.rfilename.endswith(".parquet") and slug in f.rfilename]
    except Exception:
        files = []

    if not files:
        log.info("No existing parquet on HF for %s/%s", riwayah, slug)
        return None

    tables = []
    for fname in files:
        local = hf_hub_download(REPO_ID, fname, repo_type="dataset", token=HF_TOKEN)
        tables.append(pq.read_table(local))

    table = tables[0] if len(tables) == 1 else pq.concat_tables(tables)
    log.info("Loaded existing parquet: %d rows from %d shard(s)", len(table), len(files))

    # Require duration_ms for clip boundary comparison
    if "duration_ms" not in table.column_names:
        log.info("Existing parquet missing duration_ms column — full rebuild required")
        return None

    return table


def _reuse_audio(existing_table, rows, is_surah):
    """Reuse audio bytes from existing HF parquet where clip boundaries match.

    Compares (surah, ayah, clip_start, clip_end) between old and new rows.
    Returns (audio_bytes_list, changed_count).  Falls back to full download
    if >10% of clips changed.
    """
    # Build lookup: (surah, ayah) → row index in existing table
    old_surah = existing_table.column("surah").to_pylist()
    old_ayah = existing_table.column("ayah").to_pylist()
    old_offset = existing_table.column("source_offset_ms").to_pylist()
    old_duration = existing_table.column("duration_ms").to_pylist()
    old_audio = existing_table.column("audio")

    existing_by_key: dict[tuple[int, int], int] = {}
    for i in range(len(existing_table)):
        existing_by_key[(old_surah[i], old_ayah[i])] = i

    audio_bytes_list = [None] * len(rows)
    need_download: list[int] = []
    reused = 0

    for i, row in enumerate(rows):
        key = (row["surah"], row["ayah"])
        old_idx = existing_by_key.get(key)

        if old_idx is None:
            need_download.append(i)
            continue

        old_start = old_offset[old_idx]
        old_end = old_start + old_duration[old_idx]

        if row["clip_start"] == old_start and row["clip_end"] == old_end:
            # Clip unchanged — extract raw MP3 bytes (no decode/re-encode)
            audio_struct = old_audio[old_idx].as_py()
            audio_bytes_list[i] = audio_struct["bytes"]
            reused += 1
        else:
            need_download.append(i)

    log.info("Audio reuse: %d/%d reused, %d need re-slice",
             reused, len(rows), len(need_download))

    if not need_download:
        return audio_bytes_list, 0

    # >10% changed — full download is more efficient than partial
    if len(need_download) > len(rows) * 0.1:
        log.info("Too many clips changed (%d/%d), full rebuild",
                 len(need_download), len(rows))
        full_bytes, failed = download_all_audio(rows, is_surah=is_surah)
        return full_bytes, len(need_download)

    # Partial: download only the surahs/ayahs that changed
    if is_surah:
        AS = _lazy_import_pydub()
        url_to_indices = defaultdict(list)
        for idx in need_download:
            url_to_indices[rows[idx]["audio_url"]].append(idx)

        log.info("Partial download: %d surahs for %d changed verses",
                 len(url_to_indices), len(need_download))
        for url, indices in url_to_indices.items():
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=120) as resp:
                    raw_data = resp.read()
                audio = AS.from_file(io.BytesIO(raw_data))
                del raw_data
                for idx in indices:
                    row = rows[idx]
                    clip = audio[row["clip_start"]:row["clip_end"]]
                    buf = io.BytesIO()
                    clip.export(buf, format="mp3", bitrate="128k")
                    audio_bytes_list[idx] = buf.getvalue()
                del audio
            except Exception as e:
                log.warning("Partial download failed for %s: %s", url, e)
    else:
        def _dl(idx):
            row = rows[idx]
            return idx, download_and_slice(row["audio_url"], row["clip_start"], row["clip_end"])

        with ThreadPoolExecutor(max_workers=64) as pool:
            for future in as_completed(
                    {pool.submit(_dl, i): i for i in need_download}):
                try:
                    idx, mp3 = future.result()
                    audio_bytes_list[idx] = mp3
                except Exception as e:
                    log.warning("Partial download failed for index %d: %s",
                                future, e)

    return audio_bytes_list, len(need_download)


# ---------------------------------------------------------------------------
# Dataset push
# ---------------------------------------------------------------------------
def push_reciter(slug, audio_type, full_rebuild=False):
    """Build and push a reciter to the HF dataset."""
    is_surah = "by_surah" in audio_type

    timestamps, detailed_by_ref, segments, surah_info, letter_data, dk_words = load_data(slug, audio_type)
    rows = build_rows(timestamps, detailed_by_ref, segments, surah_info, letter_data, dk_words)
    log.info("Built %d rows for %s", len(rows), slug)

    if SAMPLE_PCT > 0:
        step = max(1, 100 // SAMPLE_PCT)
        rows = rows[::step]
        log.info("Sampling %d%% → %d rows", SAMPLE_PCT, len(rows))

    # Smart audio reuse: load existing parquet from HF when possible
    existing_table = None
    if not full_rebuild and SAMPLE_PCT == 0:
        existing_table = _try_load_existing(slug)

    if existing_table is not None and len(existing_table) == len(rows):
        audio_bytes_list, changed = _reuse_audio(existing_table, rows, is_surah)
        del existing_table
        failed = [f"{rows[i]['surah']}:{rows[i]['ayah']}"
                  for i, b in enumerate(audio_bytes_list) if b is None]
    else:
        if existing_table is not None:
            log.info("Row count changed (%d → %d), full rebuild",
                     len(existing_table), len(rows))
            del existing_table
        audio_bytes_list, failed = download_all_audio(rows, is_surah=is_surah)

    data = {
        "audio": [],
        "surah": [],
        "ayah": [],
        "duration_ms": [],
        "text_uthmani": [],
        "segments": [],
        "word_timestamps": [],
        "letter_timestamps": [],
        "source_url": [],
        "source_offset_ms": [],
    }

    skipped = 0
    for i, row in enumerate(rows):
        if audio_bytes_list[i] is None:
            skipped += 1
            continue
        data["audio"].append({
            "bytes": audio_bytes_list[i],
            "path": f"{row['surah']:03d}{row['ayah']:03d}.mp3",
        })
        data["surah"].append(row["surah"])
        data["ayah"].append(row["ayah"])
        data["duration_ms"].append(row["duration_ms"])
        data["text_uthmani"].append(row["text_uthmani"])
        data["segments"].append(row["segments"])
        data["word_timestamps"].append(row["word_timestamps"])
        data["letter_timestamps"].append(row["letter_timestamps"])
        # Strip protocol so HF viewer doesn't render as audio widget
        src_url = row["audio_url"]
        for prefix in ("https://", "http://"):
            if src_url.startswith(prefix):
                src_url = src_url[len(prefix):]
                break
        data["source_url"].append(src_url)
        cs = row["clip_start"]
        data["source_offset_ms"].append(int(round(cs)) if isinstance(cs, float) else int(cs))

    if skipped:
        log.warning("Skipped %d verses due to download failures", skipped)

    log.info("Creating dataset with %d rows...", len(data["audio"]))
    features = Features({
        "audio": Audio(),
        "surah": Value("int32"),
        "ayah": Value("int32"),
        "duration_ms": Value("int32"),
        "text_uthmani": Value("string"),
        "segments": Sequence(Sequence(Value("int32"))),
        "word_timestamps": Sequence(Sequence(Value("int32"))),
        "letter_timestamps": Sequence({
            "word_idx": Value("int32"),
            "char": Value("string"),
            "start_ms": Value("int32"),
            "end_ms": Value("int32"),
        }),
        "source_url": Value("string"),
        "source_offset_ms": Value("int32"),
    })

    ds = Dataset.from_dict(data, features=features)

    api = HfApi(token=HF_TOKEN)
    api.create_repo(repo_id=REPO_ID, repo_type="dataset", exist_ok=True)

    riwayah = get_riwayah(slug)
    log.info("Pushing to hub as %s/%s...", riwayah, slug)

    push_kwargs = dict(
        config_name=riwayah,
        split=slug,
        token=HF_TOKEN,
        max_shard_size="10GB",
        commit_message=f"Add {riwayah}/{slug}",
    )
    try:
        ds.push_to_hub(REPO_ID, **push_kwargs)
    except ValueError as e:
        if "Features of the new split don't match" not in str(e):
            raise
        log.warning("Feature mismatch on hub for config '%s' — updating README and retrying", riwayah)
        # The mismatch lives in the README.md YAML frontmatter on the hub.
        # Re-upload the local dataset card to fix it, then retry.
        update_dataset_readme()
        ds.push_to_hub(REPO_ID, **push_kwargs)

    log.info("Done: %s uploaded to %s", slug, REPO_ID)


# ---------------------------------------------------------------------------
# Dataset README management
# ---------------------------------------------------------------------------
def get_audio_source_label(slug):
    """Get human-readable audio source from segments meta."""
    seg_file = ROOT / "data" / "recitation_segments" / slug / "segments.json"
    if seg_file.exists():
        try:
            first_line = seg_file.read_text().split("\n", 1)[0]
            meta = json.loads(first_line).get("_meta", {})
            source = meta.get("audio_source", "")
            source_map = {
                "by_ayah/everyayah": "everyayah.com",
                "by_surah/mp3quran": "mp3quran.net",
                "by_surah/qul": "qul.tarteel.ai",
                "by_surah/surah-quran": "surah-quran.com",
                "by_surah/youtube": "youtube.com",
                "by_surah/archive": "archive.org",
                "by_surah/soundcloud": "soundcloud.com",
                "by_surah/spreaker": "spreaker.com",
            }
            return source_map.get(source, source)
        except Exception:
            pass
    return "unknown"


def get_display_name(slug):
    """Get display name from audio manifest _meta.name_en, fallback to slug."""
    meta = _find_audio_manifest_meta(slug)
    if meta and meta.get("name_en") and meta["name_en"] != "unknown":
        return meta["name_en"]
    return slug.replace("_", " ").title()


def get_style(slug):
    """Get recitation style from audio manifest _meta.style."""
    meta = _find_audio_manifest_meta(slug)
    if meta and meta.get("style") and meta["style"] != "unknown":
        return meta["style"]
    return "unknown"


def get_coverage(slug):
    """Verse count from segments.json (compound keys expanded)."""
    seg_file = ROOT / "data" / "recitation_segments" / slug / "segments.json"
    if seg_file.exists():
        try:
            return compute_coverage(json.loads(seg_file.read_text()))["ayahs"]
        except (json.JSONDecodeError, OSError):
            pass
    return 0


def _find_audio_manifest(slug):
    """Find first audio manifest for slug and return full parsed dict."""
    audio_dir = ROOT / "data" / "audio"
    for category in ("by_surah", "by_ayah"):
        cat_dir = audio_dir / category
        if not cat_dir.is_dir():
            continue
        for source_dir in cat_dir.iterdir():
            if not source_dir.is_dir():
                continue
            manifest = source_dir / f"{slug}.json"
            if manifest.exists():
                try:
                    return json.loads(manifest.read_text())
                except (json.JSONDecodeError, OSError):
                    pass
    return None


def _find_audio_manifest_meta(slug):
    """Find first audio manifest for slug and return its _meta dict."""
    data = _find_audio_manifest(slug)
    return data.get("_meta", {}) if data else None


def _vbr_chapters_for_manifest(slug):
    """Return sorted VBR chapter numbers from data/.audio_meta.json."""
    path = ROOT / "data" / ".audio_meta.json"
    try:
        doc = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []
    by_chapter = (doc.get(slug) or {}).get("by_chapter") or {}
    out = []
    for chapter, entry in by_chapter.items():
        if not isinstance(entry, dict) or not entry.get("vbr"):
            continue
        try:
            out.append(int(chapter))
        except (TypeError, ValueError):
            continue
    return sorted(out)


def _build_reciter_info(eligible):
    """Build a list of info dicts for eligible reciters, grouped by riwayah."""
    from collections import defaultdict
    by_riwayah = defaultdict(list)
    for slug in sorted(eligible):
        riwayah = get_riwayah(slug)
        verses = get_coverage(slug)
        by_riwayah[riwayah].append({
            "slug": slug,
            "name": get_display_name(slug),
            "style": get_style(slug),
            "source": get_audio_source_label(slug),
            "verses": f"{verses:,}",
            "num_examples": verses,
        })
    return by_riwayah


def update_dataset_readme():
    """Rebuild docs/hf_dataset_card.md YAML configs and markdown tables from eligible reciters."""
    readme_path = ROOT / "docs" / "hf_dataset_card.md"
    text = readme_path.read_text()

    # Split YAML frontmatter from body
    parts = text.split("---", 2)
    if len(parts) < 3:
        log.error("Could not parse README.md frontmatter")
        return
    yaml_text = parts[1]
    body = parts[2]

    eligible = find_eligible_reciters(ROOT)
    by_riwayah = _build_reciter_info(eligible)

    # --- Rebuild YAML configs and data_files ---
    data_files_lines = []
    split_lines = []
    for riwayah in sorted(by_riwayah):
        for info in by_riwayah[riwayah]:
            data_files_lines.append(
                f"  - split: {info['slug']}\n"
                f"    path: {riwayah}/{info['slug']}-*"
            )
            split_lines.append(
                f"  - name: {info['slug']}\n"
                f"    num_bytes: 0\n"
                f"    num_examples: {info['num_examples']}"
            )

    # Replace configs block (riwayah configs + reciters catalog)
    configs_str = "configs:\n" + "".join(
        f"- config_name: {riwayah}\n  data_files:\n"
        + "\n".join(df for df in data_files_lines
                    if f"path: {riwayah}/" in df)
        + "\n"
        for riwayah in sorted(by_riwayah)
    )
    configs_str += (
        "- config_name: reciters\n"
        "  data_files:\n"
        "  - split: all\n"
        "    path: reciters/all-*\n"
    )
    yaml_text = re.sub(
        r"configs:\n(?:- config_name:.*\n(?:  .*\n)*)*",
        configs_str,
        yaml_text,
    )

    # Replace splits block (keep existing num_bytes for known splits)
    existing_bytes = {}
    for m in re.finditer(r"- name: ([^\n]+)\n\s+num_bytes: (\d+)", yaml_text):
        existing_bytes[m.group(1)] = m.group(2)

    new_splits = "  splits:\n"
    for riwayah in sorted(by_riwayah):
        for info in by_riwayah[riwayah]:
            nb = existing_bytes.get(info["slug"], "0")
            new_splits += (
                f"  - name: {info['slug']}\n"
                f"    num_bytes: {nb}\n"
                f"    num_examples: {info['num_examples']}\n"
            )
    yaml_text = re.sub(
        r"  splits:\n(?:  - name: [^\n]+\n    num_bytes: \d+\n    num_examples: \d+\n)+",
        new_splits,
        yaml_text,
        count=1,  # Only replace the first (riwayah) splits block, not reciters
    )

    # --- Rebuild markdown tables (one per subset) ---
    tables_md = "Subset (config) is the riwayah, split is the reciter.\n"
    for riwayah in sorted(by_riwayah):
        tables_md += f"\n### `{riwayah}`\n\n"
        tables_md += "| Reciter | Style | Verses | Audio Source |\n"
        tables_md += "|---------|-------|--------|-------------|\n"
        for info in by_riwayah[riwayah]:
            tables_md += (
                f"| [{info['name']}](#{info['slug']}) "
                f"| {info['style']} "
                f"| {info['verses']} "
                f"| {info['source']} |\n"
            )

    # Replace existing configs section in body
    body = re.sub(
        r"Subset \(config\) is the riwayah.*?(?=\n## |\Z)",
        tables_md,
        body,
        flags=re.DOTALL,
    )

    # Update badge counts
    all_slugs = set()
    riwayat_with_data = set()
    audio_dir = ROOT / "data" / "audio"
    if audio_dir.is_dir():
        for source_type in audio_dir.iterdir():
            if not source_type.is_dir():
                continue
            for source in source_type.iterdir():
                if source.is_dir():
                    for f in source.glob("*.json"):
                        all_slugs.add(f.stem)
                        try:
                            meta = json.loads(f.read_text()).get("_meta", {})
                            riwayat_with_data.add(meta.get("riwayah", "hafs_an_asim"))
                        except (json.JSONDecodeError, OSError):
                            pass

    all_total = len(all_slugs)

    # Segmented = reciters with segments.json on disk
    seg_dir = ROOT / "data" / "recitation_segments"
    segmented_slugs = {
        d.name for d in seg_dir.iterdir()
        if d.is_dir() and (d / "segments.json").exists()
    } if seg_dir.is_dir() else set()
    segmented_count = len(segmented_slugs)
    unsegmented_slugs = all_slugs - segmented_slugs
    unsegmented_count = len(unsegmented_slugs)

    # Load hours from cache
    cache_path = ROOT / "data" / ".audio_durations.json"
    unseg_hours = 0
    seg_hours = 0
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
            unseg_hours = round(sum(cache[s]["duration_s"] for s in unsegmented_slugs if s in cache) / 3600)
            seg_hours = round(sum(cache[s]["duration_s"] for s in segmented_slugs if s in cache) / 3600)
        except Exception as e:
            log.warning("Could not read audio durations cache: %s", e)

    # Unsegmented badge
    unseg_val = f"{unsegmented_count}%20reciters%20%C2%B7%20{unseg_hours:,}h"
    body = re.sub(r"Unsegmented-[^-]+-d4842a", f"Unsegmented-{unseg_val}-d4842a", body)

    # Segmented badge
    seg_val = f"{segmented_count}%20reciters%20%C2%B7%20{seg_hours:,}h"
    body = re.sub(r"Segmented-[^-]+-d4842a", f"Segmented-{seg_val}-d4842a", body)

    # Riwayat badge
    riwayat_total_path = ROOT / "data" / "riwayat.json"
    riwayat_total = len(json.loads(riwayat_total_path.read_text())) if riwayat_total_path.exists() else 20
    body = re.sub(
        r"Riwayat-\d+(%20%2F%20)\d+",
        rf"Riwayat-{len(riwayat_with_data)}\g<1>{riwayat_total}",
        body,
    )

    # Update prose counts
    reciters_rounded = (all_total // 50) * 50
    body = re.sub(r"\d+\+ reciters", f"{reciters_rounded}+ reciters", body)
    body = re.sub(r"across \d+ riwayat", f"across {len(riwayat_with_data)} riwayat", body)

    text = f"---{yaml_text}---{body}"
    readme_path.write_text(text)

    # Upload to HF
    api = HfApi(token=HF_TOKEN)
    api.upload_file(
        path_or_fileobj=str(readme_path),
        path_in_repo="README.md",
        repo_id=REPO_ID,
        repo_type="dataset",
        commit_message="Update dataset card",
    )
    log.info("Dataset README updated")


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------
def delete_reciter(slug):
    """Delete a reciter's parquet data from HF dataset."""
    from huggingface_hub import CommitOperationDelete
    api = HfApi(token=HF_TOKEN)
    riwayah = get_riwayah(slug)
    prefix = f"{riwayah}/{slug}-"
    try:
        all_files = list(api.list_repo_tree(
            REPO_ID, path_in_repo=riwayah, repo_type="dataset",
        ))
        to_delete = [
            CommitOperationDelete(path_in_repo=f.rfilename)
            for f in all_files
            if hasattr(f, "rfilename") and f.rfilename.startswith(prefix)
        ]
        if not to_delete:
            log.warning("No files found matching %s*", prefix)
        else:
            api.create_commit(
                repo_id=REPO_ID, repo_type="dataset",
                operations=to_delete,
                commit_message=f"Remove {riwayah}/{slug}",
            )
            log.info("Deleted %d files for %s from %s", len(to_delete), slug, REPO_ID)
    except Exception as e:
        log.error("Failed to delete %s: %s", prefix, e)

    update_dataset_readme()


# ---------------------------------------------------------------------------
# Timestamp shards (deployed Inspector read path)
# ---------------------------------------------------------------------------

# Lazy imports — keep this module importable even when qua_shared isn't on
# sys.path (e.g. for the existing `--reciters-config` flow on a fresh CI runner).
sys.path.insert(0, str(ROOT / "qua_shared"))


def _load_existing_shard_hashes(
    slug: str, *, hash_key: str = "shard_hashes",
) -> dict[str, str]:
    """Read shard hashes for `slug` out of the dataset's manifest.json.gz.

    ``hash_key`` selects which hash table to read from
    ``manifest.reciters.<slug>._build`` — defaults to the timestamps shards
    (``shard_hashes``); pass ``"seg_shard_hashes"`` for segments shards.

    Returns ``{chapter_str: sha256_hex}``. Empty dict if manifest doesn't
    exist yet (first build), the slug isn't in it (new reciter), or the
    requested key is missing (manifest predates the parallel hashes block).
    """
    import gzip
    from huggingface_hub import HfApi
    api = HfApi(token=HF_TOKEN)
    try:
        path = api.hf_hub_download(
            repo_id=REPO_ID, repo_type="dataset",
            filename="manifest.json.gz",
        )
    except Exception:
        return {}
    try:
        with gzip.open(path, "rb") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        log.warning("Could not parse existing manifest.json.gz: %s", e)
        return {}
    reciter_block = (manifest.get("reciters") or {}).get(slug, {})
    return (reciter_block.get("_build") or {}).get(hash_key) or {}


def _resolve_audio_template(slug: str, audio_type: str) -> tuple[str, str, dict]:
    """Find audio manifest, derive (template, audio_category, manifest_dict).

    `audio_type` is the timestamps-side category (`by_surah_audio` /
    `by_ayah_audio`); the audio manifest's category drops the `_audio` suffix.
    """
    audio_cat = audio_type.replace("_audio", "")  # by_surah_audio → by_surah
    manifest = _find_audio_manifest(slug) or {}
    template = _derive_url_template(manifest, audio_cat) if manifest else ""
    return template, audio_cat, manifest


def build_timestamp_shards(slug: str, *, dry_run: bool = False) -> None:
    """Split a reciter's timestamps_full.json into per-chapter gzipped shards
    and upload only the changed ones to the HF dataset.

    Diffs against ``manifest.reciters.<slug>._build.shard_hashes`` from the
    last manifest build. New + changed shards are uploaded; chapters present
    on HF but not locally are deleted. A single ``create_commit`` keeps the
    per-reciter sync atomic.

    With ``dry_run=True``, the upload/delete plan is printed to stdout but
    no commit is made. Useful for CI safety + local verification.
    """
    from huggingface_hub import (
        CommitOperationDelete,
        CommitOperationAdd,
        HfApi,
    )

    from timestamps_shards import gzip_shard, sha256_hex, split_to_shards

    audio_type = detect_audio_source(slug)
    if not audio_type:
        sys.exit(f"Could not detect audio source for {slug}")

    ts_path = (
        ROOT / "data" / "timestamps" / audio_type / slug / "timestamps_full.json"
    )
    if not ts_path.exists():
        sys.exit(f"timestamps_full.json not found for {slug} at {ts_path}")
    log.info("Loading %s", ts_path)
    doc = json.loads(ts_path.read_bytes())

    template, audio_cat, audio_manifest = _resolve_audio_template(slug, audio_type)
    if not template:
        log.warning(
            "%s: url_template empty — falling back to per-verse audio_urls "
            "in shard _meta", slug,
        )

    shards = split_to_shards(
        doc,
        reciter=slug,
        audio_category=audio_cat,
        url_template=template,
        audio_urls_fallback=audio_manifest if not template else None,
    )

    # Hash each shard, diff against existing manifest hashes.
    new_hashes: dict[str, str] = {}
    payloads: dict[str, bytes] = {}
    for chapter, shard in shards.items():
        body = gzip_shard(shard)
        digest = sha256_hex(body)
        new_hashes[str(chapter)] = digest
        payloads[str(chapter)] = body

    existing_hashes = _load_existing_shard_hashes(slug)
    to_upload = [c for c, h in new_hashes.items() if existing_hashes.get(c) != h]
    to_delete = [c for c in existing_hashes if c not in new_hashes]

    log.info(
        "%s: %d total chapters, %d to upload, %d to delete (unchanged: %d)",
        slug, len(shards), len(to_upload), len(to_delete),
        len(shards) - len(to_upload),
    )

    if dry_run:
        log.info("[dry-run] would upload:")
        for c in sorted(to_upload, key=int):
            log.info("  + timestamps/%s/%s.json.gz  (%d bytes, sha %s...)",
                     slug, c, len(payloads[c]), new_hashes[c][:12])
        log.info("[dry-run] would delete:")
        for c in sorted(to_delete, key=int):
            log.info("  - timestamps/%s/%s.json.gz", slug, c)
        return

    if not to_upload and not to_delete:
        log.info("%s: nothing to do (all shard hashes match)", slug)
        return

    operations = []
    for c in to_upload:
        operations.append(CommitOperationAdd(
            path_in_repo=f"timestamps/{slug}/{c}.json.gz",
            path_or_fileobj=payloads[c],
        ))
    for c in to_delete:
        operations.append(CommitOperationDelete(
            path_in_repo=f"timestamps/{slug}/{c}.json.gz",
        ))

    api = HfApi(token=HF_TOKEN)
    api.create_commit(
        repo_id=REPO_ID, repo_type="dataset",
        operations=operations,
        commit_message=(
            f"timestamps/{slug}: upload {len(to_upload)}, delete {len(to_delete)}"
        ),
    )
    log.info("Pushed %d shard ops for %s", len(operations), slug)


def _resolve_segments_doc(slug: str) -> tuple[dict, str]:
    """Load `data/recitation_segments/<slug>/detailed.json` + audio category.

    The audio category (`by_surah` / `by_ayah`) is read from the document's
    `_meta.audio_source` field (e.g. ``"by_surah/mp3quran"`` → ``"by_surah"``).
    Falls back to ``detect_audio_source`` if `_meta` is silent.
    """
    detailed_path = ROOT / "data" / "recitation_segments" / slug / "detailed.json"
    if not detailed_path.exists():
        sys.exit(f"detailed.json not found for {slug} at {detailed_path}")

    log.info("Loading %s", detailed_path)
    doc = json.loads(detailed_path.read_bytes())

    audio_source = (doc.get("_meta") or {}).get("audio_source", "") or ""
    if "/" in audio_source:
        audio_cat = audio_source.split("/", 1)[0]
    else:
        ts_audio_type = detect_audio_source(slug) or ""
        audio_cat = ts_audio_type.replace("_audio", "")

    if audio_cat not in ("by_surah", "by_ayah"):
        sys.exit(
            f"Could not determine audio category for {slug} "
            f"(audio_source={audio_source!r})"
        )
    return doc, audio_cat


def build_segment_shards(slug: str, *, dry_run: bool = False) -> None:
    """Split a reciter's detailed.json into per-chapter gzipped segments shards
    and upload only the changed ones to the HF dataset.

    Twin of ``build_timestamp_shards`` — same diff/upload/delete contract,
    consumed by the aligner Space's preload mode (see plan
    ``wondrous-hopping-mochi.md``). Reads from
    ``manifest.reciters.<slug>._build.seg_shard_hashes`` for diff-skip.
    """
    from huggingface_hub import (
        CommitOperationDelete,
        CommitOperationAdd,
        HfApi,
    )

    from segments_shards import (
        gzip_shard as seg_gzip_shard,
        sha256_hex as seg_sha256_hex,
        split_to_shards as seg_split_to_shards,
    )

    detailed_doc, audio_cat = _resolve_segments_doc(slug)

    shards = seg_split_to_shards(
        detailed_doc, reciter=slug, audio_category=audio_cat,
    )

    new_hashes: dict[str, str] = {}
    payloads: dict[str, bytes] = {}
    for chapter, shard in shards.items():
        body = seg_gzip_shard(shard)
        digest = seg_sha256_hex(body)
        new_hashes[str(chapter)] = digest
        payloads[str(chapter)] = body

    existing_hashes = _load_existing_shard_hashes(slug, hash_key="seg_shard_hashes")
    to_upload = [c for c, h in new_hashes.items() if existing_hashes.get(c) != h]
    to_delete = [c for c in existing_hashes if c not in new_hashes]

    log.info(
        "%s: %d total chapters, %d to upload, %d to delete (unchanged: %d)",
        slug, len(shards), len(to_upload), len(to_delete),
        len(shards) - len(to_upload),
    )

    if dry_run:
        log.info("[dry-run] would upload:")
        for c in sorted(to_upload, key=int):
            log.info("  + segments/%s/%s.json.gz  (%d bytes, sha %s...)",
                     slug, c, len(payloads[c]), new_hashes[c][:12])
        log.info("[dry-run] would delete:")
        for c in sorted(to_delete, key=int):
            log.info("  - segments/%s/%s.json.gz", slug, c)
        return

    if not to_upload and not to_delete:
        log.info("%s: nothing to do (all segment shard hashes match)", slug)
        return

    operations = []
    for c in to_upload:
        operations.append(CommitOperationAdd(
            path_in_repo=f"segments/{slug}/{c}.json.gz",
            path_or_fileobj=payloads[c],
        ))
    for c in to_delete:
        operations.append(CommitOperationDelete(
            path_in_repo=f"segments/{slug}/{c}.json.gz",
        ))

    api = HfApi(token=HF_TOKEN)
    api.create_commit(
        repo_id=REPO_ID, repo_type="dataset",
        operations=operations,
        commit_message=(
            f"segments/{slug}: upload {len(to_upload)}, delete {len(to_delete)}"
        ),
    )
    log.info("Pushed %d segment shard ops for %s", len(operations), slug)


# ---------------------------------------------------------------------------
# Global resources (qpc, dk, font) — fetched once per Inspector session
# ---------------------------------------------------------------------------

# Quran reference assets (qpc text, digital-khatt script, font) ship from the
# standalone quranic-universal-aligner repo's data/ dir (gitignored sibling of
# .local inside this repo). Override with QUA_ALIGNER_DATA_DIR.
# Local-only step (no CI caller); missing files are skipped with a warning below.
# Tuple shape: (manifest_key, source_path, dataset_path, gzip).
_RESOURCE_SPECS = [
    ("qpc_hafs",
     "qpc_hafs.json", "qpc_hafs.json.gz", True),
    ("digital_khatt",
     "digital_khatt_v2_script.json", "digital_khatt_v2_script.json.gz", True),
    ("digital_khatt_otf",
     "DigitalKhattV2.otf", "DigitalKhattV2.otf", False),
]
_QUA_DATA_DIR = Path(
    os.environ.get("QUA_ALIGNER_DATA_DIR")
    or ROOT / "quranic-universal-aligner" / "data"
)


def _hash_file_payload(path: Path, *, gzip_it: bool) -> tuple[bytes, str]:
    """Read `path`, optionally gzip, return (payload_bytes, sha256_hex)."""
    import gzip as _gz

    from timestamps_shards import sha256_hex

    body = path.read_bytes()
    if gzip_it:
        body = _gz.compress(body, compresslevel=6, mtime=0)
    return body, sha256_hex(body)


def _load_existing_resource_hashes() -> dict[str, str]:
    """Return ``manifest._build.resource_hashes`` from the live manifest."""
    import gzip
    from huggingface_hub import HfApi
    api = HfApi(token=HF_TOKEN)
    try:
        path = api.hf_hub_download(
            repo_id=REPO_ID, repo_type="dataset",
            filename="manifest.json.gz",
        )
    except Exception:
        return {}
    try:
        with gzip.open(path, "rb") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return (manifest.get("_build") or {}).get("resource_hashes") or {}


def build_resources(*, dry_run: bool = False) -> None:
    """Upload global qpc/dk/font resources to the dataset root.

    Idempotent — diffs each file's SHA-256 against the last manifest's
    ``_build.resource_hashes`` and skips uploads that match. Safe to call
    on every sync.
    """
    from huggingface_hub import CommitOperationAdd, HfApi

    existing = _load_existing_resource_hashes()
    operations: list = []
    new_hashes: dict[str, str] = {}
    for key, src_name, dst_name, gzip_it in _RESOURCE_SPECS:
        src_path = _QUA_DATA_DIR / src_name
        if not src_path.exists():
            log.warning("Resource missing: %s — skipping", src_path)
            continue
        body, digest = _hash_file_payload(src_path, gzip_it=gzip_it)
        new_hashes[key] = digest
        if existing.get(key) == digest:
            log.info("resource %s: unchanged (sha %s...)", dst_name, digest[:12])
            continue
        log.info("resource %s: %s (%d bytes, sha %s...)",
                 dst_name, "would upload" if dry_run else "queued",
                 len(body), digest[:12])
        operations.append(CommitOperationAdd(
            path_in_repo=dst_name, path_or_fileobj=body,
        ))

    if dry_run:
        log.info("[dry-run] resource hash plan: %s",
                 {k: v[:12] for k, v in new_hashes.items()})
        return

    if not operations:
        log.info("resources: nothing to upload (all hashes match)")
        return

    api = HfApi(token=HF_TOKEN)
    api.create_commit(
        repo_id=REPO_ID, repo_type="dataset",
        operations=operations,
        commit_message=f"resources: upload {len(operations)} file(s)",
    )
    log.info("Pushed %d resource ops", len(operations))


# ---------------------------------------------------------------------------
# Deployment manifest (the catalog clients fetch on Inspector start)
# ---------------------------------------------------------------------------

def _list_dataset_chapters(slug: str, *, subdir: str = "timestamps") -> list[int]:
    """Return chapter numbers currently published under ``<subdir>/<slug>/``.

    Returns ``[]`` if the path doesn't exist on HF yet (new reciter or
    one that hasn't had a build run against it).
    """
    from huggingface_hub import HfApi
    from huggingface_hub.errors import RepositoryNotFoundError, RemoteEntryNotFoundError
    api = HfApi(token=HF_TOKEN)
    try:
        items = list(api.list_repo_tree(
            REPO_ID, path_in_repo=f"{subdir}/{slug}",
            repo_type="dataset", recursive=False,
        ))
    except (RepositoryNotFoundError, RemoteEntryNotFoundError):
        return []
    except Exception as e:
        log.warning("list_repo_tree(%s/%s) failed: %s", subdir, slug, e)
        return []
    chapters: list[int] = []
    for item in items:
        name = getattr(item, "rfilename", None) or getattr(item, "path", "")
        if not name:
            continue
        base = name.rsplit("/", 1)[-1]
        if not base.endswith(".json.gz"):
            continue
        try:
            chapters.append(int(base[:-len(".json.gz")]))
        except ValueError:
            continue
    return sorted(chapters)


def _list_dataset_reciter_slugs(*, subdir: str = "timestamps") -> list[str]:
    """Return slugs that currently have a ``<subdir>/<slug>/`` directory on HF."""
    from huggingface_hub import HfApi
    from huggingface_hub.errors import RepositoryNotFoundError, RemoteEntryNotFoundError
    api = HfApi(token=HF_TOKEN)
    try:
        items = list(api.list_repo_tree(
            REPO_ID, path_in_repo=subdir,
            repo_type="dataset", recursive=False,
        ))
    except (RepositoryNotFoundError, RemoteEntryNotFoundError):
        return []
    except Exception as e:
        log.warning("list_repo_tree(%s) failed: %s", subdir, e)
        return []
    slugs: list[str] = []
    for item in items:
        path = getattr(item, "rfilename", None) or getattr(item, "path", "")
        if not path:
            continue
        # Directory entries surface as "<subdir>/<slug>" with no extension.
        leaf = path.rsplit("/", 1)[-1]
        if leaf and "." not in leaf:
            slugs.append(leaf)
    return sorted(set(slugs))


def _local_reciter_state(slug: str) -> dict:
    """Compute manifest fields that come from local source files in one pass.

    Returns ``{"validation": {...}, "shard_hashes": {...},
    "seg_shard_hashes": {...}}`` where the hash dicts are SHA-256 of each
    gzipped shard recomputed from local source files (same code path as
    --build-timestamps / --build-segments, so hashes match what was
    uploaded). Either hash dict is empty when the corresponding source
    file is missing locally — keeps partial-eligibility reciters from
    poisoning the manifest.
    """
    sys.path.insert(0, str(ROOT))
    from qua_shared.boundary_check import compute_boundary_mismatches  # noqa: E402

    from timestamps_shards import gzip_shard, sha256_hex, split_to_shards
    from segments_shards import (
        gzip_shard as seg_gzip_shard,
        sha256_hex as seg_sha256_hex,
        split_to_shards as seg_split_to_shards,
    )

    out: dict = {
        "validation": {"boundary_mismatches": []},
        "shard_hashes": {},
        "seg_shard_hashes": {},
    }

    audio_type = detect_audio_source(slug)
    if not audio_type:
        return out
    ts_path = ROOT / "data" / "timestamps" / audio_type / slug / "timestamps_full.json"
    seg_path = ROOT / "data" / "recitation_segments" / slug / "segments.json"
    detailed_path = ROOT / "data" / "recitation_segments" / slug / "detailed.json"
    if not ts_path.exists():
        return out

    try:
        doc = json.loads(ts_path.read_bytes())
    except (json.JSONDecodeError, OSError):
        return out

    # Validation: compare ts/seg boundaries (same logic the runtime
    # validator uses; pre-computed here so the deployed Inspector
    # doesn't need segments.json on the read path).
    verses = {
        k: v.get("words", []) if isinstance(v, dict) else v
        for k, v in doc.items()
        if not k.startswith("_")
    }
    boundary = compute_boundary_mismatches(verses, seg_path)
    out["validation"]["boundary_mismatches"] = [
        {"verse_key": m["verse_key"], "side": m["side"], "diff_ms": m["diff_ms"]}
        for m in boundary["mismatches"]
    ]

    # Shard hashes: regenerate locally so we don't have to round-trip
    # through HF for what is essentially a deterministic function of
    # the source file. The hashes match what --build-timestamps wrote.
    audio_cat = audio_type.replace("_audio", "")
    audio_manifest = _find_audio_manifest(slug) or {}
    template = (
        _derive_url_template(audio_manifest, audio_cat) if audio_manifest else ""
    )
    shards = split_to_shards(
        doc, reciter=slug, audio_category=audio_cat, url_template=template,
        audio_urls_fallback=audio_manifest if not template else None,
    )
    out["shard_hashes"] = {
        str(ch): sha256_hex(gzip_shard(shard)) for ch, shard in shards.items()
    }

    # Segment shard hashes: same idea, computed from detailed.json. The
    # aligner preload UI consumes these via the manifest's
    # `segments_shard_url_template`. We only emit hashes when the
    # detailed.json is locally present — eligibility is enforced upstream
    # via `find_eligible_reciters`.
    if detailed_path.exists():
        try:
            detailed_doc = json.loads(detailed_path.read_bytes())
        except (json.JSONDecodeError, OSError):
            detailed_doc = None
        if detailed_doc is not None:
            seg_shards = seg_split_to_shards(
                detailed_doc, reciter=slug, audio_category=audio_cat,
            )
            out["seg_shard_hashes"] = {
                str(ch): seg_sha256_hex(seg_gzip_shard(shard))
                for ch, shard in seg_shards.items()
            }
    return out


def build_manifest(*, dry_run: bool = False) -> None:
    """Walk the dataset, compose manifest.json.gz, and push it.

    The manifest carries:
      - dataset_base_url + shard_url_template + resources (URL templating)
      - per-reciter metadata (name, riwayah, style, audio_category,
        url_template, ts_chapters, validation.boundary_mismatches)
      - _build.shard_hashes per reciter + _build.resource_hashes globally
        (drives next run's diff-skip)
      - schema_version, generated_at, commit

    Orphan reciters (present on HF but not eligible locally) are reported
    and their `timestamps/<slug>/` trees deleted in the same commit.
    """
    import gzip
    from datetime import datetime, timezone

    from huggingface_hub import (
        CommitOperationAdd,
        CommitOperationDelete,
        HfApi,
    )

    sys.path.insert(0, str(ROOT))
    from list_reciters import discover_reciters  # noqa: E402

    # Per-slug local metadata (one row per slug, prefer by_surah).
    records = discover_reciters()
    by_slug: dict[str, dict] = {}
    for rec in records:
        slug = rec["slug"]
        if slug not in by_slug:
            by_slug[slug] = rec
        elif rec["audio_cat"] == "by_surah" and by_slug[slug]["audio_cat"] == "by_ayah":
            by_slug[slug] = rec

    eligible = set(find_eligible_reciters(ROOT))
    log.info("manifest: %d eligible reciter(s)", len(eligible))

    on_hf_slugs_ts = set(_list_dataset_reciter_slugs(subdir="timestamps"))
    on_hf_slugs_seg = set(_list_dataset_reciter_slugs(subdir="segments"))
    orphans_ts = sorted(on_hf_slugs_ts - eligible)
    orphans_seg = sorted(on_hf_slugs_seg - eligible)
    if orphans_ts:
        log.warning("Orphans on HF timestamps/ (will delete): %s",
                    ", ".join(orphans_ts))
    if orphans_seg:
        log.warning("Orphans on HF segments/ (will delete): %s",
                    ", ".join(orphans_seg))

    reciters_block: dict[str, dict] = {}
    for slug in sorted(eligible):
        rec = by_slug.get(slug, {})
        audio_cat = rec.get("audio_cat", "")
        manifest_data = _find_audio_manifest(slug) or {}
        url_template = (
            _derive_url_template(manifest_data, audio_cat) if manifest_data else ""
        )

        chapters = _list_dataset_chapters(slug, subdir="timestamps")
        seg_chapters = _list_dataset_chapters(slug, subdir="segments")
        # Recompute validation + shard hashes from local source files in one
        # pass — deterministic, no HF round-trip, hashes always match what
        # --build-timestamps / --build-segments wrote.
        local_state = _local_reciter_state(slug)

        block: dict = {
            "name_en": rec.get("name_en", slug.replace("_", " ").title()),
            "name_ar": rec.get("name_ar"),
            "riwayah": rec.get("riwayah", "hafs_an_asim"),
            "style": rec.get("style", "murattal"),
            "source": rec.get("source", ""),
            "audio_category": audio_cat,
            "url_template": url_template,
            "ts_chapters": chapters,
            "vbr_chapters": _vbr_chapters_for_manifest(slug),
            # `seg_chapters` mirrors `ts_chapters` once the segments build has
            # caught up — the aligner Space's preload UI reads it as the
            # surah-dropdown source of truth. Build invariant: a chapter is
            # "published" iff both lists contain it.
            "seg_chapters": seg_chapters,
            "validation": local_state["validation"],
            "_build": {
                "shard_hashes": local_state["shard_hashes"],
                "seg_shard_hashes": local_state["seg_shard_hashes"],
            },
        }
        reciters_block[slug] = block

    # Resource hashes — recomputed from local files for source-of-truth.
    resource_hashes: dict[str, str] = {}
    for key, src_name, _dst, gzip_it in _RESOURCE_SPECS:
        src_path = _QUA_DATA_DIR / src_name
        if src_path.exists():
            _, digest = _hash_file_payload(src_path, gzip_it=gzip_it)
            resource_hashes[key] = digest

    # Resolve commit sha (best-effort — falls back to empty when not in a git repo).
    commit_sha = ""
    try:
        import subprocess
        commit_sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip()
    except Exception:
        pass

    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commit": commit_sha,
        "dataset_base_url": (
            f"https://huggingface.co/datasets/{REPO_ID}/resolve/main"
        ),
        "shard_url_template": "timestamps/{reciter}/{chapter}.json.gz",
        # Aligner Space preload reads this; Inspector ignores unknown keys.
        "segments_shard_url_template": "segments/{reciter}/{chapter}.json.gz",
        "resources": {
            "qpc_hafs": "qpc_hafs.json.gz",
            "digital_khatt": "digital_khatt_v2_script.json.gz",
            "digital_khatt_otf": "DigitalKhattV2.otf",
        },
        "reciters": reciters_block,
        "_build": {"resource_hashes": resource_hashes},
    }

    body = gzip.compress(
        json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
        compresslevel=6, mtime=0,
    )
    log.info(
        "manifest.json.gz: %d bytes (%d reciters, %d ts orphans, %d seg orphans)",
        len(body), len(reciters_block), len(orphans_ts), len(orphans_seg),
    )

    operations: list = [CommitOperationAdd(
        path_in_repo="manifest.json.gz", path_or_fileobj=body,
    )]
    # Recursive delete of orphan reciter trees — separate per subdir since the
    # ts and segments rollouts can drift during transitions.
    for slug in orphans_ts:
        for ch in _list_dataset_chapters(slug, subdir="timestamps"):
            operations.append(CommitOperationDelete(
                path_in_repo=f"timestamps/{slug}/{ch}.json.gz",
            ))
    for slug in orphans_seg:
        for ch in _list_dataset_chapters(slug, subdir="segments"):
            operations.append(CommitOperationDelete(
                path_in_repo=f"segments/{slug}/{ch}.json.gz",
            ))

    if dry_run:
        log.info("[dry-run] would push manifest + %d orphan deletion(s)",
                 len(operations) - 1)
        log.info("[dry-run] sample reciter: %s", next(iter(reciters_block.values()), {}))
        return

    total_orphans = len(orphans_ts) + len(orphans_seg)
    api = HfApi(token=HF_TOKEN)
    api.create_commit(
        repo_id=REPO_ID, repo_type="dataset",
        operations=operations,
        commit_message=(
            f"manifest: {len(reciters_block)} reciters"
            + (f", drop {total_orphans} orphan(s)" if total_orphans else "")
        ),
    )
    log.info("Pushed manifest (%d ops)", len(operations))


# ---------------------------------------------------------------------------
# Reciters catalog config
# ---------------------------------------------------------------------------
def build_reciters_config():
    """Build and push the 'reciters' config — a lightweight catalog of all reciters."""
    from list_reciters import discover_reciters

    with open(ROOT / "data" / "surah_info.json") as f:
        surah_info = json.load(f)

    all_records = discover_reciters()
    log.info("Found %d manifest records", len(all_records))

    # Deduplicate: one row per slug, prefer by_surah
    seen = {}
    for rec in all_records:
        slug = rec["slug"]
        if slug not in seen:
            seen[slug] = rec
        elif rec["audio_cat"] == "by_surah" and seen[slug]["audio_cat"] == "by_ayah":
            seen[slug] = rec

    data = {
        "reciter": [], "is_timestamped": [],
        "name_en": [], "name_ar": [],
        "riwayah": [], "style": [], "country": [], "source": [],
        "audio_category": [], "url_template": [],
        "coverage_surahs": [], "coverage_ayahs": [],
    }

    # Timestamped reciters first; secondary sort by slug (alphabetical).
    is_ts = {s: has_tracked_timestamps(s, ROOT) for s in seen}
    sorted_slugs = sorted(seen.keys(), key=lambda s: (not is_ts[s], s))

    for slug in sorted_slugs:
        rec = seen[slug]
        manifest = _find_audio_manifest(slug)
        meta = manifest.get("_meta", {}) if manifest else {}

        url_template = ""
        if manifest:
            url_template = _derive_url_template(manifest, rec["audio_cat"])

        if rec["audio_cat"] == "by_surah":
            coverage_surahs = rec["coverage"]
            if manifest:
                entries = {k for k in manifest if k != "_meta"}
                coverage_ayahs = sum(
                    len(surah_info[s]["verses"])
                    for s in entries if s in surah_info
                )
            else:
                coverage_ayahs = 0
        else:
            coverage_ayahs = rec["coverage"]
            if manifest:
                surahs = {k.split(":")[0] for k in manifest if k != "_meta" and ":" in k}
                coverage_surahs = len(surahs)
            else:
                coverage_surahs = 0

        data["reciter"].append(slug)
        data["is_timestamped"].append(is_ts[slug])
        data["name_en"].append(rec["name_en"])
        data["name_ar"].append(meta.get("name_ar", "") or "")
        data["riwayah"].append(rec["riwayah"])
        data["style"].append(rec["style"])
        data["country"].append(rec["country"])
        data["source"].append(rec["source"])
        data["audio_category"].append(rec["audio_cat"])
        data["url_template"].append(url_template)
        data["coverage_surahs"].append(coverage_surahs)
        data["coverage_ayahs"].append(coverage_ayahs)

    log.info("Built %d reciters catalog rows", len(data["reciter"]))

    features = Features({
        "reciter": Value("string"),
        "is_timestamped": Value("bool"),
        "name_en": Value("string"),
        "name_ar": Value("string"),
        "riwayah": Value("string"),
        "style": Value("string"),
        "country": Value("string"),
        "source": Value("string"),
        "audio_category": Value("string"),
        "url_template": Value("string"),
        "coverage_surahs": Value("int32"),
        "coverage_ayahs": Value("int32"),
    })

    ds = Dataset.from_dict(data, features=features)

    api = HfApi(token=HF_TOKEN)
    api.create_repo(repo_id=REPO_ID, repo_type="dataset", exist_ok=True)

    ds.push_to_hub(
        REPO_ID,
        config_name="reciters",
        split="all",
        token=HF_TOKEN,
        commit_message="Update reciters catalog",
    )
    log.info("Reciters config pushed to %s (%d rows)", REPO_ID, len(data["reciter"]))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Build and upload reciter data to HF dataset")
    parser.add_argument("slug", nargs="?", help="Reciter slug to upload")
    parser.add_argument("--all", action="store_true", help="Upload all eligible reciters")
    parser.add_argument("--delete", metavar="SLUG", help="Delete a reciter from the dataset")
    parser.add_argument("--update-readme", action="store_true", help="Update dataset card only")
    parser.add_argument("--reciters-config", action="store_true",
                        help="Build and push reciters catalog config")
    parser.add_argument("--build-timestamps", metavar="SLUG",
                        help="Split timestamps_full.json into per-chapter "
                             "gzipped shards and upload changed ones")
    parser.add_argument("--build-segments", metavar="SLUG",
                        help="Split detailed.json into per-chapter gzipped "
                             "segments shards (consumed by aligner Space "
                             "preload mode) and upload changed ones")
    parser.add_argument("--build-resources", action="store_true",
                        help="Upload qpc/dk/font global resources to "
                             "dataset root (idempotent — hash-skip)")
    parser.add_argument("--build-manifest", action="store_true",
                        help="Build and push manifest.json.gz "
                             "(catalog + per-reciter validation + hashes)")
    parser.add_argument("--full-rebuild", action="store_true",
                        help="Force full audio re-download (skip smart reuse)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print upload/delete plan without committing "
                             "(applies to --build-timestamps, "
                             "--build-segments, --build-resources, "
                             "--build-manifest)")
    args = parser.parse_args()

    if not HF_TOKEN:
        sys.exit("HF_TOKEN not set")

    if args.build_timestamps:
        build_timestamp_shards(args.build_timestamps, dry_run=args.dry_run)
        return

    if args.build_segments:
        build_segment_shards(args.build_segments, dry_run=args.dry_run)
        return

    if args.build_resources:
        build_resources(dry_run=args.dry_run)
        return

    if args.build_manifest:
        build_manifest(dry_run=args.dry_run)
        return

    if args.reciters_config:
        build_reciters_config()
        return

    if args.update_readme:
        build_reciters_config()
        update_dataset_readme()
        return

    if args.delete:
        delete_reciter(args.delete)
        build_reciters_config()
        return

    if args.all:
        eligible = find_eligible_reciters(ROOT)
        if not eligible:
            log.info("No eligible reciters found")
            return
        log.info("Found %d eligible reciter(s): %s", len(eligible), ", ".join(eligible))
        for slug in eligible:
            audio_type = detect_audio_source(slug)
            if not audio_type:
                log.warning("Could not detect audio source for %s, skipping", slug)
                continue
            push_reciter(slug, audio_type, full_rebuild=args.full_rebuild)
        build_reciters_config()
        update_dataset_readme()
        return

    if not args.slug:
        parser.print_help()
        return

    audio_type = detect_audio_source(args.slug)
    if not audio_type:
        sys.exit(f"Could not detect audio source for {args.slug}")

    push_reciter(args.slug, audio_type, full_rebuild=args.full_rebuild)
    update_dataset_readme()


if __name__ == "__main__":
    main()
