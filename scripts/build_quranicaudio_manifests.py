#!/usr/bin/env python3
"""Build by_surah manifests for the quranicaudio source.

Reads ``data/audio/quranicaudio_raw.json`` (produced by ``fetch_quranicaudio.py``)
and emits ``data/audio/by_surah/quranicaudio/<slug>.json`` per reciter, plus a
``slug_map.json`` recording the QA id → repo slug mapping for traceability.

Slug strategy: shared ``scripts.lib.reciter_slug.make_unique_slug``. Canonical
readings (Hafs Murattal, default section) processed first so they take the
bare slug.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.lib.reciter_slug import make_unique_slug  # noqa: E402

RAW_PATH = REPO_ROOT / "data" / "audio" / "quranicaudio_raw.json"
OUT_DIR = REPO_ROOT / "data" / "audio" / "by_surah" / "quranicaudio"
SOURCE_URL = "https://quranicaudio.com/"
CDN = "https://download.quranicaudio.com/quran"

# QA bracket label → riwayah slug
RIWAYAH_BRACKET = {
    "warsh": "warsh_an_nafi",
    "qaloon": "qalon_an_nafi",
    "soosi": "susi_abu_amr",
    "doori": "duri_abu_amr",
    "ad-doori an abi amr": "duri_abu_amr",
    "shu'bah an asim": "shubah_an_asim",
    "khalaf": "khalaf_an_hamzah",
    "abi al-haarith an al-kasaa'ee": "layth_al_kisai",
}

# QA bracket label → style slug
STYLE_BRACKET = {
    "murattal": "murattal",
    "mujawwad": "mujawwad",
    "taraweeh": "taraweeh",
    "with children": "children_repeat",
}

# Normalize spelling variants in QA index labels so the same person yields one base slug.
NAME_NORMALIZE = {
    "Mahmoud Khalil Al-Husary": "Mahmoud Khaleel Al-Husary",
}

IMAM_RE = re.compile(r"Contains\s+\d+\s+Imams?:\s*([^.]+)", re.I)
TARAWEEH_LOC_RE = re.compile(r"(makkah|madinah|nabawi|haram)", re.I)


def classify(brackets: list[str], section: str) -> tuple[str, str, str | None]:
    """Return (style, riwayah_slug, year_label) from brackets + section."""
    style = "murattal"
    riwayah = "hafs_an_asim"
    year_label = None
    for b in brackets:
        bl = b.lower().strip()
        if bl in STYLE_BRACKET:
            style = STYLE_BRACKET[bl]
            continue
        if bl in RIWAYAH_BRACKET:
            riwayah = RIWAYAH_BRACKET[bl]
            continue
        # "Soosi, 2020" → riwayah + year
        parts = [p.strip() for p in bl.split(",")]
        if len(parts) > 1:
            for p in parts:
                if p in RIWAYAH_BRACKET:
                    riwayah = RIWAYAH_BRACKET[p]
                if re.fullmatch(r"\d{4}", p):
                    year_label = p
    if section == "taraweeh":
        style = "taraweeh"
    return style, riwayah, year_label


def parse_imams(desc: str) -> list[str]:
    m = IMAM_RE.search(desc or "")
    if not m:
        return []
    raw = m.group(1).strip()
    raw = re.sub(r"\s+and\s+", ", ", raw)
    return [p.strip() for p in raw.split(",") if p.strip()]


def taraweeh_location(desc: str, name_en: str) -> str | None:
    if "makkah" in name_en.lower() or "haram" in (desc or "").lower():
        return "Masjid al-Haram, Makkah"
    if "madinah" in name_en.lower() or "nabawi" in (desc or "").lower():
        return "Masjid an-Nabawi, Madinah"
    return None


def order_key(rec: dict) -> tuple:
    """Sort so canonical readings get bare slug:
    1. default section, no brackets, no style/riwayah modifier (canonical Hafs Murattal)
    2. default section with brackets
    3. non-hafs section
    4. taraweeh section
    """
    sec = rec["sections"][0]
    sec_rank = {"default": 0, "non_hafs": 1, "taraweeh": 2}[sec]
    has_bracket = 1 if rec.get("brackets") else 0
    return (sec_rank, has_bracket, rec["id"])


def build_manifest(rec: dict, slug: str, style: str, riwayah: str,
                   year_label: str | None) -> dict:
    name_en = rec["name"] or rec["index_label"]
    desc = rec.get("description") or ""
    is_taraweeh_set = re.match(r"(Makkah|Madinah)\s+Taraweeh\s+\d+", name_en)

    meta = {
        "reciter": slug,
        "name_en": name_en,
        "name_ar": "unknown",
        "riwayah": riwayah,
        "style": style,
        "audio_category": "by_surah",
        "source": SOURCE_URL,
        "source_slug": rec["slug"],
        "source_page": rec["page_url"],
        "source_id": rec["id"],
        "source_section": rec["sections"][0],
        "country": "unknown",
        "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if rec.get("year_hijri"):
        meta["year_hijri"] = rec["year_hijri"]
    elif year_label:
        meta["year_hijri"] = int(year_label) if int(year_label) < 1500 else None
    if rec.get("bitrate_kbps"):
        meta["bitrate_kbps"] = rec["bitrate_kbps"]
    if desc:
        meta["source_description"] = desc
    attrs = [a for a in (rec.get("attributions") or []) if "quranicaudio.com" not in a["url"]]
    if attrs:
        meta["source_credits"] = attrs

    if is_taraweeh_set:
        imams = parse_imams(desc)
        if imams:
            meta["imams"] = imams
        loc = taraweeh_location(desc, name_en)
        if loc:
            meta["location"] = loc

    manifest = {"_meta": meta}
    detail = rec.get("probe_detail") or {}
    for n in range(1, 115):
        probe = detail.get(str(n))
        if probe and probe.get("ok"):
            manifest[str(n)] = f"{CDN}/{rec['slug']}/{n:03d}.mp3"
    return manifest


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAW_PATH)
    p.add_argument("--out-dir", type=Path, default=OUT_DIR)
    p.add_argument("--min-coverage", type=int, default=1,
                   help="Skip reciters with fewer than N present surahs (default 1)")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    raw = json.loads(args.raw.read_text())
    reciters = sorted(raw["reciters"], key=order_key)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    slug_map: dict[int, dict] = {}
    written = 0
    skipped: list[tuple[int, str, str]] = []

    for rec in reciters:
        if not rec.get("slug") or not rec.get("coverage"):
            skipped.append((rec["id"], rec["index_label"], "no slug/coverage"))
            continue
        n_present = rec["coverage"]["n_present"]
        if n_present < args.min_coverage:
            skipped.append((rec["id"], rec["index_label"], f"coverage={n_present}"))
            continue

        style, riwayah, year_label = classify(rec.get("brackets", []), rec["sections"][0])
        name_en = rec["name"] or rec["index_label"]
        name_en = NAME_NORMALIZE.get(name_en, name_en)
        # Avoid double "_taraweeh" when the name already contains it (multi-imam sets).
        slug_style = style
        if style == "taraweeh" and "taraweeh" in name_en.lower():
            slug_style = "murattal"  # neutral suffix → bare base preserved
        slug = make_unique_slug(name_en, "", slug_style, riwayah, seen)
        manifest = build_manifest(rec, slug, style, riwayah, year_label)

        slug_map[rec["id"]] = {
            "slug": slug,
            "name_en": name_en,
            "style": style,
            "riwayah": riwayah,
            "section": rec["sections"][0],
            "n_present": n_present,
            "source_slug": rec["slug"],
        }
        if not args.dry_run:
            (args.out_dir / f"{slug}.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2)
            )
        written += 1

    slug_map_path = args.out_dir.parent.parent / "quranicaudio_slug_map.json"
    if not args.dry_run:
        (args.out_dir / "SOURCE").write_text(SOURCE_URL + "\n")
        slug_map_path.write_text(json.dumps(slug_map, indent=2, ensure_ascii=False))

    print(f"manifests written: {written}", file=sys.stderr)
    print(f"skipped: {len(skipped)}", file=sys.stderr)
    for s in skipped:
        print(f"  {s}", file=sys.stderr)


if __name__ == "__main__":
    main()
