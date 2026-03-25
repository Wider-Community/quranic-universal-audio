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
        "— no duplicates across sources. A reciter *can* appear in both `by_surah` and `by_ayah` "
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
    """Regenerate the Available section of RECITERS.md, preserving Processed section.

    Returns total reciter count (available + processed).
    """
    reciters_path = REPO / "data" / "RECITERS.md"
    md = reciters_path.read_text()

    # Split at "## Available Reciters" — preserve everything before it
    marker = "## Available Reciters"
    idx = md.find(marker)
    if idx == -1:
        print(f"ERROR: Could not find '{marker}' in RECITERS.md", file=sys.stderr)
        sys.exit(1)

    header = md[:idx]
    available_md, available_count = generate_available_markdown(data)

    reciters_path.write_text(header + available_md + "\n")
    print(f"Updated: {reciters_path}")

    # Count processed reciters from the header section
    processed_count = sum(
        1 for line in header.split("\n")
        if line.startswith("|") and "| Reciter" not in line and "|---" not in line and line.strip()
    )
    total = available_count + processed_count

    # Update README.md
    readme_path = REPO / "README.md"
    readme = readme_path.read_text()
    import re
    # Update badge
    readme = re.sub(r"Reciters-\d+-green", f"Reciters-{total}-green", readme)
    # Update paragraph count
    readme = re.sub(r"\d+ reciters available", f"{total} reciters available", readme)
    readme_path.write_text(readme)
    print(f"Updated: {readme_path} (total: {total}, processed: {processed_count})")

    return total


def main():
    parser = argparse.ArgumentParser(description="List available audio reciters")
    parser.add_argument("--detail", action="store_true", help="List every reciter")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--write", action="store_true",
                        help="Regenerate RECITERS.md Available section and update README.md counts")
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
