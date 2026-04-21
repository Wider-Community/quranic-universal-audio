# Stage 2 — Wave 2a Handoff (interim)

**Status**: COMPLETE (interim — Wave 2b still pending)
**Branch**: `worktree-refactor+inspector-modularize`
**Known-good entry commit**: `6d32308` (WIP pre-Wave-2 carry-forward on top of `7961bae` Wave-1 exit)
**Known-good exit commit**: `5addf33` (all 7 gates green; Docker smoke skipped for lack of docker)
**Agent**: Opus 4.6 (1M), role: implementation-Wave-2a, 2026-04-13.

---

## 1. Scope delivered

| Item | Description | Commit |
|------|-------------|--------|
| 0 | WIP-commit inspection — document what `6d32308` already did | (notes below) |
| 1 | Pre-flight baseline at entry — all 7 gates green | (verification only) |
| 2 | `config.py` — `INSPECTOR_DATA_DIR` env override; all 5 data paths + `CACHE_DIR` derive from `DATA_DIR` | `c1e4ca5` |
| 3 | Vendor `validators/` into `inspector/validators/`; delete `sys.path.insert` hack | `5be027a` |
| 4 | Dockerfile + docker-compose.yml + .dockerignore at repo root | `7b72085` |
| 5 | `inspector/requirements-dev.txt` placeholder | `55e175a` |
| 6 | `.refactor/stage2-checks.sh` — enable Docker smoke gate, guard on `command -v docker` | `5addf33` |
| 7 | This handoff doc | (bundled with orchestration log commit) |
| 8 | Orchestration log row | (bundled with this handoff) |

### Item 0 — WIP commit findings

`6d32308 wip(inspector): pre-Wave-2 work-in-progress from prior session` (22 files,
+248/-121). Themes:

1. On-demand waveform peaks via HTTP Range (frontend + `routes/audio_proxy.py`).
2. Qalqala "End of verse" filter (backend + frontend).
3. "Auto Fix" → "Auto Fill" relabelling.
4. Stale seg-index refresh after split.
5. Accordion-context defaults flipped (`low_confidence`, `cross_verse` → `hidden`) — **touches `config.py`**.
6. Continuous-play playhead clearing fix.
7. Edit-overlay body-class cleanup.
8. Muqattaat exemption from `ignored_categories` on ref edit.
9. Error-card animation cleanup.

**Wave 2a impact**: Only `inspector/config.py` overlapped with Wave 2a scope.
The WIP only flipped two `ACCORDION_CONTEXT` dict values (lines 75, 78). No
partial `INSPECTOR_DATA_DIR` wiring existed — a fresh write on top of the
WIP state was safe and I built on the WIP lines (the new `DATA_DIR` block
sits above the unchanged `ACCORDION_CONTEXT`). No reconciliation needed.

`services/validation.py` got a 2-line qalqala `end_of_verse` addition that's
fully orthogonal to Wave 2a's vendoring work.

### Item 1 — Entry pre-flight

At `6d32308`: all 7 gates pass. `23` `import/no-cycle` warnings — exactly
matches the Wave-1 baseline ceiling (no new cycles introduced by the WIP's
13 frontend segments files, which is good).

### Item 2 — `config.py`

- New `DATA_DIR = Path(os.environ.get("INSPECTOR_DATA_DIR", str(_REPO / "data"))).resolve()`.
- Five per-category paths derived from `DATA_DIR`:
  - `AUDIO_PATH = DATA_DIR` (**critical**: stays equal to the root, NOT
    `DATA_DIR/recitation_segments` as the docker-distribution doc draft
    suggested — verified by reading `app.py`'s `/audio/<reciter>/<file>`
    route which maps to `<DATA_DIR>/<reciter>/<file>`, and the draft doc
    was wrong on this point).
  - `SURAH_INFO_PATH = DATA_DIR / "surah_info.json"`
  - `RECITATION_SEGMENTS_PATH = DATA_DIR / "recitation_segments"`
  - `AUDIO_METADATA_PATH = DATA_DIR / "audio"`
  - `TIMESTAMPS_PATH = DATA_DIR / "timestamps"`
- `CACHE_DIR` moves from `_REPO / "inspector" / ".cache"` to `DATA_DIR / ".cache"`
  (S2-D04), with an `INSPECTOR_CACHE_DIR` env override as an escape hatch.
- Existing `INSPECTOR_QUA_DATA_PATH` override kept untouched.

**Cache-location migration**: The default `CACHE_DIR` changed location. Users
with a populated old `inspector/.cache/` will see peaks re-compute on first
view per reciter (one-time ffmpeg cost), and the audio-proxy / phoneme
caches will rebuild on-demand. Not a data-loss issue — all three caches are
derived artifacts. Documented here so a reviewer isn't surprised by the
one-time perf hit. An explicit `INSPECTOR_CACHE_DIR=<old_path>` env works as
a non-destructive escape.

