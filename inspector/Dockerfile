# syntax=docker/dockerfile:1.7
# Inspector — two-stage build. Stage 1 builds the Vite frontend with Node;
# Stage 2 is a lean Python runtime that copies the built dist/ across and
# ships the Flask app. Reviewers run `docker compose up` and visit :5000.
#
# Build context is the REPO ROOT (one level above inspector/).
# `validators/` lives at repo root as a sibling of `inspector/`; both are
# copied into the image so `from validators.X import Y` resolves correctly.
#
# Build:    docker build -t inspector:dev -f inspector/Dockerfile .   # from repo root
# Run dev:  docker run --rm -p 5000:5000 -v "$PWD/data:/data" inspector:dev

# --- Stage 1: build frontend ---
FROM node:20-slim AS frontend-build
WORKDIR /app
# npm install (not `ci`) — matches the "no package-lock.json committed" reality
# that CLAUDE.md's run instructions already assume. Switch to `npm ci` once a
# lockfile lands.
COPY inspector/frontend/package.json ./
RUN npm install
COPY inspector/frontend ./
RUN npm run build


# --- Stage 2: Python runtime ---
FROM python:3.11-slim AS runtime
WORKDIR /app

# Runtime system deps — ffmpeg is required by services/peaks.py for waveform
# peak extraction. `--no-install-recommends` keeps the layer small.
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Python deps first so the layer caches across code-only changes.
COPY inspector/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code. Place the inspector tree under ./inspector/ and the validators
# package at ./validators/ so that `from validators.X import Y` resolves
# correctly when `python3 inspector/app.py` is run from WORKDIR /app.
# app.py inserts /app (repo root) onto sys.path[0] at startup.
COPY inspector/ ./inspector/
COPY validators/ ./validators/

# Built frontend from stage 1.
COPY --from=frontend-build /app/dist ./inspector/frontend/dist

# Data volume is mounted here at runtime (see docker-compose.yml). Inside the
# container every data path derives from DATA_DIR via inspector/config.py.
ENV INSPECTOR_DATA_DIR=/data \
    PYTHONUNBUFFERED=1

EXPOSE 5000

CMD ["python3", "inspector/app.py"]
