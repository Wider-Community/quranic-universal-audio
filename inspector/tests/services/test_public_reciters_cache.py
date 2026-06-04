"""The public-reciters read model is cached and self-invalidates on writes.

``/api/public/reciters`` is the only high-frequency anonymous concurrent path;
``all_public_reciters()`` must not rebuild the whole catalog model + state JOIN
per visitor. It caches keyed on ``db_seq`` so repeated reads are free and ANY
committed write transparently invalidates the entry.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone

import pytest

from qua_shared.schemas import (
    Actor,
    AudioCategory,
    Delivery,
    ReciterEntry,
    Role,
)
from services import catalog as catalog_service
from services import public_state as public_state_service


def _seed_one(slug="rec_a", reciter_id="rec_a", name="Reciter A"):
    from tests.conftest import _seed_catalog, _seed_state

    _seed_catalog(
        reciters=[ReciterEntry(reciter_id=reciter_id, name_en=name)],
        deliveries=[
            Delivery(
                slug=slug,
                reciter_id=reciter_id,
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
    _seed_state(slug, state="catalogued", reciter_id=reciter_id)


def test_repeated_reads_hit_cache(monkeypatch):
    _seed_one()
    calls = []
    real_snapshot = catalog_service.snapshot
    monkeypatch.setattr(
        catalog_service,
        "snapshot",
        lambda: (calls.append(1), real_snapshot())[1],
    )

    a = public_state_service.all_public_reciters()
    b = public_state_service.all_public_reciters()
    c = public_state_service.all_public_reciters()

    assert [r["reciter_id"] for r in a] == ["rec_a"]
    assert a == b == c
    # Only the first call rebuilt the catalog model; the rest were cache hits.
    assert len(calls) == 1


def test_write_invalidates_cache(monkeypatch):
    _seed_one()
    calls = []
    real_snapshot = catalog_service.snapshot
    monkeypatch.setattr(
        catalog_service,
        "snapshot",
        lambda: (calls.append(1), real_snapshot())[1],
    )

    public_state_service.all_public_reciters()  # miss → 1 rebuild
    public_state_service.all_public_reciters()  # hit
    assert len(calls) == 1

    # A committed write bumps db_seq → next read must recompute.
    catalog_service.add_reciter(
        actor=Actor(hf_user_id="u-O", login_at_time="o", role=Role.OWNER),
        reciter_id="rec_b",
        name_en="Reciter B",
    )
    public_state_service.all_public_reciters()  # miss → 2 rebuilds
    assert len(calls) == 2


def test_returned_list_is_a_copy(monkeypatch):
    """Callers (the route) sort/filter in place — that must not corrupt the
    cached canonical list."""
    _seed_one("rec_a")
    _seed_one("rec_c", reciter_id="rec_c", name="Reciter C")

    first = public_state_service.all_public_reciters()
    first.sort(key=lambda r: r["reciter_id"], reverse=True)  # mutate the copy
    first.pop()

    second = public_state_service.all_public_reciters()
    assert {r["reciter_id"] for r in second} == {"rec_a", "rec_c"}
