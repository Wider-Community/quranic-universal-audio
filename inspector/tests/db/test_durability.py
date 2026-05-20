"""The durability seam exercised through a real service mutation.

The autouse ``_substrate_db`` fixture disables bucket sync for the bulk of the
suite; these tests re-enable it and drive ``catalog.add_reciter`` (a top-level
``durable_transaction``) so the ``durable_transaction → mark_durable → upload``
path is actually verified end-to-end against a FilesystemBackend bucket. This
is the "no 200 without a durable bucket copy" invariant.
"""

from __future__ import annotations

import pytest

from scripts.lib.schemas import Actor, Role
from services import catalog as catalog_service
from services import hf_bucket as _hf_bucket
from services.db import sync


def _owner() -> Actor:
    return Actor(hf_user_id="u-O", login_at_time="owner", role=Role.OWNER)


@pytest.fixture
def synced_bucket(tmp_path):
    """A FilesystemBackend bucket + sync ARMED (the autouse fixture disarms it)."""
    backend = _hf_bucket.FilesystemBackend(tmp_path / "bucket")
    _hf_bucket.set_backend(backend)
    sync.set_sync_enabled(True)
    sync._reset_for_test()
    try:
        yield backend
    finally:
        sync.set_sync_enabled(False)
        _hf_bucket.reset_backend()


def test_service_mutation_uploads_db_to_bucket(synced_bucket):
    """A committed service mutation makes the DB durable on the bucket before
    returning (the durable_transaction upload fires once, top-level)."""
    catalog_service.add_reciter(actor=_owner(), reciter_id="recx", name_en="Rec X")

    # The DB blob + seq sidecar landed on the bucket.
    assert len(sync._read_direct(sync.DB_BUCKET_PATH)) > 0
    meta = sync._serde.json_loads(sync._read_direct(sync.SEQ_BUCKET_PATH))
    assert meta["seq"] >= 1 and meta["nonce"] == sync._NONCE
    st = sync.status()
    assert st["last_bucket_upload_ts"] is not None
    assert st["last_error"] is None


def test_upload_failure_propagates_and_local_stays_ahead(synced_bucket, monkeypatch):
    """If the bucket upload fails, the exception propagates (the route turns it
    into 5xx — never a 200 for a write absent from the bucket), while the local
    commit stays ahead so a later retry re-uploads."""
    def boom(path, data):  # noqa: ANN001
        raise IOError("network down")

    monkeypatch.setattr(sync, "_write_direct", boom)

    with pytest.raises(IOError):
        catalog_service.add_reciter(actor=_owner(), reciter_id="recy", name_en="Rec Y")

    # Local commit happened (the txn committed before the upload was attempted).
    assert catalog_service.find_reciter("recy") is not None
    # Sanitized error recorded, no token leakage.
    assert sync.status()["last_error"] is not None
    assert "OSError" in sync.status()["last_error"]
