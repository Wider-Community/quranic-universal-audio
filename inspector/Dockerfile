# syntax=docker/dockerfile:1.7
# Inspector — three-stage build targeting a small runtime image.
# Stage 1 builds the Vite frontend with Node.
# Stage 2 compiles a minimal static ffmpeg (mp3→PCM only) so the runtime
#   doesn't ship the ~130MB video codec chain (x265/aom/SvtAv1Enc/jxl/vpx)
#   that distro ffmpeg packages pull in but inspector never uses.
# Stage 3 is a lean python:3.11-alpine runtime that ships the Flask app.
# Reviewers run `docker compose up` and visit :5000.
#
# Build context is the REPO ROOT (one level above inspector/). `scripts/lib/`
# ships alongside `inspector/` so the in-process imports of
# `scripts.lib.boundary_check` (timestamps validator) and similar resolve.
#
# Build:    docker build -t inspector:dev -f inspector/Dockerfile .   # from repo root
# Run dev:  docker run --rm -p 5000:5000 -v "$PWD/data:/data" inspector:dev

# --- Stage 1: build frontend ---
FROM node:20-alpine AS frontend-build
WORKDIR /app
COPY inspector/frontend/package.json inspector/frontend/package-lock.json ./
RUN npm ci
COPY inspector/frontend ./
RUN npm run build


# --- Stage 2: compile minimal static ffmpeg (mp3 decode + s16le/wav output) ---
FROM alpine:3.20 AS ffmpeg-build
RUN apk add --no-cache build-base yasm nasm curl tar xz \
                       openssl-dev openssl-libs-static zlib-dev zlib-static

# Build libmp3lame statically from source. Alpine 3.20 dropped the
# `lame-static` subpackage so the static archive isn't shipped via apk
# any more; ffmpeg's --enable-libmp3lame still needs libmp3lame.a for
# the fully-static link. Source is ~3 MB and compiles in <30 s.
ARG LAME_VERSION=3.100
RUN curl -fsSL "https://downloads.sourceforge.net/project/lame/lame/${LAME_VERSION}/lame-${LAME_VERSION}.tar.gz" \
        | tar -xz -C /tmp && \
    cd /tmp/lame-${LAME_VERSION} && \
    ./configure --prefix=/usr --enable-static --disable-shared --disable-frontend && \
    make -j"$(nproc)" && make install && \
    cd / && rm -rf /tmp/lame-${LAME_VERSION}

ARG FFMPEG_VERSION=7.1
RUN curl -fsSL "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz" | tar -xJ -C /tmp
WORKDIR /tmp/ffmpeg-${FFMPEG_VERSION}
# --disable-everything then whitelist only what services/peaks.py +
# routes/audio/clip.py use:
#   decoder/demuxer: mp3 input
#   encoder/muxer:   pcm_s16le + wav output for peaks (s16le muxer is silently
#                    dropped unless pcm_s16le muxer is listed alongside in
#                    ffmpeg 7.1) AND libmp3lame + mp3 muxer for clip.py
#                    (segment-clip route re-encodes the requested window to
#                    mono 96k mp3 — without libmp3lame the route returns
#                    200 OK / 0 bytes silently and browser playback hangs)
#   bsf:             mp3_to_xing (injects VBR seek TOC, used by audio_fetch)
#   filter:          aresample (for `-ar` sample-rate conversion), aformat, anull
#   protocol:        file + pipe (local I/O) + http,https,tcp,tls (CDN reads —
#                    lets `_ffmpeg_decode_segment` decode remote-only chapters
#                    directly via HTTP Range without the Python ID3v2 + byte-
#                    arithmetic workaround. Costs ~8.5 MB statically-linked
#                    OpenSSL, measured.)
# ffprobe is built alongside ffmpeg; needed by services/peaks.py stream probe.
RUN ./configure \
      --prefix=/ff \
      --disable-everything \
      --disable-autodetect \
      --disable-doc --disable-htmlpages --disable-manpages --disable-podpages --disable-txtpages \
      --disable-debug --disable-ffplay \
      --disable-shared --enable-static \
      --enable-small \
      --enable-openssl \
      --enable-libmp3lame \
      --enable-decoder=mp3,mp3float,pcm_s16le \
      --enable-demuxer=mp3,wav,s16le \
      --enable-encoder=libmp3lame,pcm_s16le \
      --enable-muxer=mp3,s16le,wav,pcm_s16le \
      --enable-bsf=mp3_to_xing \
      --enable-filter=aresample,aformat,anull \
      --enable-protocol=file,pipe,http,https,tcp,tls \
      --enable-parser=mpegaudio \
      --extra-ldflags="-static" \
      --extra-libs="-lmp3lame" \
      --pkg-config-flags="--static" && \
    make -j"$(nproc)" && make install && \
    strip /ff/bin/ffmpeg /ff/bin/ffprobe


