"""Round-trip tests for the ``AudioManifestSidecar`` Pydantic schema.

Schema lives at ``qua_shared/schemas/bucket/catalog.py``. The sidecar is the
per-delivery ``catalog/audio_manifest/<slug>.json`` artefact — a ``_meta``
provenance block plus a ``chapters`` map of stringified surah keys to
per-chapter URL/probe records.

These assert the canonical on-disk shape round-trips byte/shape-equal via
``model_dump(by_alias=True)`` (the ``_meta`` alias must survive), that
``extra="forbid"`` + the ``strip_and_warn`` pre-validator keep the artefact's
tolerance policy consistent with the other bucket schemas (unknown keys
stripped + warned, never crashing the read), and that a seeded legacy key
strips at INFO when promoted into ``DEAD_FIELDS``.
"""

from __future__ import annotations

import logging

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


# -- extra="forbid" / strip_and_warn policy ----------------------------


def test_unknown_top_level_key_stripped_and_warned(caplog):
    """An unknown top-level key is stripped (not absorbed as an extra) and
    surfaces a WARNING — the artefact's tolerance policy now matches its
    sibling bucket schemas instead of crashing the read."""
    caplog.set_level(logging.WARNING, logger="qua_shared.schemas._extras")
    raw = _canonical_sidecar()
    raw["unexpected_bloat"] = {"junk": True}
    m = AudioManifestSidecar.model_validate(raw)
    assert (m.model_extra or {}) == {}
    assert not hasattr(m, "unexpected_bloat")
    msgs = " ".join(r.getMessage() for r in caplog.records)
    assert "unexpected_bloat" in msgs
    assert "UNRECOGNIZED" in msgs


def test_seeded_legacy_key_strips_at_info(caplog):
    """``AudioManifestSidecar.DEAD_FIELDS`` starts empty, so the only way to
    exercise the legacy (INFO) branch of the artefact's pre-validator is to
    invoke ``strip_and_warn`` the same way the model does — declared set +
    the ``_meta`` alias — with a seeded dead key. This certifies the model
    routes a promoted legacy field to INFO, not WARNING, the day one is added.
    """
    from qua_shared.schemas._extras import strip_and_warn

    declared = set(AudioManifestSidecar.model_fields)
    declared.add("_meta")

    caplog.set_level(logging.INFO, logger="qua_shared.schemas._extras")
    raw = _canonical_sidecar()
    raw["legacy_generated_at"] = "2026-01-01T00:00:00Z"
    cleaned = strip_and_warn(
        raw,
        declared=declared,
        dead={"legacy_generated_at"},
        model_name="AudioManifestSidecar",
    )
    assert "legacy_generated_at" not in cleaned
    records = [r for r in caplog.records if "legacy_generated_at" in r.getMessage()]
    assert records, "expected a log mentioning the seeded legacy key"
    assert records[0].levelno == logging.INFO
    assert "legacy" in records[0].getMessage().lower()

    # The cleaned dict still parses into a valid model (the seeded key gone).
    m = AudioManifestSidecar.model_validate(cleaned)
    assert not hasattr(m, "legacy_generated_at")


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
