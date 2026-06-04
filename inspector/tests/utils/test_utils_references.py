"""Unit tests for inspector/utils/references.py."""
from utils.references import (
    chapter_from_ref,
    is_by_ayah_source,
    normalize_ref,
    seg_belongs_to_entry,
    seg_sort_key,
)


class TestChapterFromRef:
    def test_surah_only(self):
        assert chapter_from_ref("1") == 1

    def test_verse_level_returns_surah(self):
        # chapter_from_ref returns the FIRST element (surah), not the ayah.
        assert chapter_from_ref("1:7") == 1
        assert chapter_from_ref("37:151") == 37

    def test_cross_verse(self):
        assert chapter_from_ref("37:151:3-37:152:2") == 37


class TestSegBelongsToEntry:
    def test_same_verse(self):
        assert seg_belongs_to_entry("1:1:1-1:1:4", "1:1") is True

    def test_different_verse(self):
        assert seg_belongs_to_entry("1:2:1-1:2:3", "1:1") is False

    def test_surah_level_entry(self):
        # Surah-level entry → match by chapter only.
        assert seg_belongs_to_entry("1:5", "1") is True

    def test_empty_inputs(self):
        assert seg_belongs_to_entry("", "1:1") is False
        assert seg_belongs_to_entry("1:1", "") is False


class TestNormalizeRef:
    def test_canonical_passthrough(self):
        wc = {(1, 7): 3}
        assert normalize_ref("1:7:1-1:7:3", wc) == "1:7:1-1:7:3"

    def test_short_to_canonical(self):
        wc = {(1, 7): 3}
        assert normalize_ref("1:7", wc) == "1:7:1-1:7:3"

    def test_single_word_expand(self):
        wc = {(1, 7): 3}
        assert normalize_ref("1:7:3", wc) == "1:7:3-1:7:3"

    def test_cross_verse_short(self):
        wc = {(1, 7): 3, (1, 8): 4}
        assert normalize_ref("1:7-1:8", wc) == "1:7:1-1:8:4"

    def test_unknown_word_count_falls_back_to_one(self):
        assert normalize_ref("1:99", {}) == "1:99:1-1:99:1"

    def test_empty_returns_empty(self):
        assert normalize_ref("", {}) == ""


class TestSegSortKey:
    def test_regular_ref_sorts_numerically(self):
        keys = ["1:10", "1:2", "1:1"]
        assert sorted(keys, key=seg_sort_key) == ["1:1", "1:2", "1:10"]

    def test_cross_verse_ref_sorts_on_start(self):
        # "37:151:3-37:152:2" starts at (37, 151, 3) so it sits after "37:151"
        # ((37, 151)) but before "37:152" ((37, 152)).
        keys = ["37:152", "37:151:3-37:152:2", "37:151"]
        got = sorted(keys, key=seg_sort_key)
        assert got == ["37:151", "37:151:3-37:152:2", "37:152"]


class TestIsByAyahSource:
    def test_by_ayah_marker_detected(self):
        assert is_by_ayah_source("by_ayah/everyayah") is True

    def test_by_surah_not_detected(self):
        assert is_by_ayah_source("by_surah/mp3quran") is False
