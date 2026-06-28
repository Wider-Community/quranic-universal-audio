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
| Open in a browser too | `… up --open` |
| What's running? | `python scripts/devenv/launch.py list` |
| Stop this worktree's stack | `python scripts/devenv/launch.py down` |
| Stop everything | `python scripts/devenv/launch.py down --all` |
| Fix "wrong port / two Flasks / stale Vite" | `python scripts/devenv/launch.py doctor --fix` |

## Modes

**Every mode is fully local** — your branch's Flask backend + Vite, no HF Space proxy, no `hf-mount`. Bucket reads use the `hffs` fallback (sub-second on the dev bucket; the bigger prod bucket is slower, multi-second cold); audio CDN-falls-back via the proxy. The only thing that changes between modes is **which data the backend reads**. Needs `HF_TOKEN` (in `.env`) for the bucket modes.

- **dev** *(default)* — backend reads the **DEV bucket**, read-write. The everyday mode: runs your branch end-to-end (audio + analysis included), HMR for FE changes.
- **prod** — backend reads the **PROD bucket**, **read-only** (two guards: `INSPECTOR_READ_ONLY=1` makes the storage backend refuse *every* write — segment saves, manifests, job records — and `INSPECTOR_DB_SYNC=0` keeps DB commits local). Nothing local can mutate production by any path; an edit attempt fails loud rather than corrupting prod. A safe look at real production data. First reads are slow (big uncached prod bucket over hffs).
- **fixtures** — fully offline: filesystem backend on seeded fixtures (auto-seeds on first run) + Vite. No token, no network.

### Per-content read source

The bucket isn't the fastest source for every content type locally. By default in `dev`/`prod`:
- **Audio → CDN** (not the bucket): the bucket's hffs full-MP3 read is slow locally, and the CDN is the same audio for most reciters. `--bucket-audio` forces the bucket (to verify the re-encoded/stereo-fixed audio that can differ from the CDN). `fixtures` always reads local audio (offline, no CDN).
- **Peaks → bucket** (slim `peaks/*.json.gz`): `--ffmpeg-peaks` skips them so the FE computes per-segment peaks via ffmpeg instead.
- **Shards / detailed / manifest → bucket** always (no toggle).

Knobs: `INSPECTOR_AUDIO_FROM_BUCKET` / `INSPECTOR_PEAKS_FROM_BUCKET` (the launcher owns these per mode; the flags above override).

## For agents (driving the running app)

Run `up` (it starts both backend + Vite), read the `LAUNCH_JSON` line for the `url`, then drive that URL with a browser MCP. Use **dev** (the default).

**Default driver: `chrome-devtools-mcp`.** Measured on this app's Dashboard, its a11y snapshot is ~2.6× smaller than playwright's (≈14 KB vs ≈38 KB for the same page), its actions return a one-line ack (snapshot is opt-in, not forced on every call), and it carries the DevTools tools we actually use here — network request bodies, console, `performance_start_trace`, `evaluate_script`, throttling/emulation. Net: fewer tokens per step and the right debugging surface.

Reach for **`playwright`** instead only for pure interaction (multi-step forms, exploratory clicking) where its auto-snapshot-on-every-action is convenient and you don't need network/console/perf.

Typical loop: `navigate_page` → `take_snapshot` (grab the `uid`s) → `click`/`fill` by `uid` → `take_screenshot`. There's no built-in liveness check — your first `navigate` + `take_snapshot` already tells you whether the stack is serving real data.

## Parallel & conflict-safety

Two worktrees (or two stacks) can run at once: ports are allocated free + reserved in the registry, and each worktree gets its own `INSPECTOR_DB_PATH` so the **local** SQLite never clobbers. `doctor` detects the failure modes we actually hit — two processes bound to one port (serving stale code), a foreign/orphan Flask or Vite, dead registry entries — and `--fix` cleans them.

**The bucket is NOT isolated, though.** All `dev` stacks (and the live dev Space) share one dev bucket: the DB syncs full-file with a CAS guard (no row merge) and per-reciter content is last-write-wins, so **two concurrent dev *writers* can clobber each other** — the single-writer invariant. Launch **warns** when you start a 2nd `dev` stack while another is up. For a safe parallel stack use `prod` (read-only) or `fixtures` (local disk, fully isolated); only ever *edit* in one `dev` stack at a time.

## Env ownership (`.env` vs launch)

The launcher **owns every run-mode knob** — `INSPECTOR_BACKEND`, `INSPECTOR_FILESYSTEM_ROOT`, `INSPECTOR_ALLOW_PROD_BUCKET`, `INSPECTOR_READ_ONLY`, `INSPECTOR_DB_SYNC`, `INSPECTOR_AUTO_MOUNT`, `INSPECTOR_DB_PATH` — and sets them per mode, so a stale `.env` can't perturb the profile. `dev` forces `ALLOW_PROD_BUCKET=0` (can never touch prod; fails closed if `.env` names the prod repo). `.env` only supplies **secrets + identity** (HF/GitHub/QF tokens, session secret, dev-owner id) and the one per-machine choice the launcher reads in `dev`: your own `INSPECTOR_BUCKET_REPO` dev bucket. Those knobs in `.env` matter only when hand-running `python inspector/app.py`.

## Notes

- First run in a fresh worktree needs deps: `scripts/devenv/setup.sh` (or `npm ci` in `inspector/frontend`). The `wt` skill's setup does this.
- **The full app runs locally on Windows** — audio + analysis included, no `hf-mount` needed. Bucket reads go through the `hffs` fallback (dev bucket sub-second; prod bucket multi-second cold) and audio CDN-falls-back via the proxy. A shard 404 in `dev` is the released-gate (the reciter isn't `released` in this worktree's isolated DB) or missing bucket data, **not** a platform limit. FE changes are always live via local Vite.
- Logs: `<worktree>/.local/launch/logs/`. Registry: `<main-worktree>/.local/launch/registry.json` (gitignored).
- Python changes need a `down` + `up` (Flask reloader is off by design — single-worker invariant). Vite changes hot-reload.
