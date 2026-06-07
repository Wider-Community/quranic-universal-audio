"""Tests for ``services.catalog.edit_delivery`` — the per-delivery counterpart
to ``edit_reciter``. Used by ``services.pending_requests.apply_and_archive_completed``
to apply requester-proposed catalog changes, and by future admin
catalog-edit routes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone

import pytest

from qua_shared.schemas import (
    Actor,
    AudioCategory,
    Channel,
    Delivery,
    ReciterCatalog,
    ReciterEntry,
    RecordingContext,
    Riwayah,
    Role,
    Source,
    Style,
    Vocab,
)


@pytest.fixture
def fresh_catalog(tmp_path, monkeypatch):
    from services import catalog as catalog_service
    from services import hf_bucket as _hf_bucket
    from services import storage_paths

    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)

    from tests.conftest import _seed_catalog

    _seed_catalog(
        vocab=Vocab(
            riwayat=[
                Riwayah(slug="hafs", short="H", name="Hafs"),
                Riwayah(slug="warsh", short="W", name="Warsh"),
            ],
            styles=[
                Style(slug="murattal", short="M", name="Murattal"),
                Style(slug="mujawwad", short="J", name="Mujawwad"),
            ],
            sources=[Source(slug="src1", name="Source One")],
            channels=[Channel(slug="ch1", short="c1", name="Channel One")],
            recording_contexts=[
                RecordingContext(slug="studio", name="Studio"),
                RecordingContext(slug="broadcast", name="Broadcast"),
            ],
        ),
        reciters=[ReciterEntry(reciter_id="rec_a", name_en="Reciter A")],
        deliveries=[
            Delivery(
                slug="rec_a",
                reciter_id="rec_a",
                riwayah="hafs",
                style="murattal",
                recording_context="studio",
                recording_year=2010,
                source="src1",
                channel="ch1",
                audio_category=AudioCategory.BY_SURAH,
                chapter_count=114,
                added_at=datetime.now(UTC),
                added_by_hf_id="seed",
            ),
        ],
    )

    yield catalog_service, backend

    _hf_bucket.reset_backend()


def _actor(role: str = "maintainer") -> Actor:
    return Actor(hf_user_id="u-1", login_at_time="alice", role=Role(role))


def test_edit_delivery_updates_fields(fresh_catalog, monkeypatch):
    catalog_service, _ = fresh_catalog
    from services import audit as audit_service

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    catalog_service.edit_delivery(
        actor=_actor(),
        slug="rec_a",
        riwayah="warsh",
        recording_year=2020,
    )
    d = catalog_service.find_delivery("rec_a")
    assert d is not None
    assert d.riwayah == "warsh"
    assert d.recording_year == 2020
    assert d.style == "murattal"  # untouched


def test_edit_delivery_no_op_when_values_unchanged(fresh_catalog, monkeypatch):
    """No-op edit must skip the txn entirely so it doesn't bump db_seq
    (which would trigger a spurious bucket upload + cache invalidation)."""
    catalog_service, _ = fresh_catalog
    from services import audit as audit_service
    from services import db as _db

    calls = []
    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: calls.append(kw))

    seq_before = _db.current_db_seq()
    catalog_service.edit_delivery(
        actor=_actor(),
        slug="rec_a",
        riwayah="hafs",  # same as current
    )
    assert calls == []  # nothing audited for a no-op
    # The early-return guard must prevent the durable_transaction; the only
    # way to assert that is to pin db_seq.
    assert _db.current_db_seq() == seq_before


def test_edit_delivery_rejects_unknown_slug(fresh_catalog):
    catalog_service, _ = fresh_catalog
    with pytest.raises(catalog_service.InvalidCatalogChange):
        catalog_service.edit_delivery(actor=_actor(), slug="nope", riwayah="warsh")


def test_edit_delivery_rejects_contributor(fresh_catalog):
    catalog_service, _ = fresh_catalog
    with pytest.raises(catalog_service.NotAuthorizedForCatalog):
        catalog_service.edit_delivery(
            actor=_actor(role="contributor"),
            slug="rec_a",
            riwayah="warsh",
        )


def test_edit_delivery_rejects_unknown_riwayah(fresh_catalog, monkeypatch):
    catalog_service, _ = fresh_catalog
    from services import audit as audit_service

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)

    with pytest.raises(catalog_service.InvalidCatalogChange):
        catalog_service.edit_delivery(
            actor=_actor(),
            slug="rec_a",
            riwayah="not_in_vocab",
        )


def test_edit_delivery_audit_record_shape(fresh_catalog, monkeypatch):
    catalog_service, _ = fresh_catalog
    from services import audit as audit_service

    calls = []
    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: calls.append(kw))

    catalog_service.edit_delivery(
        actor=_actor(),
        slug="rec_a",
        recording_context="broadcast",
        reason="proposed update",
    )
    assert len(calls) == 1
    rec = calls[0]
    assert rec["event"] == "catalog.edited"
    assert rec["slug"] == "rec_a"
    assert rec["payload"]["kind"] == "delivery"
    assert rec["payload"]["slug"] == "rec_a"
    assert rec["payload"]["patch"]["recording_context"] == {
        "from": "studio",
        "to": "broadcast",
    }
    # The patch contract excludes unchanged fields; pinning the key set keeps
    # a regression that accidentally leaked riwayah/style/recording_year
    # from passing this assertion.
    assert set(rec["payload"]["patch"].keys()) == {"recording_context"}
    assert rec["reason"] == "proposed update"


def test_edit_delivery_persists_to_substrate(fresh_catalog, monkeypatch):
    catalog_service, _ = fresh_catalog

    catalog_service.edit_delivery(actor=_actor(), slug="rec_a", riwayah="warsh")
    # Read back through the catalog snapshot (the substrate is the source of truth).
    d = catalog_service.find_delivery("rec_a")
    assert d.riwayah == "warsh"


def _seed_hf_row(slug: str) -> None:
    from services import db
    from services.db import repo_releases

    with db.transaction():
        repo_releases.insert_per_recitation_release(
            track="hf",
            slug=slug,
            version=f"v-{slug}",
            produced_at=datetime.now(UTC),
            produced_by="seed",
        )


def test_edit_delivery_stamps_catalog_edit_stale(fresh_catalog, monkeypatch):
    """Editing a public-projection field marks the slug's published HF row stale
    with reason ``catalog_edit`` so the dataset drift surfaces."""
    catalog_service, _ = fresh_catalog
    from services import audit as audit_service
    from services.db import repo_releases

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)
    _seed_hf_row("rec_a")

    catalog_service.edit_delivery(actor=_actor(), slug="rec_a", recording_year=2020)
    hf = repo_releases.current_release("hf", "rec_a")
    assert hf["stale_since"] is not None
    assert hf["stale_reason"] == "catalog_edit"


def test_edit_reciter_name_fans_out_catalog_stale(fresh_catalog, monkeypatch):
    """A public reciter field (name_en) stamps catalog_edit staleness on the
    reciter's published deliveries."""
    catalog_service, _ = fresh_catalog
    from services import audit as audit_service
    from services.db import repo_releases

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)
    _seed_hf_row("rec_a")

    catalog_service.edit_reciter(actor=_actor(), reciter_id="rec_a", name_en="Reciter Alpha")
    hf = repo_releases.current_release("hf", "rec_a")
    assert hf["stale_reason"] == "catalog_edit"


def test_edit_reciter_notes_only_does_not_stamp(fresh_catalog, monkeypatch):
    """``notes`` is admin-only (not in any public projection) — editing it must
    NOT stale the published artifacts."""
    catalog_service, _ = fresh_catalog
    from services import audit as audit_service
    from services.db import repo_releases

    monkeypatch.setattr(audit_service, "append", lambda *a, **kw: None)
    _seed_hf_row("rec_a")

    catalog_service.edit_reciter(actor=_actor(), reciter_id="rec_a", notes="internal note")
    hf = repo_releases.current_release("hf", "rec_a")
    assert hf["stale_since"] is None
    assert hf["stale_reason"] is None
