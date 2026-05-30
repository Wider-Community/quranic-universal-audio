"""Static-data routes (/api/static/*).

Read-only projections of in-memory services for the frontend. Each route
picks its own cache discipline:

- ``/catalog.json`` — short TTL; catalog edits should propagate quickly.
- ``/quran-refs.json`` — immutable + content-hashed; reference data is
  fixed across users / reciters / sessions and only changes on a rebuild.
- ``/quran-refs/version`` — tiny version probe, no-cache; FE polls once at
  app boot to learn the current hash and cache-bust the payload URL.
"""
from __future__ import annotations

import orjson
from flask import Blueprint, Response, jsonify

from services import catalog as catalog_service
from services import db as db_service
from services import quran_refs as quran_refs_service
from services.storage import cache

static_bp = Blueprint("static_data", __name__, url_prefix="/api/static")


# Catalog is updated infrequently (maintainer admin actions); 5 minutes is
# long enough to absorb most repeat reads within a session and short enough
# that catalog edits show up without manual cache-busting.
_CATALOG_CACHE_CONTROL = "public, max-age=300"

# Quran-refs payload is content-hashed; immutable means the browser never
# revalidates within the cache lifetime, and the FE busts via ``?v=<hash>``
# on the rare deploy that rebuilds Digital Khatt or surah metadata.
_QURAN_REFS_CACHE_CONTROL = "public, max-age=31536000, immutable"


@static_bp.route("/catalog.json")
def catalog_json() -> Response:
    """Serve the in-memory ``ReciterCatalog`` snapshot as JSON.

    Shape matches ``scripts.lib.schemas.ReciterCatalog`` — the frontend
    reads ``reciters[]`` + ``deliveries[]`` to build the Timestamps tab
    reciter dropdown.
    """
    # Byte-cache keyed on db_seq: the snapshot model is already db_seq-cached,
    # but the model_dump + serialize ran per request. Hand back cached bytes on
    # a warm hit; rebuild only when a committed write has bumped db_seq.
    seq = db_service.current_db_seq()
    body = cache.get_catalog_json_bytes_cache(seq)
    if body is None:
        snapshot = catalog_service.snapshot()
        body = orjson.dumps(snapshot.model_dump(mode="json", by_alias=True))
        cache.set_catalog_json_bytes_cache(seq, body)
    response = Response(body, mimetype="application/json")
    response.headers["Cache-Control"] = _CATALOG_CACHE_CONTROL
    return response


@static_bp.route("/quran-refs/version")
def quran_refs_version() -> Response:
    """Return the current Quran-refs payload hash for cache busting."""
    response = jsonify({"version": quran_refs_service.payload_hash()})
    response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@static_bp.route("/quran-refs.json")
def quran_refs_json() -> Response:
    """Serve the dk_words + verse_word_counts bundle.

    Bytes are computed once at module scope (see
    ``services/quran_refs.py``); each request just hands them back with
    immutable cache headers + an ETag matching the version endpoint.
    """
    body = quran_refs_service.build_payload()
    digest = quran_refs_service.payload_hash()
    response = Response(body, mimetype="application/json")
    response.headers["Cache-Control"] = _QURAN_REFS_CACHE_CONTROL
    response.headers["ETag"] = f'"{digest}"'
    return response
