# Stage 2 — Wave 2 Handoff (full; supersedes interim 2a)

**Status**: COMPLETE
**Branch**: `worktree-refactor+inspector-modularize`
**Known-good entry commit**: `7961bae` (Wave 1 exit)
**Known-good exit commit**: `0cd5830` (all 7 pre-flight gates green)
**Agents**: Opus 4.6 (1M), roles: implementation-Wave-2a + implementation-Wave-2b, 2026-04-13.

This supersedes `.refactor/stage2-wave-2a-handoff.md`, which was an interim
doc written at the end of sub-wave 2a (HEAD `5addf33`). The 2a doc is
retained for historical detail; this one is the single handoff for
downstream waves to read.

---

## 1. Scope delivered

### Wave 2a — config + Docker + vendoring (5 commits + 1 mid-wave relocation)

| Item | Description | Commit |
|------|-------------|--------|
| 2a-1 | Pre-flight baseline at entry (`6d32308` / post-WIP) — all 7 gates green | (verification only) |
| 2a-2 | `config.py` — `INSPECTOR_DATA_DIR` env override; all 5 data paths + `CACHE_DIR` derive from `DATA_DIR` | `c1e4ca5` |
| 2a-3 | Vendor `validators/` into `inspector/validators/`; delete `sys.path.insert` hack | `5be027a` |
| 2a-4 | `Dockerfile` + `docker-compose.yml` + `.dockerignore` | originally `7b72085` at repo root; relocated to `inspector/` in `e98fb20` (see §3) |
| 2a-5 | `inspector/requirements-dev.txt` placeholder | `55e175a` |
| 2a-6 | `.refactor/stage2-checks.sh` — Docker smoke gate, `command -v docker` guarded | `5addf33` |
| 2a-7 | Wave 2a interim handoff doc | `8d6e448` |

### Wave 2b — app cleanup + thin routes + targeted decomposition (6 commits)

| Item | Description | Commit |
|------|-------------|--------|
| 2b-1 | Pre-flight baseline at Wave-2b entry (`e98fb20`) — all 7 gates green | (verification only) |
| 2b-2 | `app.py` — stdlib `logging` + JSON formatter, central `@app.errorhandler`, `debug=False` default, `FLASK_ENV=development` branch | `e805f4e` |
| 2b-3/1 | Thin-route extraction: `seg_data` → `services/segments_query.py::get_chapter_data` | `d3137e7` |
| 2b-3/2 | Thin-route extraction: `ts_data` → `services/ts_query.py::get_verse_data` | `3269d77` |
| 2b-3/3 | Thin-route extraction: `seg_edit_history` → `services/history_query.py::load_edit_history` | `e7bb136` |
| 2b-4 | `save_seg_data` decomposition — 4 phase helpers + ~20-LOC orchestrator (S2-D08, pure extract-method) | `ddb743a` |
| 2b-5 | `config.py` magic-number sweep (peaks flags, worker counts, port default, `LOW_CONFIDENCE_RED`) | `0cd5830` |

### Item-level details — Wave 2b

#### Item 2b-2: `app.py` structured logging + error handler

