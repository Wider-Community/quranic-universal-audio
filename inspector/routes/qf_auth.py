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


def _callback_url() -> str:
    """Derive the OAuth callback from the current request host so the same
    value is used on localhost and the deployed Space (the pre-prod client
    accepts any redirect URI). Falls back to the configured default."""
    root = request.host_url.rstrip("/")
    if root:
        return f"{root}/api/qf/callback"
    return qf_config.redirect_uri()


def _set_cookie(resp, name: str, value: str, max_age: int) -> None:
    # The OAuth round-trip returns from a different site (prelive.auth.quran.com)
    # and the deployed app may run inside the huggingface.co iframe — both are
    # cross-site contexts where only SameSite=None;Secure cookies are sent.
    # Mirror the app's HF-OAuth state cookie policy (app.py SESSION_COOKIE_SAMESITE).
    https = _secure_cookie()
    resp.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        samesite="None" if https else "Lax",
        secure=https,
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
    redirect_uri = _callback_url()
    url = oauth.build_authorize_url(
        state=state, nonce=nonce, code_challenge=pkce.challenge, redirect_uri=redirect_uri
    )
    resp = make_response(redirect(url))
    tmp = session.encode_oauth_tmp(
        {
            "state": state,
            "verifier": pkce.verifier,
            "redirect_uri": redirect_uri,
            "popup": request.args.get("popup") == "1",
        }
    )
    _set_cookie(resp, session.QF_OAUTH_TMP_COOKIE_NAME, tmp, session.QF_OAUTH_TMP_MAX_AGE)
    return resp


def _popup_close_html(status: str) -> str:
    """Page returned to the popup after auth.

    If it's a real popup, signal the opener and close. If the browser turned
    the popup into a same-tab navigation (e.g. inside the huggingface.co
    iframe), there's no opener to close — so redirect back into the app instead
    of dead-ending on a "you can close this window" page."""
    target = "/?qf_connected=1" if status == "connected" else "/?qf_error=1"
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Quran.Foundation</title></head>"
        "<body><p style='font-family:sans-serif;color:#444'>Connecting…</p>"
        "<script>(function(){"
        "var status=" + repr(status) + ";var target=" + repr(target) + ";"
        "function go(){try{window.location.replace(target);}catch(e){}}"
        "try{if(window.opener&&window.opener!==window){"
        "window.opener.postMessage({type:'qf-auth',status:status},window.location.origin);"
        "window.close();setTimeout(go,600);}else{go();}}catch(e){go();}"
        "})();</script></body></html>"
    )


def _finish(popup: bool, status: str, redirect_to: str):
    """Build the callback response: a self-closing page for popup mode, else a
    redirect back into the SPA."""
    if popup:
        return make_response(_popup_close_html(status))
    return make_response(redirect(redirect_to))


@qf_auth_bp.route("/callback", methods=["GET"])
def qf_callback():
    """Finish the OAuth2 flow: validate state, exchange code, mint session."""
    tmp = session.decode_oauth_tmp(request.cookies.get(session.QF_OAUTH_TMP_COOKIE_NAME, ""))
    popup = bool(tmp and tmp.get("popup"))
    err = request.args.get("error")
    if err:
        logger.warning("QF callback error: %s", request.args.get("error_description", err))
        return _finish(popup, "error", "/?qf_error=1")
    code = request.args.get("code", "")
    state = request.args.get("state", "")
    logger.info(
        "QF callback: popup=%s has_code=%s has_tmp=%s state_match=%s",
        popup,
        bool(code),
        bool(tmp),
        bool(tmp) and tmp.get("state") == state,
    )
    if not code or not tmp or tmp.get("state") != state:
        return _finish(popup, "error", "/?qf_error=state")
    try:
        token = oauth.exchange_code(
            code=code,
            code_verifier=tmp.get("verifier", ""),
            redirect_uri=tmp.get("redirect_uri", _callback_url()),
        )
    except oauth.QfOAuthError as e:
        logger.warning("QF token exchange failed: %s", e)
        return _finish(popup, "error", "/?qf_error=token")
    resp = _finish(popup, "connected", "/?qf_connected=1")
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
    return jsonify(
        {
            "connected": True,
            "login": payload.get("login"),
            "dev": bool(payload.get("dev")),
        }
    )


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