# --- Stage 3: Python runtime ---
FROM python:3.11-alpine AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    INSPECTOR_DATA_DIR=/app/data \
    INSPECTOR_QUA_DATA_PATH=/app/data \
    INSPECTOR_CACHE_DIR=/tmp/inspector-cache \
    INSPECTOR_BUCKET_MOUNT=/data/inspector-bucket \
    INSPECTOR_BUCKET_REPO=hetchyy/quranic-inspector-bucket-dev \
    INSPECTOR_PARSED_CACHE_BYTES=134217728 \
    INSPECTOR_BEHIND_PROXY=1 \
    INSPECTOR_FORCE_FLUSH_ON_SAVE=0 \
    INSPECTOR_AUDIO_PREFETCH=1 \
    GUNICORN_WORKERS=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY --from=ffmpeg-build /ff/bin/ffmpeg /ff/bin/ffprobe /usr/local/bin/

# Python deps — single source of truth in inspector/requirements.txt.
# pip/setuptools/wheel are purged — not needed at runtime.
COPY inspector/requirements.txt ./inspector/requirements.txt
RUN pip install --no-cache-dir -r ./inspector/requirements.txt && \
    pip uninstall -y pip setuptools wheel && \
    find /usr/local/lib/python3.11 -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# App code. Selective COPY — inspector/frontend/{src,public,node config} and
# tests/ aren't needed at runtime (only the built dist/ from stage 1 is).
# app.py inserts /app (repo root) onto sys.path[0] at startup so that
# `from scripts.lib.X import Y` resolves.
COPY inspector/app.py inspector/config.py inspector/constants.py ./inspector/
COPY inspector/adapters/ ./inspector/adapters/
COPY inspector/domain/ ./inspector/domain/
COPY inspector/routes/ ./inspector/routes/
COPY inspector/services/ ./inspector/services/
COPY inspector/utils/ ./inspector/utils/
# scripts/lib/ is shared with the CI build pipeline. Inspector imports
# ``scripts.lib.timestamps_shards`` for ``SCHEMA_VERSION`` + ``derive_url_template``
# when composing the bucket-mode manifest. Top-level scripts/ contains local
# CLIs we don't need at runtime — only lib/ ships.
COPY scripts/__init__.py ./scripts/__init__.py
COPY scripts/lib/ ./scripts/lib/
# Linguistic data read by services/data_loader.py via config.py's _QUA_DATA,
# plus surah_info.json read by services/data_loader.py at startup. These four
# files are the entire on-disk data surface in deployed mode — everything else
# (state, catalog, audit, per-reciter wip/published) lives in the bucket
# mounted at /data/inspector-bucket. INSPECTOR_QUA_DATA_PATH=/app/data tells
# config.py to look here instead of the default sibling-project path.
COPY data/surah_info.json \
     data/qpc_hafs.json \
     data/digital_khatt_v2_script.json \
     data/phoneme_sub_costs.json \
     ./data/
COPY --from=frontend-build /app/dist ./inspector/frontend/dist

# Data volume is mounted here at runtime (see docker-compose.yml). Inside the
# container every data path derives from DATA_DIR via inspector/config.py.
# Run as non-root. uid/gid 1000 matches the common host-user convention so
# bind-mounted /data stays readable without chown gymnastics. The inspector
# cache dir (see config.py) needs to be writable by this user.
RUN addgroup -g 1000 -S inspector && \
    adduser -u 1000 -S -G inspector -D inspector && \
    chown -R inspector:inspector /app /home/inspector
USER inspector

EXPOSE 7860

# Production WSGI server. -w 1 is load-bearing — state_store, per-slug
# mutex, signed-cookie session, and the role cache all assume one process.
# The app asserts at import time and refuses to boot on any multi-worker
# signal.
#
# --threads 16: thread pool sized for CPU-basic. The parsed-cache + bucket-
#   read workload is mostly I/O-bound.
# --max-requests + jitter: rolling worker recycle bounds slow memory leaks.
# --timeout 60: peaks computation can take ~30 s on cold cache.
# --graceful-timeout 30: allows in-flight saves to finish on SIGTERM.
CMD ["gunicorn", "-k", "gthread", "-w", "1", "--threads", "16", \
     "--max-requests", "5000", "--max-requests-jitter", "500", \
     "--timeout", "60", "--graceful-timeout", "30", \
     "--bind", "0.0.0.0:7860", \
     "--access-logfile", "-", "--error-logfile", "-", \
     "--chdir", "/app/inspector", \
     "app:app"]
