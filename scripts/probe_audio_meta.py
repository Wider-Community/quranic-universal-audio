"""Probe audio manifests for VBR/CBR status; write data/.audio_meta.json.

The Inspector reads this file to route playback for VBR-without-Xing-header
MP3s, which mis-seek under HTML5 <audio>.currentTime and our peaks.py byte
arithmetic. Detection is hybrid:

  1. mutagen.mp3.MP3.info.bitrate_mode reads Xing/Info/VBRI/LAME headers
     when present (authoritative).
  2. Direct MP3 frame-header bitrate scan as fallback. The 4-bit bitrate
     field per frame is the spec-level ground truth — distinct values
     across frames means VBR.

Default scope: reciters under data/recitation_segments/ (the inspector's
read scope). Use --all to probe every reciter that has an audio manifest
under data/audio/by_*.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from mutagen.mp3 import MP3, BitrateMode

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIO_META_PATH = REPO_ROOT / "data" / ".audio_meta.json"
SEGMENTS_DIR = REPO_ROOT / "data" / "recitation_segments"
AUDIO_DIR = REPO_ROOT / "data" / "audio"

SCHEMA_VERSION = 1
PROBE_CHUNK_BYTES = 262_144  # 256 KB — accuracy floor empirically validated
PROBE_METHOD = "mutagen+frame-scan"
TOOL_VERSION = "vbr-detect/1.0"
FETCH_TIMEOUT_S = 30
MAX_WORKERS = 12

MODE_NAMES = {
    BitrateMode.UNKNOWN: "UNKNOWN",
    BitrateMode.CBR: "CBR",
    BitrateMode.VBR: "VBR",
    BitrateMode.ABR: "ABR",
}

# MPEG-1 Layer III bitrate table (kbps), indexed 1..14. 0 = free, 15 = bad.
BITRATE_V1_L3 = [None, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, None]
BITRATE_V2_L3 = [None, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, None]

logger = logging.getLogger("probe_audio_meta")


def scan_frame_bitrates(buf: bytes, max_frames: int = 2000) -> list[int]:
    """Walk MP3 frame headers, return bitrates (kbps) seen.

    Reads the 4-bit bitrate index from each MPEG-1/2/2.5 Layer III frame
    header and resolves it via the spec table. Distinct values across
    frames is the spec-level VBR signal (no padding-bit false positives).
    """
    bitrates: list[int] = []
    i = 0
    n = len(buf)
    while i < n - 4 and len(bitrates) < max_frames:
        if buf[i] == 0xFF and (buf[i + 1] & 0xE0) == 0xE0:
            b1 = buf[i + 1]
            b2 = buf[i + 2]
            version_id = (b1 >> 3) & 0x03
            layer = (b1 >> 1) & 0x03
            if layer != 1 or version_id == 1:
                i += 1
                continue
            br_index = (b2 >> 4) & 0x0F
            sr_index = (b2 >> 2) & 0x03
            padding = (b2 >> 1) & 0x01
            if br_index in (0, 15) or sr_index == 3:
                i += 1
                continue
            if version_id == 3:
                bitrate = BITRATE_V1_L3[br_index]
                sr_table = [44100, 48000, 32000]
            else:
                bitrate = BITRATE_V2_L3[br_index]
                sr_table = [22050, 24000, 16000] if version_id == 2 else [11025, 12000, 8000]
            if bitrate is None:
                i += 1
                continue
            sample_rate = sr_table[sr_index]
            samples_per_frame = 1152 if version_id == 3 else 576
            frame_size = (samples_per_frame // 8) * (bitrate * 1000) // sample_rate + padding
            if frame_size < 24 or i + frame_size + 4 > n:
                i += 1
                continue
            # Sync-validate: next position should also start with a frame sync
            if i + frame_size < n - 1:
                if buf[i + frame_size] != 0xFF or (buf[i + frame_size + 1] & 0xE0) != 0xE0:
                    i += 1
                    continue
            bitrates.append(bitrate)
            i += frame_size
        else:
            i += 1
    return bitrates


def fetch_head(url: str, n: int = PROBE_CHUNK_BYTES) -> bytes:
    """Range-fetch the first n bytes. Retries transient DNS/connection errors
    once with a short backoff — Python's urllib on Windows has a known stale
    getaddrinfo behaviour under burst load that resolves on retry.
    """
    import time
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            req = Request(url, headers={
                "Range": f"bytes=0-{n - 1}",
                "User-Agent": f"{TOOL_VERSION} (+https://github.com/anthropics/quranic-universal-audio)",
            })
            with urlopen(req, timeout=FETCH_TIMEOUT_S) as r:
                return r.read()
        except (URLError, TimeoutError, OSError) as e:
            last_err = e
            time.sleep(0.5)
    raise last_err if last_err else RuntimeError("fetch_head failed without exception")


def classify(url: str) -> dict:
    """Return per-chapter audio_meta entry, or {'error': ...} on failure."""
    try:
        buf = fetch_head(url)
    except (URLError, TimeoutError, OSError) as e:
        return {"error": f"fetch: {type(e).__name__}: {e}"}

    out: dict = {"url": url}

    # Layer 1: header tags via mutagen
    try:
        mp3 = MP3(io.BytesIO(buf))
        mut_mode = MODE_NAMES.get(mp3.info.bitrate_mode, "UNKNOWN")
        out["bitrate_kbps"] = mp3.info.bitrate // 1000
        out["sample_rate"] = mp3.info.sample_rate
    except Exception as e:
        mut_mode = f"ERR:{type(e).__name__}"

    # Layer 2: frame-header bitrate scan (always run for ground truth)
    bitrates = scan_frame_bitrates(buf)
    if not bitrates:
        frame_mode = "NO_FRAMES"
    elif len(set(bitrates)) == 1:
        frame_mode = "CBR"
    else:
        frame_mode = "VBR"

    if mut_mode in ("CBR", "VBR", "ABR"):
        verdict = mut_mode
    elif frame_mode in ("CBR", "VBR"):
        verdict = frame_mode
    else:
        verdict = "UNKNOWN"

    out["bitrate_mode"] = verdict
    out["vbr"] = verdict in ("VBR", "ABR")

    # Fill bitrate/sample_rate from frame-scan if mutagen errored
    if "bitrate_kbps" not in out and bitrates:
        out["bitrate_kbps"] = round(sum(bitrates) / len(bitrates))
    return out


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def find_audio_manifest(reciter: str) -> Path | None:
    """Return the by_surah manifest path for a reciter, preferred over by_ayah.

    The inspector's segments tab plays full-surah audio; by_surah is the
    canonical source. Falls back to by_ayah if no by_surah variant exists.
    """
    for category in ("by_surah", "by_ayah"):
        for source_dir in (AUDIO_DIR / category).glob("*/"):
            candidate = source_dir / f"{reciter}.json"
            if candidate.is_file():
                return candidate
    return None


def list_inspector_reciters() -> list[str]:
    if not SEGMENTS_DIR.is_dir():
        return []
    return sorted(p.name for p in SEGMENTS_DIR.iterdir() if p.is_dir() and not p.name.startswith("."))


def list_all_reciters_with_manifest() -> list[str]:
    seen: set[str] = set()
    for category in ("by_surah", "by_ayah"):
        cat_dir = AUDIO_DIR / category
        if not cat_dir.is_dir():
            continue
        for source_dir in cat_dir.iterdir():
            if not source_dir.is_dir():
                continue
            for p in source_dir.glob("*.json"):
                seen.add(p.stem)
    return sorted(seen)


def load_existing_meta() -> dict:
    if AUDIO_META_PATH.is_file():
        with open(AUDIO_META_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {
        "_schema": SCHEMA_VERSION,
        "_probe": {
            "chunk_bytes": PROBE_CHUNK_BYTES,
            "method": PROBE_METHOD,
            "tool_version": TOOL_VERSION,
        },
    }


def save_meta(meta: dict) -> None:
    AUDIO_META_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(AUDIO_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")


def probe_reciter(reciter: str, *, full: bool = False, refresh: bool = False,
                  meta: dict | None = None) -> tuple[str, dict | None, str]:
    """Return (reciter, section_dict_or_None, status_message)."""
    manifest_path = find_audio_manifest(reciter)
    if manifest_path is None:
        return reciter, None, "no manifest"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_hash = md5_file(manifest_path)

    if meta is not None and not refresh:
        existing = meta.get(reciter)
        if existing and existing.get("manifest_hash") == manifest_hash:
            return reciter, existing, "skipped (hash match)"

    chapters = [(k, v) for k, v in manifest.items()
                if not k.startswith("_") and isinstance(v, str) and v.startswith("http")]

    by_chapter: dict[str, dict] = {}
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futs = {ex.submit(classify, url): chapter for chapter, url in chapters}
        for fut in as_completed(futs):
            chapter = futs[fut]
            res = fut.result()
            if "error" in res:
                errors.append(f"{chapter}: {res['error']}")
                continue
            entry = {
                "url": res["url"],
                "vbr": res["vbr"],
                "bitrate_mode": res["bitrate_mode"],
            }
            if "bitrate_kbps" in res:
                entry["bitrate_kbps"] = res["bitrate_kbps"]
            if "sample_rate" in res:
                entry["sample_rate"] = res["sample_rate"]
            # Default: only persist VBR entries (missing key implies CBR).
            # --full keeps everything for diagnostic dumps.
            if full or res["vbr"]:
                by_chapter[chapter] = entry

    section = {
        "manifest_hash": manifest_hash,
        "manifest_path": str(manifest_path.relative_to(REPO_ROOT)).replace("\\", "/"),
        "probed_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "by_chapter": dict(sorted(by_chapter.items(), key=lambda kv: int(kv[0]) if kv[0].isdigit() else 9999)),
    }
    if errors:
        section["_errors"] = errors

    n_total = len(chapters)
    n_vbr = sum(1 for v in by_chapter.values() if v["vbr"])
    status = f"{n_vbr}/{n_total} VBR" + (f"; {len(errors)} errors" if errors else "")
    return reciter, section, status


def main() -> int:
    p = argparse.ArgumentParser(description="Probe audio manifests for VBR status.")
    target = p.add_mutually_exclusive_group()
    target.add_argument("--reciter", help="Probe a single reciter slug.")
    target.add_argument("--all", action="store_true", help="Probe every reciter with an audio manifest.")
    p.add_argument("--inspector", action="store_true", default=True,
                   help="Probe reciters under data/recitation_segments/ (default).")
    p.add_argument("--refresh-existing", action="store_true",
                   help="Re-probe even when the manifest hash matches the cached entry.")
    p.add_argument("--full", action="store_true",
                   help="Persist a per-chapter entry for every chapter, not just VBR ones.")
    p.add_argument("--dry-run", action="store_true",
                   help="Probe and print results, but do not write data/.audio_meta.json.")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    if args.reciter:
        reciters = [args.reciter]
    elif args.all:
        reciters = list_all_reciters_with_manifest()
    else:
        reciters = list_inspector_reciters()

    if not reciters:
        logger.error("No reciters to probe.")
        return 1

    logger.info("Probing %d reciters; chunk=%d KB", len(reciters), PROBE_CHUNK_BYTES // 1024)

    meta = load_existing_meta()
    for reciter in reciters:
        reciter, section, status = probe_reciter(
            reciter, full=args.full, refresh=args.refresh_existing, meta=meta,
        )
        if section is None:
            logger.warning("  %-32s skipped: %s", reciter, status)
            continue
        meta[reciter] = section
        logger.info("  %-32s %s", reciter, status)

    if args.dry_run:
        logger.info("Dry-run; not writing %s", AUDIO_META_PATH)
        return 0

    save_meta(meta)
    logger.info("Wrote %s", AUDIO_META_PATH.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
