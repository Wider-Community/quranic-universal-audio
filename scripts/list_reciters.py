#!/usr/bin/env python3
"""List all available audio reciters, grouped by qira'ah and riwayah.

Walks data/audio/{by_surah,by_ayah}/<source>/*.json, reads manifest _meta,
and generates RECITERS.md with:
- Summary tables (riwayah counts, style counts, source counts)
- Processed section grouped by qira'ah > riwayah
- Available section grouped by qira'ah > riwayah

Also scans data/recitation_segments/ and data/timestamps/ to build the
Processed Reciters section.

Usage:
    python scripts/list_reciters.py              # summary table
    python scripts/list_reciters.py --detail      # list every reciter
    python scripts/list_reciters.py --json        # machine-readable output
    python scripts/list_reciters.py --write       # regenerate RECITERS.md + README badges
"""

import argparse
import concurrent.futures
import hashlib
import json
import random
import re
import subprocess
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AUDIO_PATH = REPO / "data" / "audio"
SEGMENTS_PATH = REPO / "data" / "recitation_segments"
TIMESTAMPS_PATH = REPO / "data" / "timestamps"
CACHE_PATH = REPO / "data" / ".audio_durations.json"

MAX_WORKERS = 64
FFPROBE_TIMEOUT = 15
AYAH_SAMPLE_SIZE = 20

# Cache for git-tracked file checks
_git_tracked_cache: set[str] | None = None


def _is_git_tracked(path: Path) -> bool:
    """Check if a file is tracked by git (not just on disk)."""
    global _git_tracked_cache
    if _git_tracked_cache is None:
        try:
            result = subprocess.run(
                ["git", "ls-files", "data/timestamps/"],
                capture_output=True, text=True, cwd=REPO,
            )
            _git_tracked_cache = set(result.stdout.strip().splitlines())
        except OSError:
            _git_tracked_cache = set()
    try:
        rel = str(path.relative_to(REPO))
    except ValueError:
        return False
    return rel in _git_tracked_cache

# Qira'ah hierarchy: canonical reader -> list of riwayah slugs (display order)
QIRAAT_HIERARCHY = [
    ("Asim", ["hafs_an_asim", "shubah_an_asim"]),
    ("Nafi", ["warsh_an_nafi", "qalon_an_nafi"]),
    ("Abu Amr", ["duri_abu_amr", "susi_abu_amr"]),
    ("Ibn Kathir", ["bazzi_ibn_kathir", "qunbul_ibn_kathir"]),
    ("Hamzah", ["khalaf_an_hamzah", "khallad_an_hamzah"]),
    ("Al-Kisa'i", ["duri_al_kisai", "layth_al_kisai"]),
    ("Ibn Amir", ["ibn_dhakwan_ibn_amir", "hisham_ibn_amir"]),
    ("Abu Ja'far", ["isa_abu_jafar", "ibn_jummaz_abu_jafar"]),
    ("Ya'qub", ["ruways_an_yaqub", "rawh_an_yaqub"]),
    ("Khalaf", ["ishaq_an_khalaf", "idris_an_khalaf"]),
]

SOURCE_LABELS = {
    "mp3quran": "MP3Quran",
    "everyayah": "EveryAyah",
    "qul": "QUL",
    "surah-quran": "Surah-Quran",
    "youtube": "YouTube",
}


def load_source_urls() -> dict[str, str]:
    """Load source slug -> URL from sources.json."""
    sources_path = REPO / "data" / "sources.json"
    if not sources_path.exists():
        return {}
    data = json.loads(sources_path.read_text())
    return {s["slug"]: s["url"] for s in data}


def source_link(slug: str, source_urls: dict[str, str]) -> str:
    """Format source as a markdown hyperlink."""
    label = SOURCE_LABELS.get(slug, slug)
    url = source_urls.get(slug)
    if url:
        return f"[{label}]({url})"
    return label


def load_riwayat_names() -> dict[str, str]:
    """Load riwayah slug -> display name from riwayat.json."""
    riwayat_path = REPO / "data" / "riwayat.json"
    if not riwayat_path.exists():
        return {}
    data = json.loads(riwayat_path.read_text())
    return {r["slug"]: r["name"] for r in data}


def _is_full_coverage(audio_cat: str, coverage: int) -> bool:
    """Check if coverage count represents full Qur'an coverage."""
    return (audio_cat == "by_surah" and coverage == 114) or \
           (audio_cat == "by_ayah" and coverage == 6236)


