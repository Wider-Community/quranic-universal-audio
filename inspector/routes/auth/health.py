"""Health endpoints for liveness/readiness probes and ops dashboards.

Two routes share one blueprint:

- ``GET /healthz`` — readiness signal. Reports SQLite DB + bucket mount status.
  Returns 200 in local mode (where there's no mount to check) and 503 in
  deployed mode when DB/bucket are degraded so probes fail loud.

  ``?deep=1`` adds a ``sample_validation`` block: a bounded external-bucket
  drift probe (DB-catalog round-trip + a small reciter-folder sample) delegated
  to ``services.storage.bucket_audit.sample_validation``. It is OPT-IN — the
  default probe never walks the bucket, so its latency is unchanged. A deep
  probe that finds drift flips the response to degraded (503 in deployed mode)
  so the misconfiguration surfaces at health-check time, not mid-request.

- ``GET /livez``  — liveness signal. Always 200 with a tiny body; use it when
  a probe should not touch the bucket.
"""

from __future__ import annotations

import os
from pathlib import Path

from flask import Blueprint, jsonify, request

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
        # Always False on a deployed Space (is_dev_mode() is forced off behind
        # the proxy); a True here would signal the OAuth-bypass misconfig.
        "dev_mode": auth_service.is_dev_mode(),
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

    # Opt-in deep probe: validate the DB catalog + a small reciter-folder
    # sample so external-bucket drift surfaces here, not mid-request. Off the
    # default path entirely — only ``?deep=1`` pays the bucket walk.
    # NEVER wire ``?deep=1`` into the load-balancer / automated liveness probe:
    # it does bucket I/O on the single worker and a sampled drift flips the
    # response to 503. The LB must hit plain ``/healthz`` (or ``/livez``).
    if request.args.get("deep") == "1":
        from services.storage import bucket_audit

        sample = bucket_audit.sample_validation()
        payload["sample_validation"] = sample
        healthy = healthy and sample["ok"]

    # Return 503 in deployed mode (mount configured) so probes fail loud.
    # Local mode has no mount and would always 503 — keep it 200 there.
    if not healthy and os.environ.get("INSPECTOR_BUCKET_MOUNT"):
        return jsonify(payload), 503
    return jsonify(payload)


@health_bp.route("/livez")
def livez():
    return jsonify({"status": "ok"})
