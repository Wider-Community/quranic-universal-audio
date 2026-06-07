"""Title→surah matching + ``PlaylistChapterMap`` validation guard.

The YouTube/yt-dlp playlist intake maps a playlist's entries to the 114 chapters.
A playlist is **not** guaranteed to be in mushaf order (a reciter may upload
surahs in any sequence), so the chapter assignment MUST be derived from each
entry's *title*, never from its playlist position. The segments-extraction skill
does this review step and emits a :class:`PlaylistChapterMap`.

This module is the safety net for that step. ``validate_chapter_map`` re-derives
the surah from every entry's title and **rejects** a map whose declared
``chapter`` contradicts what the title says, or that isn't a clean bijection over
the chapters it claims to cover. It exists because a positional map
(``chapter = playlist position``) once slipped through stamped ``confidence:
"exact"`` — the title said *Az-Zalzalah* but the entry claimed chapter 94
(*Ash-Sharh*), and nothing caught it until the audio for 9 chapters shipped under
the wrong surah number.

Dependency-light on purpose (stdlib only — ``re`` + ``difflib``) so it can run in
the offline extraction driver, in CI, and inside the Inspector without pulling
``thefuzz``. ``surah_info`` (``{num_str: {name_en, name_ar, ...}}``) is passed in
by the caller; this module hardcodes no paths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

# --- Arabic / English normalisation (kept in lockstep with scripts/playlist_manifest.py) ---

_AR_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟـۖ-ۭ]")
_AR_ALEF_VARIANTS = re.compile(r"[ٱآأإ]")


def strip_arabic_diacritics(text: str) -> str:
    """Remove tashkeel / small marks / tatweel and fold alef variants to plain alef."""
    text = _AR_DIACRITICS.sub("", text)
    return _AR_ALEF_VARIANTS.sub("ا", text)


def normalize_en(name: str) -> str:
    """Normalise an English surah name for comparison (drop article + punctuation)."""
    name = name.lower().strip()
    name = re.sub(r"^(surah?|surat)\s+", "", name)
    name = re.sub(r"^(aal-i|ash|adh|al|an|ar|as|at|ad|az)-?\s*", "", name)
    return re.sub(r"['’\-\s]", "", name)


def normalize_ar(name: str) -> str:
    """Normalise an Arabic surah name for comparison (drop سورة / ال prefixes)."""
    name = strip_arabic_diacritics(name)
    name = re.sub(r"^سورة\s*(ال)?\s*", "", name)
    name = re.sub(r"^ال", "", name)
    return name.strip()


# Common English transliteration aliases (alias → canonical name_en in surah_info).
ENGLISH_ALIASES: dict[str, str] = {
    "fatiha": "Al-Faatiha", "fatihah": "Al-Faatiha", "baqara": "Al-Baqara",
    "baqarah": "Al-Baqara", "imran": "Aal-i-Imraan", "ale imran": "Aal-i-Imraan",
    "aali imran": "Aal-i-Imraan", "nisa": "An-Nisaa", "maidah": "Al-Maaida",
    "maida": "Al-Maaida", "anam": "Al-An'aam", "anaam": "Al-An'aam", "araf": "Al-A'raaf",
    "araaf": "Al-A'raaf", "anfal": "Al-Anfaal", "tawba": "At-Tawba", "tawbah": "At-Tawba",
    "rad": "Ar-Ra'd", "ra'd": "Ar-Ra'd", "hijr": "Al-Hijr", "nahl": "An-Nahl",
    "isra": "Al-Israa", "kahf": "Al-Kahf", "anbiya": "Al-Anbiyaa", "hajj": "Al-Hajj",
    "muminun": "Al-Muminoon", "muminoon": "Al-Muminoon", "nur": "An-Noor", "noor": "An-Noor",
    "furqan": "Al-Furqaan", "shu'ara": "Ash-Shu'araa", "shuara": "Ash-Shu'araa",
    "naml": "An-Naml", "qasas": "Al-Qasas", "ankabut": "Al-Ankaboot", "ankabout": "Al-Ankaboot",
    "rum": "Ar-Room", "room": "Ar-Room", "sajdah": "As-Sajda", "sajda": "As-Sajda",
    "ahzab": "Al-Ahzaab", "fatir": "Faatir", "yaseen": "Yaseen", "yasin": "Yaseen",
    "saffat": "As-Saaffaat", "saad": "Saad", "zumar": "Az-Zumar",
    "ghafir": "Ghafir", "fussilat": "Fussilat", "shuraa": "Ash-Shura", "shura": "Ash-Shura",
    "zukhruf": "Az-Zukhruf", "dukhan": "Ad-Dukhaan", "jathiyah": "Al-Jaathiya",
    "jathiya": "Al-Jaathiya", "ahqaf": "Al-Ahqaf", "fath": "Al-Fath", "hujurat": "Al-Hujuraat",
    "qaf": "Qaaf", "dhariyat": "Adh-Dhaariyat", "tur": "At-Tur", "najm": "An-Najm",
    "qamar": "Al-Qamar", "rahman": "Ar-Rahmaan", "waqiah": "Al-Waaqia", "waqia": "Al-Waaqia",
    "hadid": "Al-Hadid", "mujadila": "Al-Mujaadila", "mujadilah": "Al-Mujaadila",
    "mujadalah": "Al-Mujaadila", "mujadala": "Al-Mujaadila",
    "hashr": "Al-Hashr", "mumtahanah": "Al-Mumtahana", "mumtahana": "Al-Mumtahana",
    "mumtahinah": "Al-Mumtahana", "saff": "As-Saff", "jumuah": "Al-Jumua",
    "jumu'ah": "Al-Jumua", "jumua": "Al-Jumua", "munafiqun": "Al-Munaafiqoon",
    "munafiqoon": "Al-Munaafiqoon", "taghabun": "At-Taghaabun", "talaq": "At-Talaaq",
    "tahrim": "At-Tahrim", "mulk": "Al-Mulk", "qalam": "Al-Qalam", "haqqah": "Al-Haaqqa",
    "haqqa": "Al-Haaqqa", "ma'arij": "Al-Ma'aarij", "maarij": "Al-Ma'aarij", "nuh": "Nooh",
    "nooh": "Nooh", "jinn": "Al-Jinn", "muzzammil": "Al-Muzzammil",
    "muddaththir": "Al-Muddaththir", "muddathir": "Al-Muddaththir", "qiyamah": "Al-Qiyaama",
    "qiyama": "Al-Qiyaama", "insan": "Al-Insaan", "mursalat": "Al-Mursalaat", "naba": "An-Naba",
    "naziat": "An-Naazi'aat", "abasa": "'Abasa", "takwir": "At-Takwir", "infitar": "Al-Infitaar",
    "mutaffifin": "Al-Mutaffifin", "inshiqaq": "Al-Inshiqaaq", "buruj": "Al-Burooj",
    "tariq": "At-Taariq", "a'la": "Al-A'laa", "ala": "Al-A'laa", "ala'": "Al-A'laa",
    "ghasiyah": "Al-Ghaashiya", "ghashiya": "Al-Ghaashiya", "ghashiyah": "Al-Ghaashiya",
    "fajr": "Al-Fajr", "balad": "Al-Balad", "shams": "Ash-Shams", "layl": "Al-Lail",
    "lail": "Al-Lail", "duhaa": "Ad-Dhuhaa", "duha": "Ad-Dhuhaa", "sharh": "Ash-Sharh",
    "inshirah": "Ash-Sharh", "tin": "At-Tin", "alaq": "Al-Alaq", "qadr": "Al-Qadr",
    "bayyinah": "Al-Bayyina", "bayyina": "Al-Bayyina", "zalzalah": "Az-Zalzala",
    "zalzala": "Az-Zalzala", "adiyat": "Al-Aadiyaat", "aadiyat": "Al-Aadiyaat",
    "qariah": "Al-Qaari'a", "qaria": "Al-Qaari'a", "takathur": "At-Takaathur",
    "takaathur": "At-Takaathur", "asr": "Al-Asr", "humazah": "Al-Humaza",
    "humaza": "Al-Humaza", "fil": "Al-Fil", "feel": "Al-Fil", "quraysh": "Quraish",
    "quraish": "Quraish", "ma'un": "Al-Maa'un", "maun": "Al-Maa'un", "kawthar": "Al-Kawthar",
    "kauthar": "Al-Kawthar", "kafirun": "Al-Kaafiroon", "kafiroon": "Al-Kaafiroon",
    "nasr": "An-Nasr", "masad": "Al-Masad", "lahab": "Al-Masad", "ikhlas": "Al-Ikhlaas",
    "falaq": "Al-Falaq", "nas": "An-Naas",
}


@dataclass(frozen=True)
class SurahMatchers:
    en: dict[str, int]
    ar: dict[str, int]
    alias: dict[str, int]
    canonical_en: dict[int, str]


def build_surah_matchers(surah_info: dict) -> SurahMatchers:
    """Build normalised name→number lookups from ``surah_info``."""
    en: dict[str, int] = {}
    ar: dict[str, int] = {}
    canonical: dict[int, str] = {}
    name_to_num: dict[str, int] = {}
    for num_str, info in surah_info.items():
        num = int(num_str)
        en[normalize_en(info["name_en"])] = num
        canonical[num] = info["name_en"]
        name_to_num[info["name_en"]] = num
        if info.get("name_ar"):
            ar[normalize_ar(info["name_ar"])] = num
    alias = {
        normalize_en(a): name_to_num[c] for a, c in ENGLISH_ALIASES.items() if c in name_to_num
    }
    return SurahMatchers(en=en, ar=ar, alias=alias, canonical_en=canonical)


def _surah_name_from_title(title: str) -> str:
    """Pull the surah-name chunk out of a title (handles 'Surah X | ...' and Arabic)."""
    # Prefer an English '| Surah X' suffix if present.
    for seg in reversed(title.split("|")):
        s = seg.strip()
        if re.search(r"sur", s, re.IGNORECASE):
            return re.sub(r"(?:surah?|surat)\s+", "", s, flags=re.IGNORECASE).strip()
    return title.split("|")[0].strip()


def match_title_to_surah(title: str, m: SurahMatchers) -> tuple[int | None, str]:
    """Resolve a playlist entry title to a surah number.

    Returns ``(surah_num, confidence)`` where confidence is one of
    ``"exact"`` (English/alias/Arabic exact hit), ``"high"`` (≥0.9 fuzzy),
    ``"low"`` (0.8–0.9 fuzzy — eyeball it), or ``(None, "none")`` (no match).
    Conservative by design: the guard treats only ``exact``/``high`` as
    authoritative for flagging a contradiction.
    """
    name = _surah_name_from_title(title)
    en_norm = normalize_en(name)
    if en_norm in m.en:
        return m.en[en_norm], "exact"
    if en_norm in m.alias:
        return m.alias[en_norm], "exact"
    # Arabic exact (bounded to the name chunk before كامل / etc.)
    arabic = re.findall(r"[؀-ۿ]+", title)
    if arabic:
        ar_chunk = normalize_ar(" ".join(arabic).split("كامل")[0])
        if ar_chunk in m.ar:
            return m.ar[ar_chunk], "exact"
    # Fuzzy English fallback (stdlib difflib; high thresholds only).
    best_num, best_ratio = None, 0.0
    for ref, num in m.en.items():
        r = SequenceMatcher(None, ref, en_norm).ratio()
        if r > best_ratio:
            best_num, best_ratio = num, r
    if best_ratio >= 0.9:
        return best_num, "high"
    if best_ratio >= 0.8:
        return best_num, "low"
    return None, "none"


@dataclass
class ChapterMapReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_chapter_map(
    cmap: dict, surah_info: dict, *, expect_count: int | None = 114
) -> ChapterMapReport:
    """Validate a ``PlaylistChapterMap`` dict against the entry titles.

    Catches the failure mode that shipped a positional map as ``exact``:

    * **Title contradiction (ERROR):** the entry's title resolves (exact/high
      confidence) to a surah ≠ its declared ``chapter``.
    * **matched_name mismatch (ERROR):** ``matched_name`` is set but doesn't
      equal the canonical name of the declared ``chapter``.
    * **Not a bijection (ERROR):** duplicate ``chapter`` values, out-of-range
      chapters, or — when ``expect_count`` is set — a count that isn't a clean
      1..N cover.
    * **Unresolved title (WARNING):** title couldn't be matched — needs a human
      eyeball, doesn't block.

    Returns a :class:`ChapterMapReport`; ``report.ok`` is True iff no errors.
    """
    m = build_surah_matchers(surah_info)
    r = ChapterMapReport()
    entries = cmap.get("entries") or []
    if not entries:
        r.errors.append("chapter map has no entries")
        return r

    seen: dict[int, int] = {}
    chapters: list[int] = []
    for i, e in enumerate(entries):
        ch = e.get("chapter")
        title = e.get("title") or ""
        if not isinstance(ch, int) or not (1 <= ch <= 114):
            r.errors.append(f"entry[{i}] chapter={ch!r} out of range 1..114")
            continue
        chapters.append(ch)
        if ch in seen:
            r.errors.append(f"chapter {ch} assigned to >1 entry (entries {seen[ch]} and {i})")
        seen[ch] = i

        # matched_name must agree with the chapter it claims.
        mn = (e.get("matched_name") or "").strip()
        if mn and normalize_en(mn) != normalize_en(m.canonical_en.get(ch, "")):
            r.errors.append(
                f"entry[{i}] chapter {ch}: matched_name {mn!r} != canonical "
                f"{m.canonical_en.get(ch)!r}"
            )

        # The critical guard: does the TITLE actually say this surah?
        num, conf = match_title_to_surah(title, m)
        if num is None:
            r.warnings.append(f"entry[{i}] chapter {ch}: title not resolvable {title!r} — eyeball it")
        elif num != ch and conf in ("exact", "high"):
            r.errors.append(
                f"entry[{i}] TITLE CONTRADICTION: title {title!r} matches surah {num} "
                f"({m.canonical_en.get(num)}) but entry claims chapter {ch} "
                f"({m.canonical_en.get(ch)}) [conf={conf}]"
            )
        elif num != ch and conf == "low":
            r.warnings.append(
                f"entry[{i}] chapter {ch}: low-confidence title match to surah {num} — eyeball it"
            )

    if expect_count is not None:
        if len(chapters) != expect_count:
            r.errors.append(f"expected {expect_count} entries, got {len(chapters)}")
        missing = [n for n in range(1, expect_count + 1) if n not in set(chapters)]
        if missing:
            r.errors.append(f"missing chapters (not a full 1..{expect_count} cover): {missing}")
    return r
