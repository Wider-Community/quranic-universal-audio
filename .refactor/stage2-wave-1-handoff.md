# Stage 2 — Wave 1 Handoff

**Status**: COMPLETE
**Branch**: `worktree-refactor+inspector-modularize`
**Known-good entry commit**: `f7bdc46` (pre-Wave-1; last Stage-1 commit)
**Known-good exit commit**: `94e1290` (the pre-flight script commit; all 6 gates green)
**Agent**: Opus 4.6 (1M), role: implementation-Wave-1, 2026-04-13.

---

## 1. Scope delivered

| Item | Description | Commits |
|------|-------------|---------|
| 0 | Commit Stage-2 planning artifacts (plan v3, bugs, decisions, Wave 0.5 handoff, orchestration log) | `bdf4ad9` |
| 1 | B02 fix — unify `segData`/`segAllData` chapter-index handling on delete | `2d06251`, `d58dfca` (bug-log) |
| 2 | Timestamps registry pattern — 6 NOTEs dissolved, 1 new module (`timestamps/registry.ts`) | `ce8426a` |
| 3 | ESLint `import/no-cycle` end-to-end wiring (TS resolver + `import/parsers`), rule downgrade to `warn`, `getActiveTab` extraction | `27c41f4` |
| 4 | `services/cache.py` absorbs `_URL_AUDIO_META` and `_phonemizer` | `2896ee3` |
| 5 | Pre-flight checks script (`stage2-checks.sh`) | `94e1290` |
| 6 | This handoff doc | (this commit) |
| 7 | Orchestration-log row update | (bundled with this commit) |

### Item 1 — B02 (delete chapter-index desync)

File: `inspector/frontend/src/segments/edit/delete.ts`. The two branches (current-chapter display-cache vs. all-data) now splice+reindex against `segAllData.segments` only. `segData.segments` is refreshed from the re-indexed source via `getChapterSegments(chapter)` when the delete was in the currently-displayed chapter. `syncChapterSegsToAll()` no longer called from here; unused import removed.

Logical smoke: after delete+save+reload, chapter indices on the reloaded segments match the saved file.

### Item 2 — Timestamps registry

New file: `inspector/frontend/src/timestamps/registry.ts`. Shapes:
- `TsIndexRegistry` (5 fns owned by `index.ts`): `getSegRelTime`, `getSegDuration`, `jumpToTsVerse`, `loadRandomTimestamp`, `onTsVerseChange`.
- `TsPlaybackRegistry` (2 fns owned by `playback.ts`): `updateDisplay`, `navigateVerse`.

Two setters `registerTsIndexFns`, `registerTsPlaybackFns`. Seven dispatch wrappers (one per fn) that throw if called before registration — stricter than the prior "runtime-only" NOTE comments.

Siblings routed to `./registry` instead of `./index` / `./playback`: `animation.ts`, `waveform.ts`, `validation.ts`, `keyboard.ts`, `unified-display.ts`, plus `playback.ts` for the 6th NOTE (not in the original task list but caught by the same invariant — see Deviations §3).

`index.ts` calls both setters at module-top; function-declaration hoisting means forward references resolve even though `jumpToTsVerse` / `loadRandomTimestamp` appear textually below.

All 6 `// NOTE: circular dependency` comments removed. Grep-clean.

### Item 3 — ESLint cycle detection (wholesale rework)

**Critical discovery**: `import/no-cycle: 'error'` was silently no-op on the inherited config. `eslint-plugin-import` needs *both* a TS resolver (to follow `./foo` → `./foo.ts`) AND an `import/parsers` setting pointing `.ts` to `@typescript-eslint/parser`. The inherited `eslint.config.js` had neither, so the cycle-detection rule walked an empty graph and reported zero findings. See **Surprises** §7 below.

Fixes applied:
1. `npm install --save-dev eslint-import-resolver-typescript` (+ 2 new dev deps via lockfile).
2. `settings.import/resolver`: `{ typescript: { project: './tsconfig.json' }, node: true }`.
3. `settings.import/parsers`: `{ '@typescript-eslint/parser': ['.ts', '.tsx'] }`.
4. Rule severity: `'error'` → `'warn'`.
5. `getActiveTab` / `setActiveTab` extracted from `main.ts` to new `src/shared/active-tab.ts`. Both tabs' `keyboard.ts` files re-import from the shared module. This dissolves the `main.ts → {timestamps,segments}/index.ts → {timestamps,segments}/keyboard.ts → main.ts` cycle.

