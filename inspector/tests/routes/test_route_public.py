"""HTTP boundary tests for ``/api/public/*`` endpoints."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timezone


def _state_row(
    slug: str,
    *,
    state: str = "awaiting_review",
    marked_ready: bool = False,
    assignee_hf_id: str | None = None,
    visibility: str = "public",
):
    from qua_shared.schemas import ReciterRow, ReciterState, Visibility

    return ReciterRow(
        slug=slug,
        state=ReciterState(state),
        state_since=datetime(2026, 5, 12, tzinfo=UTC),
        assignee_hf_id=assignee_hf_id,
        assignee_login="alice" if assignee_hf_id else None,
        assignee_since=datetime(2026, 5, 12, tzinfo=UTC) if assignee_hf_id else None,
        marked_ready=marked_ready,
        visibility=Visibility(visibility),
    )


def _delivery(
    slug: str,
    *,
    reciter_id: str,
    riwayah: str = "hafs_an_asim",
    style: str = "murattal",
    source: str = "mp3quran",
    channel: str = "mp3quran",
    chapter_count: int = 114,
):
    from qua_shared.schemas import AudioCategory, Delivery

    return Delivery(
        slug=slug,
        reciter_id=reciter_id,
        riwayah=riwayah,
        style=style,
        source=source,
        channel=channel,
        audio_category=AudioCategory.BY_SURAH,
        chapter_count=chapter_count,
        added_at=datetime(2026, 1, 1, tzinfo=UTC),
        added_by_hf_id="system_seed",
    )


def _reciter(reciter_id: str, name_en: str):
    from qua_shared.schemas import ReciterEntry

    return ReciterEntry(reciter_id=reciter_id, name_en=name_en)


def _install(reciters, deliveries, rows):
    """Seed the supplied catalog + state fixtures into the SQLite substrate."""
    from qua_shared.schemas import (
        AudioCategory,
        Channel,
        Riwayah,
        Source,
        Style,
        Vocab,
    )
    from services import db
    from services.db import repo_catalog

    vocab = Vocab(
        riwayat=[Riwayah(slug="hafs_an_asim", short="hafs", name="Hafs")],
        styles=[Style(slug="murattal", short="murattal", name="Murattal")],
        sources=[
            Source(
                slug="mp3quran",
                name="mp3quran",
                url="https://mp3quran.net",
                audio_categories=[AudioCategory.BY_SURAH],
            ),
        ],
        channels=[
            Channel(slug="mp3quran", short="mp3q", name="mp3quran", host_patterns=["mp3quran.net"]),
        ],
        recording_contexts=[],
    )
    with db.transaction():
        repo_catalog.load_vocab(vocab)
        for r in reciters:
            repo_catalog.insert_reciter(r)
        for d in deliveries:
            repo_catalog.insert_delivery(d)

    # State rows: seed delivery_states (+ synthesized claim) per ReciterRow.
    from tests.conftest import _seed_state

    for row in rows:
        _seed_state(
            row.slug,
            state=row.state.value,
            state_since=row.state_since,
            visibility=row.visibility.value,
            visibility_reason=row.visibility_reason,
            assignee_hf_id=row.assignee_hf_id,
            assignee_login=row.assignee_login or "test_user",
            marked_ready=row.marked_ready,
        )


# ---------------------------------------------------------------------------
# /api/public/stats
# ---------------------------------------------------------------------------


def test_stats_returns_five_bucket_counts(flask_client):
    _install(
        reciters=[
            _reciter("husary", "Husary"),
            _reciter("afasy", "Afasy"),
        ],
        deliveries=[
            _delivery("husary_qdc", reciter_id="husary"),
            _delivery("afasy_qdc", reciter_id="afasy"),
        ],
        rows=[
            _state_row("husary_qdc", state="released"),
            # afasy_qdc has no state row → available_for_request
        ],
    )

    resp = flask_client.get("/api/public/stats")
    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body["published"] == 1
    assert body["available_for_request"] == 1
    # Every public bucket key is present, even if count is 0.
    for key in (
        "available_for_request",
        "requested",
        "available_for_review",
        "under_review",
        "published",
    ):
        assert key in body


def test_stats_sets_cache_control(flask_client):
    # no-store: stats reflect live lifecycle state (bucket counts shift on
    # every claim/transition); a client max-age served stale counts.
    _install(reciters=[], deliveries=[], rows=[])
    resp = flask_client.get("/api/public/stats")
    assert "no-store" in resp.headers["Cache-Control"]


# ---------------------------------------------------------------------------
# /api/public/version
# ---------------------------------------------------------------------------


def test_version_returns_db_seq_with_no_store(flask_client):
    _install(reciters=[], deliveries=[], rows=[])
    resp = flask_client.get("/api/public/version")
    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert isinstance(body["db_seq"], int)
    assert "no-store" in resp.headers["Cache-Control"]


def test_version_increments_after_committed_write(flask_client):
    # The dashboard poll gates its roster refetch on this counter, so a
    # committed write must move it — otherwise the catalog would never refresh.
    from services import db

    _install(reciters=[], deliveries=[], rows=[])
    before = json.loads(flask_client.get("/api/public/version").data)["db_seq"]
    with db.transaction():
        pass  # an empty committed txn still bumps db_seq
    after = json.loads(flask_client.get("/api/public/version").data)["db_seq"]
    assert after > before


# ---------------------------------------------------------------------------
# /api/public/reciters
# ---------------------------------------------------------------------------


def test_reciters_returns_list_with_total_and_next_cursor(flask_client):
    _install(
        reciters=[_reciter("husary", "Husary"), _reciter("afasy", "Afasy")],
        deliveries=[
            _delivery("husary_qdc", reciter_id="husary"),
            _delivery("afasy_qdc", reciter_id="afasy"),
        ],
        rows=[],
    )
    resp = flask_client.get("/api/public/reciters?limit=10")
    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body["total"] == 2
    assert body["next_cursor"] is None
    assert len(body["reciters"]) == 2


def test_reciters_pagination_emits_next_cursor(flask_client):
    _install(
        reciters=[
            _reciter("aaa", "Aaa"),
            _reciter("bbb", "Bbb"),
            _reciter("ccc", "Ccc"),
        ],
        deliveries=[
            _delivery("aaa_qdc", reciter_id="aaa"),
            _delivery("bbb_qdc", reciter_id="bbb"),
            _delivery("ccc_qdc", reciter_id="ccc"),
        ],
        rows=[],
    )
    resp = flask_client.get("/api/public/reciters?limit=2")
    body = json.loads(resp.data)
    assert body["total"] == 3
    assert body["next_cursor"] == 2
    assert len(body["reciters"]) == 2


def test_reciters_bucket_filter(flask_client):
    _install(
        reciters=[_reciter("husary", "Husary"), _reciter("afasy", "Afasy")],
        deliveries=[
            _delivery("husary_qdc", reciter_id="husary"),
            _delivery("afasy_qdc", reciter_id="afasy"),
        ],
        rows=[_state_row("husary_qdc", state="released")],
    )
    resp = flask_client.get("/api/public/reciters?bucket=published")
    body = json.loads(resp.data)
    assert body["total"] == 1
    assert body["reciters"][0]["name"] == "Husary"


def test_reciters_search_matches_arabic_normalized(flask_client):
    _install(
        reciters=[
            _reciter("husary", "Mahmoud Khalil Al-Husary"),
            _reciter("afasy", "Mishary Rashid Al-Afasy"),
        ],
        deliveries=[
            _delivery("husary_qdc", reciter_id="husary"),
            _delivery("afasy_qdc", reciter_id="afasy"),
        ],
        rows=[],
    )
    resp = flask_client.get("/api/public/reciters?search=Husary")
    body = json.loads(resp.data)
    assert body["total"] == 1
    assert body["reciters"][0]["name"] == "Mahmoud Khalil Al-Husary"


def test_reciters_response_never_includes_assignee_fields(flask_client):
    _install(
        reciters=[_reciter("husary", "Husary")],
        deliveries=[_delivery("husary_qdc", reciter_id="husary")],
        rows=[
            _state_row(
                "husary_qdc",
                state="under_review",
                assignee_hf_id="should-be-redacted",
            ),
        ],
    )
    resp = flask_client.get("/api/public/reciters")
    text = resp.data.decode()
    assert "assignee_hf_id" not in text
    assert "assignee_login" not in text
    assert "should-be-redacted" not in text


def test_reciters_invalid_bucket_returns_400(flask_client):
    _install(reciters=[], deliveries=[], rows=[])
    resp = flask_client.get("/api/public/reciters?bucket=bogus")
    assert resp.status_code == 400


def test_reciters_invalid_sort_returns_400(flask_client):
    _install(reciters=[], deliveries=[], rows=[])
    resp = flask_client.get("/api/public/reciters?sort=nope")
    assert resp.status_code == 400


def test_reciters_limit_out_of_range_returns_400(flask_client):
    _install(reciters=[], deliveries=[], rows=[])
    assert flask_client.get("/api/public/reciters?limit=0").status_code == 400
    assert flask_client.get("/api/public/reciters?limit=9999").status_code == 400


def test_reciter_detail_returns_payload(flask_client):
    _install(
        reciters=[_reciter("husary", "Husary")],
        deliveries=[_delivery("husary_qdc", reciter_id="husary")],
        rows=[_state_row("husary_qdc", state="released")],
    )
    resp = flask_client.get("/api/public/reciter/husary")
    assert resp.status_code == 200
    body = json.loads(resp.data)
    assert body["name"] == "Husary"
    assert body["primary_bucket"] == "published"
    # no-store: detail folds in per-delivery lifecycle state that changes on
    # claim/transition; a client max-age made the modal stale.
    assert "no-store" in resp.headers["Cache-Control"]


def test_reciter_detail_404_on_unknown(flask_client):
    _install(reciters=[], deliveries=[], rows=[])
    resp = flask_client.get("/api/public/reciter/no-such-reciter")
    assert resp.status_code == 404


def test_reciter_detail_omits_assignee_fields(flask_client):
    _install(
        reciters=[_reciter("husary", "Husary")],
        deliveries=[_delivery("husary_qdc", reciter_id="husary")],
        rows=[
            _state_row(
                "husary_qdc",
                state="under_review",
                assignee_hf_id="should-be-redacted",
            ),
        ],
    )
    resp = flask_client.get("/api/public/reciter/husary")
    text = resp.data.decode()
    assert "assignee_hf_id" not in text
    assert "should-be-redacted" not in text


def test_reciters_sort_alphabetical(flask_client):
    _install(
        reciters=[
            _reciter("zaa", "Zaa"),
            _reciter("aaa", "Aaa"),
            _reciter("mmm", "Mmm"),
        ],
        deliveries=[
            _delivery("zaa_qdc", reciter_id="zaa"),
            _delivery("aaa_qdc", reciter_id="aaa"),
            _delivery("mmm_qdc", reciter_id="mmm"),
        ],
        rows=[],
    )
    resp = flask_client.get("/api/public/reciters?sort=alphabetical")
    body = json.loads(resp.data)
    names = [r["name"] for r in body["reciters"]]
    assert names == ["Aaa", "Mmm", "Zaa"]