def discover_reciters() -> list[dict]:
    """Walk all audio manifests and return a flat list of reciter records.

    Each record: {slug, name_en, source, style, riwayah, country, audio_cat, coverage, has_timing}
    """
    records = []
    if not AUDIO_PATH.exists():
        return records

    for category in ("by_surah", "by_ayah"):
        cat_dir = AUDIO_PATH / category
        if not cat_dir.is_dir():
            continue
        for source_dir in sorted(cat_dir.iterdir()):
            if not source_dir.is_dir():
                continue
            source = source_dir.name
            for p in sorted(source_dir.glob("*.json")):
                try:
                    with open(p, encoding="utf-8") as f:
                        data = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue

                meta = data.get("_meta", {})
                slug = p.stem
                name_en = meta.get("name_en", slug.replace("_", " ").title())
                riwayah = meta.get("riwayah", "hafs_an_asim")
                style = meta.get("style", "murattal")
                country = meta.get("country", "unknown")
                has_timing = "_timing" in meta

                entries = {k: v for k, v in data.items() if k != "_meta"}
                coverage = len(entries)

                records.append({
                    "slug": slug,
                    "name_en": name_en,
                    "source": source,
                    "style": style,
                    "riwayah": riwayah,
                    "country": country,
                    "audio_cat": category,
                    "coverage": coverage,
                    "has_timing": has_timing,
                })
    return records


def collect_processed_reciters() -> list[dict]:
    """Scan disk to build the Processed reciters list.

    Returns list of dicts sorted by name:
        [{"slug", "name_en", "audio_source", "coverage_str", "segmented",
          "manually_validated", "ts_level"}, ...]
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
                surahs.add(key.split(":")[0])
        except (json.JSONDecodeError, OSError):
            pass

        surah_count = len(surahs)
        coverage_str = f"{surah_count:,}, {ayah_count:,}"

        # Check timestamp status (use git-tracked files, not disk)
        ts_level = "\u2717"
        for audio_type in ("by_ayah_audio", "by_surah_audio"):
            ts_dir = TIMESTAMPS_PATH / audio_type / slug
            ts_file = ts_dir / "timestamps.json"
            ts_full = ts_dir / "timestamps_full.json"
            if _is_git_tracked(ts_file):
                if _is_git_tracked(ts_full):
                    ts_level = "\u2713\u2713"
                else:
                    ts_level = "\u2713"
                break

        processed.append({
            "slug": slug,
            "audio_source": audio_source,
            "coverage_str": coverage_str,
            "surah_count": surah_count,
            "ayah_count": ayah_count,
            "ts_level": ts_level,
        })

    return processed


def enrich_processed(processed: list[dict], all_records: list[dict]) -> list[dict]:
    """Enrich processed reciters with manifest metadata (riwayah, style, etc.)."""
    # Build lookup from slug -> manifest record
    by_slug = {}
    for r in all_records:
        # Prefer the source that matches the processed audio_source
        key = r["slug"]
        audio_source_path = f"{r['audio_cat']}/{r['source']}"
        by_slug.setdefault(key, {})
        by_slug[key][audio_source_path] = r

    enriched = []
    for p in processed:
        slug = p["slug"]
        manifest = None
        if slug in by_slug:
            if p["audio_source"] in by_slug[slug]:
                manifest = by_slug[slug][p["audio_source"]]
            else:
                manifest = next(iter(by_slug[slug].values()))

        enriched.append({
            **p,
            "name_en": manifest["name_en"] if manifest else slug.replace("_", " ").title(),
            "riwayah": manifest["riwayah"] if manifest else "hafs_an_asim",
            "style": manifest["style"] if manifest else "murattal",
            "source": manifest["source"] if manifest else "unknown",
            "audio_cat": manifest["audio_cat"] if manifest else "unknown",
            "has_timing": manifest["has_timing"] if manifest else False,
        })

    return sorted(enriched, key=lambda r: r["name_en"])


def granularity_str(audio_cat: str, has_timing: bool) -> str:
    """Format the granularity column value."""
    if audio_cat == "by_ayah":
        return "Ayah"
    if has_timing:
        return "Surah + Ayah timings"
    return "Surah"


def riwayah_display(slug: str, names: dict[str, str]) -> str:
    """Format riwayah for display: 'Hafs A'n Assem' from riwayat.json."""
    return names.get(slug, slug.replace("_", " ").title())


