"""Submit-recitation **intake** service (slugless new-combo / new-reciter).

Submit, owner-accept, and owner-resolve for the two contribution types that
have no catalogued delivery yet. Distinct from ``services.pending_requests``
(the slug-based edit-request flow) — but resolution funnels through the same
``repo_requests`` core (``resolve`` / ``resolve_by_id``).

Accept is the load-bearing piece. It mints the catalog entry, stashes the audio
source onto the new ``wip/<slug>/`` tree, and **advances the slug to
AWAITING_ALIGNMENT via ``reciter.requested``** (on the requester's behalf,
carrying ``auto_claim``). This is deliberate, not just "create + park at
CATALOGUED": the offline ingest pipeline requires AWAITING_ALIGNMENT to fire
``reciter.alignment_completed``, and routing through ``reciter.requested`` reuses
the entire existing align → implicit-accept → auto-claim machinery (a freshly
CATALOGUED slug can't be claimed — ``_h_claimed`` requires AWAITING_REVIEW). The
intake row itself resolves to ``accepted`` and back-fills ``requests.slug`` with
the minted delivery. Local alignment stays offline.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from scripts.lib.schemas import (
    Actor,
    AudioCategory,
    Delivery,
    IntakeSubmission,
    IntakeValidation,
    ProbeResponse,
    ProposedEdits,
)
from scripts.lib.schemas.intake_requests import IntakeSource

from services.db import _serde, repo_requests
from services.db import sync as _sync
from services.state import catalog as catalog_service
from services.state import state as state_service
from services.storage import storage_paths
from services.storage.hf_bucket import get_backend

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


def accept(
    request_id: str,
    *,
    actor: Actor,
    slug: str,
    reciter_id: str,
    source: str,
    channel: str,
) -> str:
    """Mint the catalog entry for a pending intake request, stash its source,
    queue it for alignment, and resolve the request to ``accepted``.

    ``slug`` / ``reciter_id`` / ``source`` / ``channel`` are owner-confirmed in
    the Accept dialog (the URL can't supply the source/channel vocab FKs, and
    the slug is sticky once created). Returns the minted delivery slug. Raises
    :class:`NotIntakeRequest` for a bad id; ``catalog.CatalogError`` /
    ``ValueError`` (bad slug / FK / collision) propagate for the route to 400.
    """
    row = _require_pending_intake(request_id)
    payload = _serde.json_loads(row["payload"]) or {}
    edits = ProposedEdits(**(payload.get("proposed_edits") or {}))
    src = IntakeSource(**(payload.get("source") or {"method": "links"}))
    requester = Actor(**payload["requester"])
    kind = row["kind"]

    # Build the delivery up front so a validation error aborts before any write.
    # Audio metrics (codec/bitrate/duration) are unknown until offline ingest
    # probes the files — left at their schema defaults; chapter_count reflects
    # the supplied direct links (0 for a playlist, enumerated offline).
    delivery = Delivery(
        slug=slug,
        reciter_id=reciter_id,
        riwayah=edits.riwayah,
        style=edits.style,
        recording_context=edits.recording_context,
        recording_year=edits.recording_year,
        source=source,
        channel=channel,
        audio_category=AudioCategory.BY_SURAH,
        chapter_count=len(src.links) if src.method == "links" else 0,
        added_at=datetime.now(timezone.utc),
        added_by_hf_id=actor.hf_user_id,
    )

    with _sync.durable_transaction():
        if kind == "new_reciter":
            catalog_service.add_reciter(
                actor=actor,
                reciter_id=reciter_id,
                name_en=edits.name_en or reciter_id,
                name_ar=edits.name_ar,
                country=edits.country,
                reason="accepted intake request",
            )
        catalog_service.add_delivery(
            actor=actor, delivery=delivery, reason="accepted intake request",
        )
        # Queue for alignment as the requester so auto_claim targets them. The
        # delivery already carries the proposed combination, so no proposed_edits
        # need re-applying on completion — pass an empty set.
        state_service.transition(
            slug,
            "reciter.requested",
            actor=requester,
            payload={
                "proposed_edits": {},
                "comments": row["comments"],
                "auto_claim": bool(row["auto_claim"]),
            },
        )
        repo_requests.resolve_by_id(
            request_id=request_id,
            status="accepted",
            transitioned_by=actor,
            slug=slug,
        )
    # Stash the contributor's source for the offline ingest pipeline AFTER the
    # txn commits — a rollback must not leave an orphan sidecar for a slug that
    # was never created. A committed delivery briefly missing its sidecar is
    # recoverable (ingest can re-request the source); an orphan file is silent
    # litter.
    get_backend().write_json_atomic(
        storage_paths.intake_source_path(slug), src.model_dump(mode="json"),
    )
    _invalidate()
    return slug


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
