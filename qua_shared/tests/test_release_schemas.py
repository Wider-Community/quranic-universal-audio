"""Release asset schema smoke tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from qua_shared.schemas import (
    LetterTimestampsDoc,
    QpcHafsDoc,
    ReleaseCatalog,
    ReleaseCatalogAudio,
    ReleaseCoverage,
    ReleaseRecitationCatalog,
    VerseTimestampsDoc,
    WordTimestampsDoc,
)


def _meta(tier: str, layout: str) -> dict:
    return {
        "schema_version": 1,
        "slug": "example_reciter",
        "audio_category": "by_surah",
        "verse_count": 1,
        "tier": tier,
        "layout": layout,
    }


def test_timestamp_tier_shapes_validate():
    VerseTimestampsDoc.model_validate({"_meta": _meta("verse", "[start,end]"), "100:1": [0, 2831]})
    WordTimestampsDoc.model_validate(
        {
            "_meta": _meta("word", "[[start,end], words]"),
            "100:1": [[0, 2831], [[1, 70, 1550], [2, 1550, 2790]]],
        }
    )
    LetterTimestampsDoc.model_validate(
        {
            "_meta": _meta("letter", "[[start,end], words, letters]"),
            "100:1": [
                [0, 2831],
                [[1, 70, 1550]],
                [[1, "x", 70, 240], [1, "y", 240, 420]],
            ],
        }
    )


def test_timestamp_tier_rejects_bad_verse_key():
    with pytest.raises(ValidationError):
        VerseTimestampsDoc.model_validate(
            {"_meta": _meta("verse", "[start,end]"), "surah:ayah": [0, 1]}
        )


def test_release_catalog_requires_audio_url_map():
    catalog = ReleaseCatalog(
        recitations=[
            ReleaseRecitationCatalog(
                slug="example_reciter",
                audio=ReleaseCatalogAudio(
                    chapter_urls={"100": "https://cdn.example/100.mp3"},
                    sample_rate_hz=44100,
                    channels=2,
                ),
                coverage=ReleaseCoverage(surahs=1, ayahs=3),
            )
        ]
    )
    assert catalog.recitations[0].audio.chapter_urls["100"].endswith("100.mp3")


def test_qpc_hafs_doc_validates_location_keys():
    doc = QpcHafsDoc.model_validate(
        {
            "1:1:1": {
                "id": 1,
                "surah": "1",
                "ayah": "1",
                "word": "1",
                "location": "1:1:1",
                "text": "bismi",
            }
        }
    )
    assert doc.root["1:1:1"].location == "1:1:1"

    with pytest.raises(ValidationError):
        QpcHafsDoc.model_validate(
            {
                "1:1:1": {
                    "surah": "1",
                    "ayah": "1",
                    "word": "1",
                    "location": "1:1:2",
                    "text": "bismi",
                }
            }
        )
