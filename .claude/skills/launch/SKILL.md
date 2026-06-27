---
name: launch
description: Run the Inspector app locally — any mode (dev bucket / offline fixtures / live dev or prod Space), any worktree, conflict-free. Picks free ports, isolates each worktree's SQLite, waits for real readiness, and can smoke-test the Dashboard + Timestamps tabs. Use whenever you need the app running — for a human to click around or for an agent to drive with Playwright/Chrome MCP. Also: list / stop / doctor running stacks. Trigger: /launch
---

# launch

One script runs every way of starting the Inspector and keeps parallel launches from colliding. **You almost never need to think — just run it.**

```bash
python scripts/devenv/launch.py [up] [--mode MODE] [flags]
```

The script (`scripts/devenv/launch.py`) owns everything that used to go wrong by hand: free-port allocation, per-worktree SQLite isolation (`INSPECTOR_DB_PATH`), interpreter pinning (`sys.executable`, so no python3-vs-Python313 split), Vite⇄backend proxy wiring, readiness polling (`/healthz` + the Vite port), and a machine-wide registry so it can `list` / `down` / `doctor` every stack. It prints human URLs **and** a `LAUNCH_JSON {…}` line an agent can parse.

## Just run it

| Goal | Command |
|---|---|
| **Run the app (real prod data, default)** | `python scripts/devenv/launch.py` |
| Experiment against the dev bucket's data | `python scripts/devenv/launch.py up --mode dev-remote` |
| Run your branch's local backend | `python scripts/devenv/launch.py up --mode dev` |
| Fully offline (no token/network) | `python scripts/devenv/launch.py up --mode fixtures` |
| Run a different worktree | `… up --worktree <name|path>` |
| Start + verify Dashboard & Timestamps | `… up --smoke` |
| Open in a browser too | `… up --open` |
| What's running? | `python scripts/devenv/launch.py list` |
| Stop this worktree's stack | `python scripts/devenv/launch.py down` |
| Stop everything | `python scripts/devenv/launch.py down --all` |
| Fix "wrong port / two Flasks / stale Vite" | `python scripts/devenv/launch.py doctor --fix` |
| Smoke an already-running stack or any URL | `python scripts/devenv/launch.py smoke [--url …]` |

## Modes

- **prod-remote** *(default)* — Vite only, `/api` proxied to the live PROD Space. Real published data, no local backend, fast, and works on Windows (no `hf-mount` needed). The everyday "run the app / test the FE" mode; serves audio + analysis for published reciters. Read-only and prod-safe.
- **dev-remote** — Vite only, `/api` proxied to the live DEV Space. The dev bucket's data (WIP / unpublished reciters). Use when you want to see what's in the dev bucket.
- **dev** — local Flask against the DEV bucket (read-write) + Vite HMR. The only mode that runs your branch's **backend**. Needs `HF_TOKEN`. On Windows the no-mount hffs path can't serve the audio-manifest sidecar or timestamps shards, so **audio + analysis won't load** — use it for backend/catalog work, not playback.
- **fixtures** — fully offline: filesystem backend on seeded fixtures (auto-seeds on first run) + Vite. No token, no network.

## For agents (Playwright / Chrome MCP)

Run `up` (optionally `--no-vite` for backend-only, or a `*-remote` mode for no backend), read the `LAUNCH_JSON` line for the `url`, then drive that URL. `--smoke` runs a bundled headless-chromium check of the Dashboard (catalog fetches succeed) and Timestamps (a real TS-capable reciter renders the waveform); screenshots + `result.json` land in `<worktree>/.local/launch/smoke/`.

## Parallel & conflict-safety

Two worktrees (or two stacks) can run at once: ports are allocated free + reserved in the registry, and each worktree gets its own `INSPECTOR_DB_PATH` so SQLite never clobbers. `doctor` detects the failure modes we actually hit — two processes bound to one port (serving stale code), a foreign/orphan Flask or Vite, dead registry entries — and `--fix` cleans them.

## Notes

- First run in a fresh worktree needs deps: `scripts/devenv/setup.sh` (or `npm ci` in `inspector/frontend`). The `wt` skill's setup does this.
- **Windows + audio/analysis → use a `*-remote` mode.** There's no `hf-mount` on Windows, so local `dev` reads go through the hffs fallback, which doesn't serve the audio-manifest sidecar or timestamps shards — so audio won't play and the analysis frame stays empty in `dev`. `prod-remote` (published reciters) and `dev-remote` proxy to a Space with the mounted bucket, so both work. FE changes (your branch's `inspector/frontend`) are always live in any mode via local Vite.
- Logs: `<worktree>/.local/launch/logs/`. Registry: `<main-worktree>/.local/launch/registry.json` (gitignored).
- Python changes need a `down` + `up` (Flask reloader is off by design — single-worker invariant). Vite changes hot-reload.
