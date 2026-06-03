"""Tests for the admin Releases-tab routes.

Covers:
- ``GET /api/admin/releases/status``:
  * a released reciter with a current ledger row is bucketable (lands in
    "Waiting to publish" when there's no HF row yet).
  * inert rows (no TS / HF / GH / not released) are dropped by the
    ``_is_bucketable`` server-side filter — the wire payload only contains
    rows the FE will actually render.
  * eligible vs ineligible channel scoping for the "Excluded" bucket.
  * a slug appearing in ``in_flight`` is bucketable even if it would
    otherwise be inert.
- ``POST /api/admin/publish-hf/<slug>``:
  * 409s when no current ledger row exists (the gate is strict — the
    canonical fix is to backfill the ledger via ``admin_db.py``, not to
    let the route guess from delivery state).

The autouse ``_substrate_db`` fixture gives us a fresh migrated SQLite per
test. ``list_in_flight_jobs`` is mocked to ``[]`` so we don't hit the live
HF Jobs API.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

os.environ.setdefault("INSPECTOR_SESSION_SECRET", "0" * 64)

_HEADERS = {"Content-Type": "application/json", "Origin": "http://localhost"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_jobs_api(monkeypatch, *, in_flight=()):
    """Stub the HF Jobs API so route tests don't hit the network.

    Pass ``in_flight`` as a list of ``{kind, slug, job_id, started_at}`` dicts
    to simulate live jobs (e.g. for the in-flight bucket assertion).
    """
    from services.admin.jobs import base as jobs_base

    monkeypatch.setattr(jobs_base, "list_in_flight_jobs",
                        lambda kinds: list(in_flight))
    monkeypatch.setattr(jobs_base, "running_job_for",
                        lambda **_: None)


def _seed_eligible_channel(slug: str = "mp3quran") -> None:
    """Insert a channel row with ``gh_release_eligible = 1``. Migration 0014
    only flips the flag on rows that exist at migration time; tests INSERT
    after migrations run, so we set it explicitly."""
    from services import db

    with db.transaction() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO channels(slug,short,name,gh_release_eligible) "
            "VALUES (?,?,?,1)",
            (slug, slug[:1], slug),
        )


def _seed_ineligible_channel(slug: str = "private_ch") -> None:
    from services import db

    with db.transaction() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO channels(slug,short,name,gh_release_eligible) "
            "VALUES (?,?,?,0)",
            (slug, slug[:1], slug),
        )


def _seed_delivery_on_channel(slug: str, *, channel: str, reciter_id: str = "r1") -> None:
    """Seed the FK chain for a delivery on a specific channel (the conftest
    helper only knows about ``channel='ch'``)."""
    from services import db

    with db.transaction() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO reciters(reciter_id,name_en,name_ar) "
            "VALUES (?,?,?)",
            (reciter_id, reciter_id.upper(), f"AR-{reciter_id}"),
        )
        conn.execute("INSERT OR IGNORE INTO riwayahs(slug,short,name) VALUES ('hafs','h','Hafs')")
        conn.execute("INSERT OR IGNORE INTO styles(slug,short,name) VALUES ('mur','m','Mur')")
        conn.execute("INSERT OR IGNORE INTO sources(slug,name) VALUES ('src','Src')")
        conn.execute(
            "INSERT OR IGNORE INTO deliveries(slug,reciter_id,riwayah,style,source,channel,"
            "audio_category,chapter_count,added_at,added_by_hf_id) VALUES "
            "(?,?,'hafs','mur','src',?,'by_surah',114,'2026-01-01T00:00:00Z','sys')",
            (slug, reciter_id, channel),
        )


def _seed_released(slug: str, *, channel: str = "mp3quran", reciter_id: str = "r1") -> None:
    """Seed a released-state delivery on an eligible channel."""
    from services import db
    from services.db import repo_state
    from qua_shared.schemas import ReciterState, Visibility

    _seed_eligible_channel(channel)
    _seed_delivery_on_channel(slug, channel=channel, reciter_id=reciter_id)
    with db.transaction():
        repo_state.upsert_state(
            slug,
            state=ReciterState.RELEASED,
            state_since=datetime.now(timezone.utc),
            visibility=Visibility.PUBLIC,
        )


def _seed_ledger_ts(slug: str, version: str = "real-job-id") -> None:
    """Insert a current track='ts' ledger row for ``slug``."""
    from services import db
    from services.db import repo_releases

    with db.transaction():
        repo_releases.insert_per_recitation_release(
            track="ts",
            slug=slug,
            version=version,
            produced_at=datetime.now(timezone.utc),
            produced_by="test",
        )


# ---------------------------------------------------------------------------
# /api/admin/releases/status
# ---------------------------------------------------------------------------


def test_status_released_with_ledger_is_waiting(signed_in_client, monkeypatch):
    """A released-state reciter with a current track='ts' ledger row appears
    in the response — the FE will bucket it as "Waiting to publish" because
    state='released', ts != null, hf == null."""
    client, _user = signed_in_client(role="maintainer")
    _stub_jobs_api(monkeypatch)
    _seed_released("ar.ready_to_publish", channel="mp3quran")
    _seed_ledger_ts("ar.ready_to_publish", version="real-job-id-123")

    resp = client.get("/api/admin/releases/status")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()

    rows = body["recitations"]
    assert len(rows) == 1
    row = rows[0]
    assert row["slug"] == "ar.ready_to_publish"
    assert row["state"] == "released"
    assert row["gh_release_eligible"] is True
    assert row["ts"] == {"version": "real-job-id-123", "produced_at": row["ts"]["produced_at"]}
    assert row["hf"] is None
    assert row["gh"] is None


def test_status_released_without_ledger_is_filtered(signed_in_client, monkeypatch):
    """A released-state row with NO ledger entry is dropped — the ledger
    is the source of truth for TS-existence. The canonical fix for that
    state is a one-shot backfill via ``admin_db.py``, not a route bridge."""
    client, _user = signed_in_client(role="maintainer")
    _stub_jobs_api(monkeypatch)
    _seed_released("ar.no_ledger", channel="mp3quran")
    # No _seed_ledger_ts call — the ledger stays empty.

    resp = client.get("/api/admin/releases/status")
    body = resp.get_json()
    assert body["recitations"] == []


def test_status_inert_rows_filtered(signed_in_client, monkeypatch, seed_state):
    """Rows with no TS, no HF, no GH membership, and not released are
    dropped by ``_is_bucketable`` — they have no business in the Releases
    tab (operator can't do anything with them there)."""
    client, _user = signed_in_client(role="maintainer")
    _stub_jobs_api(monkeypatch)
    _seed_eligible_channel("mp3quran")

    # Released + ledgered → bucketable.
    _seed_released("ar.visible", channel="mp3quran")
    _seed_ledger_ts("ar.visible")
    # Awaiting review — no TS, no HF, no GH — dropped.
    _seed_delivery_on_channel("ar.inert", channel="mp3quran", reciter_id="r2")
    seed_state("ar.inert", state="awaiting_review")

    resp = client.get("/api/admin/releases/status")
    body = resp.get_json()
    slugs = [r["slug"] for r in body["recitations"]]
    assert slugs == ["ar.visible"]


def test_status_excluded_only_for_candidates(signed_in_client, monkeypatch, seed_state):
    """An ineligible channel row only surfaces in the response when it
    would otherwise be a release candidate (released or has TS) — not
    every catalog row from that channel."""
    client, _user = signed_in_client(role="maintainer")
    _stub_jobs_api(monkeypatch)
    _seed_ineligible_channel("private_ch")

    # Ineligible + released → surfaces (excluded bucket).
    _seed_delivery_on_channel("ar.excluded-candidate", channel="private_ch", reciter_id="r3")
    seed_state("ar.excluded-candidate", state="released")
    # Ineligible + awaiting_review → dropped (not a candidate).
    _seed_delivery_on_channel("ar.excluded-inert", channel="private_ch", reciter_id="r4")
    seed_state("ar.excluded-inert", state="awaiting_review")

    resp = client.get("/api/admin/releases/status")
    body = resp.get_json()
    slugs = [r["slug"] for r in body["recitations"]]
    assert slugs == ["ar.excluded-candidate"]
    assert body["recitations"][0]["gh_release_eligible"] is False


def test_status_in_flight_slug_is_bucketable(signed_in_client, monkeypatch):
    """A slug appearing in ``in_flight`` is bucketable even if it would
    otherwise be inert — the operator needs to see the running job."""
    client, _user = signed_in_client(role="maintainer")
    _stub_jobs_api(monkeypatch, in_flight=[{
        "kind": "hf_publish",
        "slug": "ar.in-flight",
        "job_id": "j_abc",
        "started_at": "2026-06-01T12:00:00",
    }])
    _seed_eligible_channel("mp3quran")
    _seed_delivery_on_channel("ar.in-flight", channel="mp3quran", reciter_id="r5")
    # No state, no ledger — inert except for the live job.

    resp = client.get("/api/admin/releases/status")
    body = resp.get_json()
    slugs = [r["slug"] for r in body["recitations"]]
    assert "ar.in-flight" in slugs


# ---------------------------------------------------------------------------
# /api/admin/release-preview
# ---------------------------------------------------------------------------


def test_release_preview_uses_display_names(signed_in_client, monkeypatch):
    """The dry-run preview returns display names (NOT slugs), surah coverage,
    change_kind, and a rendered body from the shared renderer with the title
    line + display names and no slug leakage. Owner-only (release.cut_gh)."""
    client, _user = signed_in_client(role="owner")
    _stub_jobs_api(monkeypatch)
    _seed_released("ar_preview", channel="mp3quran", reciter_id="r1")
    _seed_ledger_ts("ar_preview", version="job-123")

    resp = client.get("/api/admin/release-preview")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()

    assert body["computed_version"] == "v0.1.0"
    assert body["previous_version"] is None
    assert body["change_counts"]["added"] == 1
    assert len(body["added"]) == 1
    row = body["added"][0]
    # Display names from the vocab tables — never the FK slugs.
    assert row["riwayah"] == "Hafs"
    assert row["style"] == "Mur"
    assert row["channel"] == "mp3quran"
    assert row["name_ar"] == "AR-r1"
    assert row["coverage_surahs"] == 114
    assert row["change_kind"] == "added"

    # Top-level additions for the modal.
    assert body["license"] == "CC-BY-4.0"
    assert "repo" in body["links"] and "hf_dataset" in body["links"]
    assert body["release_date"]

    md = body["changelog_preview_md"]
    assert md.startswith("# v0.1.0 · ")
    assert "Hafs" in md and "114 surahs" in md
    # The delivery slug must not leak into the human-facing body.
    assert "ar_preview" not in md


# ---------------------------------------------------------------------------
# /api/admin/publish-hf/<slug>
# ---------------------------------------------------------------------------


def test_publish_hf_accepts_ledgered_slug(signed_in_client, monkeypatch):
    """publish-hf accepts a slug that has a current track='ts' ledger row."""
    client, _user = signed_in_client(role="maintainer")
    _stub_jobs_api(monkeypatch)
    _seed_released("ar_ready", channel="mp3quran")
    _seed_ledger_ts("ar_ready")

    from services.admin.jobs import hf_publish as hf_publish_jobs

    monkeypatch.setattr(
        hf_publish_jobs, "launch",
        lambda slug, webhook_base=None: {"job_id": "j_test", "url": None},
    )

    resp = client.post("/api/admin/publish-hf/ar_ready", headers=_HEADERS)
    assert resp.status_code == 202, resp.get_data(as_text=True)


def test_publish_hf_rejects_no_ledger(signed_in_client, monkeypatch, seed_state):
    """Without a ledger row publish-hf 409s — the ledger is the source of
    truth for TS-existence. Released-state alone is not sufficient (backfill
    the ledger via admin_db.py for legacy slugs)."""
    client, _user = signed_in_client(role="maintainer")
    _stub_jobs_api(monkeypatch)
    _seed_eligible_channel("mp3quran")
    _seed_delivery_on_channel("ar_no_ledger", channel="mp3quran", reciter_id="r6")
    seed_state("ar_no_ledger", state="released")

    resp = client.post("/api/admin/publish-hf/ar_no_ledger", headers=_HEADERS)
    assert resp.status_code == 409
    assert "has no current TS release" in resp.get_json()["error"]
