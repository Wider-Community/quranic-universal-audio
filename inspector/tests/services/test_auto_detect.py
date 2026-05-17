"""Tests for ``services.auto_detect`` — server-side acceptance reconciler.

The reconciler is the replacement for a manual "Accept" button: when the
alignment pipeline writes files to ``wip/<slug>/``, it fires
``reciter.alignment_completed`` with a synthetic system actor.
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
    Vocab,
)


@pytest.fixture
def auto_detect_env(tmp_path, monkeypatch):
    from services import auto_detect as auto_detect_service
    from services import catalog as catalog_service
    from services import hf_bucket as _hf_bucket
    from services import pending_requests as pending_requests_service
    from services import state as state_service
    from services import storage_paths

    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)

    catalog = ReciterCatalog(
        vocab=Vocab(
            riwayat=[Riwayah(slug="hafs", short="H", name="Hafs")],
            styles=[Style(slug="murattal", short="M", name="Murattal")],
            sources=[Source(slug="src1", name="Source One")],
            channels=[Channel(slug="ch1", short="c1", name="Channel One")],
        ),
        reciters=[ReciterEntry(reciter_id="rec_a", name_en="Reciter A")],
        deliveries=[
            Delivery(
                slug="rec_a",
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
        ],
    )
    backend.write_json_atomic(
        storage_paths.catalog_path(), catalog.model_dump(mode="json"),
    )
    catalog_service.hydrate()
    pending_requests_service.hydrate()
    auto_detect_service._reset_seen_for_tests()

    monkeypatch.setattr(
        __import__("services.audit", fromlist=["audit"]),
        "append",
        lambda *a, **kw: None,
    )

    yield auto_detect_service, state_service, backend

    auto_detect_service._reset_seen_for_tests()
    _hf_bucket.reset_backend()


def _seed_state(backend, *, slug: str, state: ReciterState):
    from services import state as state_service
    from services import storage_paths

    rows = ReciterStateFile(
        reciters=[
            ReciterRow(
                slug=slug,
                state=state,
                state_since=datetime.now(timezone.utc),
            ),
        ]
    )
    backend.write_json_atomic(
        storage_paths.state_path(), rows.model_dump(mode="json"),
    )
    state_service.hydrate()


# ---------------------------------------------------------------------------
# hydrate_initial_seen
# ---------------------------------------------------------------------------


def test_hydrate_initial_seen_seeds_from_wip(auto_detect_env):
    svc, _, backend = auto_detect_env
    # Pre-create a folder under wip/ — anything works as long as list_dir picks
    # up the directory entry.
    backend.write_json_atomic("wip/preexisting_slug/marker.json", {"x": 1})
    svc.hydrate_initial_seen()
    fired = svc.reconcile_once()
    # preexisting_slug is in the seen set + no state row exists in
    # AWAITING_ALIGNMENT anyway, so nothing fires.
    assert fired == 0


def test_hydrate_initial_seen_catches_up_stuck_awaiting_alignment(auto_detect_env):
    """Server restart between upload and boot: wip/ contains a slug that's
    still in AWAITING_ALIGNMENT. Without catch-up firing at hydrate time
    the row would stay stuck forever (reconcile_once only sees NEW slugs).
    """
    svc, state_service, backend = auto_detect_env
    _seed_state(backend, slug="rec_a", state=ReciterState.AWAITING_ALIGNMENT)
    backend.write_json_atomic("wip/rec_a/segments.json", {"x": 1})

    svc.hydrate_initial_seen()

    # Catch-up should have transitioned the row at hydrate time.
    row = state_service.get_row("rec_a")
    assert row.state == ReciterState.AWAITING_REVIEW
    # And reconcile_once should now be a no-op (slug is in seen set + no
    # longer in AWAITING_ALIGNMENT).
    assert svc.reconcile_once() == 0


# ---------------------------------------------------------------------------
# reconcile_once
# ---------------------------------------------------------------------------


def test_reconcile_fires_on_new_wip_folder_for_awaiting_alignment(auto_detect_env):
    svc, state_service, backend = auto_detect_env
    _seed_state(backend, slug="rec_a", state=ReciterState.AWAITING_ALIGNMENT)

    # Simulate the alignment pipeline writing files.
    backend.write_json_atomic("wip/rec_a/detailed.json", {"entries": []})

    fired = svc.reconcile_once()
    assert fired == 1
    row = state_service.get_row("rec_a")
    assert row is not None
    assert row.state == ReciterState.AWAITING_REVIEW


def test_reconcile_skips_slug_not_in_awaiting_alignment(auto_detect_env):
    svc, state_service, backend = auto_detect_env
    _seed_state(backend, slug="rec_a", state=ReciterState.CATALOGUED)
    backend.write_json_atomic("wip/rec_a/detailed.json", {"entries": []})

    fired = svc.reconcile_once()
    assert fired == 0
    row = state_service.get_row("rec_a")
    assert row is not None
    assert row.state == ReciterState.CATALOGUED


def test_reconcile_idempotent_across_calls(auto_detect_env):
    svc, state_service, backend = auto_detect_env
    _seed_state(backend, slug="rec_a", state=ReciterState.AWAITING_ALIGNMENT)
    backend.write_json_atomic("wip/rec_a/detailed.json", {"entries": []})

    fired_first = svc.reconcile_once()
    fired_second = svc.reconcile_once()
    assert fired_first == 1
    assert fired_second == 0  # already seen + already in AWAITING_REVIEW


def test_reconcile_handles_no_state_row(auto_detect_env):
    """A wip/<slug>/ folder for a slug that has no state row must not raise."""
    svc, _, backend = auto_detect_env
    backend.write_json_atomic("wip/orphan_slug/x.json", {"x": 1})
    fired = svc.reconcile_once()
    assert fired == 0


def test_reconcile_handles_missing_wip_dir(tmp_path, monkeypatch):
    """If the wip/ directory doesn't exist on the bucket, list_dir returns [].
    reconcile_once must not raise.
    """
    from services import auto_detect as auto_detect_service
    from services import hf_bucket as _hf_bucket
    from services import state as _state_service  # noqa: F401

    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)
    auto_detect_service._reset_seen_for_tests()

    fired = auto_detect_service.reconcile_once()
    assert fired == 0
    _hf_bucket.reset_backend()


def test_reconcile_applies_pending_edits(auto_detect_env):
    """End-to-end: a pending request gets applied to the catalog when the
    pipeline drops files for the slug."""
    svc, state_service, backend = auto_detect_env
    from services import catalog as catalog_service
    from services import pending_requests as pending_requests_service
    from scripts.lib.schemas import Actor, ProposedEdits, Role

    _seed_state(backend, slug="rec_a", state=ReciterState.AWAITING_ALIGNMENT)
    pending_requests_service.submit(
        "rec_a",
        requester=Actor(hf_user_id="u-req", login_at_time="alice", role=Role.CONTRIBUTOR),
        edits=ProposedEdits(name_en="Approved Name", recording_year=2025),
        comments=None,
    )

    backend.write_json_atomic("wip/rec_a/detailed.json", {"entries": []})
    fired = svc.reconcile_once()
    assert fired == 1

    reciter = catalog_service.find_reciter("rec_a")
    assert reciter is not None
    assert reciter.name_en == "Approved Name"
    delivery = catalog_service.find_delivery("rec_a")
    assert delivery is not None
    assert delivery.recording_year == 2025
    assert pending_requests_service.get("rec_a") is None


def test_system_actor_is_owner_role(auto_detect_env):
    """The synthetic actor must carry owner role so it passes the catalog
    edit gates triggered by ``apply_and_archive_completed``."""
    svc, _, _ = auto_detect_env
    assert svc.SYSTEM_ACTOR.hf_user_id == "system"
    # Role is stored as a string due to use_enum_values=True on Actor.
    assert str(svc.SYSTEM_ACTOR.role) == "owner"
