#!/usr/bin/env python3
"""Generate an audio manifest from a YouTube playlist or a list of URLs.

Extracts video URLs and matches titles to surahs via fuzzy name matching
with fallback to surah numbers found in titles.

Usage:
    python3 scripts/youtube_manifest.py <playlist_url>
    python3 scripts/youtube_manifest.py <playlist_url> --non-interactive
    python3 scripts/youtube_manifest.py --from-file urls.txt
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path


def _check_dependencies():
    """Check for required dependencies and prompt to install if missing."""
    missing = []
    if not shutil.which("yt-dlp"):
        missing.append(("yt-dlp", "pip install yt-dlp"))
    try:
        import thefuzz  # noqa: F401
    except ImportError:
        missing.append(("thefuzz", "pip install thefuzz"))

    if not missing:
        return
    print("Missing dependencies:", file=sys.stderr)
    for name, cmd in missing:
        print(f"  - {name}  ({cmd})", file=sys.stderr)
    answer = input("\nInstall now? [Y/n] ").strip().lower()
    if answer in ("", "y", "yes"):
        pip_args = [pkg for _, pkg in missing]
        # flatten "pip install X" → ["X"]
        packages = [cmd.split()[-1] for _, cmd in missing]
        subprocess.check_call([sys.executable, "-m", "pip", "install", *packages])
        print()
    else:
        sys.exit(1)


_check_dependencies()

from thefuzz import fuzz  # noqa: E402

SURAH_INFO_PATH = Path(__file__).resolve().parent.parent / "data" / "surah_info.json"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data" / "audio" / "by_surah" / "youtube"

# Common English transliteration aliases not covered by fuzzy matching alone.
# Maps alias → canonical name_en from surah_info.json.
ENGLISH_ALIASES = {
    "fatiha": "Al-Faatiha",
    "fatihah": "Al-Faatiha",
    "baqara": "Al-Baqara",
    "baqarah": "Al-Baqara",
    "imran": "Aal-i-Imraan",
    "ale imran": "Aal-i-Imraan",
    "nisa": "An-Nisaa",
    "maidah": "Al-Maaida",
    "maida": "Al-Maaida",
    "anam": "Al-An'aam",
    "anaam": "Al-An'aam",
    "araf": "Al-A'raaf",
    "anfal": "Al-Anfaal",
    "tawba": "At-Tawba",
    "tawbah": "At-Tawba",
    "hud": "Hud",
    "yusuf": "Yusuf",
    "rad": "Ar-Ra'd",
    "ra'd": "Ar-Ra'd",
    "hijr": "Al-Hijr",
    "nahl": "An-Nahl",
    "isra": "Al-Israa",
    "kahf": "Al-Kahf",
    "maryam": "Maryam",
    "taha": "Taa-Haa",
    "anbiya": "Al-Anbiyaa",
    "hajj": "Al-Hajj",
    "muminun": "Al-Muminoon",
    "muminoon": "Al-Muminoon",
    "nur": "An-Noor",
    "noor": "An-Noor",
    "furqan": "Al-Furqaan",
    "shu'ara": "Ash-Shu'araa",
    "shuara": "Ash-Shu'araa",
    "naml": "An-Naml",
    "qasas": "Al-Qasas",
    "ankabut": "Al-Ankaboot",
    "ankabout": "Al-Ankaboot",
    "rum": "Ar-Room",
    "room": "Ar-Room",
    "luqman": "Luqman",
    "sajdah": "As-Sajda",
    "sajda": "As-Sajda",
    "ahzab": "Al-Ahzaab",
    "saba": "Saba",
    "fatir": "Faatir",
    "yaseen": "Yaseen",
    "yasin": "Yaseen",
    "saffat": "As-Saaffaat",
    "saad": "Saad",
    "zumar": "Az-Zumar",
    "ghafir": "Ghafir",
    "fussilat": "Fussilat",
    "shuraa": "Ash-Shura",
    "shura": "Ash-Shura",
    "zukhruf": "Az-Zukhruf",
    "dukhan": "Ad-Dukhaan",
    "jathiyah": "Al-Jaathiya",
    "jathiya": "Al-Jaathiya",
    "ahqaf": "Al-Ahqaf",
    "muhammad": "Muhammad",
    "fath": "Al-Fath",
    "hujurat": "Al-Hujuraat",
    "qaf": "Qaaf",
    "dhariyat": "Adh-Dhaariyat",
    "tur": "At-Tur",
    "najm": "An-Najm",
    "qamar": "Al-Qamar",
    "rahman": "Ar-Rahmaan",
    "waqiah": "Al-Waaqia",
    "waqia": "Al-Waaqia",
    "hadid": "Al-Hadid",
    "mujadila": "Al-Mujaadila",
    "mujadilah": "Al-Mujaadila",
    "hashr": "Al-Hashr",
    "mumtahanah": "Al-Mumtahana",
    "mumtahana": "Al-Mumtahana",
    "saff": "As-Saff",
    "jumuah": "Al-Jumua",
    "jumu'ah": "Al-Jumua",
    "jumua": "Al-Jumua",
    "munafiqun": "Al-Munaafiqoon",
    "munafiqoon": "Al-Munaafiqoon",
    "taghabun": "At-Taghaabun",
    "talaq": "At-Talaaq",
    "tahrim": "At-Tahrim",
    "mulk": "Al-Mulk",
    "qalam": "Al-Qalam",
    "haqqah": "Al-Haaqqa",
    "haqqa": "Al-Haaqqa",
    "ma'arij": "Al-Ma'aarij",
    "maarij": "Al-Ma'aarij",
    "nuh": "Nooh",
    "nooh": "Nooh",
    "jinn": "Al-Jinn",
    "muzzammil": "Al-Muzzammil",
    "muddaththir": "Al-Muddaththir",
    "qiyamah": "Al-Qiyaama",
    "qiyama": "Al-Qiyaama",
    "insan": "Al-Insaan",
    "mursalat": "Al-Mursalaat",
    "naba": "An-Naba",
    "naziat": "An-Naazi'aat",
    "abasa": "'Abasa",
    "takwir": "At-Takwir",
    "infitar": "Al-Infitaar",
    "mutaffifin": "Al-Mutaffifin",
    "inshiqaq": "Al-Inshiqaaq",
    "buruj": "Al-Burooj",
    "tariq": "At-Taariq",
    "a'la": "Al-A'laa",
    "ala": "Al-A'laa",
    "ghasiyah": "Al-Ghaashiya",
    "ghashiya": "Al-Ghaashiya",
    "fajr": "Al-Fajr",
    "balad": "Al-Balad",
    "shams": "Ash-Shams",
    "layl": "Al-Lail",
    "lail": "Al-Lail",
    "duhaa": "Ad-Dhuhaa",
    "duha": "Ad-Dhuhaa",
    "sharh": "Ash-Sharh",
    "tin": "At-Tin",
    "alaq": "Al-Alaq",
    "qadr": "Al-Qadr",
    "bayyinah": "Al-Bayyina",
    "bayyina": "Al-Bayyina",
    "zalzalah": "Az-Zalzala",
    "zalzala": "Az-Zalzala",
    "adiyat": "Al-Aadiyaat",
    "qariah": "Al-Qaari'a",
    "qaria": "Al-Qaari'a",
    "takathur": "At-Takaathur",
    "asr": "Al-Asr",
    "humazah": "Al-Humaza",
    "humaza": "Al-Humaza",
    "fil": "Al-Fil",
    "quraysh": "Quraish",
    "quraish": "Quraish",
    "ma'un": "Al-Maa'un",
    "maun": "Al-Maa'un",
    "kawthar": "Al-Kawthar",
    "kauthar": "Al-Kawthar",
    "kafirun": "Al-Kaafiroon",
    "kafiroon": "Al-Kaafiroon",
    "nasr": "An-Nasr",
    "masad": "Al-Masad",
    "lahab": "Al-Masad",
    "ikhlas": "Al-Ikhlaas",
    "falaq": "Al-Falaq",
    "nas": "An-Naas",
}


def load_surah_info() -> dict:
    """Load surah_info.json and return as dict."""
    with open(SURAH_INFO_PATH) as f:
        return json.load(f)


def strip_arabic_diacritics(text: str) -> str:
    """Remove Arabic tashkeel, diacritics, small marks, and tatweel."""
    # U+0610-061A: signs above/below (e.g. alef above)
    # U+064B-065F: core tashkeel (fathatan through hamza below)
    # U+0670: superscript alef
    # U+0640: tatweel
    # U+06D6-06ED: small marks (e.g. small high dotless head of khaa)
    text = re.sub(r"[\u0610-\u061A\u064B-\u065F\u0670\u0640\u06D6-\u06ED]", "", text)
    # Normalize alef variants (wasla, madda, hamza) to plain alef
    text = re.sub(r"[\u0671\u0622\u0623\u0625]", "\u0627", text)
    return text


def normalize_en(name: str) -> str:
    """Normalize an English surah name for comparison."""
    name = name.lower().strip()
    # Strip common prefixes
    name = re.sub(r"^(surah?|surat)\s+", "", name)
    name = re.sub(r"^(al|an|ar|as|at|ad|ash|adh|az|aal-i)-?", "", name)
    # Remove punctuation
    name = re.sub(r"['\-\s]", "", name)
    return name


def normalize_ar(name: str) -> str:
    """Normalize an Arabic surah name for comparison."""
    name = strip_arabic_diacritics(name)
    # Strip سورة prefix (with or without ال)
    name = re.sub(r"^سورة\s*(ال)?\s*", "", name)
    # Strip standalone ال prefix
    name = re.sub(r"^ال", "", name)
    return name.strip()


def build_matchers(surah_info: dict) -> tuple:
    """Build lookup structures for surah matching.

    Returns (en_map, ar_map, alias_map, name_to_num).
    """
    en_map = {}  # normalized english name → surah number
    ar_map = {}  # normalized arabic name → surah number
    name_to_num = {}  # canonical name_en → surah number

    for num_str, info in surah_info.items():
        num = int(num_str)
        name_en = info["name_en"]
        name_ar = info.get("name_ar", "")

        en_map[normalize_en(name_en)] = num
        name_to_num[name_en] = num
        if name_ar:
            ar_map[normalize_ar(name_ar)] = num

    # Alias map: normalized alias → surah number
    alias_map = {}
    for alias, canonical in ENGLISH_ALIASES.items():
        if canonical in name_to_num:
            alias_map[normalize_en(alias)] = name_to_num[canonical]

    return en_map, ar_map, alias_map, name_to_num


def extract_surah_name(title: str) -> tuple:
    """Extract surah name and number from a video title.

    Returns (name_part, number_part) where either may be None.
    """
    # Try pattern: SURAH <NAME> (<NUMBER>)
    m = re.search(r"(?:surah?|surat)\s+([^|()\d]+?)(?:\s*[\(|\|]|\s+\d)", title, re.IGNORECASE)
    name = m.group(1).strip() if m else None

    # If no name found, try first segment before | or (
    if not name:
        first_seg = re.split(r"[|(]", title)[0].strip()
        first_seg = re.sub(r"(?:surah?|surat)\s+", "", first_seg, flags=re.IGNORECASE).strip()
        if first_seg and not first_seg.isdigit():
            name = first_seg

    # Extract number in parentheses or standalone
    num_match = re.search(r"\((\d{1,3})\)", title)
    if not num_match:
        num_match = re.search(r"\b(\d{1,3})\b", title)
    number = int(num_match.group(1)) if num_match else None

    return name, number


def match_title(title: str, en_map: dict, ar_map: dict, alias_map: dict) -> tuple:
    """Match a video title to a surah number.

    Returns (surah_number, method) or (None, None).
    method is one of: 'exact', 'alias', 'fuzzy_en', 'fuzzy_ar', 'number'.
    """
    name, number = extract_surah_name(title)

    if name:
        norm = normalize_en(name)

        # 1. Exact match against canonical names
        if norm in en_map:
            return en_map[norm], "exact"

        # 2. Alias match
        if norm in alias_map:
            return alias_map[norm], "alias"

        # 3. Fuzzy match against English names
        best_score, best_num = 0, None
        for ref_norm, num in en_map.items():
            score = fuzz.ratio(norm, ref_norm)
            if score > best_score:
                best_score, best_num = score, num
        if best_score >= 70:
            return best_num, "fuzzy_en"

        # 4. Check Arabic content in title
        arabic_chars = re.findall(r"[\u0600-\u06FF]+", title)
        if arabic_chars:
            title_ar = normalize_ar(" ".join(arabic_chars))
            best_score, best_num = 0, None
            for ref_norm, num in ar_map.items():
                score = fuzz.ratio(title_ar, ref_norm)
                if score > best_score:
                    best_score, best_num = score, num
            if best_score >= 70:
                return best_num, "fuzzy_ar"

    # 5. Fallback: surah number
    if number and 1 <= number <= 114:
        return number, "number"

    return None, None


def parse_url_file(path: str) -> dict:
    """Parse a text file of `<surah_number> <youtube_url>` lines.

    Returns dict of surah_num (int) → url (str).
    """
    filepath = Path(path)
    if not filepath.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    matched = {}
    errors = []

    for lineno, raw in enumerate(filepath.read_text().splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split(None, 1)
        if len(parts) != 2:
            errors.append(f"  Line {lineno}: expected '<number> <url>', got: {line}")
            continue

        num_str, url = parts

        try:
            num = int(num_str)
        except ValueError:
            errors.append(f"  Line {lineno}: '{num_str}' is not a valid surah number")
            continue

        if not (1 <= num <= 114):
            errors.append(f"  Line {lineno}: surah number {num} out of range (1-114)")
            continue

        if "youtube.com/" not in url and "youtu.be/" not in url:
            errors.append(f"  Line {lineno}: not a YouTube URL: {url}")
            continue

        if num in matched:
            errors.append(f"  Line {lineno}: duplicate surah {num} (already mapped)")
            continue

        matched[num] = url

    if errors:
        print(f"Parse errors in {path}:", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        if not matched:
            sys.exit(1)
        print(f"\n  Parsed {len(matched)} valid entries, {len(errors)} error(s)\n")
    else:
        print(f"Parsed {len(matched)} entries from {filepath.name}")

    return matched


def fetch_playlist(url: str) -> tuple:
    """Fetch playlist metadata and entries via yt-dlp.

    Returns (playlist_info, entries) where playlist_info is a dict with
    title/channel/description and entries is a list of {title, url, id, duration}.
    """
    print("Fetching playlist...")
    result = subprocess.run(
        ["yt-dlp", "--flat-playlist", "--dump-single-json", url],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        print(f"yt-dlp error: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(result.stdout)

    playlist_info = {
        "title": data.get("title"),
        "channel": data.get("channel") or data.get("uploader"),
        "description": data.get("description"),
        "video_count": data.get("playlist_count", 0),
        "views": data.get("view_count"),
        "last_updated": data.get("modified_date"),
    }

    entries = []
    for item in data.get("entries", []):
        entries.append({
            "title": item.get("title", ""),
            "url": f"https://www.youtube.com/watch?v={item['id']}",
            "id": item["id"],
            "duration": item.get("duration"),
        })

    # Display playlist info
    print(f"\n  Playlist:  {playlist_info['title']}")
    print(f"  Channel:   {playlist_info['channel']}")
    if playlist_info["description"]:
        print(f"  About:     {playlist_info['description'][:100]}")
    if playlist_info["last_updated"]:
        d = playlist_info["last_updated"]
        print(f"  Updated:   {d[:4]}-{d[4:6]}-{d[6:]}")
    if playlist_info["views"]:
        print(f"  Views:     {playlist_info['views']:,}")
    print(f"  Videos:    {len(entries)}")

    return playlist_info, entries


def prompt_metadata(playlist_url: str) -> dict:
    """Interactive CLI to collect reciter metadata."""
    print("\n--- Reciter Metadata ---")
    print("Press Enter to accept [default]\n")

    reciter = input("  Reciter slug (snake_case, required): ").strip()
    while not reciter:
        print("  Reciter slug is required.")
        reciter = input("  Reciter slug (snake_case, required): ").strip()

    name_en = input("  English name (required): ").strip()
    while not name_en:
        print("  English name is required.")
        name_en = input("  English name (required): ").strip()

    name_ar = input("  Arabic name [unknown]: ").strip() or "unknown"
    riwayah = input("  Riwayah [hafs_an_asim]: ").strip() or "hafs_an_asim"

    print("  Style options: murattal, mujawwad, muallim, children_repeat, taraweeh")
    style = input("  Style [murattal]: ").strip() or "murattal"

    country = input("  Country [unknown]: ").strip() or "unknown"

    return {
        "reciter": reciter,
        "name_en": name_en,
        "name_ar": name_ar,
        "riwayah": riwayah,
        "style": style,
        "audio_category": "by_surah",
        "source": playlist_url,
        "country": country,
        "fetched": date.today().isoformat(),
    }


def main():
    parser = argparse.ArgumentParser(description="Generate audio manifest from YouTube playlist or URL list")
    parser.add_argument("playlist_url", nargs="?", help="YouTube playlist URL")
    parser.add_argument("--from-file", metavar="PATH",
                        help="Text file with '<surah_number> <youtube_url>' per line")
    parser.add_argument("--non-interactive", action="store_true",
                        help="Skip metadata prompts (requires --reciter and --name-en)")
    parser.add_argument("--reciter", help="Reciter slug (non-interactive mode)")
    parser.add_argument("--name-en", help="English display name (non-interactive mode)")
    parser.add_argument("--name-ar", default="unknown")
    parser.add_argument("--riwayah", default="hafs_an_asim")
    parser.add_argument("--style", default="murattal")
    parser.add_argument("--country", default="unknown")
    args = parser.parse_args()

    if not args.playlist_url and not args.from_file:
        parser.error("provide a playlist URL or --from-file")
    if args.playlist_url and args.from_file:
        parser.error("use either a playlist URL or --from-file, not both")

    # Load surah reference data
    surah_info = load_surah_info()

    if args.from_file:
        # ── From-file mode: explicit surah→URL mappings ──
        url_map = parse_url_file(args.from_file)

        matched = {num: {"url": url} for num, url in url_map.items()}
        source_for_meta = "youtube"
    else:
        # ── Playlist mode: fuzzy title matching ──
        en_map, ar_map, alias_map, name_to_num = build_matchers(surah_info)

        playlist_info, entries = fetch_playlist(args.playlist_url)
        if not entries:
            print("No videos found in playlist.", file=sys.stderr)
            sys.exit(1)

        matched = {}
        failed = []
        duplicates = []

        for entry in entries:
            num, method = match_title(entry["title"], en_map, ar_map, alias_map)
            if num is None:
                failed.append(entry)
                continue
            if num in matched:
                duplicates.append((num, entry["title"], matched[num]["title"]))
                continue
            matched[num] = {**entry, "method": method}

        print(f"\nMatched {len(matched)} of 114 surahs ({len(entries)} videos in playlist)")

        if failed:
            print(f"\nCould not match {len(failed)} video(s):")
            for entry in failed:
                print(f"  - {entry['title']}")

        if duplicates:
            print(f"\nDuplicate matches ({len(duplicates)}):")
            for num, title, existing in duplicates:
                print(f"  - Surah {num}: \"{title}\" conflicts with \"{existing}\"")

        if failed:
            print(f"\n{len(failed)} title(s) could not be matched. Fix the playlist or add aliases.")

        source_for_meta = args.playlist_url

    # Report coverage
    missing = [n for n in range(1, 115) if n not in matched]
    if missing:
        print(f"\nMissing surahs ({len(missing)}):")
        for n in missing:
            print(f"  - {n}. {surah_info[str(n)]['name_en']}")

    if not missing:
        print("\n  All 114 surahs covered!")

    # Collect metadata
    if args.non_interactive:
        if not args.reciter or not args.name_en:
            print("--reciter and --name-en are required in non-interactive mode", file=sys.stderr)
            sys.exit(1)
        meta = {
            "reciter": args.reciter,
            "name_en": args.name_en,
            "name_ar": args.name_ar,
            "riwayah": args.riwayah,
            "style": args.style,
            "audio_category": "by_surah",
            "source": source_for_meta,
            "country": args.country,
            "fetched": date.today().isoformat(),
        }
    else:
        meta = prompt_metadata(source_for_meta)

    # Build manifest
    manifest = {"_meta": meta}
    for num in sorted(matched.keys()):
        manifest[str(num)] = matched[num]["url"]

    # Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{meta['reciter']}.json"
    with open(out_path, "w") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"\nManifest written to: {out_path}")
    print(f"Coverage: {len(matched)}/114 surahs")
    print(f"\nPlease review the manifest and confirm it looks correct.")

    # Offer to delete input file
    if args.from_file and not args.non_interactive:
        answer = input(f"\nDelete {args.from_file}? [y/N] ").strip().lower()
        if answer in ("y", "yes"):
            Path(args.from_file).unlink()
            print(f"Deleted {args.from_file}")


if __name__ == "__main__":
    main()