Verification (shown in commit message):
- Default paths resolve correctly.
- `INSPECTOR_DATA_DIR=/tmp/test` overrides cleanly.
- `INSPECTOR_CACHE_DIR=...` overrides independently.
- `python3 -c "from app import app"` still imports.

### Item 3 — Vendor validators

- `cp validators/{validate_segments,validate_timestamps,validate_audio,validate_audio_ci,validate_edit_history}.py validators/README.md inspector/validators/`
- Added `inspector/validators/__init__.py` (empty) — source dir was script-only, not a package.
- Removed the 3-line `sys.path.insert` hack in `routes/timestamps.py` (lines 27-29 of the pre-state).
- Late imports stay `from validators.validate_segments import ...` / `from validators.validate_timestamps import ...`. These now resolve to the vendored copy because `python3 inspector/app.py` places `inspector/` on `sys.path[0]` and `inspector/validators/` is a proper package there.
- Verified by `python3 -c "import validators.validate_segments as vs; print(vs.__file__)"` — resolves to `inspector/validators/validate_segments.py`.
- Sibling `validators/` at repo root retained for the extract-pipeline CLIs (e.g. `validate_audio_ci.py` run from the repo root). The two copies can diverge freely from here.
- Source SHA recorded in `.refactor/stage2-decisions.md` S2-D03 (`fb889d7`, 2026-04-10).

### Item 4 — Docker distribution

Three new repo-root files. Draft source: `docs/inspector-docker-distribution.md`.

