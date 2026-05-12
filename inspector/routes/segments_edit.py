"""Segments tab edit routes (/api/seg/ — save, undo).

Decorator chain on every mutating route:

  ``@require_same_origin`` → ``@require_edit_lock(admin_bypass=True)``

- ``require_same_origin`` rejects cross-origin POSTs (CSRF defense).
- ``require_edit_lock`` rejects unauthenticated requests (401) or
  non-(assignee | maintainer | owner) attempts on a non-under_review row
  (403). On success it sets ``g.current_user`` and ``g.current_row`` so the
  handler can build an ``Actor`` from the live user identity.
"""
from flask import Blueprint, g, jsonify, request

from scripts.lib.schemas import Actor

from services.auto_split import compute_auto_split as _compute_auto_split
from services.save import save_seg_data as _save_seg_data
from services.undo import undo_batch as _undo_batch, undo_ops as _undo_ops

from utils.decorators import require_edit_lock, require_same_origin

seg_edit_bp = Blueprint("seg_edit", __name__, url_prefix="/api/seg")


def _actor_from_g() -> Actor:
    """Build an ``Actor`` from the user that ``require_edit_lock`` stashed."""
    user = g.current_user
    role_val = user.role.value if hasattr(user.role, "value") else user.role
    return Actor(
        hf_user_id=user.hf_user_id,
        login_at_time=user.login,
        role=role_val,
    )


@seg_edit_bp.route("/save/<reciter>/<int:chapter>", methods=["POST"])
@require_same_origin
@require_edit_lock(reciter_param="reciter", admin_bypass=True)
def seg_save(reciter, chapter):
    """Save edited segments back to detailed.json and segments.json."""
    updates = request.get_json()
    if not updates or "segments" not in updates:
        return jsonify({"error": "Missing segments in request body"}), 400
    result = _save_seg_data(reciter, chapter, updates, actor=_actor_from_g())
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@seg_edit_bp.route("/undo-batch/<reciter>", methods=["POST"])
@require_same_origin
@require_edit_lock(reciter_param="reciter", admin_bypass=True)
def seg_undo_batch(reciter):
    """Undo a specific saved batch by reversing its operations."""
    body = request.get_json()
    if not body or not body.get("batch_id"):
        return jsonify({"error": "Missing batch_id"}), 400
    result = _undo_batch(reciter, body["batch_id"], actor=_actor_from_g())
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@seg_edit_bp.route("/auto-split/<reciter>", methods=["POST"])
@require_same_origin
@require_edit_lock(reciter_param="reciter", admin_bypass=True)
def seg_auto_split(reciter):
    """Compute auto-split cursors + per-section refs for a segment.

    Response shape:

      ``{"cursors": list[int] | None,   # N-1 absolute ms cuts
         "refs":    list[str] | None,   # N per-section refs
         "kind":    "cross_verse" | "repetition" | null,
         "source":  "mfa" | "fallback"}``

    On a total miss (segment not found, no audio, malformed ref) all
    fields are null and the FE opens normal split at the midpoint. On MFA
    failure the response is still populated with the fallback shape (even
    cuts for repetitions, midpoint for cross-verse + suggested refs) so
    the user gets a workable cursor layout without a visible error.
    """
    body = request.get_json(silent=True) or {}
    segment_uid = body.get("segment_uid")
    chapter = body.get("chapter")
    if not segment_uid or not isinstance(chapter, int):
        return jsonify({"error": "segment_uid and chapter required"}), 400
    return jsonify(_compute_auto_split(reciter, chapter, segment_uid))


@seg_edit_bp.route("/undo-ops/<reciter>", methods=["POST"])
@require_same_origin
@require_edit_lock(reciter_param="reciter", admin_bypass=True)
def seg_undo_ops(reciter):
    """Undo specific operations within a saved batch."""
    body = request.get_json()
    if not body or not body.get("batch_id") or not body.get("op_ids"):
        return jsonify({"error": "Missing batch_id or op_ids"}), 400
    result = _undo_ops(
        reciter,
        body["batch_id"],
        set(body["op_ids"]),
        actor=_actor_from_g(),
    )
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)
