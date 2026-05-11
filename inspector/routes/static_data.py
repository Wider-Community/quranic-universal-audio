"""Static-data routes (/api/static/*).

Read-only JSON projections of in-memory services for the frontend. Uses
short ``Cache-Control`` so updates propagate within a few minutes without
needing explicit cache-busting on the client side.

Today this only carries the catalog endpoint that backs the Timestamps
tab's reciter dropdown migration off the legacy ``manifest.json.gz``
(D20 Track B). Future static reads (audio_meta, derived indices, …) can
land here too.
"""
from __future__ import annotations

from flask import Blueprint, Response, jsonify

from services import catalog as catalog_service

static_bp = Blueprint("static_data", __name__, url_prefix="/api/static")


# Catalog is updated infrequently (maintainer admin actions); 5 minutes is
# long enough to absorb most repeat reads within a session and short enough
# that catalog edits show up without manual cache-busting.
_CATALOG_CACHE_CONTROL = "public, max-age=300"


@static_bp.route("/catalog.json")
def catalog_json() -> Response:
    """Serve the in-memory ``ReciterCatalog`` snapshot as JSON.

    Shape matches ``scripts.lib.schemas.ReciterCatalog`` — the frontend
    reads ``reciters[]`` + ``deliveries[]`` to build the Timestamps tab
    reciter dropdown.
    """
    snapshot = catalog_service.snapshot()
    body = snapshot.model_dump(mode="json", by_alias=True)
    response = jsonify(body)
    response.headers["Cache-Control"] = _CATALOG_CACHE_CONTROL
    return response
