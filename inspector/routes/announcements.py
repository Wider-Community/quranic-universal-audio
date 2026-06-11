"""Public announcements read route (``GET /api/announcements``).

Serves the active global announcements to EVERY visitor — signed-in or
anonymous — for the Dashboard "My Notifications" rail. Ungated (no auth, like
``/api/static/*``) because signed-out visitors must see announcements; dismiss
and seen state live entirely in the browser (localStorage), so there is no
per-user state to scope. Owner compose / revoke live in
``routes/admin/announcements.py``.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from qua_shared.schemas import Announcement
from services import announcements as announcements_service

announcements_bp = Blueprint("announcements", __name__, url_prefix="/api")


@announcements_bp.route("/announcements")
def list_announcements():
    """Active announcements, newest-first. Public — anonymous-reachable."""
    rows = [
        Announcement(
            id=r["id"], title=r["title"], body=r["body"], created_at=r["created_at"]
        ).model_dump(mode="json")
        for r in announcements_service.list_active()
    ]
    return jsonify({"announcements": rows})
