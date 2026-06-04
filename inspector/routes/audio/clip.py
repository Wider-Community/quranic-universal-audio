"""Segment-clip route (/api/seg/segment-clip).

Streams an ffmpeg-extracted MP3 clip of a [start_ms, end_ms] window from the
reciter's chapter audio. Used by the frontend to play VBR-without-Xing-header
files without leaning on HTML5 ``<audio>.currentTime`` (which mis-seeks them).

The clip plays from byte 0 in the browser, so there's no seek and no drift.
"""

from __future__ import annotations

import logging
import shlex
import subprocess
from urllib.parse import urlparse

from flask import Blueprint, Response, jsonify, request, stream_with_context

from config import AUDIO_CACHE_MAX_AGE, FFMPEG_FULL_TIMEOUT
from services import audio_source
from services.audio import audio_meta

logger = logging.getLogger(__name__)

segment_clip_bp = Blueprint("segment_clip", __name__, url_prefix="/api/seg")

# ffmpeg output bitrate. 96k mono libmp3lame matches the tradeoff we're
# already shipping in audio_proxy — speech-friendly, ~10 KB/s on the wire.
CLIP_BITRATE = "96k"
# Stream stdout to the client in this chunk size. 64 KB keeps TTFB tight
# while still amortising syscall overhead.
STREAM_CHUNK_BYTES = 65_536


def _is_known_chapter_url(reciter: str, url: str) -> bool:
    """Reject open-proxy abuse: the URL must be a chapter audio URL we already
    serve to this reciter. Anything else gets a 403, even if it's the same
    host as a known URL.
    """
    # audio_manifest sidecar is the single source of truth post-migration #5;
    # the legacy per-entry `audio` field is stripped on read by the schema.
    return bool(url) and audio_meta.chapter_for_url(reciter, url) is not None


@segment_clip_bp.route("/segment-clip/<reciter>")
def seg_segment_clip(reciter):
    """Stream an MP3 clip of [start_ms, end_ms] from the reciter's chapter audio.

    Query params: ``url``, ``start_ms``, ``end_ms``. Returns ``audio/mpeg``
    with CORS so the existing WebAudio kill-switch (``MediaElementAudioSourceNode``
    needs CORS, see ``inspector/app.py:serve_audio``) keeps emitting samples.
    """
    url = request.args.get("url", "").strip()
    try:
        start_ms = int(request.args.get("start_ms", ""))
        end_ms = int(request.args.get("end_ms", ""))
    except ValueError:
        return jsonify({"error": "start_ms and end_ms must be integers"}), 400

    if end_ms <= start_ms:
        return jsonify({"error": "end_ms must be greater than start_ms"}), 400
    if not _is_known_chapter_url(reciter, url):
        return jsonify({"error": "url not registered for this reciter"}), 403
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return jsonify({"error": "url must be http or https"}), 400

    # Prefer the bucket-prefetched chapter file when present. ffmpeg can fetch
    # the URL directly (image ships with HTTPS support), but local read drops
    # seek/decode from ~0.7 s to ~0.15 s and avoids hitting the CDN on every
    # rapid-click. audio_source.resolve walks bucket-prefetched → CDN.
    src = audio_source.resolve(reciter, url)
    source = str(src.path) if src.path is not None else url

    start_sec = start_ms / 1000.0
    duration_sec = (end_ms - start_ms) / 1000.0

    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start_sec:.3f}",
        "-i",
        source,
        "-t",
        f"{duration_sec:.3f}",
        # Drop any non-audio streams. Most mp3quran/qdc MP3s embed an MJPEG
        # cover-art stream (ID3v2 APIC). Without -vn, ffmpeg tries to encode
        # that into the mp3 output via the muxer's default video codec
        # (png), which isn't compiled into our stripped-down static ffmpeg
        # — fails with "Default encoder for format mp3 (codec png) is
        # probably disabled" and the route returns 200 OK / 0 bytes.
        "-vn",
        "-c:a",
        "libmp3lame",
        "-b:a",
        CLIP_BITRATE,
        "-ac",
        "1",
        "-f",
        "mp3",
        "-",
    ]

    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        logger.error("ffmpeg not found on PATH")
        return jsonify({"error": "ffmpeg not available"}), 500

    def _generate():
        bytes_yielded = 0
        try:
            while True:
                chunk = proc.stdout.read(STREAM_CHUNK_BYTES)
                if not chunk:
                    break
                bytes_yielded += len(chunk)
                yield chunk
            try:
                proc.wait(timeout=FFMPEG_FULL_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                logger.warning("segment_clip ffmpeg timed out: cmd=%s", shlex.join(cmd))
        finally:
            # Drain stderr so we can diagnose silent failures (most common:
            # codec not available in the deployed static ffmpeg → 200/0).
            stderr_tail = b""
            try:
                if proc.stderr and not proc.stderr.closed:
                    stderr_tail = proc.stderr.read() or b""
            except (OSError, ValueError):
                pass
            if proc.stdout:
                proc.stdout.close()
            if proc.stderr:
                proc.stderr.close()
            if proc.poll() is None:
                proc.kill()
            rc = proc.returncode
            if bytes_yielded == 0 or (rc is not None and rc != 0):
                logger.warning(
                    "segment_clip ffmpeg produced %d bytes (rc=%s) cmd=%s stderr=%r",
                    bytes_yielded,
                    rc,
                    shlex.join(cmd),
                    stderr_tail.decode("utf-8", errors="replace")[-500:],
                )

    headers = {
        "Content-Type": "audio/mpeg",
        # Match inspector/app.py:serve_audio CORS — required by WebAudio
        # MediaElementAudioSourceNode for the pause kill-switch to silence.
        "Access-Control-Allow-Origin": "*",
        # Clip URL is deterministic (url + start_ms + end_ms), so the browser
        # HTTP cache will absorb repeat plays of the same segment.
        "Cache-Control": f"public, max-age={AUDIO_CACHE_MAX_AGE}, immutable",
    }
    return Response(stream_with_context(_generate()), headers=headers)
