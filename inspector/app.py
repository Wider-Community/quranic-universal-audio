"""
Alignment Inspector Server

Flask entry point: creates app, registers blueprints, serves the Vite-built
SPA shell (inspector/frontend/dist/) and cross-tab routes, and runs the
startup sequence.
"""
import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure the repo root (parent of inspector/) is on sys.path so that
# `from scripts.lib.X import Y` resolves to the sibling `scripts/lib/` package
# (e.g. `boundary_check`, used by the timestamps validator) when the app is
# launched via `python3 inspector/app.py` from the repo root. Inside Docker
# the WORKDIR is /app and both /app/inspector/ and /app/scripts/ are present
# at that level, so this insert is also correct there.
_REPO_ROOT = Path(__file__).parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Local dev: hydrate process env from `<repo>/.env` if present. Production
# (HF Space) gets its secrets from Space settings and the file is absent.
# Keys already in the process env win (shell `export` beats the file).
def _load_dotenv_for_local_dev() -> None:
    # Load repo-root `.env` first, then `inspector/.env` (e.g. Quran.Foundation
    # API creds live there). Keys already in the process env win; earlier files
    # win over later ones.
    for env_path in (_REPO_ROOT / ".env", Path(__file__).resolve().parent / ".env"):
        if not env_path.exists():
            continue
        try:
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        except OSError:
            pass


_load_dotenv_for_local_dev()


# Auto-enable dev-mode auth bypass when running locally outside pytest.
# Tri-state env var: unset → auto-detect; "1" → force on; "0" → force off.
# Auto-detect: on iff INSPECTOR_BEHIND_PROXY != "1" AND not running under
# pytest (mirrors the audio-prefetch gate at module-load below). HF Space
# deploys set INSPECTOR_BEHIND_PROXY=1, so they never auto-enable.
if "INSPECTOR_DEV_MODE" not in os.environ:
    if (os.environ.get("INSPECTOR_BEHIND_PROXY") != "1"
            and "pytest" not in sys.modules):
        os.environ["INSPECTOR_DEV_MODE"] = "1"


# Local dev: auto-mount the HF bucket via hf-mount so reads hit a local
# FUSE cache (~50-500x faster than going through hffs.cat_file every call).
# Mount path: inspector/.bucket/{dev,prod}/ (gitignored). Failures degrade
# silently to the API path — never blocks boot. See auto_mount.py for
# the full skip-conditions list.
from services.storage.auto_mount import auto_mount as _auto_mount_bucket

_auto_mount_bucket()


from flask import Flask, jsonify, send_from_directory
from flask_compress import Compress
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from config import (DEFAULT_PORT,
                    FLASK_DEV_VALUE, FLASK_ENV_VAR, SERVER_HOST)
from routes import register_blueprints
from services import access as access_service
from services import activity_state as activity_state_service
from services import auto_detect as auto_detect_service
from services import pending_requests as pending_requests_service
from services import request_archive as request_archive_service
from services import audit as audit_service
from services import auth as auth_service
from services import catalog as catalog_service
from services import state as state_service
from services.data_loader import load_surah_info_lite
# Phonemizer was eagerly initialized here. It's now imported lazily inside
# inspector/scripts/backfill_boundary_adj.py (the only remaining consumer).
from services.secrets_guard import MissingSecret, get_session_secret
from services.state.state import InvalidTransition, NotAuthorizedForTransition, UnknownReciter
from utils.json_response import orjson_response


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

_LEVEL_SHORT = {"CRITICAL": "CRIT", "WARNING": "WARN", "INFO": "INFO",
                "ERROR": "ERR ", "DEBUG": "DBG "}


