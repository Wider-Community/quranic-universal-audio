"""Wire-model regression net for the ``/api/audio/surahs`` response shape.

Phase-4 of the schema-unify refactor: ``qua_shared.schemas.wire.audio`` models
the shape ``inspector/routes/audio/metadata.py`` actually emits, and these
tests pin that the model both *validates* a live route response and *reproduces*
its exact key set on dump (the regression net for the Phase-5 route cutover).

The QF-routing branch (``via``/``origin_url``) can't be exercised without
wiring the Quran.Foundation Content API, so it's covered by a representative
inline fixture built to match what ``_apply_qf_routing`` writes.
"""

from __future__ import annotations

import json

from qua_shared.schemas import AudioSurahEntry, AudioSurahsResponse
from services import cache, storage_paths


def _install_manifest(backend, slug: str, chapters: dict) -> None:
    """Write a ``catalog/audio_manifest/<slug>.json`` sidecar via the backend."""
    backend.write_bytes_atomic(
        storage_paths.audio_manifest_path(slug),
        json.dumps({"chapters": chapters}).encode("utf-8"),
    )


def test_model_validates_live_audio_surahs_response(flask_client, tmp_reciter_dir):
    """The live ``/api/audio/surahs`` body validates AND round-trips key-for-key.

    Covers the un-routed (no-QF) path: every entry carries exactly ``url`` and
    ``duration_ms``. ``duration_ms`` is derived from the sidecar's
    ``duration_sec`` (chapter 1) and ``None`` when neither manifest nor peaks
    yield a length (chapter 2).
    """
    cache._audio_url.clear()
    slug = "wire_audio_fixture"
    _install_manifest(
        tmp_reciter_dir.backend,
        slug,
        {
            "1": {"url": "https://cdn.example/1.mp3", "duration_sec": 12.5},
            "2": {"url": "https://cdn.example/2.mp3"},
        },
    )

    res = flask_client.get(f"/api/audio/surahs/by_surah/quranicaudio/{slug}")
    assert res.status_code == 200, res.get_data(as_text=True)
    body = res.get_json()

    model = AudioSurahsResponse.model_validate(body)
    assert set(model.surahs.keys()) == {"1", "2"}
    assert model.surahs["1"].duration_ms == 12500
    assert model.surahs["2"].duration_ms is None

    # Dump reproduces the live response key-for-key (the Phase-5 regression net).
    # The route always emits ``duration_ms`` (nullable), so no ``exclude_none``.
    dumped = model.model_dump(by_alias=True)
    assert dumped == body
    # The un-routed entries carry neither QF key, but always carry duration_ms.
    for entry in dumped["surahs"].values():
        assert set(entry.keys()) == {"url", "duration_ms"}


def test_audio_surahs_404_is_not_this_model(flask_client, tmp_reciter_dir):
    """A missing manifest yields the error envelope, not an ``AudioSurahsResponse``."""
    cache._audio_url.clear()
    res = flask_client.get("/api/audio/surahs/by_surah/quranicaudio/does_not_exist")
    assert res.status_code == 404
    assert res.get_json() == {"error": "Reciter not found"}


def test_entry_model_round_trips_qf_routed_shape():
    """A ``via="qf_api"`` entry keeps ``origin_url`` and a null ``duration_ms``.

    Representative inline fixture matching what ``_apply_qf_routing`` writes on a
    successful Content-API swap: ``url`` becomes the QF link, ``origin_url`` holds
    our CDN link, ``duration_ms`` is dropped to ``None``.
    """
    routed = {
        "url": "https://api.quran.foundation/qdc/1.mp3",
        "duration_ms": None,
        "via": "qf_api",
        "origin_url": "https://cdn.example/1.mp3",
    }
    entry = AudioSurahEntry.model_validate(routed)
    assert entry.via == "qf_api"
    assert entry.duration_ms is None
    # ``duration_ms: None`` is kept (route always emits it); only via/origin_url
    # are dropped when unset — here both are set, so the dump is identical.
    assert entry.model_dump(by_alias=True) == routed


def test_entry_model_round_trips_qf_fallback_shape():
    """A ``via="qf_fallback"`` entry keeps our link + duration, no ``origin_url``.

    On a Content-API failure ``_apply_qf_routing`` tags every chapter
    ``qf_fallback`` without touching ``url``/``duration_ms`` and without adding
    ``origin_url``.
    """
    fallback = {
        "url": "https://cdn.example/1.mp3",
        "duration_ms": 12500,
        "via": "qf_fallback",
    }
    entry = AudioSurahEntry.model_validate(fallback)
    assert entry.via == "qf_fallback"
    assert entry.origin_url is None
    # ``origin_url`` is dropped (unset); ``duration_ms`` is kept (here 12500).
    assert entry.model_dump(by_alias=True) == fallback


def test_response_model_rejects_unknown_top_level_key():
    """``extra="forbid"`` guards the producer contract — unknown keys fail."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AudioSurahsResponse.model_validate({"surahs": {}, "unexpected": 1})


def test_entry_model_rejects_unknown_via_literal():
    """``via`` is a closed set the FE switches on — an unknown value fails."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AudioSurahEntry.model_validate({"url": "x", "duration_ms": None, "via": "qf_other"})


def test_entry_model_requires_duration_ms_key():
    """``duration_ms`` is required-nullable — the route always emits the key, so
    a missing key (vs an explicit ``None``) is a contract violation."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AudioSurahEntry.model_validate({"url": "x"})
