"""
Alignment Inspector Server

Flask entry point: creates app, registers blueprints, serves the Vite-built
SPA shell (inspector/frontend/dist/) and cross-tab routes, and runs the
startup sequence.
"""
import argparse
import concurrent.futures
import sys
from pathlib import Path

from flask import Flask, jsonify, send_file, send_from_directory

from config import AUDIO_PATH, AUDIO_MIME_TYPES, CACHE_DIR
from routes import register_blueprints
from services.data_loader import discover_ts_reciters, load_surah_info_lite, load_timestamps
from services.phonemizer_service import get_phonemizer, has_phonemizer

_HERE = Path(__file__).parent.resolve()
FRONTEND_DIST = _HERE / "frontend" / "dist"

# Flask's built-in static handler serves everything under FRONTEND_DIST at
# the site root (`/assets/<hash>.js`, `/fonts/DigitalKhattV2.otf`, …). The
# `/` route below handles index.html explicitly.
app = Flask(__name__, static_folder=str(FRONTEND_DIST), static_url_path="")
register_blueprints(app)

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
    parser.add_argument("--port", type=int, default=5000, help="Port to run on")
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if not (FRONTEND_DIST / "index.html").exists():
        print(
            f"WARNING: {FRONTEND_DIST / 'index.html'} not found.\n"
            "         Run `cd inspector/frontend && npm ci && npm run build` before visiting /.\n"
            "         For frontend development: `cd inspector/frontend && npm run dev` and\n"
            "         visit http://localhost:5173 (Vite proxies /api + /audio to this Flask).",
            file=sys.stderr,
        )

    # Eagerly initialize phonemizer
    if has_phonemizer():
        print("Initializing phonemizer...")
        get_phonemizer()
        print("Phonemizer ready.")
    else:
        print("Phonemizer not available (reference resolution disabled)")

    # Eagerly discover timestamp reciters
    reciters = discover_ts_reciters()
    print(f"Discovered {len(reciters)} timestamp reciter(s).")

    # Preload all timestamp data in background threads
    if reciters:
        def _preload(slug):
            load_timestamps(slug)
            return slug
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(reciters), 8)) as pool:
            for slug in pool.map(_preload, [r["slug"] for r in reciters]):
                print(f"  Preloaded timestamps: {slug}")
        print("All timestamp data cached.")

    # Vite owns frontend file-watching (HMR in dev; rebuild on npm run build).
    # Flask reloader only needs to watch Python modules, which it does natively.
    print(f"Starting server at http://localhost:{args.port}")
    app.run(host="0.0.0.0", port=args.port, debug=True, use_reloader=True)
