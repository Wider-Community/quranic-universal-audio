#!/usr/bin/env python3
"""List all available audio reciters, classified by category and source.

Walks data/audio/{by_surah,by_ayah}/<source>/*.json and reports:
- Reciter count per source
- Format (surah-keyed vs ayah-keyed) and entry counts
- Reciters shared across multiple sources

Usage:
    python scripts/list_reciters.py              # summary table
    python scripts/list_reciters.py --detail      # list every reciter
    python scripts/list_reciters.py --json        # machine-readable output
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AUDIO_PATH = REPO / "data" / "audio"


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


def main():
    parser = argparse.ArgumentParser(description="List available audio reciters")
    parser.add_argument("--detail", action="store_true", help="List every reciter")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    data = discover_reciters()

    if not data:
        print(f"No audio data found at {AUDIO_PATH}", file=sys.stderr)
        sys.exit(1)

    if args.json:
        print_json(data)
    elif args.detail:
        print_summary(data)
        print_detail(data)
    else:
        print_summary(data)


if __name__ == "__main__":
    main()
