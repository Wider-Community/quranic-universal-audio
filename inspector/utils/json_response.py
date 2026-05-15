"""Fast JSON responses via ``orjson``.

Drop-in replacement for ``flask.jsonify`` on the big-payload routes
(``/seg/all``, ``/seg/validate``, ``/seg/stats``, ``/seg/edit-history``)
where stdlib ``json`` encoding is ~6-10x slower than ``orjson``. Also
the only place to set ``Cache-Control`` (or other custom headers) on
those routes without breaking the JSON contract.
"""

from collections.abc import Mapping
from typing import Any

import orjson
from flask import Response


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
