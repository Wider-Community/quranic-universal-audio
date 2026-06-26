"""Tests for the stale-while-revalidate read mode of ``list_in_flight_jobs``.

The user-facing releases-status route reads with ``block=False``: a cache miss
must NOT block on the rate-limited HF ``list_jobs()`` network call — it serves
the last-known value (or ``[]``) immediately and refreshes in the background.
The automation reconciler keeps ``block=True`` (synchronous, accurate). Both
paths share ``_fetch_in_flight``, which is the only seam stubbed here so the
cache + threading behaviour is exercised for real.
"""

from __future__ import annotations

import threading

import pytest

from services.admin.jobs import base
from services.storage import cache


@pytest.fixture(autouse=True)
def _clear_inflight():
    cache.invalidate_in_flight_jobs_cache()
    base._inflight_refreshing.clear()
    yield
    cache.invalidate_in_flight_jobs_cache()
    base._inflight_refreshing.clear()


def _row(kind: str, job_id: str) -> dict:
    return {"kind": kind, "slug": None, "job_id": job_id, "started_at": None, "url": None}


def test_block_false_serves_empty_then_refreshes_in_background(monkeypatch):
    """Cold cache + ``block=False`` returns ``[]`` immediately; the background
    refresh populates the cache so the next read serves the fresh value.

    The fake fetch is gated on ``release`` to stand in for the slow real network
    call — so the immediate-return assertion can't race a too-fast background
    thread that would otherwise populate the cache before the main read."""
    kinds = ("hf_publish",)
    release = threading.Event()
    done = threading.Event()

    def fake_fetch(k):
        release.wait(timeout=2.0)
        cache.set_in_flight_jobs_cache(k, [_row(k[0], "bg")])
        done.set()
        return [_row(k[0], "bg")]

    monkeypatch.setattr(base, "_fetch_in_flight", fake_fetch)

    # Cold read returns immediately — the fetch is still blocked on ``release``.
    assert base.list_in_flight_jobs(kinds, block=False) == []
    # Let the deduped background refresh complete and cache the live result.
    release.set()
    assert done.wait(timeout=2.0)
    assert cache.get_in_flight_jobs_cache(kinds) == [_row("hf_publish", "bg")]
    # A subsequent SWR read now serves the fresh cached value.
    assert base.list_in_flight_jobs(kinds, block=False) == [_row("hf_publish", "bg")]


def test_block_false_serves_last_known_stale_value(monkeypatch):
    """When a prior value is cached but the TTL has lapsed, ``block=False``
    returns that stale value (not ``[]``) while refreshing in the background."""
    kinds = ("cut_release",)
    # Seed a value, then force-expire it by rewinding the stamp past the TTL.
    cache.set_in_flight_jobs_cache(kinds, [_row("cut_release", "old")])
    assert cache._jobs_in_flight is not None
    stamped_at, cached_kinds, value = cache._jobs_in_flight
    cache._jobs_in_flight = (stamped_at - cache._JOBS_IN_FLIGHT_TTL_S - 1.0, cached_kinds, value)

    monkeypatch.setattr(base, "_fetch_in_flight", lambda _k: [])  # bg no-op

    assert base.list_in_flight_jobs(kinds, block=False) == [_row("cut_release", "old")]


def test_block_true_fetches_synchronously(monkeypatch):
    """The reconciler path does the network fetch inline on a cache miss."""
    kinds = ("timestamps",)
    calls = {"n": 0}

    def fake_fetch(k):
        calls["n"] += 1
        out = [_row(k[0], "sync")]
        cache.set_in_flight_jobs_cache(k, out)
        return out

    monkeypatch.setattr(base, "_fetch_in_flight", fake_fetch)

    out = base.list_in_flight_jobs(kinds, block=True)
    assert calls["n"] == 1
    assert out == [_row("timestamps", "sync")]


def test_fresh_cache_hit_skips_fetch_in_both_modes(monkeypatch):
    """A within-TTL cached value short-circuits before any fetch, either mode."""
    kinds = ("refresh_catalog",)
    cache.set_in_flight_jobs_cache(kinds, [_row("refresh_catalog", "warm")])

    def _boom(_k):
        raise AssertionError("must not fetch on a fresh cache hit")

    monkeypatch.setattr(base, "_fetch_in_flight", _boom)

    assert base.list_in_flight_jobs(kinds, block=False) == [_row("refresh_catalog", "warm")]
    assert base.list_in_flight_jobs(kinds, block=True) == [_row("refresh_catalog", "warm")]
