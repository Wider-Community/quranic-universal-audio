"""Smoke tests for the v2 release repository.

Covers per_recitation_releases insert + supersede + stale-stamp, gh_releases
+ gh_release_recitations insert/membership lookup, and the partial-unique
"one current row per (track, slug)" invariant.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from services import db
from services.db import get_conn, repo_releases


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seed_minimal_delivery(slug: str = "minshawy_murattal") -> str:
    """Insert vocab + a delivery so FK constraints on slug pass.

    Must run inside a ``db.transaction()`` block — writes are gated by the
    writer connection.
    """
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO riwayahs(slug,short,name) VALUES ('hafs_an_asim','hafs','Hafs')")
    conn.execute("INSERT OR IGNORE INTO styles(slug,short,name) VALUES ('murattal','m','Murattal')")
    conn.execute("INSERT OR IGNORE INTO sources(slug,name,url,audio_categories) VALUES ('everyayah','Everyayah',NULL,'[]')")
    conn.execute("INSERT OR IGNORE INTO channels(slug,short,name,host_patterns,gh_release_eligible) VALUES ('everyayah','ea','EveryAyah','[]',1)")
    conn.execute("INSERT OR IGNORE INTO reciters(reciter_id,name_en) VALUES ('minshawy','Minshawy')")
    conn.execute(
        "INSERT OR IGNORE INTO deliveries("
        "slug,reciter_id,riwayah,style,source,channel,audio_category,chapter_count,"
        "codec,container,bitrate_mode,added_at,added_by_hf_id"
        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (slug, "minshawy", "hafs_an_asim", "murattal", "everyayah", "everyayah",
         "by_surah", 114, "mp3", "mp3", "cbr", "2024-01-01T00:00:00Z", "system"),
    )
    return slug


def test_per_recitation_release_insert_and_current(fresh_db):
    now = _now()
    with db.transaction():
        slug = _seed_minimal_delivery()
        rid = repo_releases.insert_per_recitation_release(
            track="ts", slug=slug, version="1", produced_at=now, produced_by="alice",
        )
    assert rid > 0
    current = repo_releases.current_release("ts", slug)
    assert current is not None
    assert current["id"] == rid
    assert current["version"] == "1"


def test_supersede_current_marks_zero_prior_rows(fresh_db):
    """Real write order: insert v1, supersede v1, insert v2. The partial-unique
    requires the prior current row to be superseded before a new one inserts."""
    now = _now()
    with db.transaction():
        slug = _seed_minimal_delivery()
        id1 = repo_releases.insert_per_recitation_release(
            track="ts", slug=slug, version="1", produced_at=now, produced_by="a",
        )
        repo_releases.supersede_current("ts", slug, except_id=-1, at=now)
        id2 = repo_releases.insert_per_recitation_release(
            track="ts", slug=slug, version="2", produced_at=now, produced_by="a",
        )
        n = repo_releases.supersede_current("ts", slug, except_id=id2, at=now)
    # id1 was superseded in the pre-insert sweep; supersede(except=id2) sweeps
    # nothing more (id1 already superseded).
    assert n == 0
    cur = repo_releases.current_release("ts", slug)
    assert cur["id"] == id2


def test_partial_unique_blocks_two_current(fresh_db):
    """The partial-unique ``ux_per_recitation_current`` enforces at-most-one
    current row per (track, slug). Inserting a second current row without
    superseding the first must fail."""
    import sqlite3
    now = _now()
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction():
            slug = _seed_minimal_delivery()
            repo_releases.insert_per_recitation_release(
                track="ts", slug=slug, version="1", produced_at=now, produced_by="a",
            )
            repo_releases.insert_per_recitation_release(
                track="ts", slug=slug, version="2", produced_at=now, produced_by="a",
            )


def test_stamp_stale_on_ts_regen(fresh_db):
    """When TS regenerates, the slug's current HF row gets stale_since stamped."""
    now = _now()
    with db.transaction():
        slug = _seed_minimal_delivery()
        repo_releases.insert_per_recitation_release(
            track="hf", slug=slug, version="abc123", produced_at=now, produced_by="a",
        )
        n = repo_releases.stamp_stale_on_ts_regen(slug, at=now)
    assert n == 1
    hf_row = repo_releases.current_release("hf", slug)
    assert hf_row["stale_since"] is not None