class PlainFormatter(logging.Formatter):
    """Compact human-readable single-line format: ``HH:MM:SS LVL name | msg``.

    JSON aggregation was abandoned — HF Space logs and local stdout are both
    read by humans, and the JSON wrapper made every line wider than the
    actual message. Aggregators that need structure can grep on the level
    token; nothing in our pipeline ingests structured logs today.
    """

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, datefmt="%H:%M:%S")
        lvl = _LEVEL_SHORT.get(record.levelname, record.levelname[:4])
        name = record.name
        # Trim noisy package prefixes — "services.activity.activity_state"
        # → "activity_state" keeps the useful leaf without the breadcrumb.
        if name.startswith("services."):
            name = name.rsplit(".", 1)[-1]
        line = f"{ts} {lvl} {name} | {record.getMessage()}"
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def _configure_logging() -> None:
    """Install the plain formatter on the root logger (idempotent)."""
    root = logging.getLogger()
    # Avoid duplicate handlers on reload (Flask's reloader re-imports this module).
    if any(isinstance(h, logging.StreamHandler) and isinstance(h.formatter, PlainFormatter)
           for h in root.handlers):
        return
    # Replace any pre-existing stream handlers (e.g. Flask's default) so we
    # don't double-print every record under the reloader.
    for h in list(root.handlers):
        if isinstance(h, logging.StreamHandler):
            root.removeHandler(h)
    handler = logging.StreamHandler()
    handler.setFormatter(PlainFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # Silence chatty third-party libraries:
    # - httpx logs every HTTP request at INFO (one line per bucket read);
    #   bumping to WARNING keeps real failures, drops the per-request noise.
    # - huggingface_hub._login prints a benign HF_TOKEN-already-set warning
    #   on every fresh login() call when the env var is present.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub._login").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


_configure_logging()
logger = logging.getLogger("inspector")

if auth_service.is_dev_mode():
    logger.warning(
        "INSPECTOR_DEV_MODE=1 — synthetic dev user active, OAuth bypassed. "
        "Default role 'owner'; flip via the in-app role switcher or the "
        "'inspector_dev_role' cookie."
    )

_HERE = Path(__file__).parent.resolve()
FRONTEND_DIST = _HERE / "frontend" / "dist"


# Single-process invariant: state_store, per-slug threading.Lock, signed-
# cookie session verification, and the role cache all assume one worker.
# Boot fails if any multi-worker signal is set.
def _assert_single_worker() -> None:
    """Refuse to boot under any multi-worker config.

    Three independent signals are sniffed at import time because gunicorn's
    `-w` flag isn't on the env at fork time:

    1. ``GUNICORN_CMD_ARGS`` / ``GUNICORN_WORKERS`` / ``WEB_CONCURRENCY`` env
       vars — the standard gunicorn-recognised env knobs.
    2. ``sys.argv`` of the loader process — catches `gunicorn -w 2 ...`.
    3. (Future) a post-fork hook inside gunicorn — not currently wired.

    Any signal of >1 worker → loud RuntimeError.
    """
    suspects = [
        os.environ.get("GUNICORN_WORKERS"),
        os.environ.get("WEB_CONCURRENCY"),
        os.environ.get("GUNICORN_CMD_ARGS"),
    ]
    for raw in suspects:
        if not raw:
            continue
        for token in raw.replace("=", " ").split():
            if token.isdigit() and int(token) > 1:
                raise RuntimeError(
                    f"Inspector requires a single worker (saw {token!r} via env)."
                )
    argv = list(sys.argv)
    for i, a in enumerate(argv):
        if a in ("-w", "--workers") and i + 1 < len(argv):
            try:
                n = int(argv[i + 1])
            except ValueError:
                continue
            if n > 1:
                raise RuntimeError(
                    f"Inspector requires -w 1 (got -w {n})."
                )
        elif a.startswith("--workers="):
            try:
                n = int(a.split("=", 1)[1])
            except ValueError:
                continue
            if n > 1:
                raise RuntimeError(
                    f"Inspector requires --workers=1 (got {a})."
                )


_assert_single_worker()

# Flask's built-in static handler serves everything under FRONTEND_DIST at
# the site root (`/assets/<hash>.js`, `/fonts/DigitalKhattV2.otf`, …). The
# `/` route below handles index.html explicitly.
app = Flask(__name__, static_folder=str(FRONTEND_DIST), static_url_path="")

# Gzip (and brotli when the client advertises it) every JSON response over
# ~500 bytes. Pre-gzipped octet-stream bodies (Timestamps shards) fall outside
# the default MIME allow-list, so they're left untouched — no double-compress.
Compress(app)

# Behind HF Spaces' TLS-terminating proxy the X-Forwarded-* headers carry
# the real scheme/host/client; ProxyFix tells werkzeug to trust one hop so
# request.url_root reflects the public https URL (load-bearing for the
# OAuth redirect_uri). Gated by env so local dev / docker-compose runs
# without proxy headers are unaffected.
if os.environ.get("INSPECTOR_BEHIND_PROXY") == "1":
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Flask's signed-cookie session is used by Authlib for the short-lived
# OAuth state between /authorize and /callback. Our identity cookie is
# separate (see services/auth.py). Both signed with the same secret.
try:
    app.secret_key = get_session_secret()
except MissingSecret as e:
    # Local dev / test paths may not have the secret seeded. Anyone hitting
    # an OAuth route gets a 503 from auth_service.is_oauth_configured().
    logger.warning("INSPECTOR_SESSION_SECRET unavailable: %s", e)

# HF Spaces renders the app inside an iframe under huggingface.co. The
# OAuth round-trip (authorize → callback) is iframe-scoped, so the Flask
# session cookie carrying the OAuth state must use SameSite=None;Secure
# to survive the cross-site iframe navigation. Without these, Authlib
# raises MismatchingStateError on the callback because the cookie never
# came back. Locally the app runs over plain HTTP where SameSite=None
# requires Secure (browsers reject otherwise), so fall back to Lax there.
_behind_proxy = os.environ.get("INSPECTOR_BEHIND_PROXY") == "1"
app.config["SESSION_COOKIE_SAMESITE"] = "None" if _behind_proxy else "Lax"
app.config["SESSION_COOKIE_SECURE"] = _behind_proxy
app.config["SESSION_COOKIE_HTTPONLY"] = True

# Register the HF OAuth provider with Authlib so the auth routes can
# resolve oauth.huggingface at request time.
auth_service.init_oauth(app)

register_blueprints(app)


# ---------------------------------------------------------------------------
# Bucket-resident stores: hydrate on import so both `python3 inspector/app.py`
# and `gunicorn inspector.app:app` follow the same path. Errors degrade to
# empty in-memory stores + a warning — the app still boots so contributors
# get a clear "no reciters yet" page rather than a hard 500.
# ---------------------------------------------------------------------------

def _hydrate_bucket_stores() -> None:
    for label, fn in (
        ("access", access_service.hydrate),
        ("state", state_service.hydrate),
        ("catalog", catalog_service.hydrate),
        ("activity_state", activity_state_service.hydrate),
        ("pending_requests", pending_requests_service.hydrate),
        ("request_archive", request_archive_service.hydrate),
    ):
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — log and continue
            logger.warning(
                "%s store hydrate failed (%s); continuing with empty in-memory model",
                label,
                e,
            )

    try:
        audit_service.ensure_meta_initialized()
    except Exception as e:  # noqa: BLE001
        logger.warning("audit ensure_meta_initialized failed: %s", e)

    # Wip-audio sweeper: hourly daemon enforcing the 1-week post-RELEASED
    # TTL on bucket audio + peaks. Bucket audio itself is written by the
    # katana extraction pipeline; the inspector only reads and (here) GCs.
    #
    # Opt-in via ``INSPECTOR_WIP_SWEEPER=1`` (Dockerfile sets it on prod).
    # Local dev runs (``python3 inspector/app.py``) leave it unset so a
    # mistyped INSPECTOR_BUCKET_REPO can't accidentally delete prod data.
    # Tests skip via the pytest guard.
    # Auto-detect reconciler: server-side acceptance of pending requests.
    # ``hydrate_initial_seen`` ALWAYS runs at boot — it's idempotent and only
    # fires alignment_completed for slugs already stuck in AWAITING_ALIGNMENT
    # despite having ``wip/<slug>/`` files. Without this, a reciter uploaded
    # while the server was down (or before deploy of the auto-detect feature)
    # stays in AWAITING_ALIGNMENT forever, causing the dashboard row, detail
    # modal, and segments combobox to all disagree about its bucket.
    #
    # The 60s background polling loop stays opt-in via ``INSPECTOR_AUTO_DETECT=1``
    # because dev environments don't want a CPU loop hammering the bucket.
    # Tests skip both via the pytest guard.
    if "pytest" not in sys.modules:
        try:
            auto_detect_service.hydrate_initial_seen()
        except Exception as e:  # noqa: BLE001
            logger.warning("auto_detect hydrate_initial_seen failed: %s", e)
        if os.environ.get("INSPECTOR_AUTO_DETECT") == "1":
            try:
                interval = int(os.environ.get("INSPECTOR_AUTO_DETECT_INTERVAL_S", "60"))
                auto_detect_service.start_background_loop(interval_seconds=interval)
                logger.info(
                    "auto_detect: background loop scheduled (interval=%ss)", interval,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("auto_detect background loop wiring failed: %s", e)

    if "pytest" not in sys.modules and os.environ.get("INSPECTOR_WIP_SWEEPER") == "1":
        try:
            from services import audio_prefetch

            audio_prefetch.start_cleanup_daemon()
            logger.info("wip-audio sweeper: hourly daemon started")
        except Exception as e:  # noqa: BLE001
            logger.warning("wip-audio sweeper wiring failed: %s", e)

    # SQLite substrate (transition flag, default off): pull the DB from the
    # bucket and run migrations so it's ready. Additive during the transition —
    # the legacy stores above still serve reads until the per-service cutover.
    if "pytest" not in sys.modules:
        try:
            from services import db as _db

            if _db.substrate_enabled():
                from services.db import sync as _sync

                _sync.pull()
                ver = _db.init_db()
                logger.info("db substrate: ready at schema v%s", ver)
        except Exception as e:  # noqa: BLE001
            logger.warning("db substrate init failed: %s", e)


_hydrate_bucket_stores()


# ---------------------------------------------------------------------------
# Error handlers — preserve {error: str} envelope across all routes
# ---------------------------------------------------------------------------

@app.errorhandler(HTTPException)
def _handle_http_exception(e: HTTPException):
    """Return the canonical ``{error: <description>}`` envelope with the HTTP status."""
    return jsonify({"error": e.description}), e.code


@app.errorhandler(UnknownReciter)
def _handle_unknown_reciter(e: UnknownReciter):
    return jsonify({"error": f"unknown reciter: {e}"}), 404


@app.errorhandler(InvalidTransition)
def _handle_invalid_transition(e: InvalidTransition):
    return jsonify({"error": str(e)}), 400


@app.errorhandler(NotAuthorizedForTransition)
def _handle_not_authorized_transition(e: NotAuthorizedForTransition):
    return jsonify({"error": str(e)}), 403


@app.errorhandler(Exception)
def _handle_unexpected_exception(e: Exception):
    """Log uncaught exceptions and return a generic envelope (don't leak internals)."""
    logger.exception("unhandled exception: %s", e)
    return jsonify({"error": "internal server error"}), 500


# ---------------------------------------------------------------------------
# Static / index routes
# ---------------------------------------------------------------------------

_BUILD_HINT = (
    "Frontend not built. Run:\n"
    "  cd inspector/frontend && npm ci && npm run build\n"
)


@app.route("/")
def index():
    """Serve the Vite-built SPA shell."""
    if not (FRONTEND_DIST / "index.html").exists():
        return _BUILD_HINT, 500, {"Content-Type": "text/plain"}
    return send_from_directory(str(FRONTEND_DIST), "index.html")


# ---------------------------------------------------------------------------
# Cross-tab routes (not under any single tab's namespace)
# ---------------------------------------------------------------------------

@app.route("/api/surah-info")
def get_surah_info():
    """Return lightweight surah metadata."""
    # Pure Quran-structure constants — never change without a redeploy.
    return orjson_response(
        load_surah_info_lite(),
        headers={"Cache-Control": "public, max-age=3600"},
    )


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Alignment Inspector Server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to run on")
    args = parser.parse_args()

    if not (FRONTEND_DIST / "index.html").exists():
        logger.warning(
            "%s not found. Run `cd inspector/frontend && npm ci && npm run build` "
            "before visiting /. For frontend dev: `cd inspector/frontend && npm run dev` "
            "and visit http://localhost:5173 (Vite proxies /api + /audio to this Flask).",
            FRONTEND_DIST / "index.html",
        )

    # Phonemizer is no longer used by the validate runtime path; the phonemic
    # side of boundary_adj is captured at backfill / extraction time and
    # persisted as ``is_boundary_adj`` on every segment. The remaining
    # consumer is ``inspector/scripts/backfill_boundary_adj.py`` (offline)
    # which imports lazily on demand.

    # Timestamp data loads lazily on first request now (per-reciter cache in
    # services/data_loader.py). The earlier eager preload pinned ~22 MB *
    # 300 reciters at startup, which is unviable at deployed scale.

    # Vite owns frontend file-watching (HMR in dev; rebuild on npm run build).
    # Flask reloader only needs to watch Python modules, which it does natively.
    # Debug + reloader default off for production; opt in with `FLASK_ENV=development`
    # (matches plan §4: `debug=False` unless `FLASK_ENV=development`).
    debug = os.environ.get(FLASK_ENV_VAR) == FLASK_DEV_VALUE
    logger.info("Starting server at http://localhost:%d (debug=%s)", args.port, debug)
    app.run(host=SERVER_HOST, port=args.port, debug=debug, use_reloader=debug)
