"""Schema tests for ``qua_shared.schemas.pending_requests``.

These run with no Inspector services touched — pure pydantic validation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone

import pytest
from pydantic import ValidationError

from qua_shared.schemas import (
    Actor,
    ArchivedRequest,
    ArchivedRequestsFile,
    PendingRequest,
    PendingRequestsFile,
    ProposedEdits,
    Role,
)


def _actor(hf_user_id: str = "u-1", login: str = "alice", role: str = "contributor") -> Actor:
    return Actor(hf_user_id=hf_user_id, login_at_time=login, role=Role(role))


# ---------------------------------------------------------------------------
# ProposedEdits
# ---------------------------------------------------------------------------


def test_proposed_edits_empty_is_valid():
    edits = ProposedEdits()
    assert edits.has_any() is False


def test_proposed_edits_populated():
    edits = ProposedEdits(
        riwayah="hafs",
        style="murattal",
        name_en="Sheikh Test",
        name_ar="تست",
        country="SA",
        recording_context="studio",
        recording_year=2010,
    )
    assert edits.has_any() is True
    assert edits.riwayah == "hafs"


def test_proposed_edits_rejects_bad_year_low():
    # Pre-phonograph era — 1885 is the floor.
    with pytest.raises(ValidationError):
        ProposedEdits(recording_year=1800)


def test_proposed_edits_accepts_year_at_lower_bound():
    edits = ProposedEdits(recording_year=1885)
    assert edits.recording_year == 1885


def test_proposed_edits_rejects_year_above_current():
    # Dynamic upper bound = current UTC year; anything beyond that is implausible.
    next_year = datetime.now(UTC).year + 1
    with pytest.raises(ValidationError):
        ProposedEdits(recording_year=next_year)


def test_proposed_edits_accepts_current_year():
    this_year = datetime.now(UTC).year
    edits = ProposedEdits(recording_year=this_year)
    assert edits.recording_year == this_year


def test_proposed_edits_rejects_unknown_field():
    with pytest.raises(ValidationError):
        ProposedEdits(slug="x")  # noqa — extra field forbidden


def test_proposed_edits_blank_riwayah_rejected():
    with pytest.raises(ValidationError):
        ProposedEdits(riwayah="")


# ---------------------------------------------------------------------------
# PendingRequest
# ---------------------------------------------------------------------------


def test_pending_request_minimal():
    pr = PendingRequest(
        slug="test_reciter",
        submitted_at=datetime.now(UTC),
        requester=_actor(),
    )
    assert pr.proposed_edits.has_any() is False
    assert pr.comments is None


def test_pending_request_with_comments():
    pr = PendingRequest(
        slug="test_reciter",
        submitted_at=datetime.now(UTC),
        requester=_actor(),
        proposed_edits=ProposedEdits(name_en="Updated"),
        comments="Found a better recording in 2022.",
    )
    assert pr.comments == "Found a better recording in 2022."


def test_pending_request_rejects_oversized_comments():
    with pytest.raises(ValidationError):
        PendingRequest(
            slug="test_reciter",
            submitted_at=datetime.now(UTC),
            requester=_actor(),
            comments="x" * 1001,
        )


def test_pending_request_rejects_invalid_slug():
    with pytest.raises(ValidationError):
        PendingRequest(
            slug="Bad-Slug",  # uppercase + hyphen not allowed
            submitted_at=datetime.now(UTC),
            requester=_actor(),
        )


def test_pending_request_round_trips_through_json():
    pr = PendingRequest(
        slug="test_reciter",
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
        requester=_actor(),
        proposed_edits=ProposedEdits(country="EG", recording_year=2020),
        comments="hello",
    )
    raw = pr.model_dump(mode="json")
    rt = PendingRequest.model_validate(raw)
    assert rt == pr


# ---------------------------------------------------------------------------
# PendingRequestsFile
# ---------------------------------------------------------------------------


def test_pending_requests_file_empty_default():
    f = PendingRequestsFile()
    assert f.schema_version == 1
    assert f.by_slug == {}


def test_pending_requests_file_with_entries():
    pr = PendingRequest(
        slug="a_reciter",
        submitted_at=datetime.now(UTC),
        requester=_actor(),
    )
    f = PendingRequestsFile(by_slug={"a_reciter": pr})
    rt = PendingRequestsFile.model_validate(f.model_dump(mode="json"))
    assert "a_reciter" in rt.by_slug
    assert rt.by_slug["a_reciter"].slug == "a_reciter"


def test_pending_requests_file_rejects_unknown_field():
    with pytest.raises(ValidationError):
        PendingRequestsFile(extra_field="x")


# ---------------------------------------------------------------------------
# ArchivedRequest / ArchivedRequestsFile
# ---------------------------------------------------------------------------


def test_archived_request_inherits_pending_fields():
    ar = ArchivedRequest(
        slug="test_reciter",
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
        requester=_actor(),
        proposed_edits=ProposedEdits(name_en="Updated"),
        comments="hi",
        auto_claim=True,
        archived_at=datetime(2026, 2, 1, tzinfo=UTC),
        transitioned_by=_actor(hf_user_id="system", login="system", role="owner"),
    )
    assert ar.reason is None
    assert ar.auto_claim is True
    assert ar.proposed_edits.name_en == "Updated"


def test_archived_request_round_trips_through_json():
    ar = ArchivedRequest(
        slug="test_reciter",
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
        requester=_actor(),
        proposed_edits=ProposedEdits(country="EG"),
        comments=None,
        archived_at=datetime(2026, 2, 1, tzinfo=UTC),
        transitioned_by=_actor(hf_user_id="admin-1", login="admin", role="maintainer"),
        reason="please clarify",
    )
    raw = ar.model_dump(mode="json")
    rt = ArchivedRequest.model_validate(raw)
    assert rt == ar


def test_archived_requests_file_empty_default():
    f = ArchivedRequestsFile()
    assert f.schema_version == 1
    assert f.by_slug == {}


def test_archived_requests_file_multiple_entries_per_slug():
    ar1 = ArchivedRequest(
        slug="test_reciter",
        submitted_at=datetime(2026, 1, 1, tzinfo=UTC),
        requester=_actor(),
        archived_at=datetime(2026, 1, 5, tzinfo=UTC),
        transitioned_by=_actor(hf_user_id="admin", login="admin", role="maintainer"),
        reason="reason one",
    )
    ar2 = ArchivedRequest(
        slug="test_reciter",
        submitted_at=datetime(2026, 1, 10, tzinfo=UTC),
        requester=_actor(),
        archived_at=datetime(2026, 1, 15, tzinfo=UTC),
        transitioned_by=_actor(hf_user_id="admin", login="admin", role="maintainer"),
        reason="reason two",
    )
    f = ArchivedRequestsFile(by_slug={"test_reciter": [ar1, ar2]})
    rt = ArchivedRequestsFile.model_validate(f.model_dump(mode="json"))
    assert len(rt.by_slug["test_reciter"]) == 2


def test_archived_requests_file_rejects_unknown_field():
    with pytest.raises(ValidationError):
        ArchivedRequestsFile(extra_field="x")