**Dockerfile** — two stages:
- Stage 1 (`node:20-slim`): `npm install && npm run build` produces `dist/`. Chose `install` not `ci` because the repo has no `package-lock.json` committed (CLAUDE.md's run instructions already use `npm install`).
- Stage 2 (`python:3.11-slim`): installs ffmpeg, pip-installs `inspector/requirements.txt`, copies `inspector/` (validators come along because they're vendored), copies the built `dist/` from stage 1.
- `ENV INSPECTOR_DATA_DIR=/data`, `PYTHONUNBUFFERED=1`.
- `CMD ["python3", "inspector/app.py"]` — Python auto-adds `/app/inspector/` to `sys.path[0]`, so bare `from config import ...` and vendored `from validators.xxx import ...` both resolve.

**docker-compose.yml** — minimal:
- `build: .` + `image: inspector:dev` (locally-built for now; the doc's `pull_policy: always` + `ghcr.io/...` swap is noted inline for when the publish workflow lands).
- Volume `./data:/data`, port `5000:5000`.

**.dockerignore**:
- Excludes `.git`, `data`, `docs`, `node_modules`, `dist`, caches, venvs, IDE/agent dirs, Python cruft, the sibling `validators/` at repo root (vendored now), `requirements-dev.txt` (dev-only).

**Build verification**: Docker is **not installed** on this WSL worktree (`command -v docker` returns empty). No actual build was run. Pre-flight script's new Docker smoke block is skipped on this machine; someone with docker should run `bash .refactor/stage2-checks.sh` on a docker-equipped dev machine before the Wave 2a merge to confirm end-to-end.

### Item 5 — `requirements-dev.txt`

Empty per S2-D05 + S2-D07. Header comment documents the intent. Dockerfile does NOT copy it (`.dockerignore` excludes it).

### Item 6 — Pre-flight Docker smoke gate

Replaces the commented-out draft block with a `command -v docker`-gated real invocation:
- Build with explicit FAIL branch.
- Run detached with explicit FAIL branch.
- `sleep 5` (bumped from the draft's 3 because the eager phonemizer + timestamp preload adds 2-3s of startup on a cold container).
- `curl -s -f http://localhost:5000/api/seg/config` as the smoke probe (route already exists in `routes/segments_data.py`).
- Cleanup via `docker rm -f inspector-dev` on both pass and fail branches.
- SKIPPED message when docker isn't available, so the pre-flight still exits 0 on this WSL worktree.

---

## 2. Scope deferred

Nothing from the Wave 2a plan deferred. Wave 2b items remain untouched as required:

- `app.py` structured logging.
- Thin-route extraction.
- `save_seg_data` decomposition (S2-D08).
- Magic-number sweep.

---

## 3. Deviations from plan

1. **Docker draft doc wrong on `AUDIO_PATH`**. The doc's sketch says
   `AUDIO_PATH = DATA_DIR / "recitation_segments"`. That would break the
   `/audio/<reciter>/<file>` route in `app.py` which serves `<AUDIO_PATH>/<reciter>/<file>`.
   Actual current layout: reciter audio lives directly under `data/<reciter>/`,
   so `AUDIO_PATH == DATA_DIR`. Followed the code, not the doc. No plan
   deviation — the plan said "verify current layout".
2. **`npm install` not `npm ci`** in the Dockerfile. The repo has no
   `package-lock.json` committed (CLAUDE.md's run instructions say `npm install`).
   Added a comment noting the swap once a lockfile lands.
3. **Sleep bumped 3s → 5s** in the Docker smoke gate. 3s was the draft doc's
   number; in practice the phonemizer init + timestamp preload adds a couple
   seconds inside a cold container. Non-functional deviation.

---

## 4. Surprises

None material. The advisor pass caught one potential trip (needed
`__init__.py` in `inspector/validators/`) before it happened.

One worth documenting for Wave 2b's agent:

- **WIP commit `6d32308`** left an unrelated modification in the working
  tree at `inspector/frontend/src/styles/validation.css` (a comment rewrite
  around `content-visibility` — see the diff). Wave 2a did NOT stage it. It
  continues to show in `git status` as modified. Wave 2b can safely ignore
  it or fold it into one of its own commits — not blocking.

---

## 5. Verification — gate-by-gate

Final run at `5addf33`:

| Gate | Status | Notes |
|------|--------|-------|
| 1/7 typecheck | PASS | `tsc --noEmit` clean |
| 2/7 lint | PASS | 23 warnings (all pre-existing cycles) |
| 3/7 build | PASS | Vite build 5.24s, unchanged bundle sizes |
| 4/7 global-leak | PASS | `services/cache.py` still sole owner |
| 5/7 orphan caches | PASS | `_URL_AUDIO_META` / `_phonemizer` only in cache.py |
| 6/7 cycle NOTEs | PASS | Zero `// NOTE: circular dependency` comments |
| 7/7 cycle ceiling | PASS | 23 warnings ≤ 23 ceiling |
| wave-2+ Docker smoke | SKIPPED | `docker` not available on this WSL worktree |

Additionally verified manually:
- `python3 -c "from app import app"` — clean.
- `python3 -c "from services.validation import validate_reciter_segments"` — clean.
- `python3 -c "import validators.validate_segments as vs; print(vs.__file__)"` — resolves to `inspector/validators/...`.
- `grep -rn "sys.path.insert" inspector/` → only remaining hit is inside `inspector/validators/validate_audio_ci.py` (CLI-only; not imported by the app). Acceptable.

---

## 6. Carry-forward to Wave 2b

### 6.1 Entry state
- HEAD: `5addf33`.
- All 7 pre-flight gates green; Docker smoke skipped (no docker on this worktree; should be verified on a docker-equipped machine).
- No unstaged modifications attributable to Wave 2a (only the WIP-era `validation.css` comment rewrite remains modified — see §4 Surprises).

### 6.2 Wave-2a artifacts touching Wave-2b scope
Nothing. The 5 commits are mechanical (config parameterization, vendoring, distribution scaffolding). Wave 2b's structured-logging / thin-routes / `save_seg_data` decomposition / magic-number sweep all operate on modules Wave 2a did not touch (except `routes/timestamps.py` which lost only its 3-line sys.path hack at the top — the route bodies are untouched).

### 6.3 Reviewer attention
- Verify the `CACHE_DIR` relocation doesn't break any implicit contract I missed. Grep was exhaustive (`grep -rn CACHE_DIR inspector/`); all 7 hits are imports from `config` or usages of the resolved `Path`.
- Run `bash .refactor/stage2-checks.sh` on a docker-equipped machine — confirms end-to-end image build + run + `/api/seg/config` probe succeed.

### 6.4 No bug-log impact
Wave 2a introduces no new bugs. The WIP's 9 themes all predate this wave and stay out of the Stage-2 bug log scope.

### 6.5 Wave 2b's starting-point checklist
Before editing:
1. `git log --oneline 7961bae..HEAD` — should show 5 Wave-2a commits + the WIP commit.
2. `bash .refactor/stage2-checks.sh` — all gates green.
3. Read §4 Wave 2b in `stage2-plan.md` — unchanged by Wave 2a.

---

## 7. Commits (exit-point detail)

```
5addf33 chore(inspector): stage2-checks.sh — enable Docker smoke gate for Wave 2+
55e175a chore(inspector): add requirements-dev.txt placeholder
7b72085 feat(inspector): Docker distribution — Dockerfile, docker-compose.yml, .dockerignore
5be027a refactor(inspector): vendor validators/ into inspector/validators/, delete sys.path hack
c1e4ca5 refactor(inspector): config — INSPECTOR_DATA_DIR env override, all data paths derive from it
```

Commit line count: 5 + 1 handoff/orchestration = 6 Wave-2a commits total.
