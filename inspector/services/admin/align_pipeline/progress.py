"""In-process live detail + cancel flags per run.

The DB row changes only on stage transitions (each durable write pushes the whole
database to the bucket); everything finer — the chapter being aligned, the
aligner's stage name, the beam being probed — lives here and is rebuilt from the
staged files after a restart.
"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_detail: dict[str, dict] = {}
_cancel: set[str] = set()


class Canceled(Exception):
    """Raised inside a worker when the run was canceled between steps."""


def set_detail(run_id: str, **fields) -> None:
    with _lock:
        _detail.setdefault(run_id, {}).update(fields)


def clear_detail(run_id: str) -> None:
    with _lock:
        _detail.pop(run_id, None)


def get_detail(run_id: str) -> dict:
    with _lock:
        return dict(_detail.get(run_id, {}))


def request_cancel(run_id: str) -> None:
    with _lock:
        _cancel.add(run_id)


def cancel_requested(run_id: str) -> bool:
    with _lock:
        return run_id in _cancel


def clear_cancel(run_id: str) -> None:
    with _lock:
        _cancel.discard(run_id)


def check_cancel(run_id: str) -> None:
    if cancel_requested(run_id):
        raise Canceled(run_id)


def _reset_for_tests() -> None:
    with _lock:
        _detail.clear()
        _cancel.clear()
