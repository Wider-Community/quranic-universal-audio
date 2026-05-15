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
    max_age: int = 0,
) -> Response:
    """orjson + ETag-with-revalidation + 304 handling.

    Cheap path for endpoints whose cached payload is keyed on a reciter slug
    and invalidated on save (validate / stats / edit-history). Default is
    ``Cache-Control: private, max-age=0, must-revalidate`` so the browser
    always asks the server before reusing its cached body; the server-side
    cache + ETag short-circuit cheaply returns 304 when the body is unchanged.
    Pass ``max_age=N`` to opt into a stale window for genuinely static payloads.
    """
    body = orjson.dumps(payload)
    digest = hashlib.sha256(body).hexdigest()[:12]
    etag = f'"{digest}"'
    cache_control = (
        f"private, max-age={max_age}, must-revalidate"
        if max_age == 0
        else f"private, max-age={max_age}"
    )
    headers = {
        "Cache-Control": cache_control,
        "ETag": etag,
    }
    if request.headers.get("If-None-Match", "").strip() == etag:
        return Response(status=304, headers=headers)
    return Response(body, status=200, mimetype="application/json", headers=headers)