# ---------------------------------------------------------------------------
# Audio duration probing + caching
# ---------------------------------------------------------------------------

def _ffprobe_duration(url: str) -> float | None:
    """Get duration in seconds from a remote URL via ffprobe."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", url],
            capture_output=True, text=True, timeout=FFPROBE_TIMEOUT,
        )
        return float(r.stdout.strip())
    except Exception:
        return None


def _discover_unique_manifests() -> dict[str, Path]:
    """Find all manifests, preferring by_surah over by_ayah for shared reciters."""
    manifests: dict[str, Path] = {}
    for category in ("by_surah", "by_ayah"):
        cat_dir = AUDIO_PATH / category
        if not cat_dir.is_dir():
            continue
        for source_dir in sorted(cat_dir.iterdir()):
            if not source_dir.is_dir():
                continue
            for f in sorted(source_dir.glob("*.json")):
                slug = f.stem
                if slug not in manifests:
                    manifests[slug] = f
    return manifests


def _get_timestamped_slugs() -> set[str]:
    """Find reciters that have timestamps.json."""
    slugs: set[str] = set()
    for audio_type in ("by_ayah_audio", "by_surah_audio"):
        ts_dir = TIMESTAMPS_PATH / audio_type
        if not ts_dir.exists():
            continue
        for d in ts_dir.iterdir():
            if d.is_dir() and (d / "timestamps.json").exists():
                slugs.add(d.name)
    return slugs


def compute_audio_hours() -> dict[str, float]:
    """Compute per-slug audio duration in seconds, with file-hash caching.

    Returns {slug: duration_s} for all manifests with successful probes.
    Cache is stored at data/.audio_durations.json, keyed by manifest MD5.
    """
    manifests = _discover_unique_manifests()

    # Load existing cache
    cache: dict[str, dict] = {}
    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Determine which manifests need re-probing
    slug_hashes: dict[str, str] = {}
    stale_slugs: list[str] = []
    for slug, path in manifests.items():
        h = hashlib.md5(path.read_bytes()).hexdigest()
        slug_hashes[slug] = h
        if slug in cache and cache[slug].get("hash") == h:
            continue
        stale_slugs.append(slug)

    # Remove deleted slugs from cache
    for slug in list(cache):
        if slug not in manifests:
            del cache[slug]

    if not stale_slugs:
        print(f"Audio durations: all {len(manifests)} cached", file=sys.stderr)
        return {s: cache[s]["duration_s"] for s in cache}

    print(f"Audio durations: {len(stale_slugs)} to probe, "
          f"{len(manifests) - len(stale_slugs)} cached", file=sys.stderr)

    # Collect all URLs to probe in one flat list
    # Each item: (slug, url, is_sampled, total_url_count)
    probe_items: list[tuple[str, str, bool, int]] = []
    for slug in stale_slugs:
        path = manifests[slug]
        with open(path) as f:
            data = json.load(f)
        urls = {k: v for k, v in data.items() if k != "_meta" and isinstance(v, str)}
        url_list = list(urls.values())

        if "by_ayah" in str(path) and len(url_list) > AYAH_SAMPLE_SIZE:
            rng = random.Random(slug)
            sample = rng.sample(url_list, AYAH_SAMPLE_SIZE)
            for u in sample:
                probe_items.append((slug, u, True, len(url_list)))
        else:
            for u in url_list:
                probe_items.append((slug, u, False, len(url_list)))

    print(f"Probing {len(probe_items)} URLs with {MAX_WORKERS} workers...",
          file=sys.stderr)

    # Probe all URLs in parallel
    results: dict[str, list[tuple[float, bool, int]]] = defaultdict(list)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {
            ex.submit(_ffprobe_duration, url): (slug, is_sampled, total_count)
            for slug, url, is_sampled, total_count in probe_items
        }
        done = 0
        for future in concurrent.futures.as_completed(futures):
            slug, is_sampled, total_count = futures[future]
            dur = future.result()
            if dur is not None:
                results[slug].append((dur, is_sampled, total_count))
            done += 1
            if done % 500 == 0:
                print(f"  ...probed {done}/{len(probe_items)}", file=sys.stderr)

    print(f"  ...probed {done}/{len(probe_items)}", file=sys.stderr)

    # Aggregate and update cache
    today = date.today().isoformat()
    for slug in stale_slugs:
        slug_results = results.get(slug, [])
        if not slug_results:
            continue
        if slug_results[0][1]:  # sampled
            total_count = slug_results[0][2]
            avg = sum(d for d, _, _ in slug_results) / len(slug_results)
            duration_s = avg * total_count
        else:
            duration_s = sum(d for d, _, _ in slug_results)

        source = str(manifests[slug].parent.parent.name) + "/" + str(manifests[slug].parent.name)
        cache[slug] = {
            "hash": slug_hashes[slug],
            "duration_s": round(duration_s, 1),
            "source": source,
            "probed_at": today,
        }

    # Save cache
    CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")
    print(f"Cache saved: {CACHE_PATH}", file=sys.stderr)

    return {s: cache[s]["duration_s"] for s in cache}


# ---------------------------------------------------------------------------
# Summary / markdown generation
# ---------------------------------------------------------------------------

def generate_summary_tables(
    all_records: list[dict],
    riwayah_names: dict[str, str],
    slug_hours: dict[str, float],
) -> str:
    """Generate a single 9-column side-by-side summary table: riwayah | style | source."""
    riwayah_counts: dict[str, int] = defaultdict(int)
    riwayah_secs: dict[str, float] = defaultdict(float)
    style_counts: dict[str, int] = defaultdict(int)
    style_secs: dict[str, float] = defaultdict(float)
    source_counts: dict[str, int] = defaultdict(int)
    source_secs: dict[str, float] = defaultdict(float)

    # Deduplicate hours: each slug counted once per dimension using its best manifest
    seen_rw: dict[str, set[str]] = defaultdict(set)
    seen_st: dict[str, set[str]] = defaultdict(set)
    seen_src: dict[str, set[str]] = defaultdict(set)

    for r in all_records:
        slug = r["slug"]
        riwayah_counts[r["riwayah"]] += 1
        style_counts[r["style"]] += 1
        source_counts[r["source"]] += 1

        dur = slug_hours.get(slug, 0)
        if slug not in seen_rw[r["riwayah"]]:
            riwayah_secs[r["riwayah"]] += dur
            seen_rw[r["riwayah"]].add(slug)
        if slug not in seen_st[r["style"]]:
            style_secs[r["style"]] += dur
            seen_st[r["style"]].add(slug)
        if slug not in seen_src[r["source"]]:
            source_secs[r["source"]] += dur
            seen_src[r["source"]].add(slug)

    def _fmt_hours(secs: float) -> str:
        h = secs / 3600
        return f"{h:,.1f}" if h >= 0.05 else ""

    # Build ordered lists for each dimension
    riwayah_rows = []
    seen = set()
    for _qari, riwayat in QIRAAT_HIERARCHY:
        for rw in riwayat:
            if rw in riwayah_counts:
                riwayah_rows.append((
                    riwayah_display(rw, riwayah_names),
                    riwayah_counts[rw],
                    _fmt_hours(riwayah_secs[rw]),
                ))
                seen.add(rw)
    for rw, count in sorted(riwayah_counts.items(), key=lambda x: -x[1]):
        if rw not in seen:
            riwayah_rows.append((
                riwayah_display(rw, riwayah_names),
                count,
                _fmt_hours(riwayah_secs[rw]),
            ))

    style_order = ["murattal", "mujawwad", "muallim", "children_repeat", "taraweeh"]
    style_rows = []
    seen_styles = set()
    for s in style_order:
        if s in style_counts:
            label = s.replace("_", " ").title()
            style_rows.append((label, style_counts[s], _fmt_hours(style_secs[s])))
            seen_styles.add(s)
    for s, count in sorted(style_counts.items(), key=lambda x: -x[1]):
        if s not in seen_styles:
            label = s.replace("_", " ").title()
            style_rows.append((label, count, _fmt_hours(style_secs[s])))

    source_urls = load_source_urls()
    source_rows = []
    for src, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        source_rows.append((
            source_link(src, source_urls),
            count,
            _fmt_hours(source_secs[src]),
        ))

    # Pad to same length
    max_rows = max(len(riwayah_rows), len(style_rows), len(source_rows))
    while len(riwayah_rows) < max_rows:
        riwayah_rows.append(("", "", ""))
    while len(style_rows) < max_rows:
        style_rows.append(("", "", ""))
    while len(source_rows) < max_rows:
        source_rows.append(("", "", ""))

    lines = [
        "## Summary",
        "",
        "| Riwayah | Count | Hours | Style | Count | Hours | Source | Count | Hours |",
        "|---------|:-----:|:-----:|-------|:-----:|:-----:|--------|:-----:|:-----:|",
    ]
    for (rw_name, rw_n, rw_h), (st_name, st_n, st_h), (src_name, src_n, src_h) in zip(
        riwayah_rows, style_rows, source_rows
    ):
        lines.append(
            f"| {rw_name} | {rw_n} | {rw_h} | {st_name} | {st_n} | {st_h} | {src_name} | {src_n} | {src_h} |"
        )

    return "\n".join(lines)


def group_by_riwayah(records: list[dict]) -> dict[str, list[dict]]:
    """Group records by riwayah slug."""
    groups = defaultdict(list)
    for r in records:
        groups[r["riwayah"]].append(r)
    # Sort each group by name
    for rw in groups:
        groups[rw].sort(key=lambda r: r["name_en"])
    return groups


def generate_processed_markdown(
    processed: list[dict],
    riwayah_names: dict[str, str],
    slug_hours: dict[str, float],
) -> tuple[str, int]:
    """Generate the Processed Reciters markdown section grouped by qira'ah > riwayah."""
    lines = [
        "## Aligned Reciters",
        "",
        "Reciters that have been through the alignment and timestamp pipelines.",
        "",
        "Timestamps: `\u2713\u2713` = words + letters/phonemes, `\u2713` = words only.",
        "",
    ]

    if not processed:
        lines.append("*No aligned reciters yet.*")
        return "\n".join(lines), 0

    by_rw = group_by_riwayah(processed)
    count = 0

    for qari, riwayat in QIRAAT_HIERARCHY:
        section_records = []
        for rw in riwayat:
            if rw in by_rw:
                section_records.extend([(rw, r) for r in by_rw[rw]])

        if not section_records:
            continue

        lines.append(f"### {qari}")
        lines.append("")

        current_rw = None
        for rw, r in section_records:
            if rw != current_rw:
                if current_rw is not None:
                    lines.append("")
                lines.append(f"#### {riwayah_display(rw, riwayah_names)}")
                lines.append("")
                lines.append(
                    "| Reciter | Style | Source | Granularity | Coverage | Hours "
                    "| Segmented | Manually Validated | Timestamped |"
                )
                lines.append(
                    "|---------|-------|--------|-------------|:--------:|:-----:"
                    "|:---------:|:------------------:|:-----------:|"
                )
                current_rw = rw

            gran = granularity_str(r["audio_cat"], r["has_timing"])
            src = SOURCE_LABELS.get(r["source"], r["source"])
            hours = slug_hours.get(r["slug"], 0) / 3600
            lines.append(
                f"| {r['name_en']} | {r['style'].title()} | {src} | {gran} | {r['coverage_str']} | {hours:,.1f} "
                f"| \u2713 | \u2713 | {r['ts_level']} |"
            )
            count += 1

        lines.append("")

    return "\n".join(lines), count


