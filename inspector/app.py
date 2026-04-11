"""
Alignment Inspector Server

Flask entry point: creates app, registers blueprints, serves static files
and cross-tab routes, and runs the startup sequence.
"""
import argparse
import concurrent.futures
from pathlib import Path

from flask import Flask, jsonify, send_file, send_from_directory

from config import AUDIO_PATH, AUDIO_MIME_TYPES, CACHE_DIR
from routes import register_blueprints
from services.data_loader import discover_ts_reciters, load_surah_info_lite, load_timestamps
from services.phonemizer_service import get_phonemizer, has_phonemizer

app = Flask(__name__, static_folder="static")
register_blueprints(app)

# ---------------------------------------------------------------------------
# Static / index routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    """Serve the main HTML page."""
    return send_from_directory("static", "index.html")


@app.route("/static/<path:filename>")
def serve_static(filename):
    """Serve static files."""
    return send_from_directory("static", filename)


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

    # extra_files for Flask reloader — watches static assets and route modules
    _base = Path(__file__).parent
    extra = [
        str(_base / "static" / "segments.js"),
        str(_base / "static" / "app.js"),
        str(_base / "static" / "audio.js"),
        str(_base / "static" / "style.css"),
        str(_base / "static" / "index.html"),
    ]

    print(f"Starting server at http://localhost:{args.port}")
    app.run(host="0.0.0.0", port=args.port, debug=True, use_reloader=True,
            extra_files=extra)
