"""catalog_service.snapshot() is cached on db_seq and self-invalidates on writes.

The full ReciterCatalog rebuild is on hot read paths (/api/static/catalog.json,
public detail pages, activity descriptors). It must not rebuild per request.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone

from qua_shared.schemas import Actor, AudioCategory, Delivery, ReciterEntry, Role
from services import catalog as catalog_service
from services.db import repo_catalog


def _seed():
    from tests.conftest import _seed_catalog

    _seed_catalog(
        reciters=[ReciterEntry(reciter_id="rec_a", name_en="Reciter A")],
        deliveries=[
            Delivery(
                slug="rec_a",
                reciter_id="rec_a",
                riwayah="hafs",
                style="mur",
                source="src",
                channel="ch",
                audio_category=AudioCategory.BY_SURAH,
                chapter_count=114,
                added_at=datetime.now(UTC),
                added_by_hf_id="seed",
            )
        ],
    )


def _count_rebuilds(monkeypatch):
    calls = []
    real = repo_catalog.snapshot
    monkeypatch.setattr(repo_catalog, "snapshot", lambda: (calls.append(1), real())[1])
    return calls


def test_repeated_snapshots_rebuild_once(monkeypatch):
    _seed()
    calls = _count_rebuilds(monkeypatch)

    a = catalog_service.snapshot()
    b = catalog_service.snapshot()
    c = catalog_service.snapshot()

    assert [r.reciter_id for r in a.reciters] == ["rec_a"]
    # Cache hits return the SAME instance (read-only contract).
    assert a is b is c
    assert len(calls) == 1


def test_catalog_write_invalidates(monkeypatch):
    _seed()
    calls = _count_rebuilds(monkeypatch)

    catalog_service.snapshot()  # miss → 1 rebuild
    catalog_service.snapshot()  # hit
    assert len(calls) == 1

    # A catalog write bumps db_seq → next snapshot must recompute and reflect it.
    catalog_service.add_reciter(
        actor=Actor(hf_user_id="u-O", login_at_time="o", role=Role.OWNER),
        reciter_id="rec_b",
        name_en="Reciter B",
    )
    snap = catalog_service.snapshot()  # miss → 2 rebuilds
    assert len(calls) == 2
    assert {r.reciter_id for r in snap.reciters} == {"rec_a", "rec_b"}


def test_state_write_also_invalidates(monkeypatch):
    """db_seq keying means ANY committed write invalidates (safe over-
    invalidation — the catalog can never be served stale)."""
    _seed()
    from tests.conftest import _seed_state

    calls = _count_rebuilds(monkeypatch)

    catalog_service.snapshot()  # miss → 1
    catalog_service.snapshot()  # hit
    assert len(calls) == 1

    _seed_state("rec_a", state="awaiting_review")  # a committed write → db_seq++
    catalog_service.snapshot()  # miss → 2
    assert len(calls) == 2
