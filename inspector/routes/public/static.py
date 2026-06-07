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

import re
from pathlib import Path

import orjson
from flask import Blueprint, Response, abort, jsonify, send_file

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

    Shape matches ``qua_shared.schemas.ReciterCatalog`` — the frontend
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


# Segments-guide example clips. Served here (not as a plain dist static asset)
# because on the deployed Space HF auto-LFS promotes the larger ``.mp3`` (by
# size, ~100 KB+), so the in-image ``dist/guide-audio/`` copy is a git-lfs
# pointer stub. The bucket (Xet-backed) always carries the real bytes, so we
# resolve local-dist-first then fall back to ``reference/guide-audio/``.
_GUIDE_AUDIO_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist" / "guide-audio"
_GUIDE_AUDIO_BUCKET_DIR = "reference/guide-audio"
_GUIDE_AUDIO_CACHE_CONTROL = "public, max-age=31536000, immutable"
_GUIDE_AUDIO_NAME_RE = re.compile(r"^[a-z0-9_]+\.mp3$")


def _is_lfs_pointer(p: Path) -> bool:
    """True if ``p`` is an unsmudged git-LFS pointer stub, not the real bytes."""
    try:
        with p.open("rb") as f:
            return f.read(40).startswith(b"version https://git-lfs")
    except OSError:
        return False


@static_bp.route("/guide-audio/<name>")
def guide_audio(name: str) -> Response:
    """Serve a segments-guide example mp3 clip (real bytes, never an LFS stub).

    Resolves the local ``dist/guide-audio/<name>`` first (real in dev / a
    correctly-shipped image), else the bucket ``reference/guide-audio/<name>``.
    """
    if not _GUIDE_AUDIO_NAME_RE.match(name):
        abort(404)
    local = _GUIDE_AUDIO_DIST / name
    if local.is_file() and not _is_lfs_pointer(local):
        resp = send_file(str(local), mimetype="audio/mpeg", conditional=True)
        resp.headers["Cache-Control"] = _GUIDE_AUDIO_CACHE_CONTROL
        return resp
    from services.storage.hf_bucket import get_backend

    try:
        body = get_backend().read_bytes(f"{_GUIDE_AUDIO_BUCKET_DIR}/{name}")
    except Exception:
        abort(404)
    resp = Response(body, mimetype="audio/mpeg")
    resp.headers["Cache-Control"] = _GUIDE_AUDIO_CACHE_CONTROL
    return resp
