"""Segments tab edit routes (/api/seg/ — save, undo).

Decorator chain on every mutating route:

  ``@require_same_origin`` → ``@require_edit_lock(admin_bypass=True)`` → ``@_gate_local_writes``

- ``require_same_origin`` rejects cross-origin POSTs (CSRF defense).
- ``require_edit_lock`` rejects unauthenticated requests (401) or
  non-(assignee | maintainer | owner) attempts on a non-under_review row
  (403). On success it sets ``g.current_user`` and ``g.current_row`` so the
  handler can build an ``Actor`` from the live user identity.
- ``_gate_local_writes`` catches the local-mode write-guard exception.
"""
from functools import wraps

from flask import Blueprint, g, jsonify, request

from scripts.lib.schemas import Actor

from services.save import LocalWritesDisabled, save_seg_data as _save_seg_data
from services.undo import undo_batch as _undo_batch, undo_ops as _undo_ops

from utils.decorators import require_edit_lock, require_same_origin

seg_edit_bp = Blueprint("seg_edit", __name__, url_prefix="/api/seg")


def _gate_local_writes(fn):
    """Convert ``LocalWritesDisabled`` into a 403 JSON envelope.

    Local mode reads the shared dev bucket but refuses to write to it by
    default (deployment plan §Local writes). Set ``INSPECTOR_LOCAL_WRITES=1``
    to opt in.
    """

    @wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except LocalWritesDisabled as e:
            return jsonify({"error": str(e)}), 403

    return wrapped


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
@_gate_local_writes
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
@_gate_local_writes
def seg_undo_batch(reciter):
    """Undo a specific saved batch by reversing its operations."""
    body = request.get_json()
    if not body or not body.get("batch_id"):
        return jsonify({"error": "Missing batch_id"}), 400
    result = _undo_batch(reciter, body["batch_id"], actor=_actor_from_g())
    if isinstance(result, tuple):
        return jsonify(result[0]), result[1]
    return jsonify(result)


@seg_edit_bp.route("/undo-ops/<reciter>", methods=["POST"])
@require_same_origin
@require_edit_lock(reciter_param="reciter", admin_bypass=True)
@_gate_local_writes
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
