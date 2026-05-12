"""Cross-cutting Flask route decorators.

- ``require_same_origin`` — CSRF defense via Origin/Referer check on POST/PUT/DELETE.

Future drops in Phase 3 add ``require_edit_lock`` (save/undo gating) and
``require_role`` (admin endpoints) alongside this one.
"""

from __future__ import annotations

from functools import wraps
from urllib.parse import urlparse

from flask import abort, request


def require_same_origin(fn):
    """Reject mutating requests whose Origin/Referer doesn't match the host.

    ``SameSite=Lax`` already blocks most cross-site cookie sending on POST,
    but the Origin/Referer check is the explicit second line of defense.

    GET/HEAD/OPTIONS are always allowed (no state mutation). For mutating
    methods we require an ``Origin`` or ``Referer`` header whose scheme +
    netloc match this request's. Missing both headers → 403.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return fn(*args, **kwargs)
        expected_host = request.host
        expected_scheme = request.scheme
        origin = request.headers.get("Origin", "")
        if origin:
            p = urlparse(origin)
            if p.scheme == expected_scheme and p.netloc == expected_host:
                return fn(*args, **kwargs)
            abort(403, description="cross-origin request rejected")
        referer = request.headers.get("Referer", "")
        if referer:
            p = urlparse(referer)
            if p.scheme == expected_scheme and p.netloc == expected_host:
                return fn(*args, **kwargs)
            abort(403, description="cross-origin request rejected")
        abort(403, description="missing Origin/Referer header on mutating request")

    return wrapper
