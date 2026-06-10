"""Phase-5 regression net: ``qua_shared.schemas.wire.public`` models validate
the live ``/api/public/*`` route responses byte-for-byte.

Each test seeds a catalog + state fixture into the SQLite substrate, hits the
real route via the Flask test client, then asserts:

1. ``Model.model_validate(response.json)`` succeeds (the model accepts what the
   route emits, and ``extra="forbid"`` proves there are no unmodeled keys).
2. ``model_dump(by_alias=True)`` (nulls kept — the wire carries present-with-null
   fields like ``next_cursor`` / ``state_since``) reproduces the response. On the
   cached list path the two modal-only delivery keys are absent, so they are
   stripped from the dump before comparison; the modal (detail / admin-view)
   paths attach them and compare byte-for-byte.

When Phase 5 reroutes the producers through these models, this net catches any
shape drift. See ``inspector/services/reference/public_state.py`` (the producer)
and ``inspector/routes/public/public.py`` (the routes).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from qua_shared.schemas import (
    AdminViewReciter,
    BucketCounts,
    PublicReciter,
    PublicReciterPage,
)

# Delivery fields the route omits entirely on the cached list path (attached
# only by the modal detail / admin-view paths via ``_attach_bucket_dates``).
# Everything else is always emitted (present-with-null), so the model
# reproduces the wire by dumping with nulls KEPT and only these two excluded
# when absent.
_MODAL_ONLY_DELIVERY_KEYS = {"bucket_dates", "ts_refresh_dates"}


def _strip_modal_keys(delivery: dict) -> dict:
    """Drop the modal-only delivery keys from a model dump for list-path compare."""
    return {k: v for k, v in delivery.items() if k not in _MODAL_ONLY_DELIVERY_KEYS}


# ---------------------------------------------------------------------------
# seeding helpers (mirror inspector/tests/routes/test_route_public.py)
# ---------------------------------------------------------------------------


def _reciter(reciter_id: str, name_en: str, **kw):
    from qua_shared.schemas import ReciterEntry

    return ReciterEntry(reciter_id=reciter_id, name_en=name_en, **kw)


def _delivery(
    slug: str,
    *,
    reciter_id: str,
    riwayah: str = "hafs_an_asim",
    style: str = "murattal",
    source: str = "mp3quran",
    channel: str = "mp3quran",
    chapter_count: int = 114,
    recording_context: str | None = None,
    recording_year: int | None = None,
    source_url: str | None = None,
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
        recording_context=recording_context,
        recording_year=recording_year,
        source_url=source_url,
        added_at=datetime(2026, 1, 1, tzinfo=UTC),
        added_by_hf_id="system_seed",
    )


def _install(reciters, deliveries, rows):
    """Seed catalog (vocab + reciters + deliveries) + state rows into SQLite."""
    from qua_shared.schemas import (
        Channel,
        RecordingContext,
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
                audio_categories=["by_surah"],
            ),
        ],
        channels=[
            Channel(
                slug="mp3quran", short="mp3q", name="MP3 Quran", host_patterns=["mp3quran.net"]
            ),
        ],
        recording_contexts=[RecordingContext(slug="studio", name="Studio")],
    )
    with db.transaction():
        repo_catalog.load_vocab(vocab)
        for r in reciters:
            repo_catalog.insert_reciter(r)
        for d in deliveries:
            repo_catalog.insert_delivery(d)

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


def _state_row(slug: str, *, state: str = "released", visibility: str = "public"):
    from qua_shared.schemas import ReciterRow, ReciterState, Visibility

    return ReciterRow(
        slug=slug,
        state=ReciterState(state),
        state_since=datetime(2026, 5, 12, tzinfo=UTC),
        visibility=Visibility(visibility),
        visibility_reason="hidden" if visibility == "discarded" else None,
    )


# ---------------------------------------------------------------------------
# /api/public/stats  →  BucketCounts
# ---------------------------------------------------------------------------


def test_bucket_counts_model_validates_stats_response(flask_client):
    _install(
        reciters=[_reciter("husary", "Husary"), _reciter("afasy", "Afasy")],
        deliveries=[
            _delivery("husary_qdc", reciter_id="husary"),
            _delivery("afasy_qdc", reciter_id="afasy"),
        ],
        rows=[_state_row("husary_qdc", state="released")],
    )

    resp = flask_client.get("/api/public/stats")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = json.loads(resp.data)

    model = BucketCounts.model_validate(body)
    assert model.model_dump() == body
    # Every public bucket key present; counts sum to the public reciter total.
    assert set(body.keys()) == {
        "available_for_request",
        "requested",
        "available_for_review",
        "under_review",
        "published",
    }
    assert body["published"] == 1
    assert body["available_for_request"] == 1


# ---------------------------------------------------------------------------
# /api/public/reciters  →  PublicReciterPage  (list path — no modal extras)
# ---------------------------------------------------------------------------


def test_public_reciter_page_model_validates_reciters_response(flask_client):
    _install(
        reciters=[_reciter("husary", "Husary", name_ar="الحصري", country="EG")],
        deliveries=[
            _delivery(
                "husary_qdc",
                reciter_id="husary",
                recording_context="studio",
                recording_year=1970,
                source_url="https://mp3quran.net/husary",
            ),
        ],
        rows=[_state_row("husary_qdc", state="released")],
    )

    resp = flask_client.get("/api/public/reciters?limit=10")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = json.loads(resp.data)

    model = PublicReciterPage.model_validate(body)
    # Keep nulls (next_cursor / state_since / name_ar / … are present-with-null
    # on the wire); the modal-only delivery keys are absent on the list path, so
    # strip them from the dump before comparing values.
    dumped = model.model_dump(by_alias=True)
    for reciter in dumped["reciters"]:
        reciter["deliveries"] = [_strip_modal_keys(d) for d in reciter["deliveries"]]
    assert dumped == body

    # The list delivery payload must NOT carry the modal-only keys.
    delivery_keys = set(body["reciters"][0]["deliveries"][0].keys())
    assert "bucket_dates" not in delivery_keys
    assert "ts_refresh_dates" not in delivery_keys
    # next_cursor is present-with-null on the last page, not omitted.
    assert "next_cursor" in body and body["next_cursor"] is None


def test_public_reciter_page_next_cursor_is_int_on_pagination(flask_client):
    _install(
        reciters=[_reciter("aaa", "Aaa"), _reciter("bbb", "Bbb"), _reciter("ccc", "Ccc")],
        deliveries=[
            _delivery("aaa_qdc", reciter_id="aaa"),
            _delivery("bbb_qdc", reciter_id="bbb"),
            _delivery("ccc_qdc", reciter_id="ccc"),
        ],
        rows=[],
    )
    resp = flask_client.get("/api/public/reciters?limit=2")
    body = json.loads(resp.data)
    model = PublicReciterPage.model_validate(body)
    assert model.next_cursor == 2
    assert model.total == 3


# ---------------------------------------------------------------------------
# /api/public/reciter/<id>  →  PublicReciter  (detail path — modal extras present)
# ---------------------------------------------------------------------------


def test_public_reciter_model_validates_detail_response(flask_client):
    _install(
        reciters=[_reciter("husary", "Husary")],
        deliveries=[_delivery("husary_qdc", reciter_id="husary")],
        rows=[_state_row("husary_qdc", state="released")],
    )

    resp = flask_client.get("/api/public/reciter/husary")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = json.loads(resp.data)

    # Detail path attaches the modal-only keys (real dict/list values) to each
    # delivery, so the full by_alias dump reproduces the wire byte-for-byte.
    model = PublicReciter.model_validate(body)
    assert model.model_dump(by_alias=True) == body

    delivery = body["deliveries"][0]
    assert "bucket_dates" in delivery
    assert "ts_refresh_dates" in delivery


# ---------------------------------------------------------------------------
# /api/public/reciter/<id> (maintainer caller)  →  AdminViewReciter
# ---------------------------------------------------------------------------


def test_admin_view_reciter_model_validates_admin_detail_response(signed_in_client):
    client, _ = signed_in_client(role="maintainer", hf_user_id="maint-1", login="maint")
    _install(
        reciters=[_reciter("husary", "Husary")],
        deliveries=[
            _delivery("husary_public", reciter_id="husary"),
            _delivery("husary_hidden", reciter_id="husary", channel="mp3quran"),
        ],
        rows=[
            _state_row("husary_public", state="released"),
            _state_row("husary_hidden", state="awaiting_review", visibility="discarded"),
        ],
    )

    resp = client.get("/api/public/reciter/husary")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = json.loads(resp.data)

    # Admin shape carries discarded_deliveries + fully_discarded.
    assert "discarded_deliveries" in body
    assert "fully_discarded" in body
    assert len(body["discarded_deliveries"]) == 1

    # Admin view attaches the modal-only keys to BOTH public and discarded
    # deliveries, so the full by_alias dump reproduces the wire byte-for-byte.
    model = AdminViewReciter.model_validate(body)
    assert model.model_dump(by_alias=True) == body

    discarded = body["discarded_deliveries"][0]
    assert discarded["visibility"] == "discarded"


def test_admin_view_fully_discarded_returns_200_with_empty_deliveries(signed_in_client):
    client, _ = signed_in_client(role="maintainer", hf_user_id="maint-2", login="maint2")
    _install(
        reciters=[_reciter("ghost", "Ghost")],
        deliveries=[_delivery("ghost_qdc", reciter_id="ghost")],
        rows=[_state_row("ghost_qdc", state="awaiting_review", visibility="discarded")],
    )

    resp = client.get("/api/public/reciter/ghost")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = json.loads(resp.data)

    model = AdminViewReciter.model_validate(body)
    assert model.fully_discarded is True
    assert model.deliveries == []
    assert model.model_dump(by_alias=True) == body
