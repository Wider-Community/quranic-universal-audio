#!/usr/bin/env python3
"""
Build and upload a reciter config to the HuggingFace dataset.

Usage:
    python dataset/build_reciter.py <slug>              # Upload one reciter
    python dataset/build_reciter.py --all               # Upload all eligible
    python dataset/build_reciter.py --delete <slug>     # Delete a reciter's data
    python dataset/build_reciter.py --update-readme     # Update dataset card only

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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from datasets import Audio, Dataset, Features, Sequence, Value
from huggingface_hub import HfApi

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
REPO_ID = "hetchyy/quranic-universal-ayahs"
RIWAYAH = "hafs_an_asim"
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
    end). This avoids requiring timestamps_full.json which contains large
    letter/phoneme data not used by the HF dataset.
    """
    ts_path = ROOT / "data" / "timestamps" / audio_type / slug / "timestamps.json"
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

    detailed_by_ref = {}
    for entry in detailed["entries"]:
        detailed_by_ref[entry["ref"]] = entry

    return timestamps, detailed_by_ref, segments, surah_info


# ---------------------------------------------------------------------------
# Row building
# ---------------------------------------------------------------------------
def build_rows(timestamps, detailed_by_ref, segments, surah_info):
    """Build row metadata (without audio bytes) in canonical verse order."""
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

            # Clip boundaries
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

            text = " ".join(seg["matched_text"] for seg in entry["segments"])

            verse_segments = []
            if ref in segments and ref != "_meta":
                for seg in segments[ref]:
                    verse_segments.append([
                        seg[0], seg[1],
                        max(0, seg[2] - clip_start),
                        seg[3] - clip_start,
                    ])

            verse_words = []
            if ref in timestamps and ref != "_meta":
                for word in timestamps[ref]["words"]:
                    verse_words.append([
                        word[0],
                        word[1] - clip_start,
                        word[2] - clip_start,
                    ])

            rows.append({
                "surah": int(surah_num),
                "ayah": ayah,
                "text": text,
                "segments": verse_segments,
                "words": verse_words,
                "audio_url": entry["audio"],
                "clip_start": clip_start,
                "clip_end": clip_end,
            })

    return rows


# ---------------------------------------------------------------------------
# Audio download
# ---------------------------------------------------------------------------
_surah_cache = {}  # url -> AudioSegment (for by_surah sources)


def _lazy_import_pydub():
    from pydub import AudioSegment as AS
    return AS


