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
| Dev (real DEV-bucket data, this worktree) | `python scripts/devenv/launch.py` |
| Fully offline (no token/network) | `python scripts/devenv/launch.py up --mode fixtures` |
| Read-only view of the live DEV Space | `python scripts/devenv/launch.py up --mode dev-remote` |
| Read-only view of the live PROD Space | `python scripts/devenv/launch.py up --mode prod-remote` |
| Run a different worktree | `… up --worktree <name|path>` |
| Start + verify Dashboard & Timestamps | `… up --smoke` |
| Open in a browser too | `… up --open` |
| What's running? | `python scripts/devenv/launch.py list` |
| Stop this worktree's stack | `python scripts/devenv/launch.py down` |
| Stop everything | `python scripts/devenv/launch.py down --all` |
| Fix "wrong port / two Flasks / stale Vite" | `python scripts/devenv/launch.py doctor --fix` |
| Smoke an already-running stack or any URL | `python scripts/devenv/launch.py smoke [--url …]` |

## Modes

- **dev** — local Flask against the DEV bucket (real, read-write) + Vite HMR. The default. Needs `HF_TOKEN` (from `.env`); without it, use `fixtures`.
- **fixtures** — fully offline: filesystem backend on seeded fixtures (auto-seeds on first run) + Vite. No token, no network.
- **dev-remote** / **prod-remote** — Vite only, `/api` proxied to the live Space. No local backend, read-only, fast. Use to look at real deployed data or for FE-only work. `prod-remote` never touches the prod bucket locally, so it's safe.

## For agents (Playwright / Chrome MCP)

Run `up` (optionally `--no-vite` for backend-only, or a `*-remote` mode for no backend), read the `LAUNCH_JSON` line for the `url`, then drive that URL. `--smoke` runs a bundled headless-chromium check of the Dashboard (catalog fetches succeed) and Timestamps (a real TS-capable reciter renders the waveform); screenshots + `result.json` land in `<worktree>/.local/launch/smoke/`.

## Parallel & conflict-safety

Two worktrees (or two stacks) can run at once: ports are allocated free + reserved in the registry, and each worktree gets its own `INSPECTOR_DB_PATH` so SQLite never clobbers. `doctor` detects the failure modes we actually hit — two processes bound to one port (serving stale code), a foreign/orphan Flask or Vite, dead registry entries — and `--fix` cleans them.

## Notes

- First run in a fresh worktree needs deps: `scripts/devenv/setup.sh` (or `npm ci` in `inspector/frontend`). The `wt` skill's setup does this.
- On Windows there's no `hf-mount`, so `dev` reads fall back to slower hffs; first reciter load takes a few seconds. `fixtures` and the `*-remote` modes avoid that.
- Logs: `<worktree>/.local/launch/logs/`. Registry: `<main-worktree>/.local/launch/registry.json` (gitignored).
- Python changes need a `down` + `up` (Flask reloader is off by design — single-worker invariant). Vite changes hot-reload.
