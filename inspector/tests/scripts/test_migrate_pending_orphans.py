"""End-to-end test for the one-shot orphan-migration CLI.

Seeds a FilesystemBackend with one orphan (pending entry whose state row
is AWAITING_REVIEW) and one active entry (state row at AWAITING_ALIGNMENT),
then runs ``migrate_pending_orphans.main(['--apply'])`` and asserts:

- orphan moved out of ``requests/pending.json`` and into ``requests/completed.json``
- active entry untouched
- second run is a no-op (idempotent)
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib.schemas import (
    Actor,
    PendingRequest,
    PendingRequestsFile,
    ProposedEdits,
    ReciterRow,
    ReciterState,
    ReciterStateFile,
    Role,
)


@pytest.fixture
def migration_env(tmp_path, monkeypatch):
    from services import hf_bucket as _hf
    from services import pending_requests as pending_requests_service
    from services import request_archive as request_archive_service
    from services import state as state_service
    from services import storage_paths

    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTOR_BACKEND", "filesystem")
    backend = _hf.FilesystemBackend(tmp_path)
    _hf.set_backend(backend)

    # Seed pending: one orphan (state will be AWAITING_REVIEW) + one active.
    pending = PendingRequestsFile(
        by_slug={
            "orphan_reciter": PendingRequest(
                slug="orphan_reciter",
                submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                requester=Actor(
                    hf_user_id="u-1", login_at_time="alice", role=Role.CONTRIBUTOR,
                ),
                proposed_edits=ProposedEdits(name_en="Orphan Name"),
                comments="i was orphaned",
            ),
            "active_reciter": PendingRequest(
                slug="active_reciter",
                submitted_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
                requester=Actor(
                    hf_user_id="u-2", login_at_time="bob", role=Role.CONTRIBUTOR,
                ),
                proposed_edits=ProposedEdits(),
                comments=None,
            ),
        }
    )
    backend.write_json_atomic(
        storage_paths.pending_requests_path(), pending.model_dump(mode="json"),
    )

    # Seed state: orphan past AWAITING_ALIGNMENT, active still in it.
    state = ReciterStateFile(
        reciters=[
            ReciterRow(
                slug="orphan_reciter",
                state=ReciterState.AWAITING_REVIEW,
                state_since=datetime(2026, 1, 5, tzinfo=timezone.utc),
            ),
            ReciterRow(
                slug="active_reciter",
                state=ReciterState.AWAITING_ALIGNMENT,
                state_since=datetime(2026, 2, 5, tzinfo=timezone.utc),
            ),
        ]
    )
    backend.write_json_atomic(
        storage_paths.state_path(), state.model_dump(mode="json"),
    )

    state_service.hydrate()
    pending_requests_service.hydrate()
    request_archive_service.hydrate()

    yield (
        backend,
        tmp_path,
        pending_requests_service,
        request_archive_service,
        state_service,
        storage_paths,
    )

    _hf.reset_backend()


def _load_migrate_module():
    spec = importlib.util.spec_from_file_location(
        "migrate_pending_orphans",
        Path(__file__).resolve().parents[2] / "scripts" / "migrate_pending_orphans.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dry_run_does_not_mutate(migration_env, capsys):
    backend, _, pending_svc, archive_svc, _, paths = migration_env
    mod = _load_migrate_module()

    rc = mod.main([])  # no --apply
    assert rc == 0

    out = capsys.readouterr().out
    assert "orphan_reciter" in out
    assert "Dry-run" in out

    # Pending unchanged
    assert pending_svc.get("orphan_reciter") is not None
    # No archive written
    assert archive_svc.get_for_slug("orphan_reciter", archive_svc.ArchiveKind.COMPLETED) == []


def test_apply_archives_orphan_and_keeps_active(migration_env):
    backend, _, pending_svc, archive_svc, _, paths = migration_env
    mod = _load_migrate_module()

    rc = mod.main(["--apply"])
    assert rc == 0

    # Orphan moved
    assert pending_svc.get("orphan_reciter") is None
    archived = archive_svc.get_for_slug(
        "orphan_reciter", archive_svc.ArchiveKind.COMPLETED,
    )
    assert len(archived) == 1
    entry = archived[0]
    assert entry.proposed_edits.name_en == "Orphan Name"
    assert entry.comments == "i was orphaned"
    assert entry.reason == "migrated from orphan"
    assert entry.transitioned_by.hf_user_id == "system"

    # Active untouched
    assert pending_svc.get("active_reciter") is not None
    assert archive_svc.get_for_slug(
        "active_reciter", archive_svc.ArchiveKind.COMPLETED,
    ) == []


def test_apply_is_idempotent(migration_env, capsys):
    """Second run finds no orphans."""
    mod = _load_migrate_module()

    rc1 = mod.main(["--apply"])
    assert rc1 == 0
    capsys.readouterr()  # drain

    rc2 = mod.main(["--apply"])
    assert rc2 == 0
    out = capsys.readouterr().out
    assert "Found 0 orphan" in out
    assert "Nothing to migrate" in out


def test_no_orphans_clean_dryrun(tmp_path, monkeypatch, capsys):
    """Fresh backend with only an active pending request — dry-run prints
    Found 0 orphan / Nothing to migrate, mutates nothing."""
    from services import hf_bucket as _hf
    from services import pending_requests as pending_requests_service
    from services import request_archive as request_archive_service
    from services import state as state_service
    from services import storage_paths

    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    monkeypatch.setenv("INSPECTOR_BACKEND", "filesystem")
    backend = _hf.FilesystemBackend(tmp_path)
    _hf.set_backend(backend)

    backend.write_json_atomic(
        storage_paths.pending_requests_path(),
        PendingRequestsFile(
            by_slug={
                "active_reciter": PendingRequest(
                    slug="active_reciter",
                    submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                    requester=Actor(
                        hf_user_id="u-1",
                        login_at_time="alice",
                        role=Role.CONTRIBUTOR,
                    ),
                ),
            }
        ).model_dump(mode="json"),
    )
    backend.write_json_atomic(
        storage_paths.state_path(),
        ReciterStateFile(
            reciters=[
                ReciterRow(
                    slug="active_reciter",
                    state=ReciterState.AWAITING_ALIGNMENT,
                    state_since=datetime(2026, 1, 1, tzinfo=timezone.utc),
                ),
            ]
        ).model_dump(mode="json"),
    )

    state_service.hydrate()
    pending_requests_service.hydrate()
    request_archive_service.hydrate()

    mod = _load_migrate_module()
    rc = mod.main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Found 0 orphan" in out

    _hf.reset_backend()
