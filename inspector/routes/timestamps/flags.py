"""Public Timestamps-tab verse-flag routes (``/api/ts/<slug>/flags``).

Any visitor — including anonymous — flags the verse currently playing on a
published recitation and leaves an optional comment about its alignment. A
verse accumulates one comment per identity (signed-in ``hf_user_id`` or an
anonymous browser ``anon_token``), all globally viewable. A new comment fans a
notification out to review-alert recipients (owners by default).

Gated by ``timestamps.flag`` (anon-eligible, open by default — an owner can
revoke it from the Permissions tab). Comment-author identity in the GET
response is gated by ``timestamps.see_flagger_identity`` (owner-default).
Writes wrap ``sync.durable_transaction``; mutations require a same-origin POST.
"""

from __future__ import annotations

import logging
import re

from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from qua_shared.schemas.wire.ts_flags import (
    TsFlagAuthor,
    TsFlagComment,
    TsFlagCreateRequest,
    TsFlagVerseCount,
    TsReciterFlags,
    TsVerseFlags,
)
from services import auth as auth_service
from services.auth import capabilities as cap_service
from services.db import _serde, repo_ts_flags
from services.db import sync as _sync
from services.notifications import emit as _notify
from services.permissions import role_of
from utils.decorators import require_same_origin

logger = logging.getLogger(__name__)

ts_flags_bp = Blueprint("ts_flags", __name__, url_prefix="/api/ts")

_FLAG_CAP = "timestamps.flag"
_IDENTITY_CAP = "timestamps.see_flagger_identity"
_VERSE_KEY_RE = re.compile(r"^\d{1,3}:\d{1,3}$")


def _comment_view(row: dict, *, mine: bool, show_author: bool) -> TsFlagComment:
    author = None
    if show_author:
        author = TsFlagAuthor(
            hf_user_id=row["hf_user_id"],
            login=row["login_at_time"],
            role=row["role_at_time"],
        )
    return TsFlagComment(
        comment=row["comment"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        mine=mine,
        author=author,
    )


def _is_mine(row: dict, *, hf_user_id: str | None, anon_token: str | None) -> bool:
    if hf_user_id is not None:
        return row["hf_user_id"] == hf_user_id
    if anon_token:
        return row["anon_token"] == anon_token
    return False


@ts_flags_bp.route("/<slug>/flags", methods=["GET"])
def get_reciter_flags(slug: str):
    """Flagged-verse pills + counts for the accordion. Public read."""
    try:
        counts = repo_ts_flags.verse_counts(slug)
        resp = TsReciterFlags(flags=[TsFlagVerseCount(**c) for c in counts])
        return jsonify(resp.model_dump(mode="json"))
    except Exception:  # noqa: BLE001
        logger.exception("ts_flags.get_reciter_flags failed for %s", slug)
        return jsonify({"error": "failed to load flags"}), 500


@ts_flags_bp.route("/<slug>/flags/<verse_key>", methods=["GET"])
def get_verse_flags(slug: str, verse_key: str):
    """All comments on a verse. Public read; author shown only to
    identity-capable callers. ``mine`` matched by cookie or ``?anon_token=``."""
    try:
        user = auth_service.current_user()
        show_author = cap_service.can(user, _IDENTITY_CAP)
        hf_user_id = user.hf_user_id if user is not None else None
        anon_token = request.args.get("anon_token") if user is None else None
        rows = repo_ts_flags.list_for_verse(slug, verse_key)
        comments = [
            _comment_view(
                r,
                mine=_is_mine(r, hf_user_id=hf_user_id, anon_token=anon_token),
                show_author=show_author,
            )
            for r in rows
        ]
        return jsonify(TsVerseFlags(verse_key=verse_key, comments=comments).model_dump(mode="json"))
    except Exception:  # noqa: BLE001
        logger.exception("ts_flags.get_verse_flags failed for %s %s", slug, verse_key)
        return jsonify({"error": "failed to load flags"}), 500


@ts_flags_bp.route("/<slug>/flags", methods=["POST"])
@require_same_origin
def create_flag(slug: str):
    """Create or update the caller's flag on a verse. Anonymous allowed."""
    user = auth_service.current_user()
    if not cap_service.can(user, _FLAG_CAP):
        return jsonify({"error": "not available"}), 403
    try:
        req = TsFlagCreateRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError as e:
        return jsonify({"error": "invalid flag", "detail": e.errors(include_url=False)}), 400
    if not _VERSE_KEY_RE.match(req.verse_key):
        return jsonify({"error": "invalid verse_key"}), 400

    comment = (req.comment or "").strip() or None
    if user is not None:
        hf_user_id: str | None = user.hf_user_id
        anon_token: str | None = None
        login_at_time: str | None = user.login
        role_at_time: str | None = role_of(user).value
    else:
        anon = (req.anon_token or "").strip()
        if not anon:
            return jsonify({"error": "anon_token required for anonymous flags"}), 400
        hf_user_id, anon_token = None, anon
        login_at_time = role_at_time = None

    try:
        with _sync.durable_transaction():
            row, created = repo_ts_flags.upsert_flag(
                slug=slug,
                verse_key=req.verse_key,
                hf_user_id=hf_user_id,
                anon_token=anon_token,
                login_at_time=login_at_time,
                role_at_time=role_at_time,
                comment=comment,
            )
    except Exception:  # noqa: BLE001
        logger.exception("ts_flags.create_flag failed for %s %s", slug, req.verse_key)
        return jsonify({"error": "failed to save flag"}), 500

    if created:
        at_utc = _serde.to_iso(row["updated_at"])
        if at_utc is not None:
            _notify.notify_owners_ts_flag(
                slug=slug,
                verse_key=req.verse_key,
                comment=comment,
                author_id=hf_user_id,
                author_login=login_at_time,
                at_utc=at_utc,
            )

    show_author = cap_service.can(user, _IDENTITY_CAP)
    return jsonify(
        _comment_view(row, mine=True, show_author=show_author).model_dump(mode="json")
    ), (201 if created else 200)


@ts_flags_bp.route("/<slug>/flags/<verse_key>", methods=["DELETE"])
@require_same_origin
def delete_flag(slug: str, verse_key: str):
    """Delete the caller's own comment on a verse."""
    user = auth_service.current_user()
    if not cap_service.can(user, _FLAG_CAP):
        return jsonify({"error": "not available"}), 403
    if user is not None:
        hf_user_id: str | None = user.hf_user_id
        anon_token: str | None = None
    else:
        anon_token = (request.args.get("anon_token") or "").strip()
        if not anon_token:
            return jsonify({"error": "anon_token required"}), 400
        hf_user_id = None
    try:
        with _sync.durable_transaction():
            removed = repo_ts_flags.delete_flag(
                slug=slug,
                verse_key=verse_key,
                hf_user_id=hf_user_id,
                anon_token=anon_token,
            )
    except Exception:  # noqa: BLE001
        logger.exception("ts_flags.delete_flag failed for %s %s", slug, verse_key)
        return jsonify({"error": "failed to delete flag"}), 500
    return jsonify({"ok": removed})
