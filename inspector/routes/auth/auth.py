"""HF OAuth + signed-cookie session routes.

- ``GET /api/auth/login?return=<path>``  redirect to HF consent screen.
- ``GET /api/auth/callback``             exchange code, set identity cookie, redirect.
- ``POST /api/auth/logout``              clear identity cookie. Claims survive.
- ``GET /api/me``                        identity + active_claim. Stable shape for
                                         anonymous (all fields null).

Cookie scheme + behaviour live in ``inspector/services/auth.py``.
"""

from __future__ import annotations

import logging
import os
from urllib.parse import parse_qs, urljoin, urlparse

from flask import Blueprint, jsonify, make_response, redirect, request

from scripts.lib.schemas import ReciterState

from services import auth as auth_service
from services import state as state_service
from services.admin import visitors as visitor_service
from services.auth import capabilities as cap_service
from services.db import repo_access
from services.db import sync as _sync

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__, url_prefix="/api")

# Behind HF Spaces' TLS proxy the app sees ``request.scheme == https`` and
# can set Secure cookies. Locally the inspector runs over plain HTTP, where
# Secure-tagged cookies are rejected — fall back to non-Secure + Lax.
_BEHIND_PROXY = os.environ.get("INSPECTOR_BEHIND_PROXY") == "1"


def _safe_return_path(raw: str | None) -> str:
    """Restrict the post-callback redirect to same-origin paths.

    Absolute URLs and anything outside this Space are rejected; falls back
    to ``/``. Protects against open-redirect via ``?return=...``.
    """
    if not raw:
        return "/"
    # Reject protocol-relative URLs (``//evil.example/path``).
    if raw.startswith("//"):
        return "/"
    if raw.startswith("/"):
        return raw
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return "/"
    # Plain relative path — treat as root-relative.
    return "/" + raw


def _callback_url() -> str:
    """Build the redirect_uri the Space announces to HF.

    Behind ProxyFix (``INSPECTOR_BEHIND_PROXY=1``), ``request.url_root``
    reflects the public https URL. Override via ``INSPECTOR_PUBLIC_URL``
    if proxy headers ever go wrong on HF.
    """
    public = os.environ.get("INSPECTOR_PUBLIC_URL", "").rstrip("/")
    if public:
        return f"{public}/api/auth/callback"
    return urljoin(request.url_root, "api/auth/callback")


def _state_from_redirect(resp) -> str | None:
    """Pull the OAuth ``state`` Authlib embedded in the authorize redirect.

    We key the post-login return path on it server-side; see
    ``auth_service.remember_return_path``.
    """
    location = resp.headers.get("Location", "")
    if not location:
        return None
    vals = parse_qs(urlparse(location).query).get("state")
    return vals[0] if vals else None


@auth_bp.route("/auth/login")
def auth_login():
    if not auth_service.is_oauth_configured():
        return jsonify({"error": "OAuth not configured on this deploy"}), 503
    return_to = _safe_return_path(request.args.get("return"))
    oauth = auth_service.get_oauth()
    redirect_uri = _callback_url()
    resp = oauth.huggingface.authorize_redirect(redirect_uri)
    # Stash the return path server-side, keyed by the freshly-minted OAuth
    # state. The Flask session cookie can't carry it: inside the cross-site HF
    # iframe it's third-party and Safari drops it (same reason the OAuth state
    # itself is now server-side — see services/auth).
    state = _state_from_redirect(resp)
    if state:
        auth_service.remember_return_path(state, return_to)
    logger.info(
        "auth.login url_root=%s host=%s scheme=%s redirect_uri=%s return=%s",
        request.url_root, request.host, request.scheme, redirect_uri, return_to,
    )
    return resp


