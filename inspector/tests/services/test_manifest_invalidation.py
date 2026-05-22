"""A committed lifecycle transition drops the TS manifest's process cache.

The manifest (services/reference/timestamps.py) is built once and cached behind
a ``_built`` flag with no other invalidation hook. Without the post-commit drop
in ``state.transition()`` it would serve the boot-time published-set until the
next restart (the bug that left freshly-published reciters missing from the
Timestamps tab). These tests pin the invalidation so that regression can't
silently return.
"""

from __future__ import annotations

from datetime import datetime, timezone

from scripts.lib.schemas import Actor, AudioCategory, Delivery, ReciterEntry, Role
from services.reference import timestamps as ts_manifest
from services.state import state as state_service


def _seed_awaiting_timestamps(slug: str = "rec_a") -> None:
    from tests.conftest import _seed_catalog, _seed_state

    _seed_catalog(
        reciters=[ReciterEntry(reciter_id=slug, name_en="Reciter A")],
        deliveries=[Delivery(
            slug=slug, reciter_id=slug, riwayah="hafs", style="mur",
            source="src", channel="ch", audio_category=AudioCategory.BY_SURAH,
            chapter_count=114, added_at=datetime.now(timezone.utc),
            added_by_hf_id="seed",
        )],
    )
    _seed_state(slug, state="awaiting_timestamps")


def test_transition_drops_manifest_cache():
    _seed_awaiting_timestamps("rec_a")
    ts_manifest.manifest_bytes()  # warm the process cache
    assert ts_manifest._built is True

    state_service.transition(
        "rec_a", "reciter.timestamps_completed",
        actor=Actor(hf_user_id="u-O", login_at_time="o", role=Role.OWNER),
        payload={"job_id": "job-1"},
    )

    # Cache dropped → next manifest request rebuilds with the new published set.
    assert ts_manifest._built is False


def test_transition_invokes_invalidate_hook(monkeypatch):
    """The drop goes through ``timestamps.invalidate()`` (the lazy import in
    ``state.transition`` resolves to the same module object we patch here)."""
    _seed_awaiting_timestamps("rec_a")
    calls: list[int] = []
    real = ts_manifest.invalidate
    monkeypatch.setattr(
        ts_manifest, "invalidate", lambda: (calls.append(1), real())[1]
    )

    state_service.transition(
        "rec_a", "reciter.timestamps_completed",
        actor=Actor(hf_user_id="u-O", login_at_time="o", role=Role.OWNER),
        payload={"job_id": "job-1"},
    )

    assert calls == [1]
