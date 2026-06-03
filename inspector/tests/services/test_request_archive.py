"""Tests for ``services/state/request_archive`` — the read facade over the
unified ``requests`` table (terminal statuses accepted/returned/discarded).

Post-cutover an archived request is a ``requests`` row whose ``status`` left
``pending`` (written by ``repo_requests.resolve``); ``request_archive`` only
reads it back. Entries are seeded here via the real submit→resolve flow.
"""

from __future__ import annotations

import pytest

from qua_shared.schemas import Actor, ProposedEdits, Role


@pytest.fixture
def fresh_archive(tmp_path, monkeypatch):
    """FilesystemBackend for any content + the substrate DB (autouse) for state."""
    from services import hf_bucket as _hf_bucket
    from services import request_archive as request_archive_service

    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)

    yield request_archive_service, backend

    _hf_bucket.reset_backend()


def _actor(hf_user_id: str = "u-1", login: str = "alice", role: str = "contributor") -> Actor:
    return Actor(hf_user_id=hf_user_id, login_at_time=login, role=Role(role))


_STATUS_FOR_KIND = {"completed": "accepted", "returned": "returned", "discarded": "discarded"}


def _archive(slug, kind, *, name_en=None, reason=None):
    """Seed an archived request for ``slug`` in ``kind`` via submit→resolve."""
    from services import db
    from services.db import repo_requests
    from tests.conftest import _seed_state

    _seed_state(slug, state="catalogued", reciter_id=slug)  # delivery FK (idempotent)
    with db.transaction():
        repo_requests.submit(
            slug=slug,
            requester=_actor(),
            proposed_edits=ProposedEdits(name_en=name_en) if name_en else ProposedEdits(),
        )
        repo_requests.resolve(
            slug=slug,
            status=_STATUS_FOR_KIND[kind.value],
            transitioned_by=_actor(hf_user_id="system", login="system", role="owner"),
            reason=reason,
        )


# ---------------------------------------------------------------------------
# snapshot / get_for_slug
# ---------------------------------------------------------------------------


def test_snapshot_empty_when_no_rows(fresh_archive):
    svc, _ = fresh_archive
    for kind in svc.ArchiveKind:
        assert svc.snapshot(kind).by_slug == {}


def test_archive_via_resolve_is_readable(fresh_archive):
    svc, _ = fresh_archive
    _archive("test_reciter", svc.ArchiveKind.COMPLETED, name_en="V1")

    archived = svc.get_for_slug("test_reciter", svc.ArchiveKind.COMPLETED)
    assert len(archived) == 1
    assert archived[0].proposed_edits.name_en == "V1"


def test_kinds_isolated(fresh_archive):
    svc, _ = fresh_archive
    _archive("rec_c", svc.ArchiveKind.COMPLETED, name_en="C")
    _archive("rec_r", svc.ArchiveKind.RETURNED, name_en="R", reason="x" * 10)
    _archive("rec_d", svc.ArchiveKind.DISCARDED, name_en="D", reason="y" * 10)

    assert len(svc.get_for_slug("rec_c", svc.ArchiveKind.COMPLETED)) == 1
    assert len(svc.get_for_slug("rec_r", svc.ArchiveKind.RETURNED)) == 1
    assert len(svc.get_for_slug("rec_d", svc.ArchiveKind.DISCARDED)) == 1
    # cross-kind isolation
    assert svc.get_for_slug("rec_c", svc.ArchiveKind.RETURNED) == []


def test_multiple_entries_per_slug_chronological(fresh_archive):
    """A slug can ride the return loop multiple times; get_for_slug returns
    them oldest→newest."""
    svc, _ = fresh_archive
    _archive("test_reciter", svc.ArchiveKind.RETURNED, name_en="first", reason="r" * 10)
    _archive("test_reciter", svc.ArchiveKind.RETURNED, name_en="second", reason="r" * 10)

    archived = svc.get_for_slug("test_reciter", svc.ArchiveKind.RETURNED)
    assert len(archived) == 2
    names = [a.proposed_edits.name_en for a in archived]
    assert names == ["first", "second"]


def test_get_for_slug_empty_when_unknown(fresh_archive):
    svc, _ = fresh_archive
    assert svc.get_for_slug("nope", svc.ArchiveKind.COMPLETED) == []


def test_get_for_slug_returns_fresh_objects(fresh_archive):
    """Each get_for_slug rebuilds from the DB, so mutating a returned entry
    can't leak back."""
    svc, _ = fresh_archive
    _archive("test_reciter", svc.ArchiveKind.COMPLETED, name_en="original")

    archived = svc.get_for_slug("test_reciter", svc.ArchiveKind.COMPLETED)
    archived[0].proposed_edits.name_en = "tampered"

    re_read = svc.get_for_slug("test_reciter", svc.ArchiveKind.COMPLETED)
    assert re_read[0].proposed_edits.name_en == "original"
