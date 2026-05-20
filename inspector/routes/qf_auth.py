"""Quran.Foundation OAuth2 routes (pre-prod, user APIs).

Thin: parse → service → redirect/jsonify. The real authorization_code + PKCE
flow is wired here; it completes once a redirect URI is registered on the QF
pre-prod client. A dev-only stub login (``INSPECTOR_DEV_MODE``) mints a
synthetic session so the bookmarks proxy is demonstrable before then.
"""

from __future__ import annotations

import logging

from flask import Blueprint, abort, jsonify, make_response, redirect, request

from services.auth.auth import is_dev_mode
from services.quran_foundation import config as qf_config
from services.quran_foundation import oauth, session
from utils.decorators import require_same_origin

logger = logging.getLogger(__name__)

qf_auth_bp = Blueprint("qf_auth", __name__, url_prefix="/api/qf")


def _secure_cookie() -> bool:
    return request.scheme == "https"


def _set_cookie(resp, name: str, value: str, max_age: int) -> None:
    resp.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        samesite="Lax",
        secure=_secure_cookie(),
        path="/",
    )


@qf_auth_bp.route("/login", methods=["GET"])
def qf_login():
    """Begin the OAuth2 flow: stash PKCE+state, redirect to QF consent."""
    if not qf_config.is_configured():
        return jsonify({"error": "Quran.Foundation client not configured"}), 503
    pkce = oauth.new_pkce()
    state = oauth.new_state()
    nonce = oauth.new_state()
    url = oauth.build_authorize_url(
        state=state, nonce=nonce, code_challenge=pkce.challenge
    )
    resp = make_response(redirect(url))
    tmp = session.encode_oauth_tmp({"state": state, "verifier": pkce.verifier})
    _set_cookie(resp, session.QF_OAUTH_TMP_COOKIE_NAME, tmp, session.QF_OAUTH_TMP_MAX_AGE)
    return resp


@qf_auth_bp.route("/callback", methods=["GET"])
def qf_callback():
    """Finish the OAuth2 flow: validate state, exchange code, mint session."""
    err = request.args.get("error")
    if err:
        logger.warning("QF callback error: %s", request.args.get("error_description", err))
        return redirect("/?qf_error=1")
    code = request.args.get("code", "")
    state = request.args.get("state", "")
    tmp = session.decode_oauth_tmp(request.cookies.get(session.QF_OAUTH_TMP_COOKIE_NAME, ""))
    if not code or not tmp or tmp.get("state") != state:
        return redirect("/?qf_error=state")
    try:
        token = oauth.exchange_code(code=code, code_verifier=tmp.get("verifier", ""))
    except oauth.QfOAuthError as e:
        logger.warning("QF token exchange failed: %s", e)
        return redirect("/?qf_error=token")
    resp = make_response(redirect("/?qf_connected=1"))
    _set_cookie(
        resp,
        session.QF_SESSION_COOKIE_NAME,
        session.session_from_token(token),
        session.QF_SESSION_MAX_AGE,
    )
    # Clear the short-lived PKCE cookie.
    resp.delete_cookie(session.QF_OAUTH_TMP_COOKIE_NAME, path="/")
    return resp


@qf_auth_bp.route("/logout", methods=["POST"])
@require_same_origin
def qf_logout():
    resp = make_response(jsonify({"ok": True}))
    resp.delete_cookie(session.QF_SESSION_COOKIE_NAME, path="/")
    return resp


@qf_auth_bp.route("/status", methods=["GET"])
def qf_status():
    payload = session.decode_session(request.cookies.get(session.QF_SESSION_COOKIE_NAME, ""))
    if not payload:
        return jsonify({"connected": False})
    return jsonify({
        "connected": True,
        "login": payload.get("login"),
        "dev": bool(payload.get("dev")),
    })


@qf_auth_bp.route("/dev-login", methods=["POST"])
@require_same_origin
def qf_dev_login():
    """Dev-only: mint a synthetic qf_session so the bookmarks proxy wiring is
    demonstrable without the real OAuth flow. 404s outside dev mode."""
    if not is_dev_mode():
        abort(404)
    payload = {
        "access_token": "",
        "refresh_token": "",
        "expires_at": 2**31,
        "login": "dev-qf-user",
        "dev": True,
    }
    resp = make_response(jsonify({"ok": True, "dev": True}))
    _set_cookie(
        resp,
        session.QF_SESSION_COOKIE_NAME,
        session.encode_session(payload),
        session.QF_SESSION_MAX_AGE,
    )
    return resp