Result: 22 pre-existing cycles surface as warnings, all in the segments tab, all runtime-safe, all scheduled to dissolve during Waves 5-10. See S2-B06 in `stage2-bugs.md`.

### Item 4 — `services/cache.py`

Two new cache surfaces with getter/setter pairs:
- `get_url_audio_meta(url)` / `set_url_audio_meta(url, meta)` — replaces `_URL_AUDIO_META` dict that lived at module level in `services/peaks.py`.
- `get_phonemizer_singleton()` / `set_phonemizer_singleton(pm)` — replaces `_phonemizer` + `global _phonemizer` in `services/phonemizer_service.py`.

Phonemizer getter/setter typed `Any` to avoid hard-importing `quranic_phonemizer` in `cache.py` (keeps graceful-degradation behavior intact).

Post-condition (verified by `stage2-checks.sh` gates 4 + 5): `global` keyword appears only inside `services/cache.py`; `_URL_AUDIO_META` and `_phonemizer` identifiers exist nowhere else in `services/`.

### Item 5 — `.refactor/stage2-checks.sh`

Executable (`chmod +x` committed). 6 gates (typecheck, lint, build, global-leak, orphan-cache, cycle-NOTE). Docker smoke block present but commented out pending Wave 2. Location-independent (resolves repo root from `$BASH_SOURCE`).

---

## 2. Scope deferred

Nothing from the Wave 1 plan was deferred.

Out of scope but surfaced during the wave:

- **22 pre-existing segments import cycles** — all tracked as S2-B06; dissolve during Waves 5-10. Not fixable in Wave 1 budget without massive scope creep.
- **Docker smoke** in the checks script — commented out; Wave 2 enables.

---

## 3. Deviations from plan

| Plan said | Actual | Reason |
|-----------|--------|--------|
| "5 NOTE comments in siblings (animation, waveform, validation, keyboard, unified-display)" | 6 NOTEs — playback.ts held a 6th on its bidirectional edge to index.ts | The verification gate in the task is "zero NOTE comments", not "5 comments gone". Routing `playback.ts` through the registry adds one extra function (`onTsVerseChange`) but keeps the invariant whole. |
| "Create ts/registry.ts, 3 setters (setTsTimingFns / setTsViewFns / setTsDataFns)" | 2 setters (`registerTsIndexFns`, `registerTsPlaybackFns`), grouped by producer module | Advisor recommended keeping it simple; grouping by source module (2 sources → 2 setters) keeps index.ts wiring to 2 lines. |
| "ESLint import/no-cycle is already at 'error'; Wave 1 confirms it catches nothing" | Rule was silently no-op (empty graph); once fixed, it catches 22 pre-existing cycles. Rule downgraded to `warn` with plan-deferred fix in Waves 5-10 | Discovered during end-to-end verification. Detailed in Surprises §7 and S2-B06. |
| "Fix cycles if < 1 hour; escalate otherwise" | Escalated the 22 via the bug log (S2-B06) + decisions log (S2-D24) rather than fixing | Those cycles are exactly what the `register*` pattern was built to handle; they dissolve naturally during Svelte migration. Fixing them mechanically now would mean rewiring 13 files on the eve of the Svelte migration that will rewrite them anyway. |

---

## 4. Verification results

### Build gates at end of Wave 1

- `npm run typecheck` — **PASS** (0 errors)
- `npm run lint` — **PASS** (0 errors; 22 warnings, all pre-existing segments cycles per S2-B06)
- `npm run build` — **PASS** (70 modules transformed; 435.91 kB / 134.56 kB gz; similar to pre-Wave-1 baseline of 434 kB)

### Pre-flight script (`.refactor/stage2-checks.sh`)

Runs 6/6 gates green. Docker smoke block present but commented out.

### Grep invariants