def generate_available_markdown(
    records: list[dict],
    processed_slugs: set[str],
    riwayah_names: dict[str, str],
    slug_hours: dict[str, float],
) -> tuple[str, int]:
    """Generate the Available Reciters section grouped by qira'ah > riwayah."""
    # Filter out processed reciters
    available = [r for r in records if r["slug"] not in processed_slugs]

    lines = [
        "## Available Reciters",
        "",
        "All reciters with audio manifests in `data/audio/`. Not yet aligned — "
        "[submit a request](https://huggingface.co/spaces/hetchyy/Quran-reciter-requests) to align.",
    ]

    if not available:
        lines.append("")
        lines.append("*No available reciters.*")
        return "\n".join(lines), 0

    by_rw = group_by_riwayah(available)
    count = 0

    for qari, riwayat in QIRAAT_HIERARCHY:
        section_records = []
        for rw in riwayat:
            if rw in by_rw:
                section_records.extend([(rw, r) for r in by_rw[rw]])

        if not section_records:
            continue

        lines.append("")
        lines.append(f"### {qari}")
        lines.append("")

        current_rw = None
        for rw, r in section_records:
            if rw != current_rw:
                if current_rw is not None:
                    lines.append("")
                lines.append(f"#### {riwayah_display(rw, riwayah_names)}")
                lines.append("")
                lines.append("| # | Reciter | Style | Source | Granularity | Coverage | Hours |")
                lines.append("|---|---------|-------|--------|-------------|:--------:|:-----:|")
                current_rw = rw
                row_num = 0

            row_num += 1
            gran = granularity_str(r["audio_cat"], r["has_timing"])
            src = SOURCE_LABELS.get(r["source"], r["source"])
            cov = f"{r['coverage']}/114" if r["audio_cat"] == "by_surah" else f"{r['coverage']}/6236"
            hours = slug_hours.get(r["slug"], 0) / 3600
            lines.append(
                f"| {row_num} | {r['name_en']} | {r['style'].title()} | {src} | {gran} | {cov} | {hours:,.1f} |"
            )
            count += 1

        lines.append("")

    # Catch any riwayat not in hierarchy
    for rw, recs in sorted(by_rw.items()):
        already = any(rw in riwayat for _, riwayat in QIRAAT_HIERARCHY)
        if already:
            continue
        lines.append("")
        lines.append(f"### Other")
        lines.append("")
        lines.append(f"#### {riwayah_display(rw, riwayah_names)}")
        lines.append("")
        lines.append("| # | Reciter | Style | Source | Granularity | Coverage | Hours |")
        lines.append("|---|---------|-------|--------|-------------|:--------:|:-----:|")
        for i, r in enumerate(recs, 1):
            gran = granularity_str(r["audio_cat"], r["has_timing"])
            src = SOURCE_LABELS.get(r["source"], r["source"])
            cov = f"{r['coverage']}/114" if r["audio_cat"] == "by_surah" else f"{r['coverage']}/6236"
            hours = slug_hours.get(r["slug"], 0) / 3600
            lines.append(
                f"| {i} | {r['name_en']} | {r['style'].title()} | {src} | {gran} | {cov} | {hours:,.1f} |"
            )
            count += 1

    return "\n".join(lines), count


