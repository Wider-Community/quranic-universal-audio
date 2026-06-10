"""Canonical HTTP wire envelopes shared by every route.

Two tiny shapes that routes otherwise hand-build as bare dict literals:

- ``ErrorEnvelope`` — the flat error body the API returns on a failed
  request (``{"error": ...}`` plus optional ``code``/``detail``). It mirrors
  the builder in ``inspector/services/errors.py`` and the FE-side
  ``ApiErrorBody`` interface (``inspector/frontend/src/lib/types/domain.ts``):
  ``error`` is always present (human-readable prose), ``code`` is the stable
  machine constant the FE maps to friendly copy, and ``detail`` is an optional
  free-text elaboration. ``None`` fields are dropped on dump via
  ``exclude_none`` so the on-the-wire body stays minimal.
- ``OkAck`` — the trivial ``{"ok": true}`` acknowledgement routes return when
  a mutation succeeds but there is no payload to hand back.

Both are FE-facing (error handling consumes ``ErrorEnvelope``; ack handling
consumes ``OkAck``).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ErrorEnvelope(BaseModel):
    """Flat error body returned on a failed request.

    ``error`` is the always-present human-readable message. ``code`` is the
    optional stable machine constant (see ``services/errors.py::Codes``) the FE
    maps to friendly copy. ``detail`` is optional free-text elaboration.

    Dump with ``exclude_none=True`` (or ``model_dump(exclude_none=True)``) so the
    optional fields vanish when unset, matching the bare-dict shape routes emit.
    """

    model_config = ConfigDict(extra="forbid")

    error: str
    detail: str | None = None
    code: str | None = None


class OkAck(BaseModel):
    """The trivial ``{"ok": true}`` success acknowledgement."""

    model_config = ConfigDict(extra="forbid")

    ok: Literal[True] = True
