"""Tests for the intake-ingest service (services/admin/intake.py::ingest).

Exercises the full mint+seed+backfill in ONE durable transaction against a
FilesystemBackend + the autouse sqlite substrate, plus the e2e handoff: after
ingest seeds AWAITING_ALIGNMENT and content lands under reciters/<slug>/,
auto_detect.reconcile_once flips it to AWAITING_REVIEW (the same path
existing_combo_edit uses).
"""

from __future__ import annotations

import pytest

from scripts.lib.schemas import (
    Actor,
    Channel,
    ReciterEntry,
    ReciterState,
    Role,
    Riwayah,
    Source,
    Style,
    Vocab,
)
from services import catalog as catalog_service
from services import state as state_service
from services import storage_paths
from services.admin import intake as intake_service
from services.db import repo_catalog, repo_requests
from services.storage.hf_bucket import get_backend


OWNER = Actor(hf_user_id="owner-1", login_at_time="owneruser", role=Role.OWNER)


@pytest.fixture
def fs_backend(tmp_path, monkeypatch):
    """Per-test FilesystemBackend + base vocab/reciter so a new-combo ingest's
    FKs resolve. The autouse ``_substrate_db`` fixture owns the SQLite DB."""
    from services import db
    from services import hf_bucket as _hf_bucket

    monkeypatch.setenv("INSPECTOR_BACKEND", "filesystem")
    monkeypatch.setenv("INSPECTOR_FILESYSTEM_ROOT", str(tmp_path))
    backend = _hf_bucket.FilesystemBackend(tmp_path)
    _hf_bucket.set_backend(backend)

    vocab = Vocab(
        riwayat=[Riwayah(slug="hafs", short="H", name="Hafs")],
        styles=[Style(slug="murattal", short="M", name="Murattal")],
        sources=[Source(slug="src1", name="Source One")],
        channels=[Channel(slug="ch1", short="c1", name="Channel One")],
    )
    with db.transaction():
        repo_catalog.load_vocab(vocab)
        repo_catalog.insert_reciter(ReciterEntry(reciter_id="rec_x", name_en="Reciter X"))

    yield backend
    _hf_bucket.reset_backend()


def _seed_accepted_intake(*, kind: str, reciter_id: str | None) -> str:
    """Insert an accepted slugless intake request (slug=NULL) and return its id."""
    from services import db

    requester = Actor(hf_user_id="u-1", login_at_time="alice", role=Role.CONTRIBUTOR)
    extra = {"reciter_id": reciter_id, "source": {"method": "links", "links": []}}
    with db.transaction():
        rid = repo_requests.submit(
            slug=None, requester=requester, kind=kind, extra_payload=extra,
        )
        repo_requests.resolve_by_id(
            request_id=rid, status="accepted", transitioned_by=OWNER,
        )
    return rid


def _delivery_block(slug: str, reciter_id: str, source="src1", channel="ch1") -> dict:
    return {
        "slug": slug, "reciter_id": reciter_id, "riwayah": "hafs",
        "style": "murattal", "source": source, "channel": channel,
        "audio_category": "by_surah", "recording_year": None,
        "recording_context": None,
    }


def _manifest_block(n=3) -> dict:
    return {
        "chapters": {
            str(c): {
                "url": f"https://cdn.example/{c:03d}.mp3",
                "bitrate_kbps": 128, "bitrate_mode": "cbr",
                "duration_sec": 60.4, "size_bytes": 1000 * c,
            }
            for c in range(1, n + 1)
        }
    }


# ---------------------------------------------------------------------------
# Existing-reciter-new-combo
# ---------------------------------------------------------------------------


