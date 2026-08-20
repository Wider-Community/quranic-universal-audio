"""Email-notification preference routes.

- ``GET /api/me/email-preferences`` — load the caller's prefs. Resolves by HF
  cookie when signed in, else by ``?token=`` (an anonymous subscription's manage
  token), else returns defaults. Capability-gated but does NOT 401 anonymous —
  subscriptions are keyed by email, not the HF account.
- ``POST /api/me/email-preferences`` — upsert the prefs for the typed email.
  Mints a stable ``manage_token`` on first save and echoes it (the FE caches it).
- ``GET /api/email-unsubscribe?token=`` — one-click unsubscribe (turns every
  event off for that email) + a tiny confirmation page that links back into the
  app to re-manage.

All three route through the ``notify.email_subscriptions`` capability so an owner
can disable the feature (incl. for anonymous) from the Permissions tab. Writes
wrap ``sync.durable_transaction``.
"""

from __future__ import annotations

import html
import logging
import re
import secrets

from flask import Blueprint, Response, jsonify, request
from pydantic import ValidationError

import config
from qua_shared.schemas.wire.email_preferences import EmailPreferences, EmailPreferencesSaved
from services import auth as auth_service
from services.auth import capabilities as cap_service
from services.db import repo_email_subscriptions as repo_subs
from services.db import sync as _sync
from utils.decorators import require_same_origin

logger = logging.getLogger(__name__)

email_prefs_bp = Blueprint("email_prefs", __name__, url_prefix="/api")

_CAP = "notify.email_subscriptions"
#: Gates the owner-facing `owner_new_request` field specifically — separate
#: from `_CAP`, which just gates the feature existing at all.
_OWNER_REQUEST_CAP = "notify.owner_request_emails"

# Mirror of the FE `isValidEmail` — a single `@` with non-empty local + domain.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _saved_payload(row: dict) -> dict:
    """Flat prefs + manage_token, validated through the wire model."""
    return EmailPreferencesSaved(**row["prefs"], manage_token=row["manage_token"]).model_dump(
        mode="json"
    )


@email_prefs_bp.route("/me/email-preferences", methods=["GET"])
def get_email_preferences():
    """Load prefs by HF cookie (signed in) or by ``?token=`` (anonymous)."""
    user = auth_service.current_user()
    if not cap_service.can(user, _CAP):
        return jsonify({"error": "not available"}), 403
    try:
        row = None
        if user is not None:
            row = repo_subs.get_by_hf_user(user.hf_user_id)
        if row is None:
            token = request.args.get("token")
            if token:
                row = repo_subs.get_by_token(token)
        if row is None:
            return jsonify(EmailPreferences().model_dump(mode="json"))
        return jsonify(_saved_payload(row))
    except Exception:  # noqa: BLE001
        logger.exception("email_prefs.get failed")
        return jsonify({"error": "failed to load preferences"}), 500


@email_prefs_bp.route("/me/email-preferences", methods=["POST"])
@require_same_origin
def set_email_preferences():
    """Upsert prefs for the typed email; mint + echo the manage token."""
    user = auth_service.current_user()
    if not cap_service.can(user, _CAP):
        return jsonify({"error": "not available"}), 403
    try:
        prefs = EmailPreferences.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return jsonify({"error": "invalid preferences", "detail": e.errors(include_url=False)}), 400

    # Defense in depth: the FE hides this toggle for non-holders, but a direct
    # POST could still try to flip it — silently drop it rather than 403 the
    # whole save.
    if prefs.owner_new_request and not cap_service.can(user, _OWNER_REQUEST_CAP):
        prefs.owner_new_request = False

    email = repo_subs.normalize_email(prefs.email)
    if not _EMAIL_RE.match(email):
        return jsonify({"error": "a valid email address is required"}), 400

    try:
        with _sync.durable_transaction():
            existing = repo_subs.get_by_email(email)
            token = existing["manage_token"] if existing else secrets.token_urlsafe(24)
            row = repo_subs.upsert(
                email=email,
                hf_user_id=user.hf_user_id if user is not None else None,
                prefs=prefs.model_dump(mode="json"),
                new_token=token,
            )
    except Exception:  # noqa: BLE001
        logger.exception("email_prefs.set failed")
        return jsonify({"error": "failed to save preferences"}), 500
    return jsonify(_saved_payload(row))


@email_prefs_bp.route("/email-unsubscribe", methods=["GET"])
def email_unsubscribe():
    """One-click unsubscribe by token + a confirmation page. Public (the token
    is the secret); idempotent and safe to re-hit."""
    token = request.args.get("token", "")
    ok = False
    if token:
        try:
            with _sync.durable_transaction():
                ok = repo_subs.unsubscribe_by_token(token) is not None
        except Exception:  # noqa: BLE001
            logger.exception("email_prefs.unsubscribe failed")
    return Response(_unsubscribe_page(ok, token), mimetype="text/html")


def _unsubscribe_page(ok: bool, token: str) -> str:
    site = html.escape(config.EMAIL_SITE_URL)
    manage = f"{config.EMAIL_APP_BASE_URL}/?manage={html.escape(token, quote=True)}"
    if ok:
        heading = "You're unsubscribed"
        msg = (
            "Assalamu Alaikum. You will no longer receive notification emails at "
            "this address. You can re-enable them any time from the site."
        )
    else:
        heading = "Link expired"
        msg = "This unsubscribe link is no longer valid. You can manage emails from the site."
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{heading}</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
         background:#0f0f23; color:#e8e8f0; margin:0;
         display:flex; min-height:100vh; align-items:center; justify-content:center; }}
  .card {{ max-width:440px; padding:32px; background:#16213e; border-radius:10px;
          border:1px solid #2a3a5e; }}
  h1 {{ font-size:20px; margin:0 0 12px; }}
  p {{ font-size:14px; line-height:1.6; color:#b8b8c8; margin:0 0 20px; }}
  a {{ display:inline-block; color:#5fd0e0; text-decoration:none; font-size:14px; }}
  a.manage {{ margin-right:16px; }}
</style></head>
<body><div class="card">
  <h1>{heading}</h1>
  <p>{msg}</p>
  <a class="manage" href="{html.escape(manage, quote=True)}">Manage preferences</a>
  <a href="{site}">Open Quranic Universal Audio</a>
</div></body></html>"""
