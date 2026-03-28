#!/usr/bin/env python3
"""
Package release zips for GitHub Releases.

Usage:
    python scripts/package_release.py                      # Build all, auto-version
    python scripts/package_release.py --dry-run             # Preview only
    python scripts/package_release.py --version v0.2.0      # Override version
    python scripts/package_release.py --output-dir /tmp/r   # Custom output dir
"""

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
from config_loader import repo_config  # noqa: E402

_cfg = repo_config()
REPO_OWNER = _cfg["repo_owner"]
REPO_NAME = _cfg["repo_name"]
DEFAULT_OUTPUT_DIR = ROOT / "dist"


# ---------------------------------------------------------------------------
# Eligibility detection
# ---------------------------------------------------------------------------
def find_release_eligible():
    """Find reciters with segments.json + timestamps.json tracked in git."""
    eligible = []
    seg_dir = ROOT / "data" / "recitation_segments"
    if not seg_dir.is_dir():
        return eligible

    for d in sorted(seg_dir.iterdir()):
        if not d.is_dir():
            continue
        slug = d.name
        if not (d / "segments.json").exists():
            continue
        # Check timestamps.json exists in either audio type
        for audio_type in ("by_ayah_audio", "by_surah_audio"):
            ts_path = ROOT / "data" / "timestamps" / audio_type / slug / "timestamps.json"
            if ts_path.exists():
                eligible.append(slug)
                break

    return eligible


# ---------------------------------------------------------------------------
# Audio source detection (pattern from quranic_universal_ayahs/build_reciter.py)
# ---------------------------------------------------------------------------
def detect_audio_source(slug):
    """Read _meta.audio_source from segments.json."""
    seg_file = ROOT / "data" / "recitation_segments" / slug / "segments.json"
    if not seg_file.exists():
        return None
    try:
        first_line = seg_file.read_text(encoding="utf-8").split("\n", 1)[0]
        meta = json.loads(first_line).get("_meta", {})
        return meta.get("audio_source", "")
    except Exception:
        return None


def find_audio_manifest(slug):
    """Resolve audio manifest path from _meta.audio_source.

    Maps e.g. 'by_ayah/everyayah' -> data/audio/by_ayah/everyayah/<slug>.json
    """
    source = detect_audio_source(slug)
    if not source:
        return None
    manifest = ROOT / "data" / "audio" / source / f"{slug}.json"
    return manifest if manifest.exists() else None


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------
def load_meta(path):
    """Load _meta from a JSON file (single-line or pretty-printed)."""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}
    # Try single-line format first (JSONL-style segments/detailed files)
    first_line = text.split("\n", 1)[0]
    try:
        meta = json.loads(first_line).get("_meta")
        if meta is not None:
            return meta
    except (json.JSONDecodeError, AttributeError):
        pass
    # Fall back to full JSON parse (pretty-printed audio manifests)
    try:
        return json.loads(text).get("_meta", {})
    except Exception:
        return {}


def compute_coverage(slug):
    """Count surahs and ayahs in segments.json."""
    seg_file = ROOT / "data" / "recitation_segments" / slug / "segments.json"
    data = json.loads(seg_file.read_text(encoding="utf-8"))
    verse_keys = [k for k in data if not k.startswith("_")]
    surahs = set()
    for k in verse_keys:
        surahs.add(k.split(":")[0])
    return {"surahs": len(surahs), "ayahs": len(verse_keys)}


