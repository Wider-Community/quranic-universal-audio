"""Owner-triggered reachability probe for intake-request audio sources.

NOT on the submit path — an owner runs this from the review panel. Per-link
``HEAD`` (falling back to a 1-byte ranged ``GET`` for hosts that reject HEAD),
fanned out over a bounded ``ThreadPoolExecutor`` (SSL recv releases the GIL, so
wall-clock collapses from sum(serial) to ~max(slowest)). Playlist sources get a
single reachability check on the playlist URL — enumeration stays offline.

Returns a :class:`ProbeResponse`; the caller persists it onto the request row's
``payload.probe`` so the panel shows the last result without re-probing.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import requests

from qua_shared.schemas import ProbeResponse, ProbeResult
from qua_shared.schemas.intake_requests import IntakeSource

from services.db import _serde

logger = logging.getLogger(__name__)

_TIMEOUT_SECS = 6
_MAX_WORKERS = 8
# Only 2xx/3xx count as reachable; many CDNs answer HEAD with 403/405 even when
# a GET works, so we retry those with a 1-byte ranged GET before giving up.
_HEAD_RETRY_STATUSES = (403, 405, 501)
_HEADERS = {"User-Agent": "QUA-Inspector-intake-probe/1.0"}


def probe_source(source: IntakeSource) -> ProbeResponse:
    """Probe every direct link (or the single playlist URL) for reachability."""
    targets: list[tuple[int | None, str]]
    if source.method == "playlist":
        url = (source.playlist_url or "").strip()
        targets = [(None, url)] if url else []
    else:
        targets = [(ln.chapter, ln.url) for ln in source.links if (ln.url or "").strip()]

    results: list[ProbeResult] = []
    if targets:
        with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(targets))) as pool:
            results = list(pool.map(lambda t: _probe_one(t[0], t[1]), targets))

    # Stable order: chapter ascending, playlist (None) last.
    results.sort(key=lambda r: (r.chapter is None, r.chapter or 0))
    return ProbeResponse(at=_serde.to_iso(_serde.now()), results=results)


def _probe_one(chapter: int | None, url: str) -> ProbeResult:
    status = _request_status("HEAD", url)
    if status in _HEAD_RETRY_STATUSES or status is None:
        retry = _request_status("GET", url, ranged=True)
        if retry is not None:
            status = retry
    reachable = status is not None and 200 <= status < 400
    return ProbeResult(chapter=chapter, url=url, status=status, reachable=reachable)


def _request_status(method: str, url: str, *, ranged: bool = False) -> int | None:
    headers = dict(_HEADERS)
    if ranged:
        headers["Range"] = "bytes=0-0"
    try:
        resp = requests.request(
            method,
            url,
            headers=headers,
            timeout=_TIMEOUT_SECS,
            allow_redirects=True,
            stream=True,
        )
        try:
            return resp.status_code
        finally:
            resp.close()
    except requests.RequestException as exc:
        logger.debug("intake_probe %s %s failed: %s", method, url, exc)
        return None
