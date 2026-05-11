#!/usr/bin/env python3
"""Build by_surah manifests for the tvquran source.

Reads ``docs/reciters-research/tvquran/tvquran_raw.json`` (from
``fetch_tvquran.py``) and emits ``data/audio/by_surah/tvquran/<slug>.json``
per moshaf panel, plus ``data/audio/tvquran_slug_map.json`` for traceability.

Filtering: translation panels (``ترجمة …``) are skipped — they're recited
translations, not the Arabic Quran. No coverage minimum: partial mushafs
are emitted as-is and only the present surahs appear in the manifest.
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

RAW_PATH = REPO_ROOT / "docs" / "reciters-research" / "tvquran" / "tvquran_raw.json"
OUT_DIR = REPO_ROOT / "data" / "audio" / "by_surah" / "tvquran"
SLUG_MAP_PATH = REPO_ROOT / "data" / "audio" / "tvquran_slug_map.json"
SOURCE_URL = "https://www.tvquran.com/"

# Map tvquran AR riwayah labels → riwayat.json slugs. Combined readings
# (Bazzi + Qunbul, Ruways + Rawh) collapse to the first reading as canonical
# slug since we don't model "joint" transmissions.
RIWAYAH_AR_MAP = {
    "حفص عن عاصم": "hafs_an_asim",
    "ورش عن نافع": "warsh_an_nafi",
    "قالون عن نافع": "qalon_an_nafi",
    "الدوري عن أبي عمرو": "duri_abu_amr",
    "السوسي عن أبي عمرو": "susi_abu_amr",
    "الدوري عن الكسائي": "duri_al_kisai",
    "الليث عن الكسائي": "layth_al_kisai",
    "خلف عن حمزة": "khalaf_an_hamzah",
    "خلاد عن حمزة": "khallad_an_hamzah",
    "شعبة عن عاصم": "shubah_an_asim",
    "هشام عن ابن عامر": "hisham_ibn_amir",
    "ابن ذكوان عن ابن عامر": "ibn_dhakwan_ibn_amir",
    "البزي عن ابن كثير": "bazzi_ibn_kathir",
    "قنبل عن ابن كثير": "qunbul_ibn_kathir",
    "البزي وقنبل عن ابن كثير": "bazzi_ibn_kathir",
    "رويس و روح عن يعقوب": "ruways_an_yaqub",
    "رويس عن يعقوب": "ruways_an_yaqub",
    "روح عن يعقوب": "rawh_an_yaqub",
    "إسحاق عن خلف": "ishaq_an_khalaf",
    "إدريس عن خلف": "idris_an_khalaf",
    "عيسى ابن وردان عن أبي جعفر": "isa_abu_jafar",
    "ابن جماز عن أبي جعفر": "ibn_jummaz_abu_jafar",
}

# AR labels that describe a *style* (not a riwayah). Riwayah defaults to Hafs.
STYLE_AR_MAP = {
    "المصحف المجود": "mujawwad",
    "المصحف المعلم": "muallim",
    "طريقة الحدر": "murattal",  # "hadr method" — fast murattal; no dedicated slug
}

# Translation panels are recited Quran translations, not Arabic Quran — skip.
TRANSLATION_PREFIX = "ترجمة"


def classify(riwayah_ar: str) -> tuple[str, str, bool]:
    """Return (style, riwayah_slug, is_translation)."""
    label = (riwayah_ar or "").strip()
    if label.startswith(TRANSLATION_PREFIX):
        return ("murattal", "hafs_an_asim", True)
    if label in STYLE_AR_MAP:
        return (STYLE_AR_MAP[label], "hafs_an_asim", False)
    riw = RIWAYAH_AR_MAP.get(label, "hafs_an_asim")
    return ("murattal", riw, False)


def order_key(scholar: dict, panel: dict) -> tuple:
    """Canonical readings sorted first so they take the bare slug."""
    style, riw, _ = classify(panel.get("riwayah_ar", ""))
    style_rank = {"murattal": 0, "muallim": 1, "mujawwad": 2}.get(style, 3)
    riw_rank = 0 if riw == "hafs_an_asim" else 1
    return (style_rank, riw_rank, scholar["id"], panel["panel_index"])


def build_manifest(scholar: dict, panel: dict, slug: str,
                   style: str, riwayah: str) -> dict:
    base = panel["cdn_base"]
    name_en = panel.get("name_en") or scholar.get("name_en") or ""
    name_ar = panel.get("name_ar") or scholar.get("name_ar") or "unknown"
    meta = {
        "reciter": slug,
        "name_en": name_en,
        "name_ar": name_ar or "unknown",
        "riwayah": riwayah,
        "style": style,
        "audio_category": "by_surah",
        "source": SOURCE_URL,
        "source_id": scholar["id"],
        "source_page_en": scholar.get("page_en"),
        "source_page_ar": scholar.get("page_ar"),
        "source_panel_index": panel["panel_index"],
        "source_cdn_base": base,
        "source_riwayah_label_ar": panel.get("riwayah_ar"),
        "source_riwayah_label_en": panel.get("riwayah_en"),
        "country": "unknown",
        "fetched": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    manifest = {"_meta": meta}
    cov = panel.get("coverage") or {}
    for n in cov.get("present", []):
        manifest[str(n)] = f"https://{base}/{int(n):03d}.mp3"
    return manifest


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--raw", type=Path, default=RAW_PATH)
    p.add_argument("--out-dir", type=Path, default=OUT_DIR)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    raw = json.loads(args.raw.read_text())
    rows: list[tuple[dict, dict]] = []
    for s in raw["scholars"]:
        for panel in s.get("panels", []):
            if not panel.get("cdn_base"):
                continue
            rows.append((s, panel))
    rows.sort(key=lambda x: order_key(*x))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    slug_map: dict[str, dict] = {}
    written = 0
    skipped: list[tuple[int, int, str, str]] = []

    for scholar, panel in rows:
        style, riw, is_translation = classify(panel.get("riwayah_ar", ""))
        if is_translation:
            skipped.append((scholar["id"], panel["panel_index"],
                            panel.get("riwayah_ar", ""), "translation"))
            continue

        name_en = panel.get("name_en") or scholar.get("name_en") or ""
        name_ar = panel.get("name_ar") or scholar.get("name_ar") or ""
        if not name_en and not name_ar:
            skipped.append((scholar["id"], panel["panel_index"], "", "empty-name"))
            continue

        slug = make_unique_slug(name_en, name_ar, style, riw, seen)
        manifest = build_manifest(scholar, panel, slug, style, riw)
        cov = panel.get("coverage") or {}
        slug_map[f"{scholar['id']}:{panel['panel_index']}"] = {
            "slug": slug,
            "scholar_id": scholar["id"],
            "panel_index": panel["panel_index"],
            "name_en": name_en,
            "name_ar": name_ar,
            "style": style,
            "riwayah": riw,
            "kind": panel.get("kind"),
            "cdn_base": panel.get("cdn_base"),
            "n_present": cov.get("n_present", 0),
        }
        if not args.dry_run:
            (args.out_dir / f"{slug}.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2)
            )
        written += 1

    if not args.dry_run:
        (args.out_dir / "SOURCE").write_text(SOURCE_URL + "\n")
        SLUG_MAP_PATH.write_text(json.dumps(slug_map, indent=2, ensure_ascii=False))

    print(f"manifests written: {written}", file=sys.stderr)
    print(f"skipped: {len(skipped)}", file=sys.stderr)
    for sid, pidx, label, reason in skipped:
        print(f"  scholar={sid} panel={pidx} reason={reason} riwayah_ar={label!r}", file=sys.stderr)


if __name__ == "__main__":
    main()
