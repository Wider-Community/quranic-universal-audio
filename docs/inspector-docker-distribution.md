# Inspector — Docker distribution notes

Notes for packaging the inspector as a Docker image so non-technical reviewers can run it without installing Python, Node, ffmpeg, or any other toolchain.

**Stage 2 implementation status** (as of Wave 11b, 2026-04-14):
- `config.py`: `INSPECTOR_DATA_DIR` env var support — **DONE** (Wave 2a)
- `inspector/Dockerfile` — **DONE** (Wave 2a)
- `inspector/docker-compose.yml` — **DONE** (Wave 2a; volume uses `../data:/data`)
- `.github/workflows/docker-publish.yml` — **NOT YET** (pending)
- Mode B single-writer flock — **NOT YET** (pending)
- GHCR package published — **NOT YET** (pending)

## Context

The inspector is a Flask app with a TypeScript + Vite frontend (bundle built to `inspector/frontend/dist/`). Running it from source requires:

- Python 3.11 + `pip install -r inspector/requirements.txt`
- Node 20+ + `npm ci && npm run build` in `inspector/frontend/`
- ffmpeg (for audio peak extraction via `services/peaks.py`)

Non-technical reviewers won't do any of that. The goal is a one-command launch. Docker is the cleanest abstraction: bundle everything into an image; reviewers install only Docker.

## Two deployment modes

The inspector reads and writes local state (`detailed.json`, `edit_history.jsonl`, peaks cache, audio files). That has implications for how it's distributed.

### Mode A — per-user local instance (expected primary mode)

Each reviewer runs their own container with their own data folder mounted in. No shared state, no concurrency issues.

### Mode B — hosted, shared dataset, few trusted editors

Single deployed container, multiple reviewers edit the same data. Needs a single-writer lock (simple `fcntl.flock`) to prevent save-race corruption. No auth unless needed.

**Same Docker image serves both modes.** Pick per deployment.

## Required code change: make `DATA_DIR` configurable

Currently `config.py` hardcodes paths like `data/recitation_segments/`. For Docker volume mounting, data paths need to come from an env var with a sensible default:

```python
# inspector/config.py (sketch)
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("INSPECTOR_DATA_DIR", "data")).resolve()
AUDIO_PATH = DATA_DIR / "recitation_segments"
# ... etc, all path constants reference DATA_DIR
```

Small refactor; one PR. Prerequisite for everything below.

## Dockerfile

Multi-stage build — Node used only for the frontend build, then discarded. Final image is Python + Flask + ffmpeg + the built `dist/`.

The Dockerfile lives at `inspector/Dockerfile` — build context is the `inspector/` directory. `inspector/validators/` is vendored into the tree (Wave 2a) so no sibling access is needed.

```dockerfile
# --- Stage 1: build frontend ---
FROM node:20-alpine AS frontend
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

# --- Stage 2: runtime ---
FROM python:3.11-slim
WORKDIR /app

# Runtime system deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code (context is inspector/; place under ./inspector/ inside image)
COPY . ./inspector

# Built frontend
COPY --from=frontend /app/dist ./inspector/frontend/dist

ENV INSPECTOR_DATA_DIR=/data
EXPOSE 5000
CMD ["python3", "inspector/app.py"]
```

Expected image size: ~300–500 MB. First pull is the only slow one.

## Mode A — reviewer distribution

Publish to GitHub Container Registry (`ghcr.io`) via CI (below). Send each reviewer a one-file `docker-compose.yml` and a two-line install instruction.

```yaml
# docker-compose.yml (reviewer saves this in a folder)
services:
  inspector:
    image: ghcr.io/YOUR_USER/inspector:latest
    pull_policy: always
    ports:
      - "5000:5000"
    volumes:
      - ./data:/data
    restart: unless-stopped
```

Reviewer workflow:

1. Install Docker Desktop (one GUI installer on Mac/Windows; `apt install docker.io` on Linux).
2. Save the `docker-compose.yml` above in a folder, edit the volume path to point at their Quran data.
3. Open a terminal in that folder. Run `docker compose up`.
4. Open http://localhost:5000.
5. Next launch: same command. `pull_policy: always` auto-fetches new versions from main.

Contributors running from a source checkout instead of the published image:

```bash
cd inspector && docker compose up
# or, from repo root:
docker build -t inspector:dev inspector/
docker run --rm -p 5000:5000 -v "$PWD/data:/data" inspector:dev
```

The in-repo `inspector/docker-compose.yml` uses `../data:/data` so the volume reaches `<repo>/data` from the `inspector/` folder.

Total install footprint on their machine: Docker Desktop. Nothing Python, nothing Node, no ffmpeg.

## Mode B — hosted deployment

Same image, deploy to any container host:

```bash
fly launch --image ghcr.io/YOUR_USER/inspector:latest --volume data:/data
# or Render / Railway / DigitalOcean / Hetzner VPS / etc.
```

Persistent volume at `/data` survives deploys. Reviewers get a URL; no client install at all.

### Single-writer lock for concurrent editors

