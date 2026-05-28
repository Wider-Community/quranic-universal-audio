"""Submit-recitation **intake** service (slugless new-combo / new-reciter).

Submit, owner-accept, and owner-resolve for the two contribution types that
have no catalogued delivery yet. Distinct from ``services.pending_requests``
(the slug-based edit-request flow) — but resolution funnels through the same
``repo_requests`` core (``resolve`` / ``resolve_by_id``).

**Accept does NOT create the catalog delivery.** A delivery requires valid
``source`` / ``channel`` vocab FKs, plus codec/bitrate/duration — all of which
are *probed from the actual audio* and only become known (and valid) once the
offline ingest pipeline fetches it. An arbitrary contributor link may not map to
any existing vocab at all, so a human can't classify it at accept time. The
slug's mandatory ``channel_short`` suffix has the same problem.

So acceptance is a lightweight approval: it records the owner's canonical
``reciter_id`` (new reciters only — the one genuinely human decision) and flips
the request to ``accepted``. The request row already carries the audio source +
proposed metadata; the offline pipeline reads accepted slugless requests, fetches
+ probes the audio, then creates the reciter + delivery (with correct
source/channel/slug) and back-fills ``requests.slug``. Local alignment + ingest
stay offline.
"""

from __future__ import annotations

import logging

from scripts.lib.schemas import (
    Actor,
    IntakeSubmission,
    IntakeValidation,
    ProbeResponse,
)
from scripts.lib.schemas.intake_requests import IntakeSource
from scripts.lib.schemas.state import SLUG_RE

from services.db import _serde, repo_requests
from services.db import sync as _sync

from . import intake_validation
from .intake_probe import probe_source

logger = logging.getLogger(__name__)

_INTAKE_KINDS = ("existing_reciter_new_combo", "new_reciter")


class IntakeError(Exception):
    """Base for caller-facing intake failures (route maps to 400)."""


class IntakeValidationError(IntakeError):
    """Structural validation failed. Carries the :class:`IntakeValidation`."""

    def __init__(self, validation: IntakeValidation):
        super().__init__("; ".join(validation.errors) or "invalid submission")
        self.validation = validation


class NotIntakeRequest(IntakeError):
    """The id isn't a pending intake request (unknown / wrong kind / resolved)."""


# ---- Submit -----------------------------------------------------------------


def submit(sub: IntakeSubmission, *, requester: Actor) -> tuple[str, IntakeValidation]:
    """Validate + record a slugless intake request. Returns ``(request_id,
    validation)``. Raises :class:`IntakeValidationError` if blocking errors
    exist. Warnings (missing chapters, dupes, likely-duplicate request) ride
    along on the returned validation."""
    validation = intake_validation.validate_submission(sub)
    _append_dedup_warning(sub, validation)
    if validation.errors:
        raise IntakeValidationError(validation)

    extra_payload = {
        "reciter_id": sub.reciter_id,
        "source": sub.source.model_dump(mode="json"),
        "attestations": sub.attestations.model_dump(mode="json"),
    }
    with _sync.durable_transaction():
        rid = repo_requests.submit(
            slug=None,
            requester=requester,
            proposed_edits=sub.proposed_edits,
            comments=sub.comments,
            auto_claim=sub.auto_claim,
            kind=sub.kind,
            extra_payload=extra_payload,
        )
        from services.state import audit
        audit.append(
            event="request.intake_submitted",
            actor=requester,
            payload={"request_id": rid, "kind": sub.kind, "reciter_id": sub.reciter_id},
        )
    _invalidate()
    return rid, validation


