"""``scripts/devenv/make_synthetic_delivery.py`` — the non-Hafs fixture builder.

The fixture is what every multi-riwayah surface is verified against, so a
fixture that quietly carried Hafs text or Hafs coordinates would make the whole
verification meaningless. These tests pin the two facts that could go wrong
silently: the coordinates are the edition's own, and the shard survives the
real producer audit.
"""

from __future__ import annotations

import pytest

import make_synthetic_delivery as msd

editions = pytest.importorskip("qua_domain", reason="qua-domain not installed")

CHAPTER = 112


@pytest.fixture
def qalun():
    words = msd._edition_words("qalun", CHAPTER)
    verses = msd._verses(words)
    return words, verses, msd._spans(len(verses), 20_000, 120)


def test_segments_carry_the_editions_own_refs_and_their_hafs_source(qalun):
    _, verses, spans = qalun
    doc = msd._detailed("s", "qalun", CHAPTER, verses, spans)

    assert doc["_meta"]["riwayah"] == "qalon_an_nafi"
    segments = doc["entries"][0]["segments"]
    assert len(segments) == len(verses)
    assert segments[0]["matched_ref"] == "112:1:1-112:1:4"
    # Recognition runs against Hafs, so the Hafs evidence rides along.
    assert segments[0]["source_ref"]
    assert segments[0]["projection_support"] in ("full", "partial")


def test_verse_spans_are_ordered_and_inside_the_audio(qalun):
    _, verses, spans = qalun
    doc = msd._detailed("s", "qalun", CHAPTER, verses, spans)
    segments = doc["entries"][0]["segments"]

    assert all(seg["time_start"] < seg["time_end"] for seg in segments)
    assert all(
        left["time_end"] < right["time_start"]
        for left, right in zip(segments, segments[1:], strict=False)
    )
    assert segments[-1]["time_end"] <= 20_000


def test_the_word_shard_passes_the_real_producer_audit(qalun):
    from qua_shared.timestamps_shards import validated_brotli_shard

    words, verses, spans = qalun
    shard = msd._word_shard("qalun", CHAPTER, verses, spans)

    # Goes through the writer's own audit, so a fixture the producer would
    # reject fails here rather than in the browser.
    assert validated_brotli_shard(shard)
    reading = shard["readings"][0]
    assert len(reading["words"]) == len(words)
    assert len(reading["boundaries"]) == len(reading["words"])
    assert [part[0] for part in reading["parts"]] == [f"112:{a}" for a, _ in verses]


def test_the_shard_text_is_the_edition_index_text(qalun):
    words, verses, spans = qalun
    shard = msd._word_shard("qalun", CHAPTER, verses, spans)

    assert [row[1] for row in shard["readings"][0]["words"]] == [w.text for w in words]
    assert shard["_meta"]["words_sha256"] == editions.get_edition("qalun").words_sha256
    assert shard["_meta"]["reference_riwayah"] == "hafs"


def test_every_word_ends_a_verse_exactly_once(qalun):
    _, verses, spans = qalun
    shard = msd._word_shard("qalun", CHAPTER, verses, spans)

    ends = [row[1] for row in shard["readings"][0]["boundaries"] if row[1] is not None]
    assert ends == [ayah for ayah, _ in verses]


def test_too_many_verses_for_the_audio_fails_loudly():
    # A silently overlapping fixture would look fine and time nothing.
    with pytest.raises(SystemExit, match="raise --duration-ms"):
        msd._spans(286, 20_000, 120)
