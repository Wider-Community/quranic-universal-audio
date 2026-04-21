# syntax=docker/dockerfile:1.7
# Inspector — three-stage build targeting a small runtime image.
# Stage 1 builds the Vite frontend with Node.
# Stage 2 compiles a minimal static ffmpeg (mp3→PCM only) so the runtime
#   doesn't ship the ~130MB video codec chain (x265/aom/SvtAv1Enc/jxl/vpx)
#   that distro ffmpeg packages pull in but inspector never uses.
# Stage 3 is a lean python:3.11-alpine runtime that ships the Flask app.
# Reviewers run `docker compose up` and visit :5000.
#
# Build context is the REPO ROOT (one level above inspector/).
# `validators/` lives at repo root as a sibling of `inspector/`; both are
# copied into the image so `from validators.X import Y` resolves correctly.
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
RUN apk add --no-cache build-base yasm nasm curl tar xz
ARG FFMPEG_VERSION=7.1
RUN curl -fsSL "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz" | tar -xJ -C /tmp
WORKDIR /tmp/ffmpeg-${FFMPEG_VERSION}
# --disable-everything then whitelist only what services/peaks.py uses:
#   decoder/demuxer: mp3 input
#   encoder/muxer:   pcm_s16le + wav output (s16le muxer is silently dropped
#                    unless pcm_s16le muxer is listed alongside in ffmpeg 7.1)
#   filter:          aresample (for `-ar` sample-rate conversion), aformat, anull
#   protocol:        file + pipe (subprocess `-i <path>`, stdout `-`)
# ffprobe is built alongside ffmpeg; needed by services/peaks.py stream probe.
RUN ./configure \
      --prefix=/ff \
      --disable-everything \
      --disable-autodetect \
      --disable-doc --disable-htmlpages --disable-manpages --disable-podpages --disable-txtpages \
      --disable-network --disable-debug --disable-ffplay \
      --disable-shared --enable-static \
      --enable-small \
      --enable-decoder=mp3,mp3float,pcm_s16le \
      --enable-demuxer=mp3,wav,s16le \
      --enable-encoder=pcm_s16le \
      --enable-muxer=s16le,wav,pcm_s16le \
      --enable-filter=aresample,aformat,anull \
      --enable-protocol=file,pipe \
      --enable-parser=mpegaudio \
      --extra-ldflags="-static" \
      --pkg-config-flags="--static" && \
    make -j"$(nproc)" && make install && \
    strip /ff/bin/ffmpeg /ff/bin/ffprobe


# --- Stage 3: Python runtime ---
FROM python:3.11-alpine AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    INSPECTOR_DATA_DIR=/data \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY --from=ffmpeg-build /ff/bin/ffmpeg /ff/bin/ffprobe /usr/local/bin/

# Python deps — inspector's requirements.txt lists flask + quranic-phonemizer.
# Install phonemizer with --no-deps: it declares pandas>=1.5 as a hard dep but
# only imports it inside the optional show_table() method, which inspector
# never calls. Skipping pandas (76MB) + numpy (73MB) saves ~150MB of nothing.
# pip/setuptools/wheel are purged — not needed at runtime.
RUN pip install --no-cache-dir flask "PyYAML>=6.0" && \
    pip install --no-cache-dir --no-deps "quranic-phonemizer>=2.0" && \
    pip uninstall -y pip setuptools wheel && \
    find /usr/local/lib/python3.11 -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# App code. Selective COPY — inspector/frontend/{src,public,node config} and
# tests/ aren't needed at runtime (only the built dist/ from stage 1 is).
# app.py inserts /app (repo root) onto sys.path[0] at startup so that
# `from validators.X import Y` resolves.
COPY inspector/app.py inspector/config.py inspector/constants.py ./inspector/
COPY inspector/routes/ ./inspector/routes/
COPY inspector/services/ ./inspector/services/
COPY inspector/utils/ ./inspector/utils/
COPY validators/ ./validators/
# Linguistic data read by services/data_loader.py via config.py's _QUA_DATA.
# Without these, UnifiedDisplay renders empty Arabic (word.text / display_text
# come from qpc_hafs + digital_khatt). Fonts/.py siblings in that dir aren't
# needed at runtime — copy only the 3 jsons config.py references.
COPY quranic_universal_aligner/data/qpc_hafs.json \
     quranic_universal_aligner/data/digital_khatt_v2_script.json \
     quranic_universal_aligner/data/phoneme_sub_costs.json \
     ./quranic_universal_aligner/data/
COPY --from=frontend-build /app/dist ./inspector/frontend/dist

# Data volume is mounted here at runtime (see docker-compose.yml). Inside the
# container every data path derives from DATA_DIR via inspector/config.py.
EXPOSE 5000

CMD ["python3", "inspector/app.py"]
