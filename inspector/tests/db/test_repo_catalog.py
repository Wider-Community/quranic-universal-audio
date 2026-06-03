"""repo_catalog: full ReciterCatalog round-trip parity + edit helpers."""

from __future__ import annotations

from datetime import datetime, timezone

from qua_shared.schemas import (
    Channel, Delivery, ReciterCatalog, ReciterEntry, Riwayah, RecordingContext,
    Source, Style, Vocab,
)
from qua_shared.schemas.catalog import Alias, Derived, SourceChannelPair

from services import db
from services.db import repo_catalog


def _catalog() -> ReciterCatalog:
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return ReciterCatalog(
        schema_version=2,
        generated_at=ts,
        vocab=Vocab(
            riwayat=[Riwayah(slug="hafs", short="h", name="Hafs")],
            styles=[Style(slug="murattal", short="mur", name="Murattal")],
            sources=[Source(slug="mp3quran", name="MP3Quran", url="https://mp3quran.net",
                            audio_categories=["by_surah"])],
            channels=[Channel(slug="ch1", short="c1", name="Channel One",
                              host_patterns=["*.mp3quran.net"])],
            recording_contexts=[RecordingContext(slug="studio", name="Studio")],
        ),
        reciters=[ReciterEntry(reciter_id="husary", name_en="Al-Husary",
                               name_ar="الحصري", country="EG", notes="classic")],
        deliveries=[Delivery(
            slug="husary_hafs_murattal", reciter_id="husary", riwayah="hafs",
            style="murattal", recording_context="studio", source="mp3quran",
            channel="ch1", audio_category="by_surah", chapter_count=114,
            added_at=ts, added_by_hf_id="seed",
        )],
        aliases=[Alias(kind="slug", old="husary_old", new="husary_hafs_murattal", ts=ts)],
        derived=Derived(source_channels=[
            SourceChannelPair(source="mp3quran", channel="ch1", delivery_count=1)
        ]),
    )


def _load(cat: ReciterCatalog) -> None:
    with db.transaction():
        repo_catalog.load_vocab(cat.vocab)
        for r in cat.reciters:
            repo_catalog.insert_reciter(r)
        for d in cat.deliveries:
            repo_catalog.insert_delivery(d)
        for a in cat.aliases:
            repo_catalog.insert_alias(a)
        repo_catalog.set_meta(generated_at=cat.generated_at, derived=cat.derived)


def test_full_catalog_roundtrip_parity(fresh_db):
    cat = _catalog()
    _load(cat)
    got = repo_catalog.snapshot()
    assert got.model_dump(mode="json", by_alias=True) == cat.model_dump(
        mode="json", by_alias=True
    )


def test_find_reciter_and_delivery(fresh_db):
    _load(_catalog())
    assert repo_catalog.find_reciter("husary").name_en == "Al-Husary"
    assert repo_catalog.find_reciter("nope") is None
    d = repo_catalog.find_delivery("husary_hafs_murattal")
    assert d is not None and d.riwayah == "hafs"


def test_edit_reciter_and_delivery(fresh_db):
    _load(_catalog())
    with db.transaction():
        r = repo_catalog.edit_reciter("husary", name_en="Mahmoud Al-Husary", notes="updated")
    assert r.name_en == "Mahmoud Al-Husary" and r.notes == "updated"
    with db.transaction():
        d = repo_catalog.edit_delivery("husary_hafs_murattal", recording_year=1960,
                                       variant_label="remastered")
    assert d.recording_year == 1960 and d.variant_label == "remastered"
    # edit persists through a fresh snapshot
    snap = repo_catalog.snapshot()
    assert snap.find_reciter("husary").name_en == "Mahmoud Al-Husary"
