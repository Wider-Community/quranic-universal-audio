"""db.sync against a FilesystemBackend (no network): upload/pull round-trip,
CAS guard, daily snapshot + retention, health counters."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services import db
from services.db import sync, _serde
from services.storage import hf_bucket
from services.storage.hf_bucket import FilesystemBackend


@pytest.fixture
def synced(tmp_path):
    backend = FilesystemBackend(str(tmp_path / "bucket"))
    hf_bucket.set_backend(backend)
    db.set_db_path_for_test(tmp_path / "local.db")
    db.init_db()
    sync._reset_for_test()
    yield tmp_path
    db.reset()
    hf_bucket.reset_backend()


def _commit_user(hf="u1", login="alice"):
    with db.transaction() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users(hf_user_id, login_cache) VALUES (?,?)",
            (hf, login),
        )


def test_upload_then_pull_roundtrip(synced):
    _commit_user()
    seq = sync.upload()
    assert seq == 1
    # sidecar reflects our seq + nonce
    meta = _serde.json_loads(sync._read_direct(sync.SEQ_BUCKET_PATH))
    assert meta["seq"] == 1 and meta["nonce"] == sync._NONCE
    # the db blob exists
    assert len(sync._read_direct(sync.DB_BUCKET_PATH)) > 0

    # pull into a brand-new local path and confirm the row survived
    new_path = synced / "pulled.db"
    assert sync.pull(dest_path=str(new_path)) is True
    db.set_db_path_for_test(new_path)
    db.init_db()  # migrations already applied in the pulled file → no-op
    row = db.get_conn().execute(
        "SELECT login_cache FROM users WHERE hf_user_id='u1'"
    ).fetchone()
    assert row[0] == "alice"


def test_pull_returns_false_when_bucket_empty(synced):
    assert sync.pull(dest_path=str(synced / "nope.db")) is False


def test_reupload_same_container_is_allowed(synced):
    _commit_user()
    assert sync.upload() == 1
    _commit_user("u2", "bob")
    # our own nonce owns the sidecar → advancing is fine
    assert sync.upload() == 2


def test_cas_conflict_from_other_container(synced):
    _commit_user()
    # simulate another container that raced ahead with a different nonce
    sync._write_direct(
        sync.SEQ_BUCKET_PATH,
        _serde.json_dumps({"seq": 99, "nonce": "other-container", "ts": "x"}).encode(),
    )
    with pytest.raises(sync.UploadConflict):
        sync.upload()
    assert sync._last_error and "CAS conflict" in sync._last_error


def test_daily_snapshot_and_retention(synced):
    _commit_user()
    today = datetime(2026, 5, 20, tzinfo=timezone.utc)
    path = sync.daily_snapshot(today=today)
    assert path == "db/inspector-2026-05-20.db"
    assert len(sync._read_direct(path)) > 0

    # plant an old snapshot, then prune as-of 2026-06-10:
    #   2026-01-01 is ~160d old (> 30) → pruned; 2026-05-20 is 21d old → kept.
    sync._write_direct("db/inspector-2026-01-01.db", b"old")
    removed = sync._prune_snapshots(today=datetime(2026, 6, 10, tzinfo=timezone.utc))
    assert "inspector-2026-01-01.db" in removed
    assert "inspector-2026-05-20.db" not in removed


def test_upload_failure_sets_last_error_and_raises(synced, monkeypatch):
    _commit_user()

    def boom(path, data):
        raise IOError("network down")

    monkeypatch.setattr(sync, "_write_direct", boom)
    with pytest.raises(IOError):
        sync.upload()
    st = sync.status()
    assert st["last_error"] is not None and "OSError" in st["last_error"]
    # no token/url leakage: only type + truncated message
    assert "network down" in st["last_error"]


def test_status_and_lag(synced):
    assert sync.bucket_lag_seconds() is None
    _commit_user()
    sync.upload()
    st = sync.status()
    assert st["last_bucket_upload_ts"] is not None
    assert st["bucket_lag_seconds"] is not None and st["bucket_lag_seconds"] >= 0
    assert st["queue"] == 0
    assert st["last_error"] is None
