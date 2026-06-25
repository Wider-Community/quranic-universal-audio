"""Schema tests for ``qua_shared.schemas.wire._envelopes``.

Pure pydantic validation — no Inspector services touched. Asserts the
``model_dump`` shapes routes rely on: ``ErrorEnvelope`` collapses to a bare
``{"error": ...}`` when only the message is set (optional ``code``/``detail``
excluded via ``exclude_none``), and ``OkAck`` is the trivial ``{"ok": True}``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from qua_shared.schemas import ErrorEnvelope, OkAck


def test_error_envelope_message_only_excludes_none_fields() -> None:
    assert ErrorEnvelope(error="x").model_dump(exclude_none=True) == {"error": "x"}


def test_error_envelope_carries_code_and_detail() -> None:
    env = ErrorEnvelope(error="boom", code="STATE_PRECONDITION", detail="needs a reason")
    assert env.model_dump(exclude_none=True) == {
        "error": "boom",
        "detail": "needs a reason",
        "code": "STATE_PRECONDITION",
    }


def test_error_envelope_default_dump_keeps_none_fields() -> None:
    # Without exclude_none the optional fields stay present as None — callers
    # that want the minimal wire body must pass exclude_none=True.
    assert ErrorEnvelope(error="x").model_dump() == {
        "error": "x",
        "detail": None,
        "code": None,
    }


def test_error_envelope_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        ErrorEnvelope(error="x", unexpected="nope")  # type: ignore[reportCallIssue]  # negative test: extra=forbid must reject unknown field at runtime


def test_ok_ack_dumps_true() -> None:
    assert OkAck().model_dump() == {"ok": True}


def test_ok_ack_rejects_false() -> None:
    with pytest.raises(ValidationError):
        OkAck(ok=False)  # type: ignore[reportArgumentType]  # negative test: ok is constrained to True, runtime must reject False


def test_ok_ack_rejects_unknown_field() -> None:
    with pytest.raises(ValidationError):
        OkAck(extra="nope")  # type: ignore[reportCallIssue]  # negative test: extra=forbid must reject unknown field at runtime