def build_info_json(slug, version):
    """Build info.json from _meta blocks."""
    seg_meta = load_meta(ROOT / "data" / "recitation_segments" / slug / "segments.json")
    audio_source = seg_meta.get("audio_source", "")

    manifest_path = find_audio_manifest(slug)
    audio_meta = load_meta(manifest_path) if manifest_path else {}

    riwayah = audio_meta.get("riwayah", "hafs_an_asim")
    display_name = audio_meta.get("name_en") or slug.replace("_", " ").title()

    return {
        "reciter": slug,
        "reciter_display": display_name,
        "name_en": audio_meta.get("name_en", ""),
        "name_ar": audio_meta.get("name_ar", ""),
        "riwayah": riwayah,
        "style": audio_meta.get("style", "unknown"),
        "country": audio_meta.get("country", "unknown"),
        "audio_source": audio_source,
        "coverage": compute_coverage(slug),
        "version": version,
        "created": str(date.today()),
    }


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------
def is_git_tracked(path):
    """Check if a file is tracked in git (not gitignored)."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(path)],
            cwd=ROOT, capture_output=True, text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


def get_last_tag():
    """Get the latest v* tag, or None."""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "--match", "v*"],
            cwd=ROOT, capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Version computation
# ---------------------------------------------------------------------------
def get_previous_manifest(tag):
    """Download manifest.json from a previous GitHub release."""
    url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/download/{tag}/manifest.json"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.warning("Could not fetch previous manifest from %s: %s", url, e)
        return None


def compute_version(current_checksums, previous_manifest):
    """Auto-compute next v0.Y.Z.

    Rules:
        - No previous manifest: v0.1.0
        - New reciter(s) added: bump minor
        - Existing reciter data changed: bump patch
        - No changes: return None (skip release)
    """
    if previous_manifest is None:
        return "v0.1.0"

    prev_version = previous_manifest.get("version", "v0.0.0")
    parts = prev_version.lstrip("v").split(".")
    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    prev_slugs = {r["slug"]: r.get("zip_sha256", "") for r in previous_manifest.get("reciters", [])}
    curr_slugs = set(current_checksums.keys())

    new_slugs = curr_slugs - set(prev_slugs.keys())
    if new_slugs:
        return f"v{major}.{minor + 1}.0"

    # Check for changed data
    changed = False
    for slug, checksum in current_checksums.items():
        if slug in prev_slugs and prev_slugs[slug] != checksum:
            changed = True
            break

    if changed:
        return f"v{major}.{minor}.{patch + 1}"

    return None  # No changes


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------
def sha256_file(path):
    """Compute SHA-256 of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def find_timestamps_dir(slug):
    """Find the timestamps directory for a reciter."""
    for audio_type in ("by_ayah_audio", "by_surah_audio"):
        ts_dir = ROOT / "data" / "timestamps" / audio_type / slug
        if (ts_dir / "timestamps.json").exists():
            return ts_dir
    return None


def package_reciter(slug, version, output_dir):
    """Create <slug>.zip with data files.

    Returns dict with slug, zip_path, sha256, size, has_timestamps_full.
    """
    ts_dir = find_timestamps_dir(slug)
    if ts_dir is None:
        log.warning("No timestamps found for %s, skipping", slug)
        return None

    zip_path = output_dir / f"{slug}.zip"
    info = build_info_json(slug, version)
    has_timestamps_full = False

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # info.json
        zf.writestr("info.json", json.dumps(info, indent=2, ensure_ascii=False))

        # audio.json
        manifest_path = find_audio_manifest(slug)
        if manifest_path:
            zf.write(manifest_path, "audio.json")
        else:
            log.warning("No audio manifest found for %s", slug)

        # segments.json
        seg_path = ROOT / "data" / "recitation_segments" / slug / "segments.json"
        zf.write(seg_path, "segments.json")

        # timestamps.json
        zf.write(ts_dir / "timestamps.json", "timestamps.json")

        # timestamps_full.json (only if git-tracked)
        ts_full = ts_dir / "timestamps_full.json"
        if ts_full.exists() and is_git_tracked(ts_full):
            zf.write(ts_full, "timestamps_full.json")
            has_timestamps_full = True

    checksum = sha256_file(zip_path)
    size = zip_path.stat().st_size

    log.info(
        "Packaged %s: %.1f MB (timestamps_full: %s)",
        slug, size / 1024 / 1024, has_timestamps_full,
    )

    return {
        "slug": slug,
        "reciter_display": info["reciter_display"],
        "riwayah": info["riwayah"],
        "audio_source": info["audio_source"],
        "coverage": info["coverage"],
        "zip_file": f"{slug}.zip",
        "zip_sha256": checksum,
        "zip_size_bytes": size,
        "has_timestamps_full": has_timestamps_full,
    }


def build_manifest(packaged, version, output_dir):
    """Write manifest.json with checksums and download URLs."""
    for entry in packaged:
        entry["download_url"] = (
            f"https://github.com/{REPO_OWNER}/{REPO_NAME}"
            f"/releases/download/{version}/{entry['zip_file']}"
        )

    manifest = {
        "version": version,
        "created": str(date.today()),
        "repo": f"{REPO_OWNER}/{REPO_NAME}",
        "hf_dataset": _cfg["hf_dataset"],
        "reciters": packaged,
    }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Wrote %s (%d reciters)", manifest_path, len(packaged))
    return manifest