- **JSONFormatter**: hand-written `logging.Formatter` subclass (~15 LOC,
  no new dependency). Emits `{time, level, name, msg, exc_info?}` as a
  single-line JSON payload. Idempotent installation (`_configure_logging`
  guards against duplicate handlers across Flask's reloader re-imports).
- **Error handlers**: `@app.errorhandler(HTTPException)` returns the
  canonical `{error: <description>}` + status code. `@app.errorhandler(Exception)`
  logs via `logger.exception(...)` and returns a generic
  `{"error": "internal server error"}` / 500 — doesn't leak internals.
- **Debug default**: `debug = os.environ.get("FLASK_ENV") == "development"`;
  `app.run(..., debug=debug, use_reloader=debug)`. Default is `False` for
  production/Docker; opt-in via env for local dev.
- Six existing `print()` startup diagnostics → `logger.info(...)` /
  `logger.warning(...)` at equivalent verbosity.
- Dropped unused `import sys`.

#### Item 2b-3: Thin-route extractions

Three separate commits, each a pure behavior-preserving move. In every
case the route handler shrinks to parse → call service → jsonify, and the
extracted service function preserves the exact response dict shape.

| Route | Before LOC | After LOC | Service | Service LOC |
|-------|-----------|-----------|---------|-------------|
| `seg_data` | 113 | 7 | `services/segments_query.py::get_chapter_data` | 131 |
| `ts_data` | 121 | 9 | `services/ts_query.py::get_verse_data` | 140 |
| `seg_edit_history` | 88 | 2 | `services/history_query.py::load_edit_history` | 105 |

- New service modules (rather than folding into `services/data_loader.py`
  at 317 LOC, or `services/undo.py` which is about reverse-applying
  ops) — consistent with the 200–300 LOC target in CLAUDE.md.
- `ts_data`'s two 404 error strings ("Reciter not found" vs "Verse not
  found") preserved via a transient `_error` discriminant in the service
  return dict that the route strips; no data shape change for the success path.
- Dropped now-unused imports from each route module after extraction
  (`json`, `statistics`, `collections.Counter`, `load_detailed`,
  `chapter_from_ref`, `load_qpc`, `load_dk`). `format_ms` in
  `routes/timestamps.py` was already dead pre-Wave-2b — left alone.
- Frontend consumers (`types/api.ts::SegDataResponse`, `TsDataResponse`,
  `SegEditHistoryResponse`) unchanged; verified no shape drift.

#### Item 2b-4: `save_seg_data` decomposition

140-LOC function decomposes into a ~20-LOC orchestrator + four module-level
phase helpers:

- `_build_seg_lookups(matching)` → `(by_time, by_uid)`.
- `_make_seg(s, existing_by_time, existing_by_uid)` — promoted from
  nested closure to module-level; the closure previously captured the two
  lookups, which are now explicit params. **This is the only structural
  change**; everything else is a cut-and-paste.
- `_apply_full_replace(matching, updates, by_time, by_uid)` — returns
  `None` on success or `(error_dict, 400)` on input validation failure.
  Route-side `isinstance(result, tuple)` check preserved.
- `_apply_patch(matching, updates)` — returns `None` (mutates in place).
- `_persist_and_record(reciter, chapter, entries, meta, val_before, updates)`
  → `{"ok": True}`.

**Per S2-D08 constraints**:
- Pure extract-method: no control-flow changes, no field renames, no
  error-handling restructure.
- `dict | tuple` return contract preserved — the orchestrator keeps the
  early-return error-tuple guards inline (advisor-recommended: a
  `_load_and_validate` helper would have forced an awkward discriminant
  return type for different error envelope shapes).
- Execution order verified identical to pre-extract inline flow.
- Comments / variable names preserved verbatim where possible.

#### Item 2b-5: Magic-number sweep

New `config.py` constants + their use sites:

| Constant | Value | Consumer | Lines touched |
|----------|-------|----------|---------------|
| `PEAKS_FFMPEG_SAMPLE_RATE` | 8000 | `services/peaks.py` | 4 (ffmpeg `-ar` flag + sample-count math, twice each) |
| `PEAKS_PCM_NORMALIZER` | 32768.0 | `services/peaks.py` | 4 (int16→float divisor, 2 call sites × 2 channels) |
| `PEAKS_WORKER_COUNT` | 8 | `services/peaks.py` (`get_peaks_for_reciter`) | 1 |
| `PEAKS_MIN_CHUNK_BYTES` | 100 | `services/peaks.py` (`_range_decode_segment`) | 1 |
| `STARTUP_PRELOAD_WORKERS` | 8 | `app.py` eager timestamp preload | 1 |
| `AUDIO_DL_WORKER_COUNT` | 8 | `routes/audio_proxy.py` by_surah cache warmup | 1 |
| `DEFAULT_PORT` | 5000 | `app.py` argparse default | 1 |
| `LOW_CONFIDENCE_RED` | 0.60 *(existing)* | `services/segments_query.py` — 2 sites (issue filter + `below_60` aggregate) | 2 |

Deferred:
- `\u0294` (glottal stop) + qalqala `"Q"` marker in
  `services/phoneme_matching.py` — these are domain constants that belong
  in `constants.py`, not `config.py`. Not touched; flagged for a later cleanup.
- Vendored `validators/validate_segments.py` `0.60` literal — out of
  scope (not inspector code).
- Frontend `0.60` literals in
  `frontend/src/segments/rendering.ts:26` +
  `frontend/src/segments/validation/index.ts:187` — Wave 2b is
  backend-only per operating constraints.

---

## 2. Scope deferred

No Wave 2 items deferred in the sense of "punted forward". All five Wave-2b
items landed; all seven Wave-2a items landed. A handful of micro-deferrals
listed per item above (glottal-stop constant relocation, two frontend
`0.60` literals).

`validate_reciter_segments` and `apply_reverse_op` god-functions remain
intact per S2-D08.

---

## 3. Deviations from plan

### Wave 2a mid-wave: Docker file relocation

Commit `e98fb20` (between Wave-2a exit and Wave-2b start) moved
`Dockerfile`, `docker-compose.yml`, `.dockerignore` from the repo root to
`inspector/`. Orchestrator/user reconsideration of self-containment —
the repo has multiple components (thesis pipeline, extract-time
validators, alignment scripts, inspector). Docker is an
inspector-specific concern. Distribution doc + Docker smoke gate build
context updated in the same commit. Behavior-preserving beyond the
one-extra-`cd` required to run `docker compose up` (documented in
`docs/inspector-docker-distribution.md`).

### Wave 2a — AUDIO_PATH

Distribution-doc draft called for `AUDIO_PATH = DATA_DIR / "recitation_segments"`.
Reading `app.py`'s `/audio/<reciter>/<file>` route showed audio files
live directly under `DATA_DIR/<reciter>/<file>`, so
`AUDIO_PATH == DATA_DIR`. Followed the code; doc was wrong on that
point. Not a plan deviation — plan said "verify current layout".

### Wave 2a — `npm install` vs `npm ci` in Dockerfile

No `package-lock.json` is committed (CLAUDE.md run instructions already
use `npm install`), so the Dockerfile uses `npm install`. Commented in
Dockerfile to note the swap once a lockfile lands.

### Wave 2a — Docker smoke sleep bump

3s → 5s in the pre-flight Docker smoke probe. Phonemizer init +
timestamp preload adds a couple seconds in a cold container.
Non-functional.

### Wave 2b — none

No deviations from plan §4 Wave 2b scope.

---

## 4. Verification results

### Gate-by-gate (final, at exit `0cd5830`)

| Gate | Status | Notes |
|------|--------|-------|
| 1/7 typecheck | PASS | `tsc --noEmit` clean |
| 2/7 lint | PASS | 23 warnings (all pre-existing cycles; ceiling intact) |
| 3/7 build | PASS | Vite 4.61s; bundle sizes unchanged across all Wave-2 commits |
| 4/7 global-leak | PASS | `services/cache.py` remains sole owner of `global` keyword |
| 5/7 orphan caches | PASS | `_URL_AUDIO_META` / `_phonemizer` only in `cache.py` |
| 6/7 cycle NOTEs | PASS | Zero `// NOTE: circular dependency` |
| 7/7 cycle ceiling | PASS | 23 ≤ 23 |
| wave-2+ Docker smoke | SKIPPED | docker not available on this WSL worktree |

### Manual-smoke reasoning

Wave 2b is backend-only; no component re-renders or CSS selector churn.
Verification flows by code-reading rather than running the server.

- **`save_seg_data`** — diff-inspected: the orchestrator calls
  `_build_seg_lookups` → inlines `meta` + `val_before` → branches to
  `_apply_full_replace` or `_apply_patch` (matching the old `if / else`)
  → tail-calls `_persist_and_record`. Operation order identical:
  backup files (detailed then segments), atomic write detailed, file
  hash, rebuild segments.json, val_after, append edit_history
  (backup-then-write), invalidate cache. All dict keys in the returned
  batch record unchanged. Error-tuple shapes for the 3 by_ayah input
  validation branches preserved verbatim.
- **`undo`** flows — untouched by Wave 2. `services/undo.py` unchanged.
- **Thin-route extractions** — 3 of 3 commits verified that each route
  handler now parses the request and calls the extracted service with
  no other logic; the service is a cut-and-paste of the prior inline
  body. Dict key enumeration matches `types/api.ts`'s corresponding
  `*Response` interface for each route.
- **`app.py` logging** — `python3 -c "from app import app"` imports
  clean. `print(` count in `inspector/app.py` = 0. JSONFormatter check
  passed via `python3` inline smoke.
- **Error envelope** — central handler returns `{"error": e.description}, e.code`.
  Existing `jsonify({"error": ...}), <code>` returns in routes continue
  to match the central handler's shape; no route-level rewrite needed.

---

## 5. Bug-log delta

No rows added. No new bugs surfaced during Wave 2 implementation or
code review. Stage-1 carry-overs remain in the same state they were at
entry (B01 Wave 5 target, B04 Wave 6, B05 Wave 9; B02 closed in Wave 1).
S2-B06 (pre-existing segments-tab cycles, ceiling=23) unchanged.

---

## 6. Review findings + disposition

[TBD: orchestrator dispatches Sonnet + Opus + Haiku reviewers after this
wave per plan §6.2 — Sonnet pattern-level, Opus for `save_seg_data` diff
specifically, Haiku for file-exists / Dockerfile syntax. Reviewer rows
and dispositions appended here when complete.]

---

## 7. Surprises / lessons

- **Advisor's `_load_and_validate` pushback was well-placed.** The naive
  5-helper decomposition from the plan (`_load_and_validate`,
  `_build_seg_lookups`, `_apply_full_replace`, `_apply_patch`,
  `_persist_and_record`) would have required the first helper to return
  a sum type (success tuple *or* error envelope + status). Keeping the
  6 lines of load+validate guards inline in `save_seg_data` preserves
  behavior-by-construction and doesn't sacrifice readability — the
  function body is now 20 LOC and reads top-to-bottom as "load → build
  lookups → snapshot before → branch → persist". Worth recording as
  a general lesson: extract-method is cheap where the phases return
  the same shape; premature helper-ification fights the sum-type
  guard-returns that Python often uses.
- **Sibling-module imports after extraction**: when the extracted
  service needed `LOW_CONFIDENCE_RED` (an already-existing constant,
  swapped in during Item 5, not Item 3), the cleanest path was to
  defer the swap to the magic-number-sweep commit rather than fold it
  into the thin-route commit. This kept each commit purely mechanical
  and easy to review. Recommended for future similar splits.
- **Unused-imports-as-you-go is risky.** `format_ms` in
  `routes/timestamps.py` was already unused before Wave 2b; resisted
  the urge to clean it up to keep the route-extraction commit purely
  about the ts_data body.

---

## 8. Handoff to Wave 3 (Svelte foundations)

### 8.1 Entry state for Wave 3

- HEAD: `0cd5830`.
- All 7 pre-flight gates green. Docker smoke still skipped (no docker
  in this WSL worktree — run `bash .refactor/stage2-checks.sh` on a
  docker-equipped machine before any release tag).
- No unstaged modifications attributable to Wave 2. The
  `inspector/frontend/src/styles/validation.css` + `inspector/README.md`
  working-tree modifications carried over from pre-Wave-2a are still
  unstaged — unrelated to Wave 2 scope, Wave 3 can fold or ignore.

### 8.2 Wave-2 artifacts touching Wave 3 prep

- **`inspector/CLAUDE.md` is now slightly out of date** in two places
  — Wave 3 or Wave 11 should sync these (Wave 11 is the planned
  CLAUDE.md sync point; adding as Wave 3 scope is also fine):
  1. `services/` section should mention
     `segments_query.py`, `ts_query.py`, `history_query.py` as
     new query-only modules. Consider grouping them under
     "*_query.py" to make the pattern visible.
  2. `services/save.py` now has 4 phase helpers + an orchestrator;
     the bullet describing save.py can stay since it's a one-liner,
     but if Wave 3 touches CLAUDE.md the internal note "decomposed
     during Wave 2b into phase helpers per S2-D08" is worth recording.
- **Three new Python modules in `services/`** (plus the decomposed
  `save.py` internals). None touch frontend imports. All are pure
  functions — safe to ignore for the Svelte conversion scope.
- **`config.py` has 7 new constants.** Frontend does not read config.py
  directly (it reads `/api/ts/config` and `/api/seg/config`); those
  endpoints' response shapes are unchanged, so the Svelte stores don't
  need new fields.
- **app.py's `FLASK_ENV=development` branch**: if Wave 3 runs
  `python3 inspector/app.py` for smoke-testing mounted Svelte dist,
  set `FLASK_ENV=development` to keep auto-reload on. Default is now
  off.
- **Logging is JSON now.** Dev-time readability trade-off: Wave 3
  agents viewing the Flask server terminal will see JSON lines, not
  plain text. Can pipe through `jq` or leave as-is.

### 8.3 Pre-Wave-3 artifacts the plan calls for

Per plan §6.2 Wave 3:

- `.refactor/stage2-css-migration-map.md` — enumerate the 9 CSS files'
  load-bearing global selectors (`body.seg-edit-active`,
  `#animation-display.anim-window`, `:root` vars set by JS) and
  assign each to the wave that rewrites its trigger. Not yet written.
- `.refactor/stage2-store-bindings.md` — pre-Wave-5 artifact (plan
  §6.2 Wave 5). Orchestrator may want it earlier, but not blocking
  Wave 3 foundations.

Wave 3 agent should produce the CSS migration map as their first
artifact (before any Svelte install).

### 8.4 Must-not-break invariants surfaced during Wave 2

- **Error envelope `{error: str}` is now centrally enforced** via
  `@app.errorhandler(HTTPException)`. Wave 3 and beyond must continue
  to raise `HTTPException`-compatible errors OR return explicit
  `jsonify({"error": ...}), <code>` pairs. Don't accidentally
  return bare strings from new routes.
- **Save-flow `dict | tuple` return contract** preserved. Any future
  refactor of `save_seg_data`'s helpers (e.g. adding a new validation
  phase) must continue to return either `dict` on success or
  `(error_dict, status_int)` tuple on failure.
