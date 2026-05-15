"""Fast JSON responses via ``orjson``.

Drop-in replacement for ``flask.jsonify`` on the big-payload routes
(``/seg/all``, ``/seg/validate``, ``/seg/stats``, ``/seg/edit-history``)
where stdlib ``json`` encoding is ~6-10x slower than ``orjson``. Also
the only place to set ``Cache-Control`` (or other custom headers) on
those routes without breaking the JSON contract.
"""

import hashlib
from collections.abc import Mapping
from typing import Any

import orjson
from flask import Response, request


def orjson_response(
    payload: Any,
    status: int = 200,
    headers: Mapping[str, str] | None = None,
) -> Response:
    """Encode *payload* with ``orjson`` and wrap in a Flask ``Response``."""
    resp = Response(
        orjson.dumps(payload),
        status=status,
        mimetype="application/json",
    )
    if headers:
        resp.headers.update(headers)
    return resp


def orjson_cached_response(
    payload: Any,
    *,
    max_age: int = 60,
) -> Response:
    """orjson + ``Cache-Control: private, max-age=N`` + ETag with 304 handling.

    Cheap path for endpoints whose cached payload is keyed on a reciter slug
    and invalidated on save (validate / stats / edit-history). The ETag is
    a sha256[:12] of the encoded body — stable as long as the upstream cache
    isn't invalidated. When ``If-None-Match`` matches, returns 304 with no
    body so the browser reuses its cached copy.
    """
    body = orjson.dumps(payload)
    digest = hashlib.sha256(body).hexdigest()[:12]
    etag = f'"{digest}"'
    headers = {
        "Cache-Control": f"private, max-age={max_age}",
        "ETag": etag,
    }
    if request.headers.get("If-None-Match", "").strip() == etag:
        return Response(status=304, headers=headers)
    return Response(body, status=200, mimetype="application/json", headers=headers)
