"""``services.quran_refs.build_payload`` + ``payload_hash`` unit tests."""

from __future__ import annotations

import orjson


def test_build_payload_strips_verse_markers(monkeypatch):
    from services import data_loader, quran_refs

    quran_refs.reset_cache()
    data_loader.cache.set_dk_words_flat_cache(None)
    monkeypatch.setattr(
        data_loader,
        "load_dk",
        lambda: {
            "1:1:1": {"text": "بِسْمِ"},
            "1:1:5": {"text": "۝١"},
            "7:1:1": {"text": "المص"},
        },
    )
    monkeypatch.setattr(
        quran_refs,
        "get_word_counts",
        lambda: {
            (1, 1): 4,
            (7, 1): 1,
        },
    )

    body = orjson.loads(quran_refs.build_payload())
    assert "1:1:1" in body["dk_words"]
    assert "7:1:1" in body["dk_words"]
    assert "1:1:5" not in body["dk_words"], "verse-end markers must be stripped"
    assert body["verse_word_counts"] == {"1:1": 4, "7:1": 1}


def test_payload_hash_is_deterministic(monkeypatch):
    from services import data_loader, quran_refs

    quran_refs.reset_cache()
    data_loader.cache.set_dk_words_flat_cache(None)
    monkeypatch.setattr(data_loader, "load_dk", lambda: {"1:1:1": {"text": "X"}})
    monkeypatch.setattr(quran_refs, "get_word_counts", lambda: {(1, 1): 1})

    h1 = quran_refs.payload_hash()
    h2 = quran_refs.payload_hash()
    assert h1 == h2
    assert len(h1) == 12
