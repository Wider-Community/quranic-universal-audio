"""Resolving a delivery's edition — the one answer validation/save/timing share."""

from __future__ import annotations

import pytest

from qua_shared.riwayat import UnsupportedRiwayah
from services.reference.delivery_edition import (
    RiwayahMismatch,
    inspector_riwayah_for,
    sdk_riwayah_for,
)
from services.storage import cache


@pytest.fixture(autouse=True)
def _clean_seg_meta(monkeypatch):
    """Keep the resolver off the bucket, and leave no cache state behind.

    ``sdk_riwayah_for`` reads ``detailed.json``'s ``_meta`` through
    ``data_loader.seg_meta``, which loads the file when nothing has read it yet.
    These cases seed the meta cache directly and never write a file, so without
    this stub every one of them reaches the real bucket — which answers 401 in
    CI, where there is no token.
    """
    from services.storage import data_loader

    monkeypatch.setattr(data_loader, "load_detailed", lambda reciter: [])
    yield
    # Both halves: the meta AND the entries cache, whose presence is what tells
    # `data_loader.seg_meta` the file has already been read.
    cache.set_seg_meta("slug-a", {})
    cache.invalidate_seg_caches("slug-a")


@pytest.fixture
def catalog_riwayah(monkeypatch):
    """Stub the catalog lookup with one delivery of a chosen riwayah."""

    def _set(value: str | None):
        class _Delivery:
            riwayah = value

        from services.state import catalog as catalog_service

        monkeypatch.setattr(
            catalog_service,
            "find_delivery",
            lambda slug: None if value is None else _Delivery(),
        )

    return _set


def test_a_delivery_with_no_catalog_row_is_hafs(catalog_riwayah):
    # A bucket folder or a fixture with no delivery predates multi-riwayah
    # support, so it is Hafs by construction.
    catalog_riwayah(None)
    assert inspector_riwayah_for("slug-a") == "hafs_an_asim"
    assert sdk_riwayah_for("slug-a") == "hafs"


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("hafs_an_asim", "hafs"),
        ("warsh_an_nafi", "warsh"),
        ("qalon_an_nafi", "qalun"),
        ("shubah_an_asim", "shuba"),
        # Fixtures and older rows carry the short form; this is a read of
        # existing state, so both vocabularies resolve.
        ("hafs", "hafs"),
        ("warsh", "warsh"),
    ],
)
def test_both_slug_vocabularies_resolve(catalog_riwayah, stored, expected):
    catalog_riwayah(stored)
    assert sdk_riwayah_for("slug-a") == expected


def test_an_unsupported_riwayah_raises_rather_than_defaulting(catalog_riwayah):
    catalog_riwayah("duri_an_abi_amr")
    with pytest.raises(UnsupportedRiwayah):
        sdk_riwayah_for("slug-a")


def test_the_alignment_on_disk_must_agree_with_the_catalog(catalog_riwayah):
    # A row edited after alignment, or a detailed.json copied between
    # deliveries. Picking either side would render one edition's coordinates
    # under the other's script; the delivery is genuinely broken.
    catalog_riwayah("warsh_an_nafi")
    cache.set_seg_meta("slug-a", {"riwayah": "qalun"})
    with pytest.raises(RiwayahMismatch, match="aligned against"):
        sdk_riwayah_for("slug-a")


def test_agreement_across_the_two_vocabularies_is_not_a_mismatch(catalog_riwayah):
    catalog_riwayah("warsh_an_nafi")
    cache.set_seg_meta("slug-a", {"riwayah": "warsh"})
    assert sdk_riwayah_for("slug-a") == "warsh"


def test_detailed_json_without_a_riwayah_is_not_evidence(catalog_riwayah):
    # Every file written before the field existed. Absence must not be read as
    # disagreement, or every legacy delivery would fail to load.
    catalog_riwayah("hafs_an_asim")
    cache.set_seg_meta("slug-a", {"chapters": 114})
    assert sdk_riwayah_for("slug-a") == "hafs"


def test_relabelling_an_aligned_hafs_delivery_is_a_mismatch(catalog_riwayah, monkeypatch):
    """The direction with teeth, and the one with no other guard.

    ``riwayah`` is an editable catalog column, and promote omits
    ``_meta.riwayah`` for Hafs — so every published delivery today is one column
    edit away from being read in another edition's script and word counts, and
    from having that edition's provenance stamped onto its segments by the next
    save. An aligned document that names no riwayah is not silent: it says Hafs.
    """
    from services.storage import data_loader

    monkeypatch.setattr(data_loader, "load_detailed", lambda reciter: [{"ref": "112"}])
    catalog_riwayah("warsh_an_nafi")
    cache.set_seg_meta("slug-a", {"audio_source": "by_surah"})

    with pytest.raises(RiwayahMismatch, match="declares no riwayah"):
        sdk_riwayah_for("slug-a")


def test_a_non_hafs_delivery_that_has_not_been_aligned_yet_resolves(catalog_riwayah):
    """The window the guard above must not close.

    An admin sets the riwayah at intake, long before any ``detailed.json``
    exists; there is nothing for it to contradict then.
    """
    catalog_riwayah("warsh_an_nafi")
    cache.set_seg_meta("slug-a", {})

    assert sdk_riwayah_for("slug-a") == "warsh"


def test_an_unsupported_riwayah_on_disk_is_a_mismatch(catalog_riwayah):
    catalog_riwayah("hafs_an_asim")
    cache.set_seg_meta("slug-a", {"riwayah": "duri"})
    with pytest.raises(RiwayahMismatch, match="unsupported riwayah"):
        sdk_riwayah_for("slug-a")


def test_a_cold_cache_still_reads_the_alignment_off_disk(catalog_riwayah, monkeypatch):
    # Reading ``cache.get_seg_meta`` directly answers "no meta" before anything
    # has loaded detailed.json, which silently skipped the cross-check on the
    # first request a process served — exactly when it matters.
    from services.storage import data_loader

    loaded: list[str] = []

    def _load_detailed(reciter: str):
        loaded.append(reciter)
        cache.set_seg_meta(reciter, {"riwayah": "qalun"})
        return []

    monkeypatch.setattr(data_loader, "load_detailed", _load_detailed)
    catalog_riwayah("warsh_an_nafi")
    cache.set_seg_meta("slug-a", {})
    cache.invalidate_seg_caches("slug-a")

    with pytest.raises(RiwayahMismatch, match="aligned against"):
        sdk_riwayah_for("slug-a")
    assert loaded == ["slug-a"]
