"""
Alignment Inspector Server

Flask entry point: creates app, registers blueprints, serves the Vite-built
SPA shell (inspector/frontend/dist/) and cross-tab routes, and runs the
startup sequence.
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

# Ensure the repo root (parent of inspector/) is on sys.path so that
# `from validators.X import Y` resolves to the sibling `validators/` package
# when the app is launched via `python3 inspector/app.py` from the repo root.
# Inside Docker the WORKDIR is /app and both /app/inspector/ and /app/validators/
# are present at that level, so this insert is also correct there.
_REPO_ROOT = Path(__file__).parent.parent.resolve()
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from flask import Flask, jsonify, send_file, send_from_directory
from werkzeug.exceptions import HTTPException

from config import (AUDIO_PATH, AUDIO_MIME_TYPES, CACHE_DIR, DEFAULT_PORT,
                    FLASK_DEV_VALUE, FLASK_ENV_VAR, SERVER_HOST)
from routes import register_blueprints
from services import access as access_service
from services import audit as audit_service
from services import catalog as catalog_service
from services import state as state_service
from services.data_loader import load_surah_info_lite
from services.phonemizer_service import get_phonemizer, has_phonemizer


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON for downstream aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "name": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _configure_logging() -> None:
    """Install the JSON formatter on the root logger (idempotent)."""
    root = logging.getLogger()
    # Avoid duplicate handlers on reload (Flask's reloader re-imports this module).
    if any(isinstance(h, logging.StreamHandler) and isinstance(h.formatter, JSONFormatter)
           for h in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)


_configure_logging()
logger = logging.getLogger("inspector")

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

# Ensure the cache dir exists at import time so gunicorn workers don't race
# on first peaks request. Local dev hits the same code path via __main__.
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Flask's built-in static handler serves everything under FRONTEND_DIST at
# the site root (`/assets/<hash>.js`, `/fonts/DigitalKhattV2.otf`, …). The
# `/` route below handles index.html explicitly.
app = Flask(__name__, static_folder=str(FRONTEND_DIST), static_url_path="")
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


_hydrate_bucket_stores()


# ---------------------------------------------------------------------------
# Error handlers — preserve {error: str} envelope across all routes
# ---------------------------------------------------------------------------

@app.errorhandler(HTTPException)
def _handle_http_exception(e: HTTPException):
    """Return the canonical ``{error: <description>}`` envelope with the HTTP status."""
    return jsonify({"error": e.description}), e.code


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
    return jsonify(load_surah_info_lite())


@app.route("/audio/<reciter>/<filename>")
def serve_audio(reciter, filename):
    """Serve audio files.

    Sends `Access-Control-Allow-Origin: *` so the frontend can mark the
    `<audio>` element with `crossorigin="anonymous"`. That CORS tag is
    required for Web Audio's `MediaElementAudioSourceNode` to emit real
    samples (the GainNode kill-switch in `lib/playback/audio-graph.ts`
    needs it to silence the OS sink at segment boundaries). Without it
    the spec mandates the source emits silence even on same-origin loads.
    """
    audio_path = AUDIO_PATH / reciter / filename
    if not audio_path.exists():
        return jsonify({"error": "Audio file not found"}), 404
    mime_type = AUDIO_MIME_TYPES.get(audio_path.suffix.lower(), "audio/mpeg")
    response = send_file(audio_path, mimetype=mime_type)
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Alignment Inspector Server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to run on")
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not (FRONTEND_DIST / "index.html").exists():
        logger.warning(
            "%s not found. Run `cd inspector/frontend && npm ci && npm run build` "
            "before visiting /. For frontend dev: `cd inspector/frontend && npm run dev` "
            "and visit http://localhost:5173 (Vite proxies /api + /audio to this Flask).",
            FRONTEND_DIST / "index.html",
        )

    # Eagerly initialize phonemizer
    if has_phonemizer():
        logger.info("Initializing phonemizer...")
        get_phonemizer()
        logger.info("Phonemizer ready.")
    else:
        logger.info("Phonemizer not available (reference resolution disabled)")

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
