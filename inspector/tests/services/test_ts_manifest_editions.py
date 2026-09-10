"""The manifest's ``editions`` block — display assets for non-Hafs deliveries.

Exercises ``_edition_blocks`` directly rather than through the route: the block
is derived purely from the composed reciter blocks, and building a real manifest
would need a staged bucket reciter per edition for no extra coverage.
"""

from __future__ import annotations

import pytest

from services.reference import editions
from services.reference.timestamps import _edition_blocks

has_editions = pytest.mark.skipif(
    not editions.available(), reason="qua-domain not installed (Hafs-only runtime)"
)


def _reciters(*riwayat: str) -> dict[str, dict]:
    return {f"r{i}": {"riwayah": slug} for i, slug in enumerate(riwayat)}


@pytest.fixture(autouse=True)
def _clean_caches():
    yield
    from services import quran_refs
    from services.storage import cache

    quran_refs.reset_cache()
    editions.clear_caches()


def test_a_hafs_only_manifest_advertises_no_editions():
    # The FE must not fetch a 0.9 MB font for a deployment that has no use
    # for one, so the block is derived from the reciters actually advertised.
    assert _edition_blocks(_reciters("hafs_an_asim", "hafs_an_asim")) == {}


def test_the_short_sdk_slug_is_also_recognised_as_hafs():
    # The manifest field is a plain catalog string; older rows and fixtures
    # carry the short form, and neither should log an "unservable" warning.
    assert _edition_blocks(_reciters("hafs")) == {}


def test_an_unknown_riwayah_is_skipped_rather_than_defaulted(caplog):
    assert _edition_blocks(_reciters("duri_an_abi_amr")) == {}
    assert "duri_an_abi_amr" in caplog.text


@has_editions
def test_each_non_hafs_edition_is_advertised_once_with_its_own_assets():
    blocks = _edition_blocks(
        _reciters("hafs_an_asim", "warsh_an_nafi", "warsh_an_nafi", "qalon_an_nafi")
    )
    assert sorted(blocks) == ["qalon_an_nafi", "warsh_an_nafi"]

    warsh = blocks["warsh_an_nafi"]
    assert warsh["riwayah"] == "warsh"
    assert warsh["font_url"] == "/api/static/edition/warsh_an_nafi/font"
    assert warsh["refs_url"] == "/api/static/quran-refs.json?riwayah=warsh_an_nafi"
    assert len(warsh["words_sha256"]) == 64
    # Warsh and Qalun share a script but not an edition id or a word list.
    assert blocks["qalon_an_nafi"]["edition_id"] != warsh["edition_id"]
    assert blocks["qalon_an_nafi"]["words_sha256"] != warsh["words_sha256"]


@has_editions
def test_the_advertised_urls_are_the_ones_the_routes_actually_serve(flask_client):
    block = _edition_blocks(_reciters("warsh_an_nafi"))["warsh_an_nafi"]

    assert flask_client.get(block["font_url"]).status_code == 200
    assert flask_client.get(block["refs_url"]).status_code == 200


@has_editions
def test_building_the_block_reads_no_font_or_refs_payload(monkeypatch):
    """The manifest is built per request; the digests it used to carry cost a
    ~0.9 MB font read and a ~3 MB word-map serialise each time, for nothing."""
    from services.reference import quran_refs as quran_refs_service

    def _boom(*_args, **_kwargs):
        raise AssertionError("manifest build must not touch the payload")

    monkeypatch.setattr(editions, "font", _boom)
    monkeypatch.setattr(quran_refs_service, "payload_hash", _boom)

    assert set(_edition_blocks(_reciters("warsh_an_nafi"))) == {"warsh_an_nafi"}


def test_an_unservable_edition_is_omitted_when_the_package_is_missing(monkeypatch, caplog):
    # Degrading to a Hafs entry would make the FE render Warsh coordinates in
    # the Hafs script; an omitted entry makes it fail visibly instead.
    monkeypatch.setattr(editions, "_module", lambda: None)
    editions.clear_caches()
    assert _edition_blocks(_reciters("warsh_an_nafi")) == {}
    assert "warsh_an_nafi" in caplog.text