- **`config.py` constants are used by both Python and — indirectly —
  the frontend** via `/api/ts/config` + `/api/seg/config`. A Wave-2b
  magic-number rename (e.g. `LOW_CONFIDENCE_RED → LOW_CONF_RED`)
  would NOT affect the frontend (the API field is spelled
  `low_confidence_red` or `below_60` in the payload, not the Python
  identifier), but is still a pattern to check at each rename.

### 8.5 Prerequisites for Wave 3

1. `git log --oneline 7961bae..HEAD` shows 14 commits — the 8 Wave-2a
   + 6 Wave-2b commits (plus the `6d32308` pre-Wave WIP, which predates
   Wave 2 proper).
2. `bash .refactor/stage2-checks.sh` — 7/7 green.
3. Read plan §4 Wave 3 — unchanged by Wave 2.
4. Read `.refactor/stage2-decisions.md` S2-D03, S2-D04, S2-D08, S2-D10
   through S2-D13 for frontend-relevant context.
5. **Audio-tab warm-up remains deferred to Wave 11** per S2-D06.
   Wave 3 foundations should provision shared components
   (`Button`, `SearchableSelect`, `AccordionPanel`, `SpeedControl`,
   `ValidationBadge`, `WaveformCanvas`) without converting tabs.

---

## 9. Suggested pre-flight additions

