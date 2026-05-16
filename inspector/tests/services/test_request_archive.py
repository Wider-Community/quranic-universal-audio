"""Tests for ``services/state/request_archive`` — three terminal-state stores.

Mirrors the hydrate / snapshot / append pattern of ``pending_requests``,
but each entry carries archival metadata and slugs can hold multiple
entries (chronological — return → re-request → return).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts.lib.schemas import Actor, ArchivedRequest, ProposedEdits, Role


@pytest.fixture
def fresh_archive(tmp_path, monkeypatch):
    """Per-test FilesystemBackend so each test starts with empty stores."""
    from services import hf_bucket as _hf_bucket
    from services import request_archive as request_archive_service

    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)
    request_archive_service.hydrate()

    yield request_archive_service, backend

    _hf_bucket.reset_backend()


def _actor(hf_user_id: str = "u-1", login: str = "alice", role: str = "contributor") -> Actor:
    return Actor(hf_user_id=hf_user_id, login_at_time=login, role=Role(role))


def _archived(
    slug: str = "test_reciter",
    *,
    archived_at: datetime | None = None,
    reason: str | None = None,
    name_en: str | None = None,
) -> ArchivedRequest:
    return ArchivedRequest(
        slug=slug,
        submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        requester=_actor(),
        proposed_edits=ProposedEdits(name_en=name_en) if name_en else ProposedEdits(),
        comments=None,
        archived_at=archived_at or datetime.now(timezone.utc),
        transitioned_by=_actor(hf_user_id="system", login="system", role="owner"),
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Hydrate
# ---------------------------------------------------------------------------


def test_hydrate_empty_when_no_files(fresh_archive):
    svc, _ = fresh_archive
    for kind in svc.ArchiveKind:
        assert svc.snapshot(kind).by_slug == {}


def test_hydrate_loads_existing_files(tmp_path, monkeypatch):
    from services import hf_bucket as _hf_bucket
    from services import request_archive as svc
    from services import storage_paths

    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)

    seed = {
        "by_slug": {
            "test_reciter": [
                {
                    "slug": "test_reciter",
                    "submitted_at": "2026-01-01T00:00:00+00:00",
                    "requester": {
                        "hf_user_id": "u-1",
                        "login_at_time": "alice",
                        "role": "contributor",
                    },
                    "proposed_edits": {"name_en": "Seeded"},
                    "comments": None,
                    "auto_claim": False,
                    "archived_at": "2026-01-02T00:00:00+00:00",
                    "transitioned_by": {
                        "hf_user_id": "system",
                        "login_at_time": "system",
                        "role": "owner",
                    },
                    "reason": None,
                }
            ]
        }
    }
    backend.write_json_atomic(storage_paths.completed_requests_path(), seed)
    svc.hydrate()
    archived = svc.get_for_slug("test_reciter", svc.ArchiveKind.COMPLETED)
    assert len(archived) == 1
    assert archived[0].proposed_edits.name_en == "Seeded"

    _hf_bucket.reset_backend()


# ---------------------------------------------------------------------------
# append / get_for_slug
# ---------------------------------------------------------------------------


def test_append_persists_to_disk(fresh_archive):
    svc, backend = fresh_archive
    from services import storage_paths

    svc.append(svc.ArchiveKind.COMPLETED, _archived(name_en="V1"))

    raw = backend.read_json(storage_paths.completed_requests_path())
    assert "test_reciter" in raw["by_slug"]
    assert raw["by_slug"]["test_reciter"][0]["proposed_edits"]["name_en"] == "V1"


def test_append_keeps_kinds_isolated(fresh_archive):
    svc, _ = fresh_archive

    svc.append(svc.ArchiveKind.COMPLETED, _archived(name_en="C"))
    svc.append(svc.ArchiveKind.RETURNED, _archived(name_en="R", reason="x" * 10))
    svc.append(svc.ArchiveKind.DISCARDED, _archived(name_en="D", reason="y" * 10))

    assert len(svc.get_for_slug("test_reciter", svc.ArchiveKind.COMPLETED)) == 1
    assert len(svc.get_for_slug("test_reciter", svc.ArchiveKind.RETURNED)) == 1
    assert len(svc.get_for_slug("test_reciter", svc.ArchiveKind.DISCARDED)) == 1


def test_append_multiple_entries_per_slug_chronological(fresh_archive):
    """A slug can ride the return loop multiple times; entries must stay
    in append order."""
    svc, _ = fresh_archive

    svc.append(
        svc.ArchiveKind.RETURNED,
        _archived(
            archived_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            reason="r" * 10,
            name_en="first",
        ),
    )
    svc.append(
        svc.ArchiveKind.RETURNED,
        _archived(
            archived_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            reason="r" * 10,
            name_en="second",
        ),
    )

    archived = svc.get_for_slug("test_reciter", svc.ArchiveKind.RETURNED)
    assert len(archived) == 2
    assert archived[0].proposed_edits.name_en == "first"
    assert archived[1].proposed_edits.name_en == "second"


def test_get_for_slug_empty_when_unknown(fresh_archive):
    svc, _ = fresh_archive
    assert svc.get_for_slug("nope", svc.ArchiveKind.COMPLETED) == []


def test_get_for_slug_returns_deep_copies(fresh_archive):
    """Mutating returned entries must not leak back into the in-memory store."""
    svc, _ = fresh_archive
    svc.append(svc.ArchiveKind.COMPLETED, _archived(name_en="original"))

    archived = svc.get_for_slug("test_reciter", svc.ArchiveKind.COMPLETED)
    archived[0].proposed_edits.name_en = "tampered"

    re_read = svc.get_for_slug("test_reciter", svc.ArchiveKind.COMPLETED)
    assert re_read[0].proposed_edits.name_en == "original"


def test_hydrate_reload_preserves_appended_entries(fresh_archive):
    """append → disk; reload should see the same entry."""
    svc, _ = fresh_archive

    svc.append(svc.ArchiveKind.COMPLETED, _archived(name_en="persisted"))
    svc.hydrate()  # reload from disk

    archived = svc.get_for_slug("test_reciter", svc.ArchiveKind.COMPLETED)
    assert len(archived) == 1
    assert archived[0].proposed_edits.name_en == "persisted"
