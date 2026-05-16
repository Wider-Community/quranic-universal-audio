"""Unit tests for ``services/public_state``.

Exercises the pure mapping bits — bucket derivation, coverage rollup,
assignee redaction — without touching Flask.
"""

from __future__ import annotations

from datetime import datetime, timezone


def _state_row(slug: str, *, state: str = "awaiting_review",
               marked_ready: bool = False,
               assignee_hf_id: str | None = None,
               visibility: str = "public"):
    from scripts.lib.schemas import ReciterRow, ReciterState, Visibility

    return ReciterRow(
        slug=slug,
        state=ReciterState(state),
        state_since=datetime(2026, 5, 12, tzinfo=timezone.utc),
        assignee_hf_id=assignee_hf_id,
        assignee_login="alice" if assignee_hf_id else None,
        assignee_since=datetime(2026, 5, 12, tzinfo=timezone.utc) if assignee_hf_id else None,
        marked_ready=marked_ready,
        visibility=Visibility(visibility),
    )


def _delivery(slug: str, *, reciter_id: str = "test_reciter",
              riwayah: str = "hafs", style: str = "murattal",
              recording_context: str | None = "studio",
              recording_year: int | None = None,
              source: str = "mp3quran", channel: str = "mp3quran",
              audio_category: str = "by_surah",
              chapter_count: int = 114):
    from scripts.lib.schemas import AudioCategory, Delivery

    return Delivery(
        slug=slug,
        reciter_id=reciter_id,
        riwayah=riwayah,
        style=style,
        recording_context=recording_context,
        recording_year=recording_year,
        source=source,
        channel=channel,
        audio_category=AudioCategory(audio_category),
        chapter_count=chapter_count,
        added_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        added_by_hf_id="system_seed",
    )


def _reciter(reciter_id: str = "test_reciter", *, name_en: str = "Test Reciter",
             country: str | None = "Saudi Arabia"):
    from scripts.lib.schemas import ReciterEntry

    return ReciterEntry(
        reciter_id=reciter_id,
        name_en=name_en,
        country=country,
    )


# ---------------------------------------------------------------------------
# bucket_for
# ---------------------------------------------------------------------------


def test_bucket_for_none_row_is_available_for_request():
    from services.public_state import bucket_for

    assert bucket_for(None) == "available_for_request"


def test_bucket_for_catalogued_is_available_for_request():
    """CATALOGUED rows haven't been requested yet — they're still requestable."""
    from services.public_state import bucket_for

    assert bucket_for(_state_row("test_a", state="catalogued")) == "available_for_request"


def test_bucket_for_awaiting_alignment_is_requested():
    """AWAITING_ALIGNMENT is the post-request, pre-acceptance state."""
    from services.public_state import bucket_for

    assert bucket_for(_state_row("test_b", state="awaiting_alignment")) == "requested"


def test_bucket_for_awaiting_review_is_available_for_review():
    from services.public_state import bucket_for

    assert (
        bucket_for(_state_row("test_a", state="awaiting_review"))
        == "available_for_review"
    )


def test_bucket_for_under_review_unmarked_is_under_review():
    from services.public_state import bucket_for

    row = _state_row("test_a", state="under_review", assignee_hf_id="u-1")
    assert bucket_for(row) == "under_review"


def test_bucket_for_under_review_marked_ready_is_under_review():
    """marked_ready is internal-only; row stays publicly under_review."""
    from services.public_state import bucket_for

    row = _state_row(
        "test_a", state="under_review", assignee_hf_id="u-1", marked_ready=True,
    )
    assert bucket_for(row) == "under_review"


def test_bucket_for_awaiting_timestamps_is_under_review():
    """Post-mark-ready, pre-released rows still surface as under_review."""
    from services.public_state import bucket_for

    assert (
        bucket_for(_state_row("test_a", state="awaiting_timestamps"))
        == "under_review"
    )


def test_bucket_for_released_and_completed_collapse_to_published():
    from services.public_state import bucket_for

    assert bucket_for(_state_row("test_a", state="released")) == "published"
    assert bucket_for(_state_row("test_b", state="completed")) == "published"


# ---------------------------------------------------------------------------
# to_public_reciter — aggregation + redaction
# ---------------------------------------------------------------------------