def test_gh_release_insert_and_membership(fresh_db):
    now = _now()
    with db.transaction():
        slug = _seed_minimal_delivery()
        rel_id = repo_releases.insert_gh_release(
            version="v0.1.0", produced_at=now, produced_by="alice",
        )
        repo_releases.insert_gh_release_recitation(
            release_id=rel_id, slug=slug,
            catalog_snapshot={"slug": slug}, zip_sha256="abc", zip_bytes=1000,
            coverage_ayahs=6236, content_hash="def", ts_version="1",
            change_kind="added",
        )
    assert rel_id > 0
    members = repo_releases.gh_release_recitations(rel_id)
    assert len(members) == 1
    assert members[0]["slug"] == slug
    assert members[0]["change_kind"] == "added"

    latest = repo_releases.latest_gh_release_member(slug)
    assert latest is not None
    assert latest["release_id"] == rel_id


def test_gh_release_supersede(fresh_db):
    now = _now()
    with db.transaction():
        id1 = repo_releases.insert_gh_release(version="v0.1.0", produced_at=now, produced_by="a")
        id2 = repo_releases.insert_gh_release(version="v0.2.0", produced_at=now, produced_by="a")
        n = repo_releases.supersede_prior_gh_releases(except_id=id2, at=now)
    assert n == 1
    latest = repo_releases.latest_gh_release()
    assert latest["id"] == id2


def test_release_by_version_finds_superseded(fresh_db):
    """``release_by_version`` returns ANY row matching (track, slug, version),
    including superseded ones. Idempotency guard for webhook retries after a
    later publish has superseded the prior row."""
    now = _now()
    with db.transaction():
        slug = _seed_minimal_delivery()
        id1 = repo_releases.insert_per_recitation_release(
            track="hf", slug=slug, version="rev-A", produced_at=now, produced_by="a",
        )
        repo_releases.supersede_current("hf", slug, except_id=-1, at=now)
        repo_releases.insert_per_recitation_release(
            track="hf", slug=slug, version="rev-B", produced_at=now, produced_by="a",
        )
    found = repo_releases.release_by_version("hf", slug, "rev-A")
    assert found is not None
    assert found["id"] == id1
    assert found["superseded_at"] is not None
    # Non-existent version → None.
    assert repo_releases.release_by_version("hf", slug, "rev-X") is None


def test_gh_release_by_version_finds_superseded(fresh_db):
    """Same idempotency guard for gh_releases."""
    now = _now()
    with db.transaction():
        id1 = repo_releases.insert_gh_release(version="v0.1.0", produced_at=now,
                                              produced_by="a")
        repo_releases.supersede_prior_gh_releases(except_id=-1, at=now)
        repo_releases.insert_gh_release(version="v0.2.0", produced_at=now,
                                        produced_by="a")
    found = repo_releases.gh_release_by_version("v0.1.0")
    assert found is not None
    assert found["id"] == id1
    assert found["superseded_at"] is not None
    assert repo_releases.gh_release_by_version("v9.9.9") is None


def test_content_hash_constraints(fresh_db):
    """zip_bytes must be > 0 and coverage_ayahs must be in [0, 6236]."""
    import sqlite3
    now = _now()
    with db.transaction():
        slug = _seed_minimal_delivery()
        rel_id = repo_releases.insert_gh_release(version="v0.1.0", produced_at=now, produced_by="a")
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction():
            repo_releases.insert_gh_release_recitation(
                release_id=rel_id, slug=slug,
                catalog_snapshot={"slug": slug}, zip_sha256="abc", zip_bytes=0,
                coverage_ayahs=6236, content_hash="def", ts_version="1",
                change_kind="added",
            )
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction():
            repo_releases.insert_gh_release_recitation(
                release_id=rel_id, slug=slug,
                catalog_snapshot={"slug": slug}, zip_sha256="abc", zip_bytes=1000,
                coverage_ayahs=7000,
                content_hash="def", ts_version="1", change_kind="added",
            )