# ---------------------------------------------------------------------------
# Release notes generation
# ---------------------------------------------------------------------------
def generate_release_notes(manifest, output_dir):
    """Write release_notes.md from manifest data."""
    lines = ["## Reciters\n"]
    for r in manifest["reciters"]:
        ts = "words + letters/phonemes" if r["has_timestamps_full"] else "words only"
        lines.append(
            f"- **{r['reciter_display']}** -- "
            f"{r['coverage']['ayahs']:,} ayahs, {r['riwayah']}, timestamps: {ts}"
        )

    lines.append("\n## Zip file structure\n")
    lines.append("Each reciter zip contains:\n")
    lines.append("| File | Description |")
    lines.append("|------|-------------|")
    lines.append("| `info.json` | Reciter metadata (name, riwayah, audio source, coverage, version) |")
    lines.append("| `audio.json` | Audio URLs by surah or ayah |")
    lines.append("| `segments.json` | Verse-level timestamped recitation segments |")
    lines.append("| `timestamps.json` | Word-level timestamps |")
    lines.append("| `timestamps_full.json` | Word + letter + phoneme timestamps (if available) |")

    lines.append("\n## Downloads\n")
    lines.append("| File | Size |")
    lines.append("|------|------|")
    for r in manifest["reciters"]:
        size_mb = r["zip_size_bytes"] / 1024 / 1024
        lines.append(f"| `{r['zip_file']}` | {size_mb:.1f} MB |")
    lines.append("| `surah_info.json` | Reference: surahs with verse and word counts |")
    lines.append("| `qpc_hafs.json` | Reference: Quran word text keyed by surah:ayah:word |")
    lines.append("| `manifest.json` | Index of all reciters with checksums and download URLs |")

    lines.append(
        f"\nHuggingFace dataset: "
        f"[{manifest['hf_dataset']}]"
        f"(https://huggingface.co/datasets/{manifest['hf_dataset']})"
    )

    notes_path = output_dir / "release_notes.md"
    notes_path.write_text("\n".join(lines), encoding="utf-8")
    return notes_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Package release zips for GitHub Releases")
    parser.add_argument("--dry-run", action="store_true", help="Preview version and eligible list")
    parser.add_argument("--version", help="Override auto-computed version (e.g. v0.2.0)")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR, help="Output directory")
    args = parser.parse_args()

    eligible = find_release_eligible()
    log.info("Found %d eligible reciter(s): %s", len(eligible), ", ".join(eligible) or "(none)")

    if not eligible:
        log.info("No eligible reciters. Nothing to release.")
        return

    # Compute checksums for version comparison (hash of segments + timestamps content)
    current_checksums = {}
    for slug in eligible:
        ts_dir = find_timestamps_dir(slug)
        seg_path = ROOT / "data" / "recitation_segments" / slug / "segments.json"
        combined = hashlib.sha256()
        for path in [seg_path, ts_dir / "timestamps.json"]:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    combined.update(chunk)
        ts_full = ts_dir / "timestamps_full.json"
        if ts_full.exists() and is_git_tracked(ts_full):
            with open(ts_full, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    combined.update(chunk)
        current_checksums[slug] = combined.hexdigest()

    # Version computation
    if args.version:
        version = args.version
        log.info("Using override version: %s", version)
    else:
        last_tag = get_last_tag()
        if last_tag:
            log.info("Last tag: %s", last_tag)
            prev_manifest = get_previous_manifest(last_tag)
        else:
            log.info("No previous tags found")
            prev_manifest = None

        version = compute_version(current_checksums, prev_manifest)
        if version is None:
            log.info("No changes since last release. Skipping.")
            return
        log.info("Computed version: %s", version)

    if args.dry_run:
        log.info("Dry run complete. Would release %s with %d reciter(s).", version, len(eligible))
        return

    # Package
    output_dir = args.output_dir
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    packaged = []
    for slug in eligible:
        result = package_reciter(slug, version, output_dir)
        if result:
            packaged.append(result)

    if not packaged:
        log.warning("No reciters were packaged successfully.")
        return

    # Copy shared reference data as top-level assets
    shutil.copy2(ROOT / "data" / "surah_info.json", output_dir / "surah_info.json")
    shutil.copy2(ROOT / "data" / "qpc_hafs.json", output_dir / "qpc_hafs.json")

    manifest = build_manifest(packaged, version, output_dir)
    generate_release_notes(manifest, output_dir)

    log.info("Release %s ready in %s (%d zips + surah_info.json)", version, output_dir, len(packaged))


if __name__ == "__main__":
    main()