None new from Wave 2. The cycle-count ceiling gate added during Wave 1
post-review (S2-D26) is working as intended — caught zero regressions
during all 6 Wave-2b commits.

A future candidate (not for this wave): a gate that asserts every route
handler is ≤ N LOC as a structural check on the "thin routes" principle.
Cheap to add, but the `seg_reciters` and `seg_save_chart` routes in
`segments_data.py` + `segments_validation.py` respectively are already
medium-complex (25-30 LOC) and would need exemption. Leaving as
"maybe-Wave-11" polish.

---

## 10. Commits (exit-point detail)

**Wave 2a (HEAD range `7961bae..5addf33` → mid-wave `e98fb20`):**

```
e98fb20 refactor(inspector): relocate Dockerfile/compose/dockerignore under inspector/
8d6e448 docs(inspector): wave 2a handoff (config + docker + vendor)
5addf33 chore(inspector): stage2-checks.sh — enable Docker smoke gate for Wave 2+
55e175a chore(inspector): add requirements-dev.txt placeholder
7b72085 feat(inspector): Docker distribution — Dockerfile, docker-compose.yml, .dockerignore
5be027a refactor(inspector): vendor validators/ into inspector/validators/, delete sys.path hack
c1e4ca5 refactor(inspector): config — INSPECTOR_DATA_DIR env override, all data paths derive from it
```

