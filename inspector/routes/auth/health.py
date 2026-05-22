"""Health endpoints for liveness/readiness probes and ops dashboards.

Two routes share one blueprint:

- ``GET /healthz`` — readiness signal. Reports SQLite DB + bucket mount status.
  Returns 200 in local mode (where there's no mount to check) and 503 in
  deployed mode when DB/bucket are degraded so probes fail loud.

- ``GET /livez``  — liveness signal. Always 200 with a tiny body; use it when
  a probe should not touch the bucket.
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Blueprint, jsonify

from services import auth as auth_service
from services import auto_detect as auto_detect_service
from services import state as state_service

health_bp = Blueprint("health", __name__)


def _bucket_mounted() -> bool:
    """True if INSPECTOR_BUCKET_MOUNT exists and contains the SQLite substrate.

    Checks the directory + the load-bearing ``db/inspector.db`` because a bucket
    attachment can succeed at the Space layer but produce an empty mount if the
    bucket itself is empty or the wrong repo. Catching that here surfaces the
    misconfiguration in the smoke tests rather than at first read. The canonical
    substrate artefact is ``db/inspector.db``.
    """
    mount = os.environ.get("INSPECTOR_BUCKET_MOUNT")
    if not mount:
        return False
    root = Path(mount)
    if not root.is_dir():
        return False
    return (root / "db" / "inspector.db").is_file()


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
        "oauth_configured": auth_service.is_oauth_configured(),
        "commit": os.environ.get("INSPECTOR_COMMIT_SHA", "unknown"),
        # Surface auto_detect status so a regression like "no background
        # loop running in prod" is visible from /healthz rather than only
        # via a state-vs-wip mismatch hours/days later.
        "auto_detect_loop": auto_detect_service.is_background_loop_running(),
    }

    # SQLite substrate status (the source of truth post-cutover). Surfaces db
    # open state + bucket-upload lag so a stuck sync is visible from /healthz.
    from services import db as _db
    from services.db import sync as _sync

    db_health = _db.healthcheck()
    sync_status = _sync.status()
    payload["db"] = {
        "open": db_health.get("open"),
        "schema_version": db_health.get("schema_version"),
        "last_bucket_upload_ts": sync_status["last_bucket_upload_ts"],
        "bucket_lag_seconds": sync_status["bucket_lag_seconds"],
        "last_error": sync_status["last_error"],
    }
    healthy = healthy and bool(db_health.get("open"))

    # Return 503 in deployed mode (mount configured) so probes fail loud.
    # Local mode has no mount and would always 503 — keep it 200 there.
    if not healthy and os.environ.get("INSPECTOR_BUCKET_MOUNT"):
        return jsonify(payload), 503
    return jsonify(payload)


@health_bp.route("/livez")
def livez():
    return jsonify({"status": "ok"})
