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

from qua_shared.schemas import ReciterState, Role, Visibility

from services import auth as auth_service
from services import permissions
from services import state as state_service
from services.auth import capabilities as _capabilities
from services.errors import Codes, api_error
from services.state.labels import humanize_state


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


def require_capability(capability: str):
    """Gate a route on a single capability via the resolver (``can()``).

    The data-driven successor to ``require_role`` — instead of a fixed tier
    list, the route names a capability and the owner-configurable matrix
    decides which tiers pass. The wrapped handler receives the resolved
    ``User | None`` as its first positional argument (same shape as
    ``require_role``; ``None`` only for an ``anon_eligible`` capability hit by
    an anonymous caller):

        @require_capability("reviews.view")
        def handler(user, slug): ...

    Envelopes (matching ``require_role``):
    - 401 ``{"error": "authentication required"}`` — anonymous caller on a
      capability that is NOT anon-eligible (an action endpoint).
    - 403 ``{"error": "insufficient permission for this action"}`` — signed-in
      caller whose tier lacks the capability, or an anonymous caller denied an
      anon-eligible (view) capability.

    Pair with ``@require_same_origin`` on POST/PUT/DELETE for CSRF defense.
    Unknown capability id raises at decoration time (a programmer error).
    """
    from qua_shared.schemas import CAPABILITIES_BY_ID

    cap = CAPABILITIES_BY_ID.get(capability)
    if cap is None:
        raise ValueError(f"require_capability: unknown capability {capability!r}")
    anon_eligible = cap.anon_eligible

    def wrap(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            user = auth_service.current_user()
            if user is None and not anon_eligible:
                return api_error(
                    "Please sign in to continue.",
                    code=Codes.AUTH_REQUIRED,
                    status=401,
                )
            if not _capabilities.can(user, capability):
                return api_error(
                    "You don't have permission for this action.",
                    code=Codes.FORBIDDEN_CAPABILITY,
                    status=403,
                )
            return fn(user, *args, **kwargs)

        return inner

    return wrap


def require_edit_lock(reciter_param: str = "reciter", *, admin_bypass: bool = False):
    """Gate a route on (signed in + editable row + authorised actor).

    **Standard path** (contributor): requires ``state.under_review`` +
    ``not marked_ready`` + ``visibility.public`` + assignee match.

    **Admin bypass** (``admin_bypass=True``): maintainer/owner can edit any
    ``under_review`` row regardless of assignee.

    **Owner bypass**: owners can edit any public row regardless of
    ``ReciterState``, assignee, or marked_ready freeze — no ``admin_bypass``
    flag required. Owner override is total.

    Marked-ready rows are otherwise frozen for everyone else; the reviewer's
    "Continue editing" flips ``marked_ready=False`` first.

    On success: ``g.current_user`` and ``g.current_row`` are set so the
    route can build an ``Actor`` from them without re-resolving.
    """

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = auth_service.current_user()
            if user is None:
                return api_error(
                    "Please sign in to edit.", code=Codes.AUTH_REQUIRED, status=401
                )
            slug = kwargs.get(reciter_param)
            if not slug:
                abort(400, description=f"missing {reciter_param!r} in route")
            row = state_service.get_row(slug)
            if row is None:
                return api_error(
                    "That reciter couldn't be found.",
                    code=Codes.UNKNOWN_RECITER,
                    status=404,
                )
            if permissions.is_owner(user):
                # Owners bypass state and marked_ready; only visibility applies.
                if row.visibility != Visibility.PUBLIC:
                    return api_error(
                        "This reciter isn't available for editing.",
                        code=Codes.VISIBILITY_BLOCKED,
                        status=403,
                        context={"visibility": row.visibility.value},
                    )
            else:
                if row.state != ReciterState.UNDER_REVIEW:
                    return api_error(
                        "This reciter isn't in an editable state right now.",
                        code=Codes.NOT_EDITABLE_STATE,
                        status=403,
                        context={
                            "current_state": row.state.value,
                            "state_label": humanize_state(row.state),
                        },
                    )
                if row.marked_ready:
                    return api_error(
                        "This reciter is marked ready for publish and is locked.",
                        code=Codes.MARKED_READY_FROZEN,
                        status=403,
                    )
                if row.visibility != Visibility.PUBLIC:
                    return api_error(
                        "This reciter isn't available for editing.",
                        code=Codes.VISIBILITY_BLOCKED,
                        status=403,
                        context={"visibility": row.visibility.value},
                    )
                # Tier dimension is now capability-driven; claim-holder stays
                # an ownership check. A contributor whose ``segment.edit`` was
                # toggled off loses self-edit; the admin-bypass arm consults
                # ``segment.edit_as_admin`` instead of a hardcoded maintainer
                # tier. Owners never reach here (handled above).
                is_assignee = permissions.is_claim_holder(user, row) and _capabilities.can(
                    user, "segment.edit"
                )
                is_admin = admin_bypass and _capabilities.can(user, "segment.edit_as_admin")
                if not (is_assignee or is_admin):
                    return api_error(
                        "You need an active claim on this reciter to edit it.",
                        code=Codes.NOT_CLAIM_HOLDER,
                        status=403,
                    )
            g.current_user = user
            g.current_row = row
            return fn(*args, **kwargs)

        return wrapper

    return deco