@auth_bp.route("/auth/callback")
def auth_callback():
    if not auth_service.is_oauth_configured():
        return jsonify({"error": "OAuth not configured on this deploy"}), 503
    # Surface HF's error response if present (e.g. ``?error=access_denied``)
    # before we burn the code on a token exchange that's going to fail.
    hf_error = request.args.get("error")
    if hf_error:
        hf_error_desc = request.args.get("error_description", "")
        logger.warning(
            "auth.callback HF returned error=%s description=%s",
            hf_error, hf_error_desc,
        )
        return jsonify({
            "error": "OAuth provider returned an error",
            "hf_error": hf_error,
            "hf_error_description": hf_error_desc,
        }), 400

    return_to = _safe_return_path(auth_service.pop_return_path(request.args.get("state")))
    oauth = auth_service.get_oauth()
    try:
        token = oauth.huggingface.authorize_access_token()
    except Exception as e:  # noqa: BLE001 — Authlib raises various; treat all as failure
        # Log the full exception so the Space's stderr surfaces the cause.
        logger.exception("auth.callback authorize_access_token failed")
        return jsonify({
            "error": "OAuth callback failed",
            "detail": f"{type(e).__name__}: {e}",
        }), 400

    userinfo = token.get("userinfo")
    if userinfo is None:
        try:
            userinfo = oauth.huggingface.userinfo(token=token)
        except Exception as e:  # noqa: BLE001
            logger.exception("auth.callback userinfo fetch failed")
            return jsonify({
                "error": "OAuth userinfo fetch failed",
                "detail": f"{type(e).__name__}: {e}",
            }), 400

    sub = userinfo.get("sub")
    login = userinfo.get("preferred_username") or userinfo.get("name")
    if not sub or not login:
        logger.warning("auth.callback userinfo missing sub/login: keys=%s", list(userinfo or {}))
        return jsonify({"error": "OAuth userinfo missing identity fields"}), 400

    # Persist the user on login so "everyone who logged in" has a row even with
    # zero edits, and stamp login recency. ensure_user upserts login_cache +
    # last_seen (+ first_seen once); touch_last_login sets last_login_at.
    # Non-fatal: a failed persist must not block sign-in (the row is recreated
    # on the next action / re-login).
    try:
        with _sync.durable_transaction():
            repo_access.ensure_user(sub, login=login)
            repo_access.touch_last_login(sub)
    except Exception:  # noqa: BLE001
        logger.exception("auth.callback: failed to persist user on login (continuing)")

    cookie = auth_service.encode_session(login=login, hf_user_id=sub)
    resp = make_response(redirect(return_to, code=302))
    resp.set_cookie(
        auth_service.SESSION_COOKIE_NAME,
        cookie,
        max_age=auth_service.SESSION_COOKIE_MAX_AGE,
        httponly=True,
        # HF Spaces serves the app inside an iframe under huggingface.co;
        # Lax cookies aren't reliably sent on the iframe's outgoing fetches.
        # Use None+Secure on the deployed Space to flow in cross-site
        # iframe contexts. Fall back to Lax on plain-HTTP local dev (where
        # SameSite=None requires Secure=true, which browsers reject without
        # HTTPS — including over localhost in some browsers).
        secure=_BEHIND_PROXY,
        samesite="None" if _BEHIND_PROXY else "Lax",
        path="/",
    )
    return resp


@auth_bp.route("/auth/logout", methods=["POST"])
def auth_logout():
    resp = make_response(jsonify({"ok": True}))
    resp.set_cookie(
        auth_service.SESSION_COOKIE_NAME,
        "",
        max_age=0,
        httponly=True,
        # HF Spaces serves the app inside an iframe under huggingface.co;
        # Lax cookies aren't reliably sent on the iframe's outgoing fetches.
        # Use None+Secure on the deployed Space to flow in cross-site
        # iframe contexts. Fall back to Lax on plain-HTTP local dev (where
        # SameSite=None requires Secure=true, which browsers reject without
        # HTTPS — including over localhost in some browsers).
        secure=_BEHIND_PROXY,
        samesite="None" if _BEHIND_PROXY else "Lax",
        path="/",
    )
    return resp


@auth_bp.route("/me")
def auth_me():
    """Identity + active_claim(s). Anonymous gets a null-filled shape so the
    SPA reads a uniform schema regardless of auth state."""
    user = auth_service.current_user()
    dev_mode = auth_service.is_dev_mode()
    if user is None:
        return jsonify({
            "login": None,
            "hf_user_id": None,
            "role": None,
            "active_claim": None,
            "active_claims": [],
            "dev_mode": dev_mode,
            # Anonymous still holds whatever anon-eligible capabilities the
            # owner left on (e.g. view.catalog) — the FE gates on this list.
            "capabilities": cap_service.capabilities_for(None),
        })
    # Page-entry recency: /api/me runs on every SPA load / focus, so this is
    # debounced (at most one write per user per window) and best-effort — a
    # failure here must never break identity resolution.
    try:
        visitor_service.maybe_touch_entry(user.hf_user_id)
    except Exception:  # noqa: BLE001
        logger.exception("auth.me: maybe_touch_entry failed (continuing)")

    active_claims = [
        r.slug for r in state_service.all_rows()
        if r.state == ReciterState.UNDER_REVIEW
        and r.assignee_hf_id == user.hf_user_id
    ]
    role_val = user.role.value if hasattr(user.role, "value") else user.role
    return jsonify({
        "login": user.login,
        "hf_user_id": user.hf_user_id,
        "role": role_val,
        "active_claim": active_claims[0] if active_claims else None,
        "active_claims": active_claims,
        "dev_mode": dev_mode,
        # Resolved capability ids the caller currently holds — recomputed fresh
        # per request (role + matrix are never cookied), so an owner's toggle
        # reflects on this caller's next /api/me with no restart.
        "capabilities": cap_service.capabilities_for(user),
    })
