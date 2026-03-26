#!/usr/bin/env python3
"""List all available audio reciters, classified by category and source.

Walks data/audio/{by_surah,by_ayah}/<source>/*.json and reports:
- Reciter count per source
- Format (surah-keyed vs ayah-keyed) and entry counts
- Reciters shared across multiple sources

Also scans data/recitation_segments/ and data/timestamps/ to build the
Processed Reciters section.  When run with --write, regenerates the entire
RECITERS.md (both Processed and Available sections) from disk state.

Usage:
    python scripts/list_reciters.py              # summary table
    python scripts/list_reciters.py --detail      # list every reciter
    python scripts/list_reciters.py --json        # machine-readable output
    python scripts/list_reciters.py --write       # regenerate RECITERS.md + README badges
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AUDIO_PATH = REPO / "data" / "audio"
SEGMENTS_PATH = REPO / "data" / "recitation_segments"
TIMESTAMPS_PATH = REPO / "data" / "timestamps"


def discover_reciters() -> dict[str, dict[str, list[dict]]]:
    """Walk data/audio/{by_surah,by_ayah}/<source>/ and build a hierarchical index.

    Reuses the same directory-walking approach as inspector/server.py _load_audio_sources().

    Returns::
        {"by_surah": {"qul": [{"slug": "...", "name": "...", "entries": 114}, ...], ...},
         "by_ayah":  {"everyayah": [...]}}
    """
    result: dict[str, dict[str, list[dict]]] = {}
    if not AUDIO_PATH.exists():
        return result

    for category in ("by_surah", "by_ayah"):
        cat_dir = AUDIO_PATH / category
        if not cat_dir.is_dir():
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
                # Count entries to show coverage
                entries = 0
                try:
                    with open(p, encoding="utf-8") as f:
                        data = json.load(f)
                    entries = len(data)
                except (json.JSONDecodeError, OSError):
                    pass
                reciters.append({"slug": slug, "name": name, "entries": entries})
            if reciters:
                cat_data[source] = reciters
        if cat_data:
            result[category] = cat_data
    return result


def collect_processed_reciters() -> list[dict]:
    """Scan disk to build the Processed reciters list.

    Walks data/recitation_segments/*/ for directories containing segments.json,
    then checks data/timestamps/ for timestamp status.

    Returns list of dicts sorted by name:
        [{"slug", "name", "audio_source", "coverage_str", "ts_level"}, ...]
    """
    processed = []
    if not SEGMENTS_PATH.is_dir():
        return processed

    for seg_dir in sorted(SEGMENTS_PATH.iterdir()):
        if not seg_dir.is_dir():
            continue
        seg_file = seg_dir / "segments.json"
        if not seg_file.exists():
            continue

        slug = seg_dir.name
        name = slug.replace("_", " ").title()

        # Read _meta and count coverage from segments.json
        audio_source = ""
        surahs = set()
        ayah_count = 0
        try:
            with open(seg_file, encoding="utf-8") as f:
                doc = json.load(f)
            audio_source = doc.get("_meta", {}).get("audio_source", "")
            for key in doc:
                if key == "_meta":
                    continue
                ayah_count += 1
                # Keys like "1:1" or cross-verse "37:151:3-37:152:2"
                surahs.add(key.split(":")[0])
        except (json.JSONDecodeError, OSError):
            pass

        surah_count = len(surahs)
        coverage_str = f"{surah_count} surahs, {ayah_count} ayahs"

        # Check timestamp status
        ts_level = "\u2717"
        for audio_type in ("by_ayah_audio", "by_surah_audio"):
            ts_dir = TIMESTAMPS_PATH / audio_type / slug
            if (ts_dir / "timestamps.json").exists():
                if (ts_dir / "timestamps_full.json").exists():
                    ts_level = "\u2713\u2713"
                else:
                    ts_level = "\u2713"
                break

        processed.append({
            "slug": slug,
            "name": name,
            "audio_source": audio_source,
            "coverage_str": coverage_str,
            "ts_level": ts_level,
        })

    return sorted(processed, key=lambda r: r["name"])


def generate_processed_markdown(processed: list[dict]) -> tuple[str, int]:
    """Generate the Processed Reciters markdown section.

    Returns (markdown_text, processed_count).
    """
    lines = [
        "## Processed Reciters",
        "",
        "Reciters that have been through the alignment and timestamp pipelines.",
        "",
        "Timestamps column: `\u2713\u2713` = words + letters/phonemes, `\u2713` = words only.",
        "",
        "",
        "| Reciter | Coverage | Segmented | Manually Validated | Timestamped |",
        "|---------|----------|:---------:|:------------------:|:-----------:|",
    ]

    for r in processed:
        lines.append(
            f"| {r['name']} | {r['coverage_str']} | \u2713 | \u2713 | {r['ts_level']} |"
        )

    return "\n".join(lines), len(processed)


def filter_available(data: dict, processed: list[dict]) -> dict:
    """Remove processed reciters from Available data.

    Matches by (slug, audio_source) so a reciter processed from by_ayah/everyayah
    is excluded from that source but still appears in by_surah/qul under a
    different slug.
    """
    processed_sources = {(r["slug"], r["audio_source"]) for r in processed}

    filtered = {}
    for category, sources in data.items():
        filtered_sources = {}
        for source, reciters in sources.items():
            source_path = f"{category}/{source}"
            kept = [r for r in reciters if (r["slug"], source_path) not in processed_sources]
            if kept:
                filtered_sources[source] = kept
        if filtered_sources:
            filtered[category] = filtered_sources
    return filtered


def find_cross_source(data: dict) -> dict[str, list[str]]:
    """Find reciters that appear in multiple sources (by slug)."""
    slug_sources: dict[str, list[str]] = defaultdict(list)
    for category, sources in data.items():
        for source, reciters in sources.items():
            for r in reciters:
                slug_sources[r["slug"]].append(f"{category}/{source}")
    return {slug: locs for slug, locs in slug_sources.items() if len(locs) > 1}


def print_summary(data: dict) -> None:
    total = 0
    print("Category        Source             Reciters  Format")
    print("-" * 62)
    for category in ("by_surah", "by_ayah"):
        sources = data.get(category, {})
        for source in sorted(sources):
            reciters = sources[source]
            count = len(reciters)
            total += count
            # Infer format from entry count of first reciter
            sample = reciters[0]["entries"] if reciters else 0
            if sample == 114:
                fmt = "surah-keyed (114)"
            elif sample == 6236:
                fmt = "ayah-keyed (6236)"
            else:
                fmt = f"{sample} entries"
            print(f"{category:<15} {source:<18} {count:>5}     {fmt}")
    print("-" * 62)
    print(f"{'Total':<34} {total:>5}")

    cross = find_cross_source(data)
    if cross:
        print(f"\nReciters in multiple sources ({len(cross)}):")
        for slug, locs in sorted(cross.items()):
            name = slug.replace("_", " ").title()
            print(f"  {name:<40} {', '.join(locs)}")


def print_detail(data: dict) -> None:
    for category in ("by_surah", "by_ayah"):
        sources = data.get(category, {})
        for source in sorted(sources):
            reciters = sources[source]
            print(f"\n=== {category}/{source} ({len(reciters)} reciters) ===")
            for r in reciters:
                print(f"  {r['name']:<45} ({r['entries']} entries)")


def print_json(data: dict) -> None:
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    print()


def generate_available_markdown(data: dict) -> tuple[str, int]:
    """Generate the Available Reciters markdown section.

    Returns (markdown_text, total_count).
    """
    lines = [
        "## Available Reciters",
        "",
        "All reciters with audio manifests in `data/audio/`. Not yet processed through the pipeline.",
        "",
        "Within a category (`by_surah` or `by_ayah`), each reciter appears under exactly one source "
        "\u2014 no duplicates across sources. A reciter *can* appear in both `by_surah` and `by_ayah` "
        "(different audio granularity from different providers).",
    ]
    total = 0

    for category, heading in [("by_surah", "By Surah"), ("by_ayah", "By Ayah")]:
        sources = data.get(category, {})
        if not sources:
            continue
        lines.append("")
        lines.append(f"### {heading}")

        for source in sorted(sources):
            reciters = sources[source]
            # Determine source label from directory name
            lines.append("")
            source_labels = {
                "qul": "`qul` (Tarteel CDN)",
                "surah-quran": "`surah-quran` (surah-quran.com)",
                "asswatul-quran": "`asswatul-quran` (asswatul-quran.com)",
                "everyayah": "`everyayah` (everyayah.com)",
            }
            label = source_labels.get(source, f"`{source}`")
            lines.append(f"#### {label}")
            lines.append("")
            lines.append("| # | Reciter |")
            lines.append("|---|---------|")
            for i, r in enumerate(reciters, 1):
                lines.append(f"| {i} | {r['name']} |")
                total += 1

    return "\n".join(lines), total


def write_reciters_md(data: dict) -> int:
    """Regenerate RECITERS.md entirely from disk state.

    Both the Processed and Available sections are rebuilt. Processed reciters
    are excluded from the Available tables.

    Returns total reciter count (available + processed).
    """
    reciters_path = REPO / "data" / "RECITERS.md"

    # Build Processed section from disk
    processed = collect_processed_reciters()
    processed_md, processed_count = generate_processed_markdown(processed)

    # Build Available section, filtering out processed reciters
    filtered = filter_available(data, processed)
    available_md, available_count = generate_available_markdown(filtered)

    # Assemble full file
    header = (
        "# Reciters\n"
        "\n"
        "Full list of available reciters. Generated from `scripts/list_reciters.py`.\n"
        "\n"
    )
    reciters_path.write_text(header + processed_md + "\n\n---\n\n" + available_md + "\n")
    print(f"Updated: {reciters_path}")

    total = available_count + processed_count

    # Update README.md badge
    readme_path = REPO / "README.md"
    readme = readme_path.read_text()
    readme = re.sub(
        r"Reciters-\d+(%20Available%20%7C%20)\d+(%20Aligned)",
        rf"Reciters-{available_count}\g<1>{processed_count}\g<2>",
        readme,
    )
    readme_path.write_text(readme)
    print(f"Updated: {readme_path} (available: {available_count}, processed: {processed_count})")

    return total


def main():
    parser = argparse.ArgumentParser(description="List available audio reciters")
    parser.add_argument("--detail", action="store_true", help="List every reciter")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--write", action="store_true",
                        help="Regenerate RECITERS.md and update README.md counts")
    args = parser.parse_args()

    data = discover_reciters()

    if not data:
        print(f"No audio data found at {AUDIO_PATH}", file=sys.stderr)
        sys.exit(1)

    if args.write:
        write_reciters_md(data)
    elif args.json:
        print_json(data)
    elif args.detail:
        print_summary(data)
        print_detail(data)
    else:
        print_summary(data)


if __name__ == "__main__":
    main()
