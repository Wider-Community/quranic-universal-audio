"""``hf_publish.complete`` idempotency.

A duplicate (already-recorded) publish must be a true no-op: it returns before
opening a ``durable_transaction``, so ``db_seq`` doesn't advance and the poll
worker stops re-pushing the whole DB to the bucket every tick for a publish that
is already recorded. ``db_seq`` is the proof — even an empty transaction bumps
it, so an unchanged seq means no transaction was opened.
"""

from __future__ import annotations

from datetime import UTC, datetime

from services import db
from services.admin.jobs import hf_publish
from services.db import current_db_seq, repo_releases


def _seed_recorded_publish(slug: str, version: str) -> None:
    from tests.conftest import _seed_state

    _seed_state(slug, state="released")
    with db.transaction():
        repo_releases.insert_per_recitation_release(
            track="hf",
            slug=slug,
            version=version,
            produced_at=datetime.now(UTC),
            produced_by="SYSTEM_ACTOR",
        )


def test_duplicate_complete_skips_without_advancing_db_seq():
    slug, version = "rec_hf", "rev-1"
    _seed_recorded_publish(slug, version)
    seq_before = current_db_seq()

    out = hf_publish.complete(slug, "job-1", version=version)

    assert out == {"ok": True, "skipped": "duplicate"}
    assert current_db_seq() == seq_before


def test_first_complete_records_and_advances_db_seq():
    slug, version = "rec_hf2", "rev-1"
    from tests.conftest import _seed_state

    _seed_state(slug, state="released")
    seq_before = current_db_seq()

    out = hf_publish.complete(slug, "job-1", version=version)

    assert out["ok"] is True
    assert "release_id" in out
    assert current_db_seq() > seq_before
    assert repo_releases.current_release("hf", slug)["version"] == version