def test_ingest_new_combo_mints_seeds_and_backfills(fs_backend):
    rid = _seed_accepted_intake(kind="existing_reciter_new_combo", reciter_id="rec_x")

    body = {
        "reciter": None,
        "delivery": _delivery_block("rec_x_hafs_ch1", "rec_x"),
        "vocab_additions": None,
        "audio_manifest": _manifest_block(3),
        "reason": "ingest test",
    }
    result = intake_service.ingest(rid, body, actor=OWNER)

    assert result == {"ok": True, "slug": "rec_x_hafs_ch1", "state": "awaiting_alignment"}

    # Delivery minted with chapter_count derived from the manifest.
    d = catalog_service.find_delivery("rec_x_hafs_ch1")
    assert d is not None
    assert d.reciter_id == "rec_x" and d.chapter_count == 3
    assert d.added_by_hf_id == "owner-1"

    # audio_manifest sidecar written with the chapter map audio_meta reads.
    manifest = get_backend().read_json(storage_paths.audio_manifest_path("rec_x_hafs_ch1"))
    assert manifest["chapters"]["1"]["url"] == "https://cdn.example/001.mp3"
    assert manifest["_meta"]["chapter_count"] == 3

    # State seeded into AWAITING_ALIGNMENT (+ pending entry from reciter.requested).
    row = state_service.get_row("rec_x_hafs_ch1")
    assert row is not None and row.state == ReciterState.AWAITING_ALIGNMENT

    # requests.slug back-filled on the intake row.
    accepted = repo_requests.get_by_id(rid)
    assert accepted["status"] == "accepted" and accepted["slug"] == "rec_x_hafs_ch1"


# ---------------------------------------------------------------------------
# New reciter + vocab additions
# ---------------------------------------------------------------------------


def test_ingest_new_reciter_creates_reciter_and_vocab(fs_backend):
    rid = _seed_accepted_intake(kind="new_reciter", reciter_id="new_guy")

    body = {
        "reciter": {"reciter_id": "new_guy", "name_en": "New Guy",
                    "name_ar": "جديد", "country": "SA"},
        "delivery": _delivery_block("new_guy_hafs_yt", "new_guy",
                                    source="youtube", channel="ytchan"),
        "vocab_additions": {
            "sources": [{"slug": "youtube", "name": "YouTube"}],
            "channels": [{"slug": "ytchan", "name": "YT Channel",
                          "short": "yt", "host_patterns": ["youtube.com"]}],
        },
        "audio_manifest": _manifest_block(2),
        "reason": None,
    }
    result = intake_service.ingest(rid, body, actor=OWNER)
    assert result["ok"] and result["slug"] == "new_guy_hafs_yt"

    # New reciter created.
    r = catalog_service.find_reciter("new_guy")
    assert r is not None and r.name_en == "New Guy" and r.country == "SA"

    # Vocab additions applied → delivery FK satisfied.
    assert repo_catalog.find_source("youtube") is not None
    assert repo_catalog.find_channel("ytchan") is not None
    d = catalog_service.find_delivery("new_guy_hafs_yt")
    assert d is not None and d.source == "youtube" and d.channel == "ytchan"


# ---------------------------------------------------------------------------
# Idempotency + error paths
# ---------------------------------------------------------------------------


def test_ingest_is_idempotent_when_slug_already_set(fs_backend):
    rid = _seed_accepted_intake(kind="existing_reciter_new_combo", reciter_id="rec_x")
    body = {
        "reciter": None,
        "delivery": _delivery_block("rec_x_hafs_ch1", "rec_x"),
        "vocab_additions": None,
        "audio_manifest": _manifest_block(1),
        "reason": None,
    }
    first = intake_service.ingest(rid, body, actor=OWNER)
    # Second call: request.slug is now set → no-op returning the existing slug.
    second = intake_service.ingest(rid, body, actor=OWNER)
    assert second["ok"] and second["slug"] == first["slug"]
    assert second["slug"] == "rec_x_hafs_ch1"


