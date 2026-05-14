"""Tests for the admin-view extensions on ``services.public_state``.

``admin_view_reciter`` surfaces discarded combos in a separate list so the
reciter modal can render them in a dedicated maintainer-only section,
without polluting the public ``detail()`` payload.

``is_reciter_fully_discarded`` is the read-time computation that drives the
"reciter as a whole is discarded" UX: true iff every combo's
``visibility == DISCARDED``.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.lib.schemas import (
    AudioCategory,
    Channel,
    Delivery,
    ReciterCatalog,
    ReciterEntry,
    ReciterRow,
    ReciterState,
    ReciterStateFile,
    Riwayah,
    Source,
    Style,
    Visibility,
    Vocab,
)


def _seed_two_combos_one_discarded(backend):
    """Seed: reciter ``rec_a`` with two deliveries — one public, one discarded."""
    from services import storage_paths

    catalog = ReciterCatalog(
        vocab=Vocab(
            riwayat=[
                Riwayah(slug="hafs", short="H", name="Hafs"),
                Riwayah(slug="warsh", short="W", name="Warsh"),
            ],
            styles=[
                Style(slug="murattal", short="M", name="Murattal"),
            ],
            sources=[Source(slug="src1", name="Source One")],
            channels=[Channel(slug="ch1", short="c1", name="Channel One")],
        ),
        reciters=[ReciterEntry(reciter_id="rec_a", name_en="Reciter A")],
        deliveries=[
            Delivery(
                slug="rec_a_hafs",
                reciter_id="rec_a",
                riwayah="hafs",
                style="murattal",
                source="src1",
                channel="ch1",
                audio_category=AudioCategory.BY_SURAH,
                chapter_count=114,
                added_at=datetime.now(timezone.utc),
                added_by_hf_id="seed",
            ),
            Delivery(
                slug="rec_a_warsh",
                reciter_id="rec_a",
                riwayah="warsh",
                style="murattal",
                source="src1",
                channel="ch1",
                audio_category=AudioCategory.BY_SURAH,
                chapter_count=114,
                added_at=datetime.now(timezone.utc),
                added_by_hf_id="seed",
            ),
        ],
    )
    backend.write_json_atomic(
        storage_paths.catalog_path(), catalog.model_dump(mode="json"),
    )

    state = ReciterStateFile(
        reciters=[
            ReciterRow(
                slug="rec_a_hafs",
                state=ReciterState.CATALOGUED,
                state_since=datetime.now(timezone.utc),
            ),
            ReciterRow(
                slug="rec_a_warsh",
                state=ReciterState.CATALOGUED,
                state_since=datetime.now(timezone.utc),
                visibility=Visibility.DISCARDED,
                visibility_reason="duplicate of warsh-other",
            ),
        ]
    )
    backend.write_json_atomic(
        storage_paths.state_path(), state.model_dump(mode="json"),
    )


@pytest.fixture
def public_state_env(tmp_path, monkeypatch):
    from services import catalog as catalog_service
    from services import hf_bucket as _hf_bucket
    from services import public_state as public_state_service
    from services import state as state_service

    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)
    _seed_two_combos_one_discarded(backend)
    catalog_service.hydrate()
    state_service.hydrate()
    yield public_state_service, backend
    _hf_bucket.reset_backend()


def test_admin_view_splits_public_and_discarded(public_state_env):
    svc, _ = public_state_env
    payload = svc.admin_view_reciter("rec_a")
    assert payload is not None
    public_slugs = [d["slug"] for d in payload["deliveries"]]
    discarded_slugs = [d["slug"] for d in payload["discarded_deliveries"]]
    assert public_slugs == ["rec_a_hafs"]
    assert discarded_slugs == ["rec_a_warsh"]


def test_admin_view_includes_visibility_reason(public_state_env):
    svc, _ = public_state_env
    payload = svc.admin_view_reciter("rec_a")
    assert payload is not None
    discarded = payload["discarded_deliveries"][0]
    assert discarded["visibility"] == "discarded"
    assert discarded["visibility_reason"] == "duplicate of warsh-other"


def test_admin_view_fully_discarded_false_when_one_public(public_state_env):
    svc, _ = public_state_env
    payload = svc.admin_view_reciter("rec_a")
    assert payload is not None
    assert payload["fully_discarded"] is False


def test_admin_view_returns_none_for_unknown_reciter(public_state_env):
    svc, _ = public_state_env
    assert svc.admin_view_reciter("nope") is None


def test_admin_view_does_not_strip_riwayat_from_public(public_state_env):
    """Public-list aggregations (riwayat, styles, etc.) only reflect public
    combos — the discarded ones don't contribute to pill/combo counts."""
    svc, _ = public_state_env
    payload = svc.admin_view_reciter("rec_a")
    assert payload is not None
    assert payload["riwayat"] == ["hafs"]  # only the public combo's riwayah
    assert payload["deliveries_count"] == 1


def test_is_reciter_fully_discarded_partial(public_state_env):
    svc, _ = public_state_env
    assert svc.is_reciter_fully_discarded("rec_a") is False


def test_is_reciter_fully_discarded_when_all_discarded(tmp_path, monkeypatch):
    from datetime import datetime as _dt, timezone as _tz

    from services import catalog as catalog_service
    from services import hf_bucket as _hf_bucket
    from services import public_state as public_state_service
    from services import state as state_service
    from services import storage_paths

    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)

    # Single delivery, discarded.
    catalog = ReciterCatalog(
        vocab=Vocab(
            riwayat=[Riwayah(slug="hafs", short="H", name="Hafs")],
            styles=[Style(slug="murattal", short="M", name="Murattal")],
            sources=[Source(slug="src1", name="Source One")],
            channels=[Channel(slug="ch1", short="c1", name="Channel One")],
        ),
        reciters=[ReciterEntry(reciter_id="rec_b", name_en="Reciter B")],
        deliveries=[
            Delivery(
                slug="rec_b",
                reciter_id="rec_b",
                riwayah="hafs",
                style="murattal",
                source="src1",
                channel="ch1",
                audio_category=AudioCategory.BY_SURAH,
                chapter_count=114,
                added_at=_dt.now(_tz.utc),
                added_by_hf_id="seed",
            ),
        ],
    )
    backend.write_json_atomic(
        storage_paths.catalog_path(), catalog.model_dump(mode="json"),
    )
    state = ReciterStateFile(
        reciters=[
            ReciterRow(
                slug="rec_b",
                state=ReciterState.CATALOGUED,
                state_since=_dt.now(_tz.utc),
                visibility=Visibility.DISCARDED,
                visibility_reason="testing",
            ),
        ]
    )
    backend.write_json_atomic(
        storage_paths.state_path(), state.model_dump(mode="json"),
    )
    catalog_service.hydrate()
    state_service.hydrate()

    assert public_state_service.is_reciter_fully_discarded("rec_b") is True
    payload = public_state_service.admin_view_reciter("rec_b")
    assert payload is not None
    assert payload["fully_discarded"] is True

    _hf_bucket.reset_backend()


def test_public_detail_still_filters_discarded(public_state_env):
    """Sanity: the existing ``detail()`` endpoint remains discarded-filtered."""
    svc, _ = public_state_env
    public = svc.detail("rec_a")
    assert public is not None
    assert {d["slug"] for d in public["deliveries"]} == {"rec_a_hafs"}
