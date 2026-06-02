"""One-shot JSON→SQLite migration: decomposition, parity, and the
activity↔transition content_hash linkage that the global tombstone store depends on."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.lib.schemas import (
    ActivityState, ArchivedRequest, ArchivedRequestsFile, Actor, Channel, Delivery,
    Member, PendingRequest, PendingRequestsFile, ProposedEdits, ReciterCatalog,
    ReciterEntry, ReciterRow, ReciterState, ReciterStateFile, Riwayah, Role, RolesFile,
    Source, Style, Vocab, Visibility,
)
from services.storage import storage_paths as sp
from services.storage import hf_bucket
from services.storage.hf_bucket import FilesystemBackend
from services.activity import activity_classification

from services import db
from services.db import repo_state, repo_access, repo_transitions, repo_activity, repo_requests

# Loaded by path: inspector/scripts/ is not a package and `scripts` resolves to
# the repo-root scripts/ (scripts.lib.schemas), so import via importlib.
_spec = importlib.util.spec_from_file_location(
    "migrate_json_to_sqlite",
    Path(__file__).resolve().parents[2] / "scripts" / "migrate_json_to_sqlite.py",
)
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


TS = datetime(2026, 5, 10, tzinfo=timezone.utc)


def _catalog() -> ReciterCatalog:
    return ReciterCatalog(
        generated_at=TS,
        vocab=Vocab(
            riwayat=[Riwayah(slug="hafs", short="h", name="Hafs"),
                     Riwayah(slug="warsh", short="w", name="Warsh")],
            styles=[Style(slug="mur", short="m", name="Murattal")],
            sources=[Source(slug="src", name="Src")],
            channels=[Channel(slug="ch", short="c", name="Ch")],
        ),
        reciters=[ReciterEntry(reciter_id="rid", name_en="Reciter")],
        deliveries=[
            Delivery(slug="rid_hafs_mur", reciter_id="rid", riwayah="hafs", style="mur",
                     source="src", channel="ch", audio_category="by_surah",
                     chapter_count=114, added_at=TS, added_by_hf_id="seed"),
            Delivery(slug="rid_warsh_mur", reciter_id="rid", riwayah="warsh", style="mur",
                     source="src", channel="ch", audio_category="by_surah",
                     chapter_count=114, added_at=TS, added_by_hf_id="seed"),
        ],
    )


def _audit_record() -> dict:
    return {
        "ts": "2026-05-10T00:00:00+00:00",
        "event": "reciter.released",
        "slug": "rid_hafs_mur",
        "from_state": "under_review",
        "to_state": "awaiting_review",
        "actor": {"hf_user_id": "owner1", "login_at_time": "owner", "role": "owner"},
        "payload": {},
        "request_id": "req_seed0001",
        "reason": None,
        "result": "ok",
    }


@pytest.fixture
def seeded_bucket(tmp_path):
    backend = FilesystemBackend(str(tmp_path / "bucket"))
    hf_bucket.set_backend(backend)
    db.set_db_path_for_test(tmp_path / "local.db")
    db.init_db()

    backend.write_json_atomic(sp.catalog_path(), _catalog().model_dump(mode="json"))
    backend.write_json_atomic(sp.roles_path(), RolesFile(members=[
        Member(hf_user_id="owner1", login="owner", role=Role.OWNER, added_at=TS,
               added_by_hf_id="bootstrap"),
    ]).model_dump(mode="json"))
    backend.write_json_atomic(sp.state_path(), ReciterStateFile(reciters=[
        ReciterRow(slug="rid_hafs_mur", state=ReciterState.UNDER_REVIEW, state_since=TS,
                   assignee_hf_id="owner1", assignee_login="owner", assignee_since=TS,
                   marked_ready=True, visibility=Visibility.PUBLIC),
    ]).model_dump(mode="json"))
    backend.write_json_atomic(sp.pending_requests_path(), PendingRequestsFile(by_slug={
        "rid_warsh_mur": PendingRequest(
            slug="rid_warsh_mur", submitted_at=TS,
            requester=Actor(hf_user_id="contrib1", login_at_time="con", role=Role.CONTRIBUTOR),
            proposed_edits=ProposedEdits(recording_year=1985), comments="pls", auto_claim=True),
    }).model_dump(mode="json"))
    backend.write_json_atomic(sp.completed_requests_path(), ArchivedRequestsFile(by_slug={
        "rid_hafs_mur": [ArchivedRequest(
            slug="rid_hafs_mur", submitted_at=TS,
            requester=Actor(hf_user_id="contrib1", login_at_time="con", role=Role.CONTRIBUTOR),
            proposed_edits=ProposedEdits(style="mur"), archived_at=TS,
            transitioned_by=Actor(hf_user_id="system", login_at_time="system", role=Role.OWNER))],
    }).model_dump(mode="json"))

    rec = _audit_record()
    aid = activity_classification.audit_id(rec)
    backend.append_jsonl(sp.audit_partition_path(TS), rec)
    # Legacy ``dismissals`` field was dropped with the admin notifications rail;
    # only the global tombstone list survives the migration.
    backend.write_json_atomic(sp.activity_state_path(), ActivityState(
        deleted=[aid]).model_dump(mode="json"))

    yield {"backend": backend, "audit_id": aid}
    db.reset()
    hf_bucket.reset_backend()


def test_migration_decomposes_and_parity_passes(seeded_bucket):
    stats = M.run(allow_orphans=False)
    assert stats["deliveries"] == 2
    assert stats["states"] == 1
    assert stats["claims"] == 1
    assert stats["requests"] == 2          # 1 pending + 1 completed archive
    assert stats["transitions"] == 1

    # state row → delivery_states + synthesized open claim, assignee from claim
    row = repo_state.get_row("rid_hafs_mur")
    assert row.state == ReciterState.UNDER_REVIEW
    assert row.assignee_hf_id == "owner1"
    assert row.marked_ready is True

    # roles
    assert repo_access.resolve_role("owner1") == Role.OWNER

    # pending preserved with original proposed_edits + submitted time
    pend = repo_requests.get_pending("rid_warsh_mur")
    assert pend is not None and pend.proposed_edits.recording_year == 1985
    assert pend.auto_claim is True


def test_activity_links_to_transition_by_content_hash(seeded_bucket):
    M.run(allow_orphans=False)
    aid = seeded_bucket["audit_id"]
    # the migrated transition carries the same content_hash the activity stores key on
    tx = repo_transitions.get_by_content_hash(aid)
    assert tx is not None and tx["event"] == "reciter.released"
    assert tx["content_hash"] == aid
    # tombstone survived and points at that hash (per-user dismissals were
    # dropped with the admin notifications rail in migration 0006)
    assert repo_activity.is_deleted(aid) is True


def test_rerun_aborts_on_nonempty_db(seeded_bucket):
    M.run(allow_orphans=False)
    with pytest.raises(SystemExit):
        M.run(allow_orphans=False)  # second run sees a populated DB → abort


def test_empty_stores_migrate_cleanly(tmp_path):
    backend = FilesystemBackend(str(tmp_path / "bucket"))
    hf_bucket.set_backend(backend)
    db.set_db_path_for_test(tmp_path / "local.db")
    db.init_db()
    try:
        stats = M.run(allow_orphans=False)  # nothing seeded → all zeros, no crash
        assert stats["transitions"] == 0 and stats["states"] == 0
        assert stats["requests"] == 0 and stats["deliveries"] == 0
    finally:
        db.reset()
        hf_bucket.reset_backend()


def test_audit_record_without_request_id_or_actor(tmp_path):
    backend = FilesystemBackend(str(tmp_path / "bucket"))
    hf_bucket.set_backend(backend)
    db.set_db_path_for_test(tmp_path / "local.db")
    db.init_db()
    try:
        backend.write_json_atomic(sp.catalog_path(), _catalog().model_dump(mode="json"))
        # one record with no request_id and no actor (older audit shape)
        backend.append_jsonl(sp.audit_partition_path(TS), {
            "ts": "2026-05-10T00:00:00+00:00", "event": "catalog.edited",
            "slug": None, "payload": {"k": "v"}, "result": "ok",
        })
        stats = M.run(allow_orphans=False)
        assert stats["transitions"] == 1
        tx = list(repo_transitions.feed(limit=5))[0]
        assert tx["event"] == "catalog.edited" and tx["actor"]["hf_user_id"] is None
    finally:
        db.reset()
        hf_bucket.reset_backend()


def test_pending_and_archive_for_same_slug(tmp_path):
    backend = FilesystemBackend(str(tmp_path / "bucket"))
    hf_bucket.set_backend(backend)
    db.set_db_path_for_test(tmp_path / "local.db")
    db.init_db()
    try:
        backend.write_json_atomic(sp.catalog_path(), _catalog().model_dump(mode="json"))
        # same slug: a returned archive (past) + a fresh pending (resubmitted)
        backend.write_json_atomic(sp.pending_requests_path(), PendingRequestsFile(by_slug={
            "rid_hafs_mur": PendingRequest(
                slug="rid_hafs_mur", submitted_at=TS,
                requester=Actor(hf_user_id="c", login_at_time="c", role=Role.CONTRIBUTOR),
                proposed_edits=ProposedEdits()),
        }).model_dump(mode="json"))
        backend.write_json_atomic(sp.returned_requests_path(), ArchivedRequestsFile(by_slug={
            "rid_hafs_mur": [ArchivedRequest(
                slug="rid_hafs_mur", submitted_at=TS,
                requester=Actor(hf_user_id="c", login_at_time="c", role=Role.CONTRIBUTOR),
                proposed_edits=ProposedEdits(), archived_at=TS,
                transitioned_by=Actor(hf_user_id="adm", login_at_time="adm", role=Role.OWNER),
                reason="needs work")],
        }).model_dump(mode="json"))
        # the pending-unique index only constrains status='pending', so this is fine
        M.run(allow_orphans=False)
        assert repo_requests.has_pending("rid_hafs_mur") is True
        assert len(repo_requests.get_for_slug("returned", "rid_hafs_mur")) == 1
    finally:
        db.reset()
        hf_bucket.reset_backend()


def test_orphan_state_slug_aborts(tmp_path):
    backend = FilesystemBackend(str(tmp_path / "bucket"))
    hf_bucket.set_backend(backend)
    db.set_db_path_for_test(tmp_path / "local.db")
    db.init_db()
    try:
        backend.write_json_atomic(sp.catalog_path(), _catalog().model_dump(mode="json"))
        backend.write_json_atomic(sp.state_path(), ReciterStateFile(reciters=[
            ReciterRow(slug="ghost_hafs_mur", state=ReciterState.CATALOGUED, state_since=TS),
        ]).model_dump(mode="json"))
        with pytest.raises(SystemExit):
            M.run(allow_orphans=False)
    finally:
        db.reset()
        hf_bucket.reset_backend()