def test_ingest_rejects_non_accepted_request(fs_backend):
    from services import db

    requester = Actor(hf_user_id="u-1", login_at_time="alice", role=Role.CONTRIBUTOR)
    with db.transaction():
        rid = repo_requests.submit(
            slug=None, requester=requester, kind="new_reciter",
            extra_payload={"reciter_id": "x", "source": {"method": "links", "links": []}},
        )
    # Still pending → not an accepted intake.
    with pytest.raises(intake_service.IngestBadRequest):
        intake_service.ingest(rid, {
            "delivery": _delivery_block("x_hafs_ch1", "rec_x"),
            "audio_manifest": _manifest_block(1),
        }, actor=OWNER)


def test_ingest_unknown_request_raises_not_intake(fs_backend):
    with pytest.raises(intake_service.NotIntakeRequest):
        intake_service.ingest("rq_doesnotexist", {
            "delivery": _delivery_block("a_b_c", "rec_x"),
            "audio_manifest": _manifest_block(1),
        }, actor=OWNER)


def test_ingest_slug_collision_raises(fs_backend):
    # Pre-create a delivery so the ingest slug collides.
    from services import db

    from scripts.lib.schemas import AudioCategory, Delivery
    from datetime import datetime, timezone
    with db.transaction():
        repo_catalog.insert_delivery(Delivery(
            slug="rec_x_hafs_ch1", reciter_id="rec_x", riwayah="hafs", style="murattal",
            source="src1", channel="ch1", audio_category=AudioCategory.BY_SURAH,
            chapter_count=114, added_at=datetime.now(timezone.utc), added_by_hf_id="seed",
        ))

    rid = _seed_accepted_intake(kind="existing_reciter_new_combo", reciter_id="rec_x")
    with pytest.raises(intake_service.IngestSlugCollision):
        intake_service.ingest(rid, {
            "delivery": _delivery_block("rec_x_hafs_ch1", "rec_x"),
            "audio_manifest": _manifest_block(1),
        }, actor=OWNER)


def test_ingest_missing_vocab_fk_raises_vocab_missing(fs_backend):
    """A delivery whose source/channel aren't in vocab and aren't supplied via
    vocab_additions → 422 IngestVocabMissing."""
    rid = _seed_accepted_intake(kind="existing_reciter_new_combo", reciter_id="rec_x")
    with pytest.raises(intake_service.IngestVocabMissing):
        intake_service.ingest(rid, {
            "delivery": _delivery_block("rec_x_hafs_zzz", "rec_x",
                                        source="ghost", channel="ghost"),
            "vocab_additions": None,
            "audio_manifest": _manifest_block(1),
        }, actor=OWNER)


def test_ingest_bad_body_raises_bad_request(fs_backend):
    rid = _seed_accepted_intake(kind="existing_reciter_new_combo", reciter_id="rec_x")
    with pytest.raises(intake_service.IngestBadRequest):
        intake_service.ingest(rid, {"delivery": None, "audio_manifest": None}, actor=OWNER)


# ---------------------------------------------------------------------------
# E2E: ingest → content lands → auto_detect flips to AWAITING_REVIEW
# ---------------------------------------------------------------------------


def test_ingest_then_autodetect_flips_to_awaiting_review(fs_backend):
    from services.segments import auto_detect

    rid = _seed_accepted_intake(kind="existing_reciter_new_combo", reciter_id="rec_x")
    slug = "rec_x_hafs_ch1"
    intake_service.ingest(rid, {
        "reciter": None,
        "delivery": _delivery_block(slug, "rec_x"),
        "vocab_additions": None,
        "audio_manifest": _manifest_block(2),
    }, actor=OWNER)

    assert state_service.get_row(slug).state == ReciterState.AWAITING_ALIGNMENT

    # The offline pipeline uploads content under reciters/<slug>/.
    fs_backend.write_json_atomic(
        storage_paths.detailed_path(slug), {"_meta": {}, "entries": []},
    )

    # Reset the process-local seen set so the freshly-appeared folder is "new".
    auto_detect._reset_seen_for_tests()
    fired = auto_detect.reconcile_once()
    assert fired == 1
    assert state_service.get_row(slug).state == ReciterState.AWAITING_REVIEW
