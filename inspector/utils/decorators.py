"""Cross-cutting Flask route decorators.

- ``require_same_origin`` — CSRF defense via Origin/Referer check on POST/PUT/DELETE.
- ``require_edit_lock`` — gate save/undo routes on (signed in + active claim
  + row is editable). Supports ``admin_bypass=True`` for maintainer/owner
  override on under_review rows.
- ``require_role(*roles)`` — generic role gate for admin endpoints. Composes
  ``require_signed_in_or_401`` + ``require_role_or_403`` and injects the
  authenticated user as the first positional argument into the handler.
  Preferred over inline helpers (``_require_maintainer_or_above`` etc.) for
  new admin routes; existing routes can migrate incrementally.
"""

from __future__ import annotations

from functools import wraps
from urllib.parse import urlparse

from flask import abort, g, request

from scripts.lib.schemas import ReciterState, Role, Visibility

from services import auth as auth_service
from services import permissions
from services import state as state_service


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


def require_role(*allowed: Role):
    """Gate a route on (signed in + role in ``allowed``).

    The wrapped handler receives the authenticated ``User`` as its first
    positional argument; remaining route args follow:

        @require_role(Role.MAINTAINER, Role.OWNER)
        def handler(user, slug): ...

    Returns canonical envelopes:
    - 401 ``{"error": "authentication required"}`` for anonymous callers.
    - 403 ``{"error": "insufficient role for this action"}`` for callers
      whose role isn't in ``allowed``.

    Pair with ``@require_same_origin`` on POST/PUT/DELETE for CSRF defense.
    """
    # Inline import to keep decorators.py free of route-layer dependencies
    # at module-import time.
    from routes._admin_helpers import (
        require_role_or_403,
        require_signed_in_or_401,
    )

    def wrap(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            user, err = require_signed_in_or_401()
            if err is not None:
                return err
            err_resp = require_role_or_403(user, *allowed)
            if err_resp is not None:
                return err_resp
            return fn(user, *args, **kwargs)

        return inner

    return wrap


def require_edit_lock(reciter_param: str = "reciter", *, admin_bypass: bool = False):
    """Gate a route on (signed in + editable row + authorised actor).

    **Standard path** (contributor): requires ``state.under_review`` +
    ``not marked_ready`` + ``visibility.public`` + assignee match.

    **Admin bypass** (``admin_bypass=True``): maintainer/owner can edit any
    ``under_review`` row regardless of assignee.

    **Owner bypass**: owners can edit any public, non-marked-ready row
    regardless of ``ReciterState`` or assignee — no ``admin_bypass`` flag
    required.

    Marked-ready rows are NEVER editable by anyone via this gate; the
    reviewer's "Continue editing" flips ``marked_ready=False`` first.

    On success: ``g.current_user`` and ``g.current_row`` are set so the
    route can build an ``Actor`` from them without re-resolving.
    """

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = auth_service.current_user()
            if user is None:
                abort(401, description="authentication required")
            slug = kwargs.get(reciter_param)
            if not slug:
                abort(400, description=f"missing {reciter_param!r} in route")
            row = state_service.get_row(slug)
            if row is None:
                abort(404, description="unknown reciter")
            if permissions.is_owner(user):
                # Owners bypass the state check; marked_ready and visibility
                # still apply.
                if row.marked_ready:
                    abort(403, description="reciter is marked ready for publish and frozen")
                if row.visibility != Visibility.PUBLIC:
                    abort(403, description="reciter visibility blocks edits")
            else:
                if row.state != ReciterState.UNDER_REVIEW:
                    abort(403, description="reciter is not in an editable state")
                if row.marked_ready:
                    abort(403, description="reciter is marked ready for publish and frozen")
                if row.visibility != Visibility.PUBLIC:
                    abort(403, description="reciter visibility blocks edits")
                is_assignee = permissions.is_claim_holder(user, row)
                is_admin = admin_bypass and permissions.is_maintainer(user)
                if not (is_assignee or is_admin):
                    abort(403, description="reciter is not editable by this user")
            g.current_user = user
            g.current_row = row
            return fn(*args, **kwargs)

        return wrapper

    return deco
