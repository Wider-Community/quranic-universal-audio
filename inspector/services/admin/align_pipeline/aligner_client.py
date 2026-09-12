"""HTTP client for the aligner Space's extraction surfaces (``/api/v1``).

Three calls: create an alignment-only batch, stream one chapter item by bucket
reference, stream the reciter-wide sidecars run. Every streamed call is SSE:
``progress`` events feed ``on_progress``, ``result`` is returned, ``error`` raises
``AlignerError`` with the Space's stable error code.

Auth: the owner's HF token as bearer (ZeroGPU quota) plus the shared extraction
secret on the bucket-reference and sidecars routes.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

import requests
from requests.adapters import HTTPAdapter

from . import params as _params

log = logging.getLogger("inspector")

CONNECT_TIMEOUT_S = 60
#: A CPU-fallback Large alignment of a two-hour chapter can stay silent for a
#: long time between stage events; the Space sends keep-alive comments, so this
#: bounds a dead connection, not a slow stage.
ITEM_READ_TIMEOUT_S = 4 * 3600
SIDECARS_READ_TIMEOUT_S = 6 * 3600
CREATE_TIMEOUT_S = 120

ProgressFn = Callable[[dict], None]


class AlignerError(RuntimeError):
    """A non-2xx reply or an SSE ``error`` event, carrying the Space's code."""

    def __init__(self, code: str, message: str, status: int | None = None):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.status = status


class AlignerClient:
    def __init__(self, *, base_url: str | None = None, session: requests.Session | None = None):
        self.base_url = (base_url or _params.aligner_url()).rstrip("/") + "/api/v1"
        self._session = session or requests.Session()
        self._session.headers["Authorization"] = f"Bearer {_params.hf_token()}"
        self._secret = _params.extraction_secret()

    def widen_pool(self, connections: int) -> None:
        """Size the HTTPS connection pool to the fan-out about to hit the Space.

        urllib3 pools 10 per host by default and *discards* the surplus, so a
        wide align stage would otherwise reconnect per chapter and log a warning
        for each one.
        """
        if connections <= 10:
            return
        adapter = HTTPAdapter(pool_connections=connections, pool_maxsize=connections)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)

    # -- batches -------------------------------------------------------------

    def create_batch(self, body: dict) -> tuple[str, int]:
        """Create an alignment-only batch. Returns ``(batch_id, max_in_flight)``."""
        resp = self._session.post(f"{self.base_url}/batches", json=body, timeout=CREATE_TIMEOUT_S)
        _raise_for_status(resp)
        doc = resp.json()
        return doc["batch_id"], int(doc.get("max_in_flight") or 1)

    def align_item(
        self, batch_id: str, chapter: int, audio_ref: str, on_progress: ProgressFn | None = None
    ) -> dict:
        """Stream one chapter item by bucket reference; return the aligner's result body."""
        with self._session.post(
            f"{self.base_url}/batches/{batch_id}/items/{chapter}/audio/stream",
            data={"audio_ref": audio_ref},
            headers={"X-Extraction-Secret": self._secret},
            stream=True,
            timeout=(CONNECT_TIMEOUT_S, ITEM_READ_TIMEOUT_S),
        ) as resp:
            _raise_for_status(resp)
            return _consume_sse(resp, on_progress)

    # -- sidecars ------------------------------------------------------------

    def sidecars(self, body: dict, on_progress: ProgressFn | None = None) -> dict:
        with self._session.post(
            f"{self.base_url}/extraction/sidecars",
            json=body,
            headers={"X-Extraction-Secret": self._secret},
            stream=True,
            timeout=(CONNECT_TIMEOUT_S, SIDECARS_READ_TIMEOUT_S),
        ) as resp:
            _raise_for_status(resp)
            return _consume_sse(resp, on_progress)


def _raise_for_status(resp: requests.Response) -> None:
    if resp.status_code < 400:
        return
    try:
        body = resp.json()
    except ValueError:
        body = {}
    code = body.get("code") or f"http_{resp.status_code}"
    message = body.get("message") or (resp.text or "")[:300]
    raise AlignerError(code, message, resp.status_code)


def _consume_sse(resp: requests.Response, on_progress: ProgressFn | None) -> dict:
    """Walk an SSE stream to its ``result`` event. Comments (keep-alives) are skipped."""
    event = "message"
    for line in resp.iter_lines(decode_unicode=True):
        raw = line.decode("utf-8") if isinstance(line, bytes) else line
        if not raw or raw.startswith(":"):
            continue
        if raw.startswith("event:"):
            event = raw[6:].strip()
            continue
        if not raw.startswith("data:"):
            continue
        data = json.loads(raw[5:].strip() or "{}")
        if event == "result":
            return data
        if event == "error":
            raise AlignerError(
                data.get("code") or "error", data.get("message") or "", data.get("status")
            )
        if event == "progress" and on_progress is not None:
            on_progress(data)
    raise AlignerError("stream_ended", "the aligner closed the stream without a result")
