"""Maintainer/owner catalog metadata editing endpoints."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from routes._admin_helpers import actor_for
from services.state import catalog as catalog_service
from utils.decorators import require_capability, require_same_origin

catalog_admin_bp = Blueprint("admin_catalog", __name__, url_prefix="/api/admin/catalog")

_RECITER_FIELDS = catalog_service.RECITER_EDITABLE_FIELDS
_DELIVERY_FIELDS = catalog_service.DELIVERY_EDITABLE_FIELDS


def _body_fields(allowed: frozenset[str]) -> tuple[dict, str | None, tuple | None]:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {}, None, (jsonify({"error": "JSON object required"}), 400)
    reason = body.get("reason")
    fields = {key: value for key, value in body.items() if key != "reason"}
    unknown = set(fields) - allowed
    if unknown:
        return (
            {},
            None,
            (
                jsonify({"error": f"unknown catalog field(s): {sorted(unknown)!r}"}),
                400,
            ),
        )
    if not fields:
        return (
            {},
            reason if isinstance(reason, str) else None,
            (
                jsonify({"error": "at least one catalog field is required"}),
                400,
            ),
        )
    return fields, reason if isinstance(reason, str) else None, None


def _error(exc: Exception):
    return jsonify({"error": str(exc)}), 400


@catalog_admin_bp.route("/reciter/<reciter_id>", methods=["PATCH"])
@require_same_origin
@require_capability("catalog.edit")
def edit_reciter(user, reciter_id: str):
    fields, reason, err = _body_fields(_RECITER_FIELDS)
    if err is not None:
        return err
    try:
        updated = catalog_service.edit_reciter_fields(
            actor=actor_for(user), reciter_id=reciter_id, fields=fields, reason=reason
        )
    except catalog_service.CatalogError as exc:
        return _error(exc)
    return jsonify({"ok": True, "reciter": updated.model_dump(mode="json")})


@catalog_admin_bp.route("/delivery/<slug>", methods=["PATCH"])
@require_same_origin
@require_capability("catalog.edit")
def edit_delivery(user, slug: str):
    fields, reason, err = _body_fields(_DELIVERY_FIELDS)
    if err is not None:
        return err
    try:
        updated = catalog_service.edit_delivery_fields(
            actor=actor_for(user), slug=slug, fields=fields, reason=reason
        )
    except catalog_service.CatalogError as exc:
        return _error(exc)
    return jsonify({"ok": True, "delivery": updated.model_dump(mode="json")})