def _append_dedup_warning(sub: IntakeSubmission, validation: IntakeValidation) -> None:
    """Non-blocking heads-up when a near-identical pending intake already exists
    (slugless rows aren't covered by ``ux_request_pending_slug``)."""
    rows = repo_requests.admin_list_rows(status="pending")
    for row in rows:
        if row["kind"] not in _INTAKE_KINDS or row["kind"] != sub.kind:
            continue
        payload = _serde.json_loads(row["payload"]) or {}
        edits = payload.get("proposed_edits") or {}
        if sub.kind == "existing_reciter_new_combo":
            if (
                payload.get("reciter_id") == sub.reciter_id
                and edits.get("riwayah") == sub.proposed_edits.riwayah
                and edits.get("style") == sub.proposed_edits.style
            ):
                validation.warnings.append(
                    "A pending request for this reciter + combination already exists."
                )
                return
        elif sub.kind == "new_reciter":
            name = (sub.proposed_edits.name_en or "").strip().lower()
            if name and (edits.get("name_en") or "").strip().lower() == name:
                validation.warnings.append(
                    f"A pending new-reciter request for '{sub.proposed_edits.name_en}' "
                    "already exists."
                )
                return


# ---- Accept (owner) ---------------------------------------------------------


def accept(request_id: str, *, actor: Actor, reciter_id: str | None = None) -> str:
    """Approve a pending intake request and queue it for offline ingest.

    Does **not** touch the catalog. For ``new_reciter`` the owner-confirmed
    ``reciter_id`` (the one human decision — a canonical curated slug) is stamped
    into the payload so ingest creates the reciter under it; for
    ``existing_reciter_new_combo`` the ``reciter_id`` is already on the payload.
    The request flips to ``accepted`` (slug stays ``NULL`` until ingest mints the
    delivery). Source/channel/bitrate/slug are deferred to the offline pipeline,
    which is the only place they can be validly determined.

    Raises :class:`NotIntakeRequest` for a bad id and :class:`IntakeError` for a
    missing/invalid ``reciter_id`` on a new-reciter request.
    """
    row = _require_pending_intake(request_id)
    kind = row["kind"]
    payload = _serde.json_loads(row["payload"]) or {}

    if kind == "new_reciter":
        rid = (reciter_id or "").strip()
        if not rid:
            raise IntakeError("reciter_id is required to accept a new-reciter request.")
        if not SLUG_RE.match(rid):
            raise IntakeError(
                f"invalid reciter_id {rid!r} — lowercase letters, digits, and "
                "single underscores only."
            )
        payload["reciter_id"] = rid

    with _sync.durable_transaction():
        if kind == "new_reciter":
            repo_requests.set_payload(request_id, payload)
        repo_requests.resolve_by_id(
            request_id=request_id, status="accepted", transitioned_by=actor,
        )
    _invalidate()
    return request_id


# ---- Resolve: send back / discard (owner) -----------------------------------


def resolve(request_id: str, *, status: str, reason: str, actor: Actor) -> None:
    """Send back (``returned``) or discard (``discarded``) a pending intake
    request. Pure request-status mutation — slugless rows have no state row, so
    no state-machine transition fires (unlike edit-request rejects)."""
    if status not in ("returned", "discarded"):
        raise IntakeError(f"invalid resolve status: {status!r}")
    _require_pending_intake(request_id)
    with _sync.durable_transaction():
        repo_requests.resolve_by_id(
            request_id=request_id, status=status, transitioned_by=actor, reason=reason,
        )
        from services.state import audit
        audit.append(
            event=f"request.intake_{status}",
            actor=actor,
            payload={"request_id": request_id},
            reason=reason,
        )
    _invalidate()


# ---- Probe (owner) ----------------------------------------------------------


def probe(request_id: str) -> ProbeResponse:
    """Reachability-probe a pending intake request's source and cache the result
    onto ``payload.probe``."""
    row = _require_pending_intake(request_id)
    payload = _serde.json_loads(row["payload"]) or {}
    src = IntakeSource(**(payload.get("source") or {"method": "links"}))
    result = probe_source(src)
    with _sync.durable_transaction():
        payload["probe"] = result.model_dump(mode="json")
        repo_requests.set_payload(request_id, payload)
    _invalidate()
    return result


# ---- Helpers ----------------------------------------------------------------


def _require_pending_intake(request_id: str):
    row = repo_requests.get_by_id(request_id)
    if row is None or row["kind"] not in _INTAKE_KINDS or row["status"] != "pending":
        raise NotIntakeRequest(request_id)
    return row


def _invalidate() -> None:
    from services.storage import cache as _cache
    _cache.invalidate_admin_requests_cache()
