"""Admin announcement endpoints (owner-only by default).

- ``GET  /api/admin/announcements``            management list (active + revoked).
- ``POST /api/admin/announcements``            compose + broadcast one announcement.
- ``POST /api/admin/announcements/<id>/revoke`` hide an announcement from every rail.

All three gate on ``announcements.send`` (owner-only default, toggleable). The
GET is read-only; the two mutating POSTs additionally carry ``@require_same_origin``
for CSRF defense (mirrors ``routes/admin/users.py``). The public read route that
serves these to anonymous visitors lives in ``routes/announcements.py``.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from qua_shared.schemas import AnnouncementAdmin, AnnouncementCreate
from routes._admin_helpers import actor_for as _actor_for
from services import announcements as announcements_service
from utils.decorators import require_capability, require_same_origin

admin_announcements_bp = Blueprint("admin_announcements", __name__, url_prefix="/api/admin")


@admin_announcements_bp.route("/announcements")
@require_capability("announcements.send")
def list_announcements(user):
    """Active + revoked announcements, newest-first, for the management tab."""
    rows = [
        AnnouncementAdmin.model_validate(r).model_dump(mode="json")
        for r in announcements_service.list_all()
    ]
    return jsonify({"announcements": rows})


@admin_announcements_bp.route("/announcements", methods=["POST"])
@require_same_origin
@require_capability("announcements.send")
def create_announcement(user):
    """Compose one global announcement. Returns the stored row (201)."""
    try:
        req = AnnouncementCreate.model_validate(request.get_json(silent=True) or {})
    except ValidationError as exc:
        return jsonify({"error": "invalid announcement", "details": exc.errors()}), 400
    try:
        row = announcements_service.send(title=req.title, body=req.body, actor=_actor_for(user))
    except announcements_service.AnnouncementError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(AnnouncementAdmin.model_validate(row).model_dump(mode="json")), 201


@admin_announcements_bp.route("/announcements/<int:announcement_id>/revoke", methods=["POST"])
@require_same_origin
@require_capability("announcements.send")
def revoke_announcement(user, announcement_id):
    """Revoke one active announcement. 404 if unknown or already revoked."""
    ok = announcements_service.revoke(announcement_id, actor=_actor_for(user))
    if not ok:
        return jsonify({"error": "announcement not found"}), 404
    return ("", 204)
