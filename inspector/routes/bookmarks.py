"""Bookmarks proxy routes (User API).

Returns ``[]`` (not 401) for anonymous callers so the frontend silently
stays in app-local mode. When a ``qf_session`` exists, proxies to QF
(``/auth/v1/bookmarks``) — or to the dev in-memory store for dev-stub
sessions.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from services.quran_foundation import bookmarks as bm
from services.quran_foundation import session
from utils.decorators import require_same_origin

logger = logging.getLogger(__name__)

bookmarks_bp = Blueprint("bookmarks", __name__, url_prefix="/api/bookmarks")


def _session():
    return session.decode_session(request.cookies.get(session.QF_SESSION_COOKIE_NAME, ""))


@bookmarks_bp.route("", methods=["GET"])
def list_bookmarks():
    sess = _session()
    if not sess:
        return jsonify({"bookmarks": [], "connected": False})
    try:
        if sess.get("dev"):
            items = bm.dev_list()
        else:
            items = bm.list_bookmarks(sess.get("access_token", ""))
    except bm.QfBookmarkError as e:
        logger.warning("QF bookmarks list failed: %s", e)
        return jsonify({"bookmarks": [], "connected": True, "error": "upstream"}), 502
    return jsonify({"bookmarks": items, "connected": True})


@bookmarks_bp.route("", methods=["POST"])
@require_same_origin
def add_bookmark():
    sess = _session()
    if not sess:
        return jsonify({"error": "not connected"}), 401
    body = request.get_json(silent=True) or {}
    try:
        surah = int(body.get("surah"))
        ayah = int(body.get("ayah"))
    except (TypeError, ValueError):
        return jsonify({"error": "surah and ayah required"}), 400
    try:
        item = bm.dev_add(surah, ayah) if sess.get("dev") else bm.add_bookmark(
            sess.get("access_token", ""), surah, ayah
        )
    except bm.QfBookmarkError as e:
        logger.warning("QF bookmark add failed: %s", e)
        return jsonify({"error": "upstream"}), 502
    return jsonify({"ok": True, "bookmark": item})


@bookmarks_bp.route("/<key>", methods=["DELETE"])
@require_same_origin
def remove_bookmark(key: str):
    sess = _session()
    if not sess:
        return jsonify({"error": "not connected"}), 401
    try:
        if sess.get("dev"):
            bm.dev_remove(key)
        else:
            bm.remove_bookmark(sess.get("access_token", ""), key)
    except bm.QfBookmarkError as e:
        logger.warning("QF bookmark remove failed: %s", e)
        return jsonify({"error": "upstream"}), 502
    return jsonify({"ok": True})