| Check | Result |
|-------|--------|
| `// NOTE: circular dependency` in `frontend/src/` | 0 matches |
| `^\s*global\s` in `inspector/services/` outside `cache.py` | 0 matches |
| `_URL_AUDIO_META` or `^\s*_phonemizer\s*=` in `services/` outside `cache.py` | 0 matches (Python sources) |
| `from '\./(index\|playback)'` in `frontend/src/timestamps/` (excluding `index.ts`'s import of `playback.ts`) | 1 match — `index.ts → playback.ts` only. No reverse edge. |

### Logical smoke (B02)

Walk-through: delete a segment, call save flow, reload. Both caches go through the same splice+reindex on `segAllData`; `segData` refreshes from there for the displayed chapter. Chapter indices in the saved JSON are contiguous 0..N regardless of branch. Verified by reading the unified code path; not executed against a running server (per task spec — logical reasoning only).

### Python import smoke

`python3 -c "from app import app"` — clean (no ImportError, no side effects beyond cache-module init).

---

## 5. Bug-log delta

### Closed this wave
- **S2-B02**: chapter-index desync on delete. Fix-SHA `2d06251`. Moved to Section 5. Status in Section 1 updated to `CLOSED`.

### Added this wave (Section 2 — Lint/build-caught)
- **S2-B06**: 22 pre-existing segments-tab import cycles surfaced when TS resolver was enabled. Status: DEFERRED. Wave-target: Waves 5-10 (Svelte migration dissolves them by construction).

### Added to decisions log
- **S2-D24**: `import/no-cycle` downgraded to `warn` + TS resolver config. Active.
- **S2-D25**: `getActiveTab` extracted to `shared/active-tab.ts`. Active.

Still OPEN from Stage 1: B01 (Wave 5), B04 (Wave 6), B05 (Wave 9).

---

## 6. Review findings + disposition

[TBD: orchestrator dispatches Sonnet + Opus reviewers after this wave]

Agent-side self-review checkpoints:
- Advisor consulted once at scope-surfacing (before Item 3 cycle work) and once mid-Item-3 when the unexpected cycle count surfaced. Both pieces of advice applied: (a) downgrade rule, (b) extract `getActiveTab`, (c) scope segments cycles to Waves 5-10.

Reviewer focus areas (suggested):
- **Sonnet** — verify the B02 fix preserves the prior call to `markDirty` + `_fixupValIndicesForDelete` + `computeSilenceAfter` + `applyVerseFilterAndRender` + `refreshOpenAccordionCards` ordering (I preserved it; Sonnet should spot-check).
- **Sonnet** — verify the timestamps registry hoisting assumption: `registerTsIndexFns` at module-top calls `jumpToTsVerse`/`loadRandomTimestamp` which appear textually below. `function` declarations hoist; `async function` declarations also hoist in ES modules — but worth a second pair of eyes.
- **Opus** — audit whether the `_requireIndex()` / `_requirePlayback()` throw-on-unregistered pattern could regress if any module-top code (outside DOMContentLoaded) calls a dispatch wrapper before `index.ts`'s registration runs. Current call sites are all event-driven; no eager paths should exist.

---

## 7. Surprises / lessons

### (a) ESLint `import/no-cycle` was silently broken for all of Stage 1

The rule was set to `'error'` in post-Stage-1 cleanup, the config was committed, and `npm run lint` returned exit 0. But the rule was walking an empty import graph because `eslint-plugin-import` can't resolve TS paths without two extra pieces:
- `eslint-import-resolver-typescript` (+ `import/resolver` setting).
- `import/parsers: { '@typescript-eslint/parser': ['.ts', '.tsx'] }` — the plugin needs to be told which parser to use *for its own AST-traversal*, separate from ESLint's top-level parser.

Verified by creating a trivial 2-file `./cycle-a.ts ⇌ ./cycle-b.ts` and watching the rule fire only after both resolver + parsers settings land.

Lesson for future waves: lint rules that appear "green" should be periodically sanity-checked with a known-bad input. Cheap insurance.

### (b) 6 NOTE comments, not 5

The task spec listed 5 sibling NOTEs; playback.ts held a 6th on its bidirectional edge to index.ts. The registry work trivially extends to a 7th function (`onTsVerseChange`) so I fixed playback.ts alongside. Zero runtime diff.

### (c) Function-declaration hoisting in ES modules

The registry setters are called at module-top in `index.ts` using function references that are declared further down (e.g. `jumpToTsVerse`, `loadRandomTimestamp`). This works because `function` declarations (including `async function`) are hoisted to the top of their enclosing scope — even inside ES modules. Arrow functions would not hoist; if a future refactor converts these to `const fn = async () => {}` the module-top setter calls would need to move.

### (d) Pre-existing dirty files in the working tree

14 modified files were present at the start of Wave 1 (unrelated work-in-progress by another author: `services/validation.py`, `segments/state.ts`, `types/domain.ts`, etc.). All edits during Wave 1 used explicit `git add <path>` — no `git add -A` or `git add .` — so this WIP stays out of every Wave 1 commit. Next wave should confirm those files are still dirty before starting and treat them the same way.

### (e) Validator for the `register*` pattern

The segments tab has 5+ such register-slot patterns, and the timestamps tab now has 1. During Svelte migration these dissolve. Pattern lesson: when two modules need each other at runtime but not at import time, the "registry + throw-on-missing" pattern is a clean type-safe bridge — but it's a design-smell for cycle avoidance that a framework like Svelte (with stores) makes unnecessary.

---

## 8. Handoff to Wave 2 (backend + Docker)

### Prerequisites Wave 2 must not break

- `services/cache.py` is the single source of truth for all mutable module-level caches. Do not re-introduce `global` outside it. Do not re-introduce `_URL_AUDIO_META` or `_phonemizer` module-level state outside `cache.py`. Pre-flight gates 4 + 5 enforce this.
- The segments `register*` pattern + the new `timestamps/registry.ts` pattern stay in place until Svelte migration (Waves 5-10) dissolves them. Do not dissolve them now — the pre-Svelte import graph still depends on them.
- `npm run lint`'s warning count should not exceed 22. If a new cycle warning appears, it's almost certainly a regression — investigate before committing.
- `shared/active-tab.ts` is the only place mutating the active-tab string; do not re-add `let activeTab` to `main.ts`.

### Wave 2 tasks per plan §4 (sub-waves 2a + 2b)

Wave 2a:
- `config.py`: `INSPECTOR_DATA_DIR` env override + 5 data paths derived; `CACHE_DIR` under `DATA_DIR`.
- Vendor `validators/` into `inspector/validators/`; delete `sys.path` hack.
- `Dockerfile` + `docker-compose.yml` + `.dockerignore`.
- `requirements-dev.txt` (empty placeholder).

Wave 2b:
- `app.py`: structured logging, `@app.errorhandler(HTTPException)`, `debug=False` default.
- Thin-route extraction for `seg_data`, `ts_data`, `seg_edit_history`.
- `save_seg_data` extract-method (4 sequential helpers).
- `config.py` magic-number sweep.

### Open questions for the orchestrator

- **Re-promote `import/no-cycle` to `error` when?** Plan says Wave 11. S2-D24 confirms. No change needed.
- **Should the 22 segments cycles be explicitly documented in each wave's CSS-migration-map equivalent?** Suggest yes — when Waves 5-10 land, verify the warning count drops monotonically and each wave's handoff notes which cycle it dissolved.
- **The pre-existing 14 dirty files in the working tree** — these are WIP by another author. Should the orchestrator move them to a stash before Wave 2 kicks off, or let them continue to ride along in subsequent waves? If they're related to multi-reciter data imports (per plan §0a), they likely need to be committed or stashed by the user before Wave 2 starts touching `config.py`.

### Suggested pre-flight additions for future waves

- **Gate 7 (Wave 2+)**: `docker build .` succeeds and the resulting image can serve `/api/seg/config`. Already templated in the script — uncomment after Wave 2a.
- **Gate 8 (Wave 3+)**: Svelte build gate — `npm run build` output contains at least one `.svelte` file (sanity-check the Svelte plugin is wired).
- **Gate 9 (Wave 5+)**: cycle count monotonically decreasing — `npm run lint | grep 'no-cycle' | wc -l ≤ <previous wave>`.

---

## 9. Time + token budget consumed

Subjective (agent-side):
- Wall-clock: ~45 minutes of active work (single run).
- Tool calls: approximately 60 (reads + edits + bashes + advisor + writes).
- Advisor consultations: 2 (scope-surfacing before Item 3 + mid-Item-3 when cycles surfaced).
- Surprising-scope items: 1 (ESLint resolver was silently broken) — added ~15 minutes of work relative to the naive "verify it passes" task item.

Orchestrator will record exact input/output tokens + duration when logging to `stage2-orchestration-log.md`.
