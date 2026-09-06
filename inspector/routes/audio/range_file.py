"""Large-chunk Range streaming for bucket-mounted audio files.

Why not ``send_file(conditional=True)``: on a ``Range`` request Werkzeug wraps
the file in ``_RangeWrapper(wrap_file(environ, f))`` and the WSGI server's
``FileWrapper`` then pulls the body in **8 KB** ``read()`` calls. On the
deployed Space the bucket is an NFS mount, so every 8 KB read is a network
round trip — measured at ~100–200 KB/s per stream on prod, i.e. a 4 MB
chapter buffers for ~30 s and a few concurrent ``<audio>`` Range fetches
saturate the mount (``OSError: [Errno 5] I/O error`` in the worker log).

This module serves the same 200 / 206 / 416 semantics with a single
``seek`` + ``read(_CHUNK_BYTES)`` loop, cutting the NFS round trips by
~128×. Files are immutable (``Cache-Control: immutable`` upstream), so a
weak ETag derived from ``(mtime, size)`` is enough for ``If-None-Match`` /
``If-Range`` handling.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from flask import Request, Response
from werkzeug.http import parse_range_header

# 1 MB per read: large enough that NFS readahead runs at line rate, small
# enough that a paused ``<audio>`` element doesn't pin tens of MB per thread.
_CHUNK_BYTES = 1024 * 1024


def _iter_file(path: Path, start: int, length: int) -> Iterator[bytes]:
    """Yield ``length`` bytes of ``path`` from ``start`` in ``_CHUNK_BYTES`` reads."""
    remaining = length
    with path.open("rb") as fh:
        fh.seek(start)
        while remaining > 0:
            chunk = fh.read(min(_CHUNK_BYTES, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def file_etag(path: Path, stat: os.stat_result | None = None) -> str:
    """Weak-but-sufficient ETag for an immutable bucket file."""
    st = stat or path.stat()
    return f'"{int(st.st_mtime)}-{st.st_size}"'


def send_range_file(req: Request, path: Path, mimetype: str) -> Response:
    """Serve ``path`` honouring ``Range`` / ``If-Range`` / ``If-None-Match``.

    Returns:
    * ``304`` when ``If-None-Match`` matches (no Range).
    * ``206`` with ``Content-Range`` for a satisfiable single range. A
      stale ``If-Range`` falls back to the full body, per RFC 9110 §13.1.5.
    * ``416`` with ``Content-Range: bytes */<size>`` for an unsatisfiable range.
    * ``200`` full body otherwise.

    Every response carries ``Accept-Ranges: bytes``, ``ETag`` and
    ``Content-Length``; callers layer caching / CORS / disposition headers on top.
    """
    st = path.stat()
    size = st.st_size
    etag = file_etag(path, st)
    base = {"Accept-Ranges": "bytes", "ETag": etag}

    range_header = req.headers.get("Range")
    if_range = req.headers.get("If-Range")
    if range_header and (not if_range or if_range == etag):
        rng = parse_range_header(range_header)
        span = rng.range_for_length(size) if rng is not None else None
        if span is None:
            return Response(status=416, headers={**base, "Content-Range": f"bytes */{size}"})
        start, end = span  # end is exclusive
        return Response(
            _iter_file(path, start, end - start),
            status=206,
            mimetype=mimetype,
            headers={
                **base,
                "Content-Length": str(end - start),
                "Content-Range": f"bytes {start}-{end - 1}/{size}",
            },
            direct_passthrough=True,
        )

    if req.if_none_match.contains_raw(etag):
        return Response(status=304, headers=base)

    return Response(
        _iter_file(path, 0, size),
        status=200,
        mimetype=mimetype,
        headers={**base, "Content-Length": str(size)},
        direct_passthrough=True,
    )
