#!/usr/bin/env python3
"""Fetch mp3quran.net reciter data and generate audio JSON manifests.

Creates by_surah/mp3quran/<slug>.json files with the standard _meta schema.
For reciters with verse timing, fetches and embeds timing data per surah.

Usage:
    python3 scripts/fetch_mp3quran.py                # all 100+ surah reciters
    python3 scripts/fetch_mp3quran.py --with-timing   # also fetch verse timing
    python3 scripts/fetch_mp3quran.py --min-surahs 114  # only full 114
    python3 scripts/fetch_mp3quran.py --dry-run       # preview without writing
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "audio" / "by_surah" / "mp3quran"
RIWAYAT_PATH = REPO_ROOT / "data" / "riwayat.json"

API_BASE = "https://mp3quran.net/api/v3"
SOURCE_URL = "https://mp3quran.net/"


# ── Riwayah / style mapping ─────────────────────────────────────────────

def load_riwayah_map():
    """Load type->riwayah_slug mapping from riwayat.json."""
    with open(RIWAYAT_PATH) as f:
        riwayat = json.load(f)
    mapping = {}
    for r in riwayat:
        for t in r["mp3quran_type"]:
            mapping[t] = r["slug"]
    return mapping


STYLE_MAP = {1: "murattal", 2: "mujawwad", 3: "muallim", 4: "murattal"}


def get_style(moshaf_type):
    if moshaf_type == 222:
        return "mujawwad"
    if moshaf_type == 213:
        return "muallim"
    return STYLE_MAP.get(moshaf_type % 10, "unknown")


# ── Slug generation ──────────────────────────────────────────────────────

# Reciters whose mp3quran English name is Arabic-only or incorrect
AR_TO_EN = {
    "عبدالله القرافي": "Abdullah Al-Qarafi",
}


def slugify(name):
    """Convert English name to snake_case slug."""
    s = name.lower().strip()
    s = re.sub(r"[''`\-]", " ", s)
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s


def make_unique_slug(name_en, name_ar, style, riwayah_slug, seen_slugs):
    """Generate a unique slug, appending style/riwayah suffixes as needed.

    When the short riwayah name (first word, e.g. "duri") would collide with
    an existing slug, falls back to the full riwayah slug before resorting to
    numeric suffixes.  E.g.: base_duri → base_duri_abu_amr.
    """
    base = slugify(name_en)
    if not base:
        en = AR_TO_EN.get(name_ar)
        base = slugify(en) if en else f"reciter_{abs(hash(name_ar)) % 100000}"

    # Append style suffix for non-murattal
    if style != "murattal":
        base = f"{base}_{style}"

    # Append riwayah suffix for non-hafs
    if riwayah_slug != "hafs_an_asim":
        short_riwayah = riwayah_slug.split("_")[0]  # e.g., "warsh", "duri", "ibn"
        candidate = f"{base}_{short_riwayah}"
        if candidate in seen_slugs:
            # Short name collides (e.g. duri_abu_amr vs duri_al_kisai) — use full
            candidate = f"{base}_{riwayah_slug}"
        base = candidate

    # Deduplicate (last resort numeric suffix)
    slug = base
    counter = 2
    while slug in seen_slugs:
        slug = f"{base}_{counter}"
        counter += 1

    seen_slugs.add(slug)
    return slug


# ── API fetching ─────────────────────────────────────────────────────────

def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "quranic-universal-audio/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_reciters():
    """Fetch English and Arabic reciter lists."""
    print("Fetching reciters (en)...", end=" ", flush=True)
    en = fetch_json(f"{API_BASE}/reciters?language=eng")
    print(f"{len(en['reciters'])} reciters")

    print("Fetching reciters (ar)...", end=" ", flush=True)
    ar = fetch_json(f"{API_BASE}/reciters?language=ar")
    print(f"{len(ar['reciters'])} reciters")

    ar_names = {r["id"]: r["name"] for r in ar["reciters"]}
    return en["reciters"], ar_names


def fetch_timing_reads():
    """Fetch list of reciters that have verse timing."""
    print("Fetching timing reads...", end=" ", flush=True)
    data = fetch_json(f"{API_BASE}/ayat_timing/reads")
    ids = {r["id"] for r in data}
    print(f"{len(ids)} reciters with timing")
    return ids


def fetch_surah_timing(reciter_id, surah_num):
    """Fetch verse timing for one surah of one reciter."""
    data = fetch_json(f"{API_BASE}/ayat_timing?surah={surah_num}&read={reciter_id}")
    # Return as [[start_ms, end_ms], ...] — ayah 0 first if present
    return [[e["start_time"], e["end_time"]] for e in data]


def fetch_all_timing(reciter_id, surah_list):
    """Fetch verse timing for all surahs of a reciter, with rate limiting."""
    timing = {}
    for surah_num in surah_list:
        try:
            timing[surah_num] = fetch_surah_timing(reciter_id, surah_num)
        except Exception as e:
            print(f"    WARNING: timing fetch failed for surah {surah_num}: {e}")
        time.sleep(0.1)  # rate limit
    return timing


# ── Manifest generation ──────────────────────────────────────────────────

def build_manifest(reciter, moshaf, ar_name, riwayah_slug, style, slug, timing=None):
    """Build the audio JSON manifest dict."""
    surah_list = sorted(int(s) for s in moshaf["surah_list"].split(",") if s.strip())
    server = moshaf["server"]

    name_en = AR_TO_EN.get(reciter["name"], reciter["name"])

    meta = {
        "reciter": slug,
        "name_en": name_en,
        "name_ar": ar_name,
        "riwayah": riwayah_slug,
        "style": style,
        "audio_category": "by_surah",
        "source": SOURCE_URL,
        "country": "unknown",
    }

    if timing:
        meta["_timing"] = {
            "source": "mp3quran_api",
            "type": "verse",
            "data": {str(k): v for k, v in timing.items()},
        }

    manifest = {"_meta": meta}

    for surah_num in surah_list:
        padded = str(surah_num).zfill(3)
        manifest[str(surah_num)] = f"{server}{padded}.mp3"

    return manifest


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fetch mp3quran.net reciters")
    parser.add_argument("--min-surahs", type=int, default=100,
                        help="Minimum surah count to include (default: 100)")
    parser.add_argument("--with-timing", action="store_true",
                        help="Also fetch verse timing for reciters that have it")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing files")
    args = parser.parse_args()

    riwayah_map = load_riwayah_map()
    reciters, ar_names = fetch_reciters()
    timing_ids = fetch_timing_reads()

    seen_slugs = set()
    manifests = []

    for reciter in reciters:
        ar_name = ar_names.get(reciter["id"], "unknown")

        for moshaf in reciter["moshaf"]:
            if moshaf["surah_total"] < args.min_surahs:
                continue

            mt = moshaf["moshaf_type"]
            riwayah_slug = riwayah_map.get(mt, "unknown")
            style = get_style(mt)
            slug = make_unique_slug(reciter["name"], ar_name, style, riwayah_slug, seen_slugs)
            has_timing = reciter["id"] in timing_ids

            manifests.append({
                "reciter": reciter,
                "moshaf": moshaf,
                "ar_name": ar_name,
                "riwayah_slug": riwayah_slug,
                "style": style,
                "slug": slug,
                "has_timing": has_timing,
            })

    print(f"\n{len(manifests)} moshaf entries with {args.min_surahs}+ surahs")
    timing_count = sum(1 for m in manifests if m["has_timing"])
    print(f"{timing_count} have verse timing available")

    if args.dry_run:
        print("\n--- DRY RUN ---")
        for m in manifests:
            timing_tag = " [timing]" if m["has_timing"] else ""
            print(f"  {m['slug']}.json — {m['reciter']['name']} — "
                  f"{m['moshaf']['surah_total']} surahs — "
                  f"{m['style']} — {m['riwayah_slug']}{timing_tag}")
        return

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    wrote = 0
    timing_fetched = 0

    for i, m in enumerate(manifests, 1):
        timing = None
        if args.with_timing and m["has_timing"]:
            surah_list = sorted(
                int(s) for s in m["moshaf"]["surah_list"].split(",") if s.strip()
            )
            print(f"  [{i}/{len(manifests)}] {m['slug']} — fetching timing "
                  f"({len(surah_list)} surahs)...", flush=True)
            timing = fetch_all_timing(m["reciter"]["id"], surah_list)
            timing_fetched += 1
        else:
            print(f"  [{i}/{len(manifests)}] {m['slug']}", flush=True)

        manifest = build_manifest(
            m["reciter"], m["moshaf"], m["ar_name"],
            m["riwayah_slug"], m["style"], m["slug"], timing,
        )

        out_path = OUT_DIR / f"{m['slug']}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False)
        wrote += 1

    print(f"\nDone: wrote {wrote} manifests to {OUT_DIR}")
    if args.with_timing:
        print(f"Fetched timing for {timing_fetched} reciters")


if __name__ == "__main__":
    main()