def test_to_public_reciter_redacts_assignee_fields():
    from services.public_state import to_public_reciter

    reciter = _reciter()
    dels = [_delivery("test_reciter_qdc")]
    state_index = {
        "test_reciter_qdc": _state_row(
            "test_reciter_qdc",
            state="under_review",
            assignee_hf_id="should-be-redacted",
        ),
    }
    public = to_public_reciter(reciter, dels, state_index)

    flat = repr(public)
    assert "assignee_hf_id" not in flat
    assert "assignee_login" not in flat
    assert "assignee_since" not in flat
    assert "should-be-redacted" not in flat


def test_to_public_reciter_aggregates_unions_of_facets():
    from services.public_state import to_public_reciter

    reciter = _reciter()
    dels = [
        _delivery("a_qdc",        riwayah="hafs", style="murattal",
                  source="mp3quran", channel="mp3quran",
                  recording_context="studio"),
        _delivery("a_qdc_v2",     riwayah="hafs", style="mujawwad",
                  source="qul",      channel="quranicaudio",
                  recording_context="broadcast"),
        _delivery("a_archive",    riwayah="hafs", style="mujawwad",
                  source="surah-quran", channel="archive_org",
                  recording_context="broadcast"),
    ]
    state_index = {}
    public = to_public_reciter(reciter, dels, state_index)

    assert public["riwayat"] == ["hafs"]
    assert public["styles"] == ["murattal", "mujawwad"]
    assert public["recording_contexts"] == ["studio", "broadcast"]
    assert public["sources"] == ["mp3quran", "qul", "surah-quran"]
    assert public["channels"] == ["mp3quran", "quranicaudio", "archive_org"]
    assert public["deliveries_count"] == 3
    assert public["chapter_count_total"] == 114 * 3


def test_to_public_reciter_coverage_rollup_full_partial_mixed():
    from services.public_state import to_public_reciter

    reciter = _reciter()

    full_only = to_public_reciter(
        reciter, [_delivery("test_a", chapter_count=114)], {},
    )
    assert full_only["coverage_kind"] == "full"

    partial_only = to_public_reciter(
        reciter, [_delivery("test_b", chapter_count=110)], {},
    )
    assert partial_only["coverage_kind"] == "partial"

    mixed = to_public_reciter(
        reciter,
        [
            _delivery("test_c", chapter_count=114),
            _delivery("test_d", chapter_count=110),
        ],
        {},
    )
    assert mixed["coverage_kind"] == "mixed"


def test_to_public_reciter_primary_bucket_is_most_progressed():
    from services.public_state import to_public_reciter

    reciter = _reciter()
    dels = [
        _delivery("test_a"),
        _delivery("test_b"),
        _delivery("test_c"),
    ]
    state_index = {
        "test_a": _state_row("test_a", state="awaiting_review"),
        "test_b": _state_row("test_b", state="under_review", assignee_hf_id="u-1"),
        # "c" has no state row → available_for_request
    }
    public = to_public_reciter(reciter, dels, state_index)
    # under_review is more progressed than awaiting_review (available_for_review)
    # and available_for_request, so it should win.
    assert public["primary_bucket"] == "under_review"
    # All three buckets are listed.
    assert set(public["buckets"]) == {
        "available_for_request",
        "available_for_review",
        "under_review",
    }


def test_to_public_reciter_skips_discarded_deliveries():
    from services.public_state import to_public_reciter

    reciter = _reciter()
    dels = [
        _delivery("test_a"),
        _delivery("test_b"),
    ]
    state_index = {
        "test_a": _state_row("test_a", state="awaiting_review"),
        "test_b": _state_row("test_b", state="awaiting_review", visibility="discarded"),
    }
    public = to_public_reciter(reciter, dels, state_index)
    assert public["deliveries_count"] == 1
    assert public["deliveries"][0]["slug"] == "test_a"


def test_to_public_reciter_last_activity_is_max_state_since():
    from services.public_state import to_public_reciter
    from scripts.lib.schemas import ReciterRow, ReciterState, Visibility

    reciter = _reciter()
    dels = [_delivery("test_a"), _delivery("test_b")]
    state_index = {
        "test_a": ReciterRow(
            slug="test_a",
            state=ReciterState("awaiting_review"),
            state_since=datetime(2024, 1, 1, tzinfo=timezone.utc),
            visibility=Visibility("public"),
        ),
        "test_b": ReciterRow(
            slug="test_b",
            state=ReciterState("awaiting_review"),
            state_since=datetime(2025, 1, 1, tzinfo=timezone.utc),
            visibility=Visibility("public"),
        ),
    }
    public = to_public_reciter(reciter, dels, state_index)
    assert public["last_activity"].startswith("2025-01-01")
