"""The automation reconciler daemon — one tick, one background loop.

``tick()`` runs every enabled evaluator once against the live state. The loop
(opt-in via ``INSPECTOR_AUTOMATIONS=1``, wired in ``app.py``) calls it every
``AUTOMATION_INTERVAL_SECONDS``. Single daemon thread in the single gunicorn
worker — no change to the single-worker invariant. A tick that finds nothing to
do performs zero DB writes (no bucket upload).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime

from config import AUTOMATION_INTERVAL_SECONDS

from . import evaluators

logger = logging.getLogger(__name__)

_background_thread: threading.Thread | None = None


def tick() -> None:
    """Run all evaluators once against the current config + state."""
    evaluators.run_all(datetime.now(UTC))


def start_background_loop(interval_seconds: int | None = None) -> threading.Thread:
    """Spawn the reconciler thread. Idempotent — returns the existing thread if
    one is already alive.

    Daemon thread (dies with the process); a single tick failure is caught and
    logged so one hiccup never kills the loop.
    """
    global _background_thread
    if _background_thread is not None and _background_thread.is_alive():
        return _background_thread

    every = interval_seconds or AUTOMATION_INTERVAL_SECONDS

    def _loop() -> None:
        logger.info("automation: reconciler loop started (interval=%ss)", every)
        while True:
            try:
                tick()
            except Exception:  # noqa: BLE001 — never let a tick kill the loop
                logger.exception("automation: tick errored")
            time.sleep(every)

    t = threading.Thread(target=_loop, daemon=True, name="automation")
    t.start()
    _background_thread = t
    return t


def is_background_loop_running() -> bool:
    return _background_thread is not None and _background_thread.is_alive()
