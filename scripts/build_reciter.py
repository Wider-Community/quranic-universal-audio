#!/usr/bin/env python3
"""
Build and upload a reciter config to the HuggingFace dataset.

Usage:
    python scripts/build_reciter.py <slug>              # Upload one reciter
    python scripts/build_reciter.py --all               # Upload all eligible
    python scripts/build_reciter.py --delete <slug>     # Delete a reciter's data
    python scripts/build_reciter.py --update-readme     # Update dataset card only

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


def _strip_quran_markers(text: str) -> str:
    """Strip non-recited markers (waqf signs, hizb, sajdah) from Uthmani text."""
    return "".join(ch for ch in text if ch not in _QURAN_MARKERS)


def _cross_verse_text(matched_ref: str, matched_text: str,
                      target_ayah: int, surah_info: dict, surah_num: str) -> str:
    """Extract only the target verse's words from a cross-verse segment's text.

    For ref '37:151:3-37:152:2' with 5 words of text, target_ayah=152
    returns the last 2 words (37:152's portion).
    """
    parts = matched_ref.split("-")
    if len(parts) != 2:
        return matched_text
    try:
        sp = parts[0].split(":")
        ep = parts[1].split(":")
        s_ayah, s_word = int(sp[1]), int(sp[2])
        e_ayah, e_word = int(ep[1]), int(ep[2])
    except (ValueError, IndexError):
        return matched_text

    words = matched_text.split()
    if target_ayah == s_ayah:
        # Target is the starting verse — take first N words
        total = surah_info[surah_num]["verses"][s_ayah - 1]["num_words"]
        n = total - s_word + 1
        return " ".join(words[:n])
    elif target_ayah == e_ayah:
        # Target is the ending verse — take last N words
        return " ".join(words[-e_word:]) if e_word > 0 else ""
    return matched_text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from config_loader import repo_config  # noqa: E402

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


def find_eligible_reciters():
    """Find all reciters with timestamps + segments (eligible for dataset)."""
    eligible = []
    seg_dir = ROOT / "data" / "recitation_segments"
    if not seg_dir.is_dir():
        return eligible

    for d in sorted(seg_dir.iterdir()):
        if not d.is_dir():
            continue
        slug = d.name
        if not (d / "detailed.json").exists() or not (d / "segments.json").exists():
            continue
        # Check timestamps exist (timestamps.json is sufficient)
        for audio_type in ("by_ayah_audio", "by_surah_audio"):
            ts_dir = ROOT / "data" / "timestamps" / audio_type / slug
            if (ts_dir / "timestamps.json").exists():
                eligible.append(slug)
                break

    return eligible


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

    log.info("Loading data for %s...", slug)
    with open(ts_path) as f:
        ts_raw = json.load(f)
    with open(detailed_path) as f:
        detailed = json.load(f)
    with open(segments_path) as f:
        segments = json.load(f)
    with open(surah_info_path) as f:
        surah_info = json.load(f)

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
        timestamps[ref] = {
            "words": words,
            "verse_start_ms": words[0][1],
            "verse_end_ms": words[-1][2],
        }

    # Optionally load letter data from timestamps_full.json
    # Each word in full format: [word_idx, start, end, [[char,s,e],...], [[phone,s,e],...]]
    letter_data = {}
    if ts_full_path.exists():
        log.info("Loading letter timestamps from %s...", ts_full_path.name)
        with open(ts_full_path) as f:
            ts_full_raw = json.load(f)
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
        del ts_full_raw

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

    return timestamps, detailed_by_ref, segments, surah_info, letter_data


# ---------------------------------------------------------------------------
# Row building
# ---------------------------------------------------------------------------
def build_rows(timestamps, detailed_by_ref, segments, surah_info, letter_data=None):
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

            # Filter segments to those overlapping the clip range
            verse_segments = []
            if ref in segments and ref != "_meta":
                for seg in segments[ref]:
                    if seg[3] <= clip_start or seg[2] >= clip_end:
                        continue  # segment fully outside clip
                    verse_segments.append([
                        seg[0], seg[1],
                        max(0, seg[2] - clip_start),
                        min(seg[3], clip_end) - clip_start,
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
                        word[0],
                        word[1] - clip_start,
                        word[2] - clip_start,
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
                            "word_idx": word_idx,
                            "char": ch,
                            "start_ms": s - clip_start,
                            "end_ms": e - clip_start,
                        })

            rows.append({
                "surah": int(surah_num),
                "ayah": ayah,
                "duration_ms": clip_end - clip_start,
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
        log.info("Downloading and slicing %d surah audio files (4 parallel)...", len(unique_urls))
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

        with ThreadPoolExecutor(max_workers=4) as pool:
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
        with ThreadPoolExecutor(max_workers=64) as pool:
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

    timestamps, detailed_by_ref, segments, surah_info, letter_data = load_data(slug, audio_type)
    rows = build_rows(timestamps, detailed_by_ref, segments, surah_info, letter_data)
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
        data["source_offset_ms"].append(row["clip_start"])

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
    """Get verse count from segments.json (keys minus _meta)."""
    seg_file = ROOT / "data" / "recitation_segments" / slug / "segments.json"
    if seg_file.exists():
        try:
            data = json.loads(seg_file.read_text())
            return len([k for k in data if k != "_meta"])
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


def _derive_url_template(manifest_data, audio_cat):
    """Derive a URL template from manifest entries.

    Returns a template string with protocol stripped (e.g.
    'server8.mp3quran.net/afs/{surah:03d}.mp3') or empty string on failure.
    Only replaces in the filename portion to avoid hitting patterns in hostnames.
    """
    entries = {k: v for k, v in manifest_data.items() if k != "_meta"}
    if not entries:
        return ""

    if audio_cat == "by_surah":
        if "1" in entries:
            url, surah_num = entries["1"], 1
        else:
            first_key = min(entries.keys(), key=int)
            url, surah_num = entries[first_key], int(first_key)

        base, _, filename = url.rpartition("/")
        if not base:
            return ""
        padded = f"{surah_num:03d}"
        if padded in filename:
            template = base + "/" + filename.replace(padded, "{surah:03d}", 1)
        else:
            s = str(surah_num)
            if s in filename:
                template = base + "/" + filename.replace(s, "{surah}", 1)
            else:
                return ""

        # Validate against another entry
        val_key = "2" if "2" in entries else ("3" if "3" in entries else None)
        if val_key:
            expected = template.format(surah=int(val_key))
            if expected != entries[val_key]:
                return ""

    elif audio_cat == "by_ayah":
        url = entries.get("1:1")
        if not url:
            return ""
        base, _, filename = url.rpartition("/")
        if not base:
            return ""
        if "001001" in filename:
            template = base + "/" + filename.replace("001001", "{surah:03d}{ayah:03d}", 1)
        else:
            return ""
        val = entries.get("2:1")
        if val:
            expected = template.format(surah=2, ayah=1)
            if expected != val:
                return ""
    else:
        return ""

    # Strip protocol so HF dataset viewer doesn't render as audio widget
    for prefix in ("https://", "http://"):
        if template.startswith(prefix):
            template = template[len(prefix):]
            break
    return template


_git_tracked_cache = None


def _get_git_tracked_files():
    """Return cached set of git-tracked files under data/."""
    global _git_tracked_cache
    if _git_tracked_cache is None:
        import subprocess
        result = subprocess.run(
            ["git", "ls-files", "data/timestamps/", "data/recitation_segments/"],
            capture_output=True, text=True, cwd=ROOT,
        )
        _git_tracked_cache = set(result.stdout.strip().splitlines())
    return _git_tracked_cache


def _has_git_tracked_timestamps(slug):
    """Check if timestamps.json is git-tracked for this reciter."""
    tracked = _get_git_tracked_files()
    for audio_type in ("by_ayah_audio", "by_surah_audio"):
        if f"data/timestamps/{audio_type}/{slug}/timestamps.json" in tracked:
            return True
    return False


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

    eligible = find_eligible_reciters()
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
                f"    num_examples: 6236"
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
                f"    num_examples: 6236\n"
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
    processed_count = len(eligible)
    all_slugs = set()
    slug_full_coverage = {}
    riwayat_with_data = set()
    audio_dir = ROOT / "data" / "audio"
    if audio_dir.is_dir():
        for source_type in audio_dir.iterdir():
            if not source_type.is_dir():
                continue
            audio_cat = source_type.name  # "by_surah" or "by_ayah"
            for source in source_type.iterdir():
                if source.is_dir():
                    for f in source.glob("*.json"):
                        slug = f.stem
                        all_slugs.add(slug)
                        try:
                            data = json.loads(f.read_text())
                            meta = data.get("_meta", {})
                            rw = meta.get("riwayah", "hafs_an_asim")
                            riwayat_with_data.add(rw)
                            entries = {k: v for k, v in data.items() if k != "_meta"}
                            cov = len(entries)
                            is_full = (audio_cat == "by_surah" and cov == 114) or \
                                      (audio_cat == "by_ayah" and cov == 6236)
                            if is_full:
                                slug_full_coverage[slug] = True
                        except (json.JSONDecodeError, OSError):
                            pass

    # Compute badge counts (inclusive: all reciters for Audio Only, subset for Timestamped)
    all_total = len(all_slugs)
    all_full = sum(1 for s in all_slugs if slug_full_coverage.get(s, False))
    all_partial = all_total - all_full

    # Aligned full coverage: check segments
    eligible_set = set(eligible)
    aligned_full = 0
    seg_dir = ROOT / "data" / "recitation_segments"
    for slug in eligible:
        seg_file = seg_dir / slug / "segments.json"
        if seg_file.exists():
            try:
                doc = json.loads(seg_file.read_text())
                surahs = set()
                ayah_count = 0
                for key in doc:
                    if key == "_meta":
                        continue
                    ayah_count += 1
                    surahs.add(key.split(":")[0])
                if len(surahs) == 114 or ayah_count == 6236:
                    aligned_full += 1
            except (json.JSONDecodeError, OSError):
                pass
    ts_partial = processed_count - aligned_full

    # Load hours from cache
    cache_path = ROOT / "data" / ".audio_durations.json"
    total_hours = 0
    ts_hours = 0
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
            total_hours = round(sum(e["duration_s"] for e in cache.values()) / 3600)
            ts_hours = round(sum(cache[s]["duration_s"] for s in eligible_set if s in cache) / 3600)
        except Exception as e:
            log.warning("Could not read audio durations cache: %s", e)

    # Audio Only badge
    audio_val = f"{all_full}%20Full%20%C2%B7%20{all_partial}%20Partial%20%C2%B7%20{total_hours:,}h"
    body = re.sub(r"Audio%20Only-[^-]+-d4842a", f"Audio%20Only-{audio_val}-d4842a", body)

    # Timestamped badge
    ts_val = f"{aligned_full}%20Full%20%C2%B7%20{ts_partial}%20Partial%20%C2%B7%20{ts_hours:,}h"
    body = re.sub(r"Timestamped-[^-]+-d4842a", f"Timestamped-{ts_val}-d4842a", body)

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
        "reciter": [], "name_en": [], "name_ar": [],
        "riwayah": [], "style": [], "country": [], "source": [],
        "audio_category": [], "url_template": [],
        "coverage_surahs": [], "coverage_ayahs": [],
        "is_timestamped": [],
    }

    for slug in sorted(seen):
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
        data["is_timestamped"].append(_has_git_tracked_timestamps(slug))

    log.info("Built %d reciters catalog rows", len(data["reciter"]))

    features = Features({
        "reciter": Value("string"),
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
        "is_timestamped": Value("bool"),
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
    parser.add_argument("--full-rebuild", action="store_true",
                        help="Force full audio re-download (skip smart reuse)")
    args = parser.parse_args()

    if not HF_TOKEN:
        sys.exit("HF_TOKEN not set")

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
        eligible = find_eligible_reciters()
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
