"""One-off script to build and upload minshawy_murattal to HF dataset."""

import io
import json
import logging
import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from datasets import Audio, Dataset, Features, Sequence, Value
from huggingface_hub import HfApi
from pydub import AudioSegment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
RECITER = "minshawy_murattal"
RIWAYAH = "hafs_an_asim"
REPO_ID = "hetchyy/quranic-universal-ayahs"
SAMPLE_PCT = int(os.environ.get("SAMPLE_PCT", "5"))  # 0 = full, else percentage
HF_TOKEN = os.environ.get("HF_TOKEN", "")

# Load .env fallback
if not HF_TOKEN:
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("HF_TOKEN="):
                HF_TOKEN = line.split("=", 1)[1].strip()
                break

if not HF_TOKEN:
    sys.exit("HF_TOKEN not set")


def load_data():
    ts_full_path = ROOT / "data/timestamps/by_ayah_audio" / RECITER / "timestamps_full.json"
    detailed_path = ROOT / "data/recitation_segments" / RECITER / "detailed.json"
    segments_path = ROOT / "data/recitation_segments" / RECITER / "segments.json"
    surah_info_path = ROOT / "data/surah_info.json"

    log.info("Loading data files...")
    with open(ts_full_path) as f:
        ts_full = json.load(f)
    with open(detailed_path) as f:
        detailed = json.load(f)
    with open(segments_path) as f:
        segments = json.load(f)
    with open(surah_info_path) as f:
        surah_info = json.load(f)

    # Index detailed entries by ref
    detailed_by_ref = {}
    for entry in detailed["entries"]:
        detailed_by_ref[entry["ref"]] = entry

    return ts_full, detailed_by_ref, segments, surah_info


def download_and_slice(url, clip_start_ms, clip_end_ms, retries=3):
    """Download MP3 from URL, slice at clip boundaries, return MP3 bytes."""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                mp3_data = resp.read()
            audio = AudioSegment.from_file(io.BytesIO(mp3_data), format="mp3")
            clip = audio[clip_start_ms:clip_end_ms]
            buf = io.BytesIO()
            clip.export(buf, format="mp3", bitrate="128k")
            return buf.getvalue()
        except Exception as e:
            if attempt == retries - 1:
                raise
            log.warning("Retry %d for %s: %s", attempt + 1, url, e)
    return None


def build_rows(ts_full, detailed_by_ref, segments, surah_info):
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
            if ref in ts_full and ref != "_meta":
                verse_data = ts_full[ref]
                clip_start = verse_data["verse_start_ms"]
                clip_end = verse_data["verse_end_ms"]
            elif ref in segments and ref != "_meta":
                seg_list = segments[ref]
                clip_start = seg_list[0][2]  # first segment time_from
                clip_end = seg_list[-1][3]    # last segment time_to
            else:
                log.warning("No timing data for %s, skipping", ref)
                continue

            # Text from segments
            text = " ".join(seg["matched_text"] for seg in entry["segments"])

            # Segments column (shifted) — [word_from, word_to, start, end]
            verse_segments = []
            if ref in segments and ref != "_meta":
                for seg in segments[ref]:
                    verse_segments.append([
                        seg[0], seg[1],
                        max(0, seg[2] - clip_start),
                        seg[3] - clip_start,
                    ])

            # Words column (shifted) — [word, start, end]
            verse_words = []
            if ref in ts_full and ref != "_meta":
                for word in ts_full[ref]["words"]:
                    verse_words.append([
                        word[0],
                        word[1] - clip_start,
                        word[2] - clip_start,
                    ])

            rows.append({
                "reciter": RECITER,
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


def download_all_audio(rows):
    """Download and slice audio for all rows in parallel."""
    audio_bytes_list = [None] * len(rows)
    failed = []

    def process(idx):
        row = rows[idx]
        mp3 = download_and_slice(row["audio_url"], row["clip_start"], row["clip_end"])
        return idx, mp3

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


def main():
    ts_full, detailed_by_ref, segments, surah_info = load_data()
    rows = build_rows(ts_full, detailed_by_ref, segments, surah_info)
    log.info("Built %d rows", len(rows))

    if SAMPLE_PCT > 0:
        step = max(1, 100 // SAMPLE_PCT)
        rows = rows[::step]
        log.info("Sampling %d%% → %d rows", SAMPLE_PCT, len(rows))

    audio_bytes_list, failed = download_all_audio(rows)

    # Build dataset dict (skip failed downloads)
    data = {
        "audio": [],
        "reciter": [],
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
        data["reciter"].append(row["reciter"])
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
        "reciter": Value("string"),
        "surah": Value("int32"),
        "ayah": Value("int32"),
        "text": Value("string"),
        "segments": Sequence(Sequence(Value("int32"))),
        "words": Sequence(Sequence(Value("int32"))),
    })

    ds = Dataset.from_dict(data, features=features)

    # Create repo and upload README first
    api = HfApi(token=HF_TOKEN)
    api.create_repo(repo_id=REPO_ID, repo_type="dataset", exist_ok=True)
    readme_path = Path(__file__).parent / "README.md"
    api.upload_file(
        path_or_fileobj=str(readme_path),
        path_in_repo="README.md",
        repo_id=REPO_ID,
        repo_type="dataset",
        commit_message="Add dataset card",
    )

    log.info("Pushing to hub as %s/%s...", RIWAYAH, RECITER)
    ds.push_to_hub(
        REPO_ID,
        config_name=RIWAYAH,
        split=RECITER,
        token=HF_TOKEN,
        max_shard_size="10GB",
        commit_message=f"Add {RIWAYAH}/{RECITER}",
    )
    log.info("Done! Dataset available at https://huggingface.co/datasets/%s", REPO_ID)


if __name__ == "__main__":
    main()
