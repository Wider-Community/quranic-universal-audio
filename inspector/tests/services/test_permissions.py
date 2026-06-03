"""Unit tests for ``inspector/services/permissions.py``.

Pure-predicate module — no Flask, no bucket. Coverage:
- ``role_of`` normalizes Role enum, string, and missing/garbage inputs
- ``is_owner`` / ``is_maintainer`` / ``is_contributor_or_higher`` truth tables
- ``has_role`` membership
- ``is_claim_holder`` + ``is_claim_holder_or_maintainer`` against varied rows
- ``normalize_reason`` edge cases
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from qua_shared.schemas import Role


def _stub(role: Any = "contributor", hf_user_id: str = "u-1"):
    """A duck-typed Actor/User stand-in with .role + .hf_user_id."""
    @dataclass
    class _Stub:
        role: Any
        hf_user_id: str
    return _Stub(role=role, hf_user_id=hf_user_id)


def _row(assignee: str | None = None):
    @dataclass
    class _Row:
        assignee_hf_id: str | None
    return _Row(assignee_hf_id=assignee)


# ---------------------------------------------------------------------------
# role_of
# ---------------------------------------------------------------------------


def test_role_of_accepts_role_enum():
    from services import permissions

    assert permissions.role_of(_stub(role=Role.MAINTAINER)) == Role.MAINTAINER


def test_role_of_accepts_string():
    from services import permissions

    assert permissions.role_of(_stub(role="owner")) == Role.OWNER
    assert permissions.role_of(_stub(role="contributor")) == Role.CONTRIBUTOR


def test_role_of_raises_on_missing_attr():
    from services import permissions

    class _Bare:
        pass

    with pytest.raises(ValueError):
        permissions.role_of(_Bare())


def test_role_of_raises_on_unknown_string():
    from services import permissions

    with pytest.raises(ValueError):
        permissions.role_of(_stub(role="superadmin"))


# ---------------------------------------------------------------------------
# is_owner / is_maintainer / is_contributor_or_higher
# ---------------------------------------------------------------------------


def test_is_owner_truth_table():
    from services import permissions

    assert permissions.is_owner(_stub(role="owner")) is True
    assert permissions.is_owner(_stub(role="maintainer")) is False
    assert permissions.is_owner(_stub(role="contributor")) is False


def test_is_maintainer_includes_owner():
    from services import permissions

    assert permissions.is_maintainer(_stub(role="maintainer")) is True
    assert permissions.is_maintainer(_stub(role="owner")) is True
    assert permissions.is_maintainer(_stub(role="contributor")) is False


def test_is_contributor_or_higher_true_for_all_known_roles():
    from services import permissions

    for r in ("contributor", "maintainer", "owner"):
        assert permissions.is_contributor_or_higher(_stub(role=r)) is True


# ---------------------------------------------------------------------------
# has_role
# ---------------------------------------------------------------------------


def test_has_role_membership():
    from services import permissions

    user = _stub(role="maintainer")
    assert permissions.has_role(user, Role.MAINTAINER) is True
    assert permissions.has_role(user, Role.MAINTAINER, Role.OWNER) is True
    assert permissions.has_role(user, Role.OWNER) is False
    assert permissions.has_role(user) is False  # empty allowed set


# ---------------------------------------------------------------------------
# is_claim_holder + is_claim_holder_or_maintainer
# ---------------------------------------------------------------------------


def test_is_claim_holder_matches_hf_user_id():
    from services import permissions

    assert permissions.is_claim_holder(
        _stub(role="contributor", hf_user_id="u-1"),
        _row(assignee="u-1"),
    ) is True


def test_is_claim_holder_rejects_mismatch():
    from services import permissions

    assert permissions.is_claim_holder(
        _stub(role="contributor", hf_user_id="u-1"),
        _row(assignee="u-2"),
    ) is False


def test_is_claim_holder_rejects_unassigned_row():
    from services import permissions

    assert permissions.is_claim_holder(
        _stub(role="contributor", hf_user_id="u-1"),
        _row(assignee=None),
    ) is False


def test_is_claim_holder_or_maintainer_maintainer_wins():
    from services import permissions

    # Maintainer who is NOT the assignee still passes.
    assert permissions.is_claim_holder_or_maintainer(
        _stub(role="maintainer", hf_user_id="u-mod"),
        _row(assignee="u-target"),
    ) is True


def test_is_claim_holder_or_maintainer_contributor_needs_match():
    from services import permissions

    # Contributor who IS the assignee passes.
    assert permissions.is_claim_holder_or_maintainer(
        _stub(role="contributor", hf_user_id="u-1"),
        _row(assignee="u-1"),
    ) is True
    # Contributor who is NOT the assignee fails.
    assert permissions.is_claim_holder_or_maintainer(
        _stub(role="contributor", hf_user_id="u-1"),
        _row(assignee="u-2"),
    ) is False


# ---------------------------------------------------------------------------
# normalize_reason
# ---------------------------------------------------------------------------


def test_normalize_reason_returns_trimmed_on_success():
    from services import permissions

    assert permissions.normalize_reason("  exactly 10!  ") == "exactly 10!"


def test_normalize_reason_returns_none_below_min():
    from services import permissions

    assert permissions.normalize_reason("too short") is None
    assert permissions.normalize_reason("   ") is None
    assert permissions.normalize_reason("") is None
    assert permissions.normalize_reason(None) is None


def test_normalize_reason_respects_custom_min_chars():
    from services import permissions

    assert permissions.normalize_reason("abc", min_chars=3) == "abc"
    assert permissions.normalize_reason("ab", min_chars=3) is None


def test_min_reason_chars_constant_is_ten():
    from services import permissions

    assert permissions.MIN_REASON_CHARS == 10