**Wave 2b (range `e98fb20..0cd5830`):**

```
0cd5830 refactor(inspector): config — magic-number sweep (peaks flags, worker counts, port default)
ddb743a refactor(inspector): save_seg_data — extract 4 phase helpers (behavior-preserving)
e7bb136 refactor(inspector): routes — extract seg_edit_history body into services
3269d77 refactor(inspector): routes — extract ts_data body into services
d3137e7 refactor(inspector): routes — extract seg_data body into services
e805f4e refactor(inspector): app — structured logging, central error handler, prod-default debug flag
```

Plus this handoff commit + orchestration-log row append (bundled as one
`docs:` commit): **14 Wave-2 commits total** across sub-waves 2a and 2b.

---

## 11. Time / token budget consumed (Wave 2b self-reported)

- Tool calls: ~40 (read/edit/write/bash/advisor)
- Edits: ~25
- Writes: 4 new files (segments_query.py, ts_query.py, history_query.py, this handoff)
- Bash invocations: ~12 (mostly verify-imports + pre-flight + commits)
- Wall-clock: single session, ~15–20 min (not instrumented precisely)
- Advisor calls: 1 (pre-implementation orientation)

Orchestrator fills exact input/output token totals from tool result
envelopes post-wave. Wave 2a numbers are in
`.refactor/stage2-wave-2a-handoff.md` §1 and `.refactor/stage2-orchestration-log.md`.

---

**END WAVE 2 HANDOFF.**