def write_reciters_md(all_records: list[dict]) -> int:
    """Regenerate RECITERS.md entirely from disk state."""
    reciters_path = REPO / "data" / "RECITERS.md"
    riwayah_names = load_riwayat_names()
    source_urls = load_source_urls()

    # Compute audio hours (cached)
    slug_hours = compute_audio_hours()

    # Summary tables
    summary_md = generate_summary_tables(all_records, riwayah_names, slug_hours)

    # Processed section
    processed = collect_processed_reciters()
    enriched = enrich_processed(processed, all_records)
    processed_md, processed_count = generate_processed_markdown(
        enriched, riwayah_names, slug_hours
    )
    processed_slugs = {p["slug"] for p in processed}

    # Available section
    available_md, available_count = generate_available_markdown(
        all_records, processed_slugs, riwayah_names, slug_hours
    )

    # Assemble full file
    header = (
        "# Reciters\n"
        "\n"
        f"**{available_count + processed_count}** reciter entries "
        f"({processed_count} aligned, {available_count} available). "
        "Generated from `scripts/list_reciters.py`.\n"
        "\n"
        "> **Note:** A \"reciter entry\" is a unique combination of reciter \u00d7 riwayah \u00d7 style \u00d7 granularity, "
        "not a unique person. For example, Mahmoud Khalil Al-Hussary appears as 5 entries: "
        "Hafs Murattal Ayah, Hafs Murattal Surah, Hafs Mujawwad Surah, Hafs Muallim Ayah, "
        "and Warsh Murattal Surah.\n"
        ">\n"
        "> Within a given source, each reciter appears only once per riwayah/style combination. "
        "Across sources, there are no duplicates \u2014 a reciter's riwayah/style pair is served by exactly one source. "
        "The same reciter *can* appear multiple times under different Surah/Ayah granularities.\n"
        "\n"
    )
    reciters_path.write_text(
        header + summary_md + "\n\n---\n\n" + processed_md + "\n\n---\n\n" + available_md + "\n"
    )
    print(f"Updated: {reciters_path}")

    # Write machine-readable index for the HF request form
    index_path = REPO / "data" / "reciters_index.json"
    index_path.write_text(json.dumps(all_records, indent=2, ensure_ascii=False) + "\n")
    print(f"Updated: {index_path}")

    total = available_count + processed_count

    # Compute badge counts (inclusive: all reciters for Audio Only, subset for Timestamped)
    all_full = sum(
        1 for r in all_records
        if _is_full_coverage(r["audio_cat"], r["coverage"])
    )
    all_partial = total - all_full
    total_hours = round(sum(slug_hours.values()) / 3600)

    ts_slugs = _get_timestamped_slugs()
    ts_full = sum(
        1 for p in processed
        if p["surah_count"] == 114 or p["ayah_count"] == 6236
    )
    ts_partial = processed_count - ts_full
    ts_hours = round(sum(slug_hours.get(s, 0) for s in ts_slugs) / 3600)

    riwayat_with_data = len({r["riwayah"] for r in all_records})
    riwayat_total = len(json.loads((REPO / "data" / "riwayat.json").read_text()))

    # Update README.md badges
    readme_path = REPO / "README.md"
    if readme_path.exists():
        readme = readme_path.read_text()

        # Audio Only badge: "X Full · Y Partial · Z,ZZZh"
        audio_val = f"{all_full}%20Full%20%C2%B7%20{all_partial}%20Partial%20%C2%B7%20{total_hours:,}h"
        readme = re.sub(r"Audio%20Only-[^-]+-d4842a", f"Audio%20Only-{audio_val}-d4842a", readme)

        # Timestamped badge: "X Full · Y Partial · Zh"
        ts_val = f"{ts_full}%20Full%20%C2%B7%20{ts_partial}%20Partial%20%C2%B7%20{ts_hours:,}h"
        readme = re.sub(r"Timestamped-[^-]+-d4842a", f"Timestamped-{ts_val}-d4842a", readme)

        # Riwayat badge
        readme = re.sub(
            r"Riwayat-\d+(%20%2F%20)\d+",
            rf"Riwayat-{riwayat_with_data}\g<1>{riwayat_total}",
            readme,
        )

        # Update prose counts
        reciters_rounded = (total // 50) * 50
        readme = re.sub(
            r"featuring \d+\+ reciters",
            f"featuring {reciters_rounded}+ reciters",
            readme,
        )
        readme = re.sub(
            r"\d+\+ reciters and \d+\+ riwayat",
            f"{reciters_rounded}+ reciters and {riwayat_with_data} riwayat",
            readme,
        )
        readme = re.sub(
            r"across \d+ riwayat",
            f"across {riwayat_with_data} riwayat",
            readme,
        )
        readme_path.write_text(readme)
        print(f"Updated: {readme_path} "
              f"(audio: {all_full} full / {all_partial} partial / {total_hours:,}h, "
              f"timestamped: {ts_full} full / {ts_partial} partial / {ts_hours:,}h, "
              f"riwayat: {riwayat_with_data}/{riwayat_total})")

    return total


def print_summary(data: list[dict]) -> None:
    riwayah_counts = defaultdict(int)
    style_counts = defaultdict(int)
    source_counts = defaultdict(int)

    for r in data:
        riwayah_counts[r["riwayah"]] += 1
        style_counts[r["style"]] += 1
        source_counts[r["source"]] += 1

    print(f"\nTotal: {len(data)} reciter entries\n")
    print("Riwayah                        Count")
    print("-" * 42)
    for rw, count in sorted(riwayah_counts.items(), key=lambda x: -x[1]):
        print(f"  {rw:<28} {count:>5}")
    print()
    print("Style                          Count")
    print("-" * 42)
    for s, count in sorted(style_counts.items(), key=lambda x: -x[1]):
        print(f"  {s:<28} {count:>5}")
    print()
    print("Source                         Count")
    print("-" * 42)
    for src, count in sorted(source_counts.items(), key=lambda x: -x[1]):
        print(f"  {src:<28} {count:>5}")


def print_detail(data: list[dict]) -> None:
    by_rw = group_by_riwayah(data)
    for rw in sorted(by_rw, key=lambda x: -len(by_rw[x])):
        recs = by_rw[rw]
        print(f"\n=== {rw} ({len(recs)} reciters) ===")
        for r in recs:
            print(f"  {r['name_en']:<40} {r['style']:<12} {r['source']:<14} {r['audio_cat']}")


def print_json(data: list[dict]) -> None:
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    print()


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