`inspector/services/save.py` (and `undo.py`) need a flock wrapper around the atomic-write + rebuild-segments.json pipeline. Roughly:

```python
import fcntl
from pathlib import Path
from inspector.config import DATA_DIR

_LOCK_PATH = DATA_DIR / ".save.lock"

def _with_save_lock(fn):
    """Serializes concurrent writes across requests."""
    def wrapper(*args, **kwargs):
        with open(_LOCK_PATH, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return fn(*args, **kwargs)
    return wrapper

# Apply to save_segments, revert_batch, undo_op, etc.
```

Second writer waits ~200ms for the first to finish. `edit_history.jsonl` appends go inside the lock so the log stays consistent. Acceptable for "few trusted editors, rarely concurrent". Skip optimistic concurrency / WebSocket presence UI unless conflicts actually appear in practice.

## CI — GitHub Actions auto-publish on push to main

One-time setup. After this workflow lands, the maintainer's only action per update is `git push`.

```yaml
# .github/workflows/docker-publish.yml
name: Build and publish Docker image
on:
  push:
    branches: [main]
    paths:
      - 'inspector/**'
      - '.github/workflows/docker-publish.yml'

jobs:
  build:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - uses: docker/build-push-action@v6
        with:
          context: inspector
          push: true
          tags: |
            ghcr.io/${{ github.repository_owner }}/inspector:latest
            ghcr.io/${{ github.repository_owner }}/inspector:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

GHCR is free for public packages and generous for private. After the first successful run, make the package public via the GitHub package settings page so reviewers can pull without auth.

## Maintainer workflow after setup

1. Land changes on `main`.
2. GitHub Actions rebuilds the image (~2–3 min) and pushes to `ghcr.io`.
3. Reviewers' next `docker compose up` pulls the new image automatically. Their `/data` volume persists.

That's the entire update loop. No manual `docker build` / `docker push` steps.

## Reviewer updates — what they see

- **Automatic** via `pull_policy: always` in their compose file. New version downloaded at each launch.
- **Data preserved** across updates (the mounted volume is independent of the image).
- **First-launch pull**: ~1–2 min on decent internet. Subsequent updates typically small deltas.

## Schema evolution

Biggest real-world risk when shipping updates to reviewers with live data:

- `detailed.json` and `edit_history.jsonl` schemas must stay **backward-compatible on read**. Precedent already exists in the codebase — e.g., the `Segment.ignored?: boolean` legacy fallback (B10 in the Stage-1 bug log) is still read by `validation/categories.ts` for pre-`ignored_categories` rows.
- If a future change requires a schema break, run a one-time migration on startup (detect old format, rewrite to new). Never silently break reviewer data.
- API contract: if endpoints ever change shape, add `/api/v2/...` routes with a grace period rather than modifying in place.

These are app-level concerns, not Docker concerns. Docker doesn't help or hurt here.

## Stage 2 (Svelte) compatibility

Stage 2 (Svelte 4 migration) is **complete** (Wave 11b, 2026-04-14). The frontend was migrated using **plain Svelte 4 + Vite** (not SvelteKit) with the same `frontend/dist/` build output directory. The Dockerfile `COPY --from=frontend /app/dist` line does not need to change. Runtime stays Flask-only. Image size unchanged.

## Decisions to make

- **Mode A vs B vs both**: for the expected user base (reviewers each with their own Quran data), Mode A is primary. Mode B only if shared-dataset review becomes a workflow.
- **Image tag strategy**: `:latest` (zero-maintenance, always current) vs semver tags (`:v1.2`, reviewer pins explicitly). `:latest` is fine for a small trusted group; add semver later if reviewers ever need to stay on an older version.
- **Public vs private GHCR package**: public is simpler for reviewers (no auth) but exposes the source indirectly via the image. Private requires reviewers to generate a personal-access-token + `docker login` once. Default to public unless there's a reason not to.
- **CLAUDE.md**: currently gitignored (`inspector/.gitignore:5`). Orthogonal to Docker, but if this distribution plan ships, unignoring CLAUDE.md and shipping it to reviewers-who-also-touch-code becomes relevant.

## Work order, if picking this up

1. ~~Refactor `config.py` to read paths from `INSPECTOR_DATA_DIR` env var (default unchanged).~~ **DONE** (Wave 2a)
2. ~~Write the `Dockerfile` under `inspector/` (co-located with the component it deploys).~~ **DONE** (Wave 2a)
3. Test locally: `docker build -t inspector inspector/ && docker run -p 5000:5000 -v $PWD/data:/data inspector`.
4. ~~Write `inspector/docker-compose.yml` as the reviewer-facing artifact.~~ **DONE** (Wave 2a)
5. Add the `.github/workflows/docker-publish.yml` workflow.
6. Push; verify CI builds green; make the GHCR package public.
7. (Mode B only) Add the flock wrapper to save + undo.
8. Send reviewers the compose file + 5-step install README.

Remaining work: steps 3 (validate Docker build + run), 5-6 (CI pipeline), 7 (optional Mode B), 8 (reviewer instructions). Roughly half a day.
