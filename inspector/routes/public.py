"""Public read-only endpoints powering the Phase 6 dashboard.

All responses are public — no authentication required, no per-user
predicates included. Assignee identity is redacted in
``services/public_state`` before the data ever reaches this layer.

Endpoints emit ``Cache-Control: public, max-age=30`` so a CDN front or a
returning visitor can absorb repeat requests; per-call work is cheap (every
reciter lives in memory after the bucket hydrate at boot).

Slice B of phase 6.
"""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from services import public_state as public_state_service
from services import search_normalize as search_normalize_service


public_bp = Blueprint("public", __name__, url_prefix="/api/public")


_LIST_CACHE = "public, max-age=30"

_VALID_BUCKETS = {
    "available_for_request",
    "requested",
    "available_for_review",
    "under_review",
    "publishing",
    "published",
}

_VALID_SORTS = {"recent", "alphabetical", "deliveries"}


def _with_cache(payload, cache: str):
    """Attach a Cache-Control header to a jsonify() response."""
    resp: Response = jsonify(payload)
    resp.headers["Cache-Control"] = cache
    return resp


@public_bp.route("/stats")
def stats():
    """Counts per public bucket. Mutually exclusive at the reciter level."""
    return _with_cache(public_state_service.stats(), _LIST_CACHE)


@public_bp.route("/reciter/<reciter_id>")
def reciter_detail(reciter_id: str):
    """Single-reciter detail payload for the dashboard detail page.

    404 when the reciter_id is unknown or every delivery has been
    discarded (admin-only visibility).
    """
    public = public_state_service.detail(reciter_id)
    if public is None:
        return jsonify({"error": "reciter not found"}), 404
    return _with_cache(public, "public, max-age=60")


@public_bp.route("/reciters")
def reciters():
    """Paginated reciter list.

    Query parameters:
    - ``bucket`` — filter to reciters whose ``primary_bucket`` matches.
      Repeat the parameter to OR multiple buckets.
    - ``search`` — Arabic-normalized substring match against reciter name.
    - ``sort`` — ``recent`` (default) | ``alphabetical`` | ``deliveries``.
    - ``cursor`` — opaque pagination cursor (integer offset).
    - ``limit`` — page size; defaults to 50, max 200.
    """
    buckets = set(request.args.getlist("bucket"))
    invalid = buckets - _VALID_BUCKETS
    if invalid:
        return jsonify({
            "error": f"invalid bucket(s): {sorted(invalid)!r}",
        }), 400

    search = (request.args.get("search") or "").strip()
    sort = (request.args.get("sort") or "recent").strip()
    if sort not in _VALID_SORTS:
        return jsonify({
            "error": f"invalid sort: {sort!r}; must be one of {sorted(_VALID_SORTS)!r}",
        }), 400

    try:
        cursor = int(request.args.get("cursor") or 0)
    except ValueError:
        return jsonify({"error": "cursor must be an integer"}), 400
    if cursor < 0:
        return jsonify({"error": "cursor must be >= 0"}), 400

    try:
        limit = int(request.args.get("limit") or 50)
    except ValueError:
        return jsonify({"error": "limit must be an integer"}), 400
    if limit < 1 or limit > 200:
        return jsonify({"error": "limit must be between 1 and 200"}), 400

    rows = public_state_service.all_public_reciters()

    if buckets:
        rows = [r for r in rows if r["primary_bucket"] in buckets]

    if search:
        rows = [r for r in rows if search_normalize_service.matches(r["name"], search)]

    if sort == "recent":
        # Most-recently active first; reciters with no activity sink to bottom.
        rows.sort(
            key=lambda r: (r["last_activity"] is not None, r["last_activity"] or ""),
            reverse=True,
        )
    elif sort == "alphabetical":
        rows.sort(key=lambda r: search_normalize_service.normalize_arabic(r["name"]))
    elif sort == "deliveries":
        rows.sort(key=lambda r: r["deliveries_count"], reverse=True)

    total = len(rows)
    page = rows[cursor : cursor + limit]
    next_cursor = cursor + limit if cursor + limit < total else None

    return _with_cache({
        "reciters": page,
        "total": total,
        "next_cursor": next_cursor,
    }, _LIST_CACHE)
