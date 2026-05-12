"""Tests for ``services/search_normalize`` — Arabic-normalizing matcher.

Symmetric with the frontend ``normalizeArabic`` in
``inspector/frontend/src/lib/components/SearchableSelect.svelte``; the
same input string normalizes to the same output in both languages.
"""

from __future__ import annotations


def test_normalize_strips_diacritics():
    from services.search_normalize import normalize_arabic

    # Fatha + kasra + damma + sukun + shaddah all stripped.
    assert normalize_arabic("مَكْتَبَة") == normalize_arabic("مكتبه")


def test_normalize_collapses_alif_variants():
    from services.search_normalize import normalize_arabic

    assert normalize_arabic("أحمد") == normalize_arabic("احمد")
    assert normalize_arabic("إبراهيم") == normalize_arabic("ابراهيم")
    assert normalize_arabic("آدم") == normalize_arabic("ادم")


def test_normalize_taa_marbuta_to_haa():
    from services.search_normalize import normalize_arabic

    assert normalize_arabic("الفاتحة") == normalize_arabic("الفاتحه")


def test_normalize_alif_maqsura_to_yaa():
    from services.search_normalize import normalize_arabic

    assert normalize_arabic("موسى") == normalize_arabic("موسي")


def test_normalize_lowercases_latin():
    from services.search_normalize import normalize_arabic

    assert normalize_arabic("Husary") == normalize_arabic("husary")


def test_matches_empty_needle_is_true():
    from services.search_normalize import matches

    assert matches("anything", "") is True


def test_matches_substring_via_normalization():
    from services.search_normalize import matches

    # Arabic-normalized substring should hit even when the user typed
    # diacritic-free variants.
    assert matches("سُورَةُ الْفَاتِحَة", "فاتحه") is True


def test_matches_latin_substring():
    from services.search_normalize import matches

    assert matches("Mishary Rashid Al-Afasy", "rashid") is True
