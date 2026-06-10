"""Round-trip tests for the ``AudioManifestSidecar`` Pydantic schema.

Schema lives at ``qua_shared/schemas/bucket/catalog.py``. The sidecar is the
per-delivery ``catalog/audio_manifest/<slug>.json`` artefact — a ``_meta``
provenance block plus a ``chapters`` map of stringified surah keys to
per-chapter URL/probe records.

These assert the canonical on-disk shape round-trips byte/shape-equal via
``model_dump(by_alias=True)`` (the ``_meta`` alias must survive) and that the
artefact is pure ``extra="forbid"`` — any unexpected top-level key raises
``ValidationError`` rather than being stripped.
"""

from __future__ import annotations

import pytest

from qua_shared.schemas import AudioManifestSidecar


def _canonical_sidecar() -> dict:
    """Canonical ``by_surah`` sidecar — ``_meta`` alias + two chapters."""
    return {
        "schema_version": 1,
        "slug": "abdul_basit_murattal",
        "_meta": {
            "checksum": "sha256:9f1c0d2e",
            "source_meta_reciter": "abdulBasit",
            "source_manifest_path": "catalog/audio_manifest/abdul_basit_murattal.json",
            "chapter_count": 2,
            "category": "by_surah",
        },
        "chapters": {
            "1": {
                "url": "https://audio-cdn.tarteel.ai/quran/surah/abdulBasit/murattal/mp3/001.mp3",
                "size_bytes": 482301,
                "duration_sec": 41,
                "bitrate_kbps": 96,
                "bitrate_mode": "cbr",
                "max_linear_seek_err_ms": 12,
            },
            "112": {
                "url": "https://audio-cdn.tarteel.ai/quran/surah/abdulBasit/murattal/mp3/112.mp3",
                "size_bytes": 120044,
                "duration_sec": 10,
                "bitrate_kbps": 96,
                "bitrate_mode": "vbr",
                "max_linear_seek_err_ms": 8,
            },
        },
    }


# -- Validation tests ---------------------------------------------------


def test_canonical_sidecar_validates():
    m = AudioManifestSidecar.model_validate(_canonical_sidecar())
    assert m.slug == "abdul_basit_murattal"
    assert m.meta.checksum == "sha256:9f1c0d2e"
    assert m.meta.chapter_count == 2
    assert set(m.chapters) == {"1", "112"}
    assert m.chapters["1"].url.endswith("001.mp3")
    assert m.chapters["112"].bitrate_mode.value == "vbr"


def test_schema_version_required():
    """``schema_version`` is the canonical on-disk discriminator. It has a
    default, but the canonical artefact always carries it — assert it
    survives the round-trip rather than silently defaulting."""
    raw = _canonical_sidecar()
    m = AudioManifestSidecar.model_validate(raw)
    assert m.schema_version == 1
    assert m.model_dump(by_alias=True)["schema_version"] == 1


def test_missing_meta_fails():
    """``_meta`` is required (no default) — a sidecar without it is corrupt."""
    raw = _canonical_sidecar()
    raw.pop("_meta")
    with pytest.raises(ValueError):
        AudioManifestSidecar.model_validate(raw)


def test_invalid_slug_fails():
    raw = _canonical_sidecar()
    raw["slug"] = "Not A Slug"
    with pytest.raises(ValueError, match="invalid slug"):
        AudioManifestSidecar.model_validate(raw)


# -- pure extra="forbid" policy ----------------------------------------


def test_unknown_top_level_key_rejected():
    """An unknown top-level key raises ``ValidationError`` under pure
    ``extra="forbid"`` — no silent strip, no absorbed extra."""
    raw = _canonical_sidecar()
    raw["unexpected_bloat"] = {"junk": True}
    with pytest.raises(ValueError):
        AudioManifestSidecar.model_validate(raw)


# -- Round-trip emission ------------------------------------------------


def test_round_trip_byte_shape_equal():
    """``model_dump(by_alias=True)`` reproduces the canonical artefact
    shape exactly — ``_meta`` alias preserved, no field renamed or dropped,
    no extra key introduced. Enum values serialize back to their string
    form so the dump is byte-equal to the input JSON shape."""
    raw = _canonical_sidecar()
    m = AudioManifestSidecar.model_validate(raw)
    out = m.model_dump(by_alias=True, mode="json")

    assert "_meta" in out and "meta" not in out
    assert out == raw


def test_chapters_default_empty():
    """A sidecar with no probed chapters yet still validates — ``chapters``
    defaults to an empty dict."""
    raw = _canonical_sidecar()
    raw.pop("chapters")
    m = AudioManifestSidecar.model_validate(raw)
    assert m.chapters == {}
    assert m.model_dump(by_alias=True)["chapters"] == {}
