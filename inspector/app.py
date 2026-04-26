"""
Alignment Inspector Server

Flask entry point: creates app, registers blueprints, serves the Vite-built
SPA shell (inspector/frontend/dist/) and cross-tab routes, and runs the
startup sequence.
"""
import argparse
import concurrent.futures
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
                    FLASK_DEV_VALUE, FLASK_ENV_VAR, SERVER_HOST,
                    STARTUP_PRELOAD_WORKERS)
from routes import register_blueprints
from services.data_loader import discover_ts_reciters, load_surah_info_lite, load_timestamps
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

# Flask's built-in static handler serves everything under FRONTEND_DIST at
# the site root (`/assets/<hash>.js`, `/fonts/DigitalKhattV2.otf`, …). The
# `/` route below handles index.html explicitly.
app = Flask(__name__, static_folder=str(FRONTEND_DIST), static_url_path="")
register_blueprints(app)


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
    """Serve audio files."""
    audio_path = AUDIO_PATH / reciter / filename
    if not audio_path.exists():
        return jsonify({"error": "Audio file not found"}), 404
    mime_type = AUDIO_MIME_TYPES.get(audio_path.suffix.lower(), "audio/mpeg")
    return send_file(audio_path, mimetype=mime_type)


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

    # Eagerly discover timestamp reciters
    reciters = discover_ts_reciters()
    logger.info("Discovered %d timestamp reciter(s).", len(reciters))

    # Preload all timestamp data in background threads
    if reciters:
        def _preload(slug):
            load_timestamps(slug)
            return slug
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(reciters), STARTUP_PRELOAD_WORKERS),
        ) as pool:
            for slug in pool.map(_preload, [r["slug"] for r in reciters]):
                logger.info("Preloaded timestamps: %s", slug)
        logger.info("All timestamp data cached.")

    # Vite owns frontend file-watching (HMR in dev; rebuild on npm run build).
    # Flask reloader only needs to watch Python modules, which it does natively.
    # Debug + reloader default off for production; opt in with `FLASK_ENV=development`
    # (matches plan §4: `debug=False` unless `FLASK_ENV=development`).
    debug = os.environ.get(FLASK_ENV_VAR) == FLASK_DEV_VALUE
    logger.info("Starting server at http://localhost:%d (debug=%s)", args.port, debug)
    app.run(host=SERVER_HOST, port=args.port, debug=debug, use_reloader=debug)
