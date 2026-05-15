"""Shared reciter slug generation.

Slug = primary reciter identifier across the repo (manifest filename,
``_meta.reciter``, segments dir, timestamps dir, reciters_index entries).

Convention:
1. ``slugify(name_en)`` → lowercase snake_case base.
2. Append ``_<style>`` when style is not ``murattal``.
3. Append ``_<riwayah_short>`` when riwayah is not ``hafs_an_asim``.
4. On short-form collision, fall back to the full riwayah slug.
5. Numeric suffix as last resort.

Process canonical readings (Hafs Murattal) first so they take the bare slug.
"""

from __future__ import annotations

import re

# Reciters whose source-listed English name is missing or incorrect.
AR_TO_EN: dict[str, str] = {
    "عبدالله القرافي": "Abdullah Al-Qarafi",
}


def slugify(name: str) -> str:
    """Convert a display name to snake_case ASCII slug."""
    s = name.lower().strip()
    s = re.sub(r"[''`\-]", " ", s)
    s = re.sub(r"[^a-z0-9\s]", "", s)
    s = re.sub(r"\s+", "_", s).strip("_")
    return s


def make_unique_slug(
    name_en: str,
    name_ar: str,
    style: str,
    riwayah_slug: str,
    seen_slugs: set[str],
) -> str:
    """Generate a unique slug, appending style/riwayah suffixes as needed.

    Mutates ``seen_slugs`` to register the returned slug.
    """
    base = slugify(name_en)
    if not base:
        en = AR_TO_EN.get(name_ar)
        base = slugify(en) if en else f"reciter_{abs(hash(name_ar)) % 100000}"

    if style != "murattal":
        base = f"{base}_{style}"

    if riwayah_slug != "hafs_an_asim":
        short = riwayah_slug.split("_")[0]
        candidate = f"{base}_{short}"
        if candidate in seen_slugs:
            candidate = f"{base}_{riwayah_slug}"
        base = candidate

    slug = base
    counter = 2
    while slug in seen_slugs:
        slug = f"{base}_{counter}"
        counter += 1

    seen_slugs.add(slug)
    return slug
