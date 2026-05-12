"""Health endpoints for liveness/readiness probes and ops dashboards.

Two routes share one blueprint:

- ``GET /healthz`` — readiness signal. Reports bucket mount + state hydration
  status. Returns HTTP 200 always (so the Space stays "running" even if the
  bucket is briefly unreachable); the body's ``status`` field is the truth.
  This is the endpoint the deploy-runbook §6 smoke tests poll.

- ``GET /livez``  — liveness signal. Always 200 with a tiny body. Use this if
  a future load-balancer wants a probe that doesn't touch the bucket.
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Blueprint, jsonify

from services import state as state_service

health_bp = Blueprint("health", __name__)


def _bucket_mounted() -> bool:
    """True if INSPECTOR_BUCKET_MOUNT exists and contains the v2 state file.

    Checks the directory + the load-bearing ``state/reciter_state.json`` because
    a bucket attachment can succeed at the Space layer but produce an empty
    mount if the bucket itself is empty or the wrong repo. Catching that here
    surfaces the misconfiguration in the smoke tests rather than at first read.
    """
    mount = os.environ.get("INSPECTOR_BUCKET_MOUNT")
    if not mount:
        return False
    root = Path(mount)
    if not root.is_dir():
        return False
    return (root / "state" / "reciter_state.json").is_file()


@health_bp.route("/healthz")
def healthz():
    bucket_ok = _bucket_mounted()
    state_loaded = state_service.is_hydrated()
    rows = state_service.all_rows()
    healthy = state_loaded and bucket_ok
    payload = {
        "status": "ok" if healthy else "degraded",
        "mode": "deployed" if os.environ.get("INSPECTOR_BUCKET_MOUNT") else "local",
        "bucket_mounted": bucket_ok,
        "state_loaded": state_loaded,
        "reciters_count": len(rows),
        "commit": os.environ.get("INSPECTOR_COMMIT_SHA", "unknown"),
    }
    # Return 503 (not 200) when degraded so probe-based monitors flag the
    # Space without parsing the body. Local-mode runs don't have a mount and
    # would always 503 here — only flip the status code when we're in
    # deployed mode (i.e. INSPECTOR_BUCKET_MOUNT is set).
    if not healthy and os.environ.get("INSPECTOR_BUCKET_MOUNT"):
        return jsonify(payload), 503
    return jsonify(payload)


@health_bp.route("/livez")
def livez():
    return jsonify({"status": "ok"})
