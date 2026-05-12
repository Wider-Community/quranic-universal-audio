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
from urllib.parse import urljoin, urlparse

from flask import Blueprint, jsonify, make_response, redirect, request, session

from scripts.lib.schemas import ReciterState

from services import auth as auth_service
from services import state as state_service

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


@auth_bp.route("/auth/login")
def auth_login():
    if not auth_service.is_oauth_configured():
        return jsonify({"error": "OAuth not configured on this deploy"}), 503
    return_to = _safe_return_path(request.args.get("return"))
    session["post_login_return"] = return_to
    oauth = auth_service.get_oauth()
    redirect_uri = _callback_url()
    logger.info(
        "auth.login url_root=%s host=%s scheme=%s redirect_uri=%s return=%s",
        request.url_root, request.host, request.scheme, redirect_uri, return_to,
    )
    return oauth.huggingface.authorize_redirect(redirect_uri)


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

    return_to = _safe_return_path(session.pop("post_login_return", "/"))
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
    """Identity + active_claim. Anonymous gets a null-filled shape so the
    SPA reads a uniform schema regardless of auth state."""
    user = auth_service.current_user()
    if user is None:
        return jsonify({
            "login": None,
            "hf_user_id": None,
            "role": None,
            "active_claim": None,
        })
    active_claim = next(
        (
            r.slug for r in state_service.all_rows()
            if r.state == ReciterState.UNDER_REVIEW
            and r.assignee_hf_id == user.hf_user_id
        ),
        None,
    )
    role_val = user.role.value if hasattr(user.role, "value") else user.role
    return jsonify({
        "login": user.login,
        "hf_user_id": user.hf_user_id,
        "role": role_val,
        "active_claim": active_claim,
    })
