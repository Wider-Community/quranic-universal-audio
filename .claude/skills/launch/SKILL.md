---
name: launch
description: Run the Inspector app locally — any mode (dev bucket / offline fixtures / live dev or prod Space), any worktree, conflict-free.
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
| **Run the app (real DEV data, default)** | `python scripts/devenv/launch.py` |
| Read-only look at PROD data (local) | `python scripts/devenv/launch.py up --mode prod` |
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

**Every mode is fully local** — your branch's Flask backend + Vite, no HF Space proxy, no `hf-mount`. Bucket reads use the `hffs` fallback (sub-second on the dev bucket; the bigger prod bucket is slower, multi-second cold); audio CDN-falls-back via the proxy. The only thing that changes between modes is **which data the backend reads**. Needs `HF_TOKEN` (in `.env`) for the bucket modes.

- **dev** *(default)* — backend reads the **DEV bucket**, read-write. The everyday mode: runs your branch end-to-end (audio + analysis included), HMR for FE changes.
- **prod** — backend reads the **PROD bucket**, **read-only**: bucket write-back is disarmed (`INSPECTOR_DB_SYNC=0`), so a stray edit can never sync the full-file DB over production. A safe local look at real production data. First reads are slow (big uncached prod bucket over hffs).
- **fixtures** — fully offline: filesystem backend on seeded fixtures (auto-seeds on first run) + Vite. No token, no network.

## For agents (Playwright / Chrome MCP)

Run `up` (it starts both backend + Vite), read the `LAUNCH_JSON` line for the `url`, then drive that URL. Use **dev** (the default). `--smoke` runs a bundled headless-chromium check of the Dashboard (catalog fetches succeed) and Timestamps (the first TS reciter renders a non-empty waveform); screenshots + `result.json` land in `<worktree>/.local/launch/smoke/`.

## Parallel & conflict-safety

Two worktrees (or two stacks) can run at once: ports are allocated free + reserved in the registry, and each worktree gets its own `INSPECTOR_DB_PATH` so SQLite never clobbers. `doctor` detects the failure modes we actually hit — two processes bound to one port (serving stale code), a foreign/orphan Flask or Vite, dead registry entries — and `--fix` cleans them.

## Notes

- First run in a fresh worktree needs deps: `scripts/devenv/setup.sh` (or `npm ci` in `inspector/frontend`). The `wt` skill's setup does this.
- **The full app runs locally on Windows** — audio + analysis included, no `hf-mount` needed. Bucket reads go through the `hffs` fallback (dev bucket sub-second; prod bucket multi-second cold) and audio CDN-falls-back via the proxy. A shard 404 in `dev` is the released-gate (the reciter isn't `released` in this worktree's isolated DB) or missing bucket data, **not** a platform limit. FE changes are always live via local Vite.
- Logs: `<worktree>/.local/launch/logs/`. Registry: `<main-worktree>/.local/launch/registry.json` (gitignored).
- Python changes need a `down` + `up` (Flask reloader is off by design — single-worker invariant). Vite changes hot-reload.