def download_and_slice(url, clip_start_ms, clip_end_ms, is_surah=False, retries=3):
    """Download audio and slice at clip boundaries, return MP3 bytes."""
    AS = _lazy_import_pydub()

    for attempt in range(retries):
        try:
            if is_surah:
                if url not in _surah_cache:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=60) as resp:
                        audio_data = resp.read()
                    _surah_cache[url] = AS.from_file(io.BytesIO(audio_data))
                clip = _surah_cache[url][clip_start_ms:clip_end_ms]
            else:
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
        # For by_surah: download surahs first (limited parallel), then slice
        unique_urls = list({row["audio_url"] for row in rows})
        log.info("Pre-downloading %d surah audio files...", len(unique_urls))
        AS = _lazy_import_pydub()

        def dl_surah(url):
            if url in _surah_cache:
                return
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            _surah_cache[url] = AS.from_file(io.BytesIO(data))

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(dl_surah, unique_urls))

        # Slice verses from cached surahs (fast, no network)
        for i, row in enumerate(rows):
            try:
                clip = _surah_cache[row["audio_url"]][row["clip_start"]:row["clip_end"]]
                buf = io.BytesIO()
                clip.export(buf, format="mp3", bitrate="128k")
                audio_bytes_list[i] = buf.getvalue()
            except Exception as e:
                ref = f"{row['surah']}:{row['ayah']}"
                log.error("Failed to slice %s: %s", ref, e)
                failed.append(ref)
            if (i + 1) % 500 == 0:
                log.info("Progress: %d/%d sliced", i + 1, len(rows))
    else:
        # For by_ayah: parallel individual downloads
        def process(idx):
            row = rows[idx]
            return idx, download_and_slice(row["audio_url"], row["clip_start"], row["clip_end"])

        log.info("Downloading and slicing %d audio files (32 workers)...", len(rows))
        completed = 0
        with ThreadPoolExecutor(max_workers=32) as pool:
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
# Dataset push
# ---------------------------------------------------------------------------
def push_reciter(slug, audio_type):
    """Build and push a reciter to the HF dataset."""
    is_surah = "by_surah" in audio_type

    timestamps, detailed_by_ref, segments, surah_info = load_data(slug, audio_type)
    rows = build_rows(timestamps, detailed_by_ref, segments, surah_info)
    log.info("Built %d rows for %s", len(rows), slug)

    if SAMPLE_PCT > 0:
        step = max(1, 100 // SAMPLE_PCT)
        rows = rows[::step]
        log.info("Sampling %d%% → %d rows", SAMPLE_PCT, len(rows))

    audio_bytes_list, failed = download_all_audio(rows, is_surah=is_surah)

    data = {
        "audio": [],
        "surah": [],
        "ayah": [],
        "text": [],
        "segments": [],
        "words": [],
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
        data["text"].append(row["text"])
        data["segments"].append(row["segments"])
        data["words"].append(row["words"])

    if skipped:
        log.warning("Skipped %d verses due to download failures", skipped)

    log.info("Creating dataset with %d rows...", len(data["audio"]))
    features = Features({
        "audio": Audio(),
        "surah": Value("int32"),
        "ayah": Value("int32"),
        "text": Value("string"),
        "segments": Sequence(Sequence(Value("int32"))),
        "words": Sequence(Sequence(Value("int32"))),
    })

    ds = Dataset.from_dict(data, features=features)

    api = HfApi(token=HF_TOKEN)
    api.create_repo(repo_id=REPO_ID, repo_type="dataset", exist_ok=True)

    log.info("Pushing to hub as %s/%s...", RIWAYAH, slug)
    ds.push_to_hub(
        REPO_ID,
        config_name=RIWAYAH,
        split=slug,
        token=HF_TOKEN,
        max_shard_size="10GB",
        commit_message=f"Add {RIWAYAH}/{slug}",
    )
    log.info("Done: %s uploaded to %s", slug, REPO_ID)

    # Clear surah cache to free memory before next reciter
    _surah_cache.clear()


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
                "by_surah/qul": "qul.tarteel.ai",
                "by_surah/surah-quran": "surah-quran.com",
                "by_surah/asswatul-quran": "asswatul-quran.com",
            }
            return source_map.get(source, source)
        except Exception:
            pass
    return "unknown"


def get_display_name(slug):
    """Convert slug to display name."""
    return slug.replace("_", " ").title()


def update_dataset_readme(add_slug=None, remove_slug=None):
    """Update dataset/README.md YAML configs and markdown table."""
    readme_path = ROOT / "dataset" / "README.md"
    text = readme_path.read_text()

    # Split YAML frontmatter from body
    parts = text.split("---", 2)
    if len(parts) < 3:
        log.error("Could not parse README.md frontmatter")
        return
    yaml_text = parts[1]
    body = parts[2]

    if add_slug:
        # Add to YAML data_files
        new_entry = f"      - split: {add_slug}\n        path: data/{RIWAYAH}/{add_slug}-*"
        if add_slug not in yaml_text:
            # Insert before the closing of data_files
            yaml_text = yaml_text.rstrip() + f"\n{new_entry}\n"

        # Add to markdown table
        source_label = get_audio_source_label(add_slug)
        display_name = get_display_name(add_slug)
        new_row = f"| `{RIWAYAH}` | `{add_slug}` | {display_name} | 6,236 | {source_label} |"
        if add_slug not in body:
            # Find the table and append
            body = re.sub(
                r"(\| `" + RIWAYAH + r"` \| .+\|[^\n]*)",
                lambda m: m.group(0) + "\n" + new_row,
                body,
                count=1,
            )
            # If no existing row, append after table header
            if add_slug not in body:
                body = body.replace(
                    "| `hafs_an_asim` |",
                    f"| `hafs_an_asim` |",
                    1,
                )
                # Append to end of table
                table_end = body.rfind("|")
                if table_end != -1:
                    # Find end of current last row
                    next_newline = body.find("\n", table_end)
                    if next_newline != -1:
                        body = body[:next_newline + 1] + new_row + "\n" + body[next_newline + 1:]

    if remove_slug:
        # Remove from YAML
        yaml_text = re.sub(
            rf"\s*- split: {remove_slug}\n\s*path: data/{RIWAYAH}/{remove_slug}-\*",
            "",
            yaml_text,
        )
        # Remove from markdown table
        body = re.sub(rf"\| `{RIWAYAH}` \| `{remove_slug}` \|[^\n]*\n?", "", body)

    text = f"---{yaml_text}---{body}"
    readme_path.write_text(text)

    # Upload to HF
    api = HfApi(token=HF_TOKEN)
    api.upload_file(
        path_or_fileobj=str(readme_path),
        path_in_repo="README.md",
        repo_id=REPO_ID,
        repo_type="dataset",
        commit_message=f"Update dataset card",
    )
    log.info("Dataset README updated")


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------
def delete_reciter(slug):
    """Delete a reciter's parquet data from HF dataset."""
    api = HfApi(token=HF_TOKEN)
    path = f"data/{RIWAYAH}/{slug}"
    try:
        api.delete_folder(
            repo_id=REPO_ID,
            path_in_repo=path,
            repo_type="dataset",
            commit_message=f"Remove {RIWAYAH}/{slug}",
        )
        log.info("Deleted %s from %s", path, REPO_ID)
    except Exception as e:
        log.error("Failed to delete %s: %s", path, e)

    update_dataset_readme(remove_slug=slug)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Build and upload reciter data to HF dataset")
    parser.add_argument("slug", nargs="?", help="Reciter slug to upload")
    parser.add_argument("--all", action="store_true", help="Upload all eligible reciters")
    parser.add_argument("--delete", metavar="SLUG", help="Delete a reciter from the dataset")
    parser.add_argument("--update-readme", action="store_true", help="Update dataset card only")
    args = parser.parse_args()

    if not HF_TOKEN:
        sys.exit("HF_TOKEN not set")

    if args.update_readme:
        # Re-sync README with all eligible reciters
        eligible = find_eligible_reciters()
        for slug in eligible:
            update_dataset_readme(add_slug=slug)
        return

    if args.delete:
        delete_reciter(args.delete)
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
            push_reciter(slug, audio_type)
            update_dataset_readme(add_slug=slug)
        return

    if not args.slug:
        parser.print_help()
        return

    audio_type = detect_audio_source(args.slug)
    if not audio_type:
        sys.exit(f"Could not detect audio source for {args.slug}")

    push_reciter(args.slug, audio_type)
    update_dataset_readme(add_slug=args.slug)


if __name__ == "__main__":
    main()
