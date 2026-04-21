# Phase 2 — `.js`→`.ts` rename, sub-folder segments, Chart.js npm migration

**Status:** COMPLETE
**Commit:** pending (this phase)
**Branch:** `worktree-refactor+inspector-modularize`

## Scope delivered

### 1. Rename every JS → TS

All 44 JS files under `inspector/frontend/src/` renamed to `.ts` via `git mv`. Zero `.js` files remain:

```
$ find inspector/frontend/src -name "*.js" | wc -l
0
```

### 2. Sub-folder 18 segments modules

| Old path | New path |
|---|---|
| `segments/edit-common.js` | `segments/edit/common.ts` |
| `segments/edit-trim.js` | `segments/edit/trim.ts` |
| `segments/edit-split.js` | `segments/edit/split.ts` |
| `segments/edit-merge.js` | `segments/edit/merge.ts` |
| `segments/edit-delete.js` | `segments/edit/delete.ts` |
| `segments/edit-reference.js` | `segments/edit/reference.ts` |
| `segments/history.js` | `segments/history/index.ts` |
| `segments/history-rendering.js` | `segments/history/rendering.ts` |
| `segments/history-filters.js` | `segments/history/filters.ts` |
| `segments/undo.js` | `segments/history/undo.ts` |
| `segments/validation.js` | `segments/validation/index.ts` |
| `segments/categories.js` | `segments/validation/categories.ts` |
| `segments/error-cards.js` | `segments/validation/error-cards.ts` |
| `segments/error-card-audio.js` | `segments/validation/error-card-audio.ts` |
| `segments/waveform.js` | `segments/waveform/index.ts` |
| `segments/waveform-draw.js` | `segments/waveform/draw.ts` |
| `segments/playback.js` | `segments/playback/index.ts` |
| `segments/audio-cache.js` | `segments/playback/audio-cache.ts` |

`segments/` root now contains 11 singleton modules per plan: `index.ts`, `state.ts`, `data.ts`, `filters.ts`, `navigation.ts`, `references.ts`, `save.ts`, `stats.ts`, `rendering.ts`, `keyboard.ts`, `event-delegation.ts`.

### 3. Rewrite every relative import

Automated via `/tmp/rewrite_imports.py` — parses every `.ts` file, finds `["'](\.{1,2}/[^"']+?)\.js["']`, strips `.js`, and rewrites the relative path if the target was sub-foldered. Rewrote 37 files (each gets at least its `.js` extensions stripped; the 18 moved files plus their ~15 direct importers also get path updates).

Verification:
- `grep -rE "from ['\"].*\.js['\"]" inspector/frontend/src/` → 0 matches.
- Spot-check: `segments/edit/split.ts` has `../state`, `../rendering`, `../data`, `../waveform/draw`, `./common`, `./reference`, etc. — all resolve.

### 4. Chart.js CDN → npm migration

- Created `inspector/frontend/src/shared/chart.ts` that imports `Chart + registerables` from `chart.js` and `annotationPlugin` from `chartjs-plugin-annotation`, calls `Chart.register(...)`, and re-exports `Chart`.
- `inspector/frontend/src/segments/stats.ts` now does `import { Chart } from '../shared/chart'` instead of relying on the global.
- Removed both `<script src="https://cdn.jsdelivr.net/...">` tags from `inspector/frontend/index.html`.
- `grep window.Chart inspector/frontend/src/` → 0. No legacy global references.

### 5. `@ts-nocheck` migration bridge

Prepended `// @ts-nocheck — removed per-file as each module is typed in Phases 4+` to every renamed `.ts` file.

**Rationale**: `.ts` files are checked more strictly than `.js` under `allowJs:true/checkJs:false`. Specifically, TypeScript infers class fields from constructor `this.X = value` only for `.js` files (with `checkJs:true`); in `.ts`, fields must be explicitly declared. Since Phase 2 is mechanical rename with no typing work (per plan anti-goals), `@ts-nocheck` preserves the "compiles without adding types" invariant. Phases 4+ remove `@ts-nocheck` per-file as each module is properly typed.

Verification:
- `find src -name "*.ts" -exec head -1 {} \; | sort -u` → single variant of the `@ts-nocheck` comment.
- Build + typecheck both clean.

### 6. `index.html` entry path update

`<script type="module" src="/src/main.js">` → `<script type="module" src="/src/main.ts">`.

## Scope deferred

- All actual TypeScript typing work — deferred to Phases 3 onward.
- `inspector/CLAUDE.md` frontend section still describes the old layout — updated in a later phase once more of the target state is real (Phase 6/7).
- Types for the registration patterns (`registerHandler`, `registerEditModes`, `setClassifyFn`, etc.) — Phase 4 when `state.ts` gets typed.

## Deviations from plan

| Plan said | Actual | Reason |
|-----------|--------|--------|
| "No type annotations yet beyond what TS infers" | Added `// @ts-nocheck` to every file | TS inference on `.ts` is stricter than on `.js` (class fields, callback params, DOM coercions). `@ts-nocheck` is the standard migration bridge to preserve the "mechanical only" intent. |
| `registerHandler`/`registerKeyboardHandler` at module top | Stayed inside DOMContentLoaded | These were already inside DOMContentLoaded pre-Phase-2 — they populate a handler map consulted at event time, so DOM-ready timing is fine. `setClassifyFn`/`registerEditModes`/`registerEditDrawFns`/`registerWaveformHandlers` ARE at module top (they break circular import-time deps). Only those four need to run before DOMContentLoaded. |

## Verification results

### Build gates (after all Phase 2 work)
- `npm run typecheck` — **PASS** (0 errors, `@ts-nocheck` on all files)
- `npm run build` — **PASS** (62 modules transformed in 4.07s). Output:
  - `dist/index.html` — 16.67 kB (CDN script tags removed vs Phase 1's 16.88 kB)
  - `dist/assets/index-<hash>.css` — 28.43 kB (unchanged)
  - `dist/assets/index-<hash>.js` — **434.21 kB** (vs Phase 1's 189.36 kB — delta is Chart.js + annotation plugin, previously external CDN; now inline)
  - Gzipped JS: 133.10 kB (vs 50.13 kB). Net initial-page-load effectively equivalent to Phase 1 once CDN fetches are accounted for; fewer network requests, no cross-origin DNS.
  - `dist/fonts/DigitalKhattV2.otf` — 521 kB (unchanged)
- `grep -c cdn.jsdelivr.net dist/index.html` → 0
- `grep /static/ dist/assets/*.js` → 0 matches
- `grep window.Chart dist/assets/*.js` → 0 matches
- Bundle confirmed to include Chart.js code (BarController, LineController, annotation plugin banner, etc.)

### Flask prod serving (port 5055)
| Endpoint | Status | Size |
|----------|-------:|-----:|
| `/` | 200 | 16,670 B |
| `/assets/<hash>.css` | 200 | 28,432 B |
| `/assets/<hash>.js` | 200 | 434,336 B |
| `/fonts/DigitalKhattV2.otf` | 200 | 521,832 B |
| `/api/surah-info` | 200 | 20,867 B |
| `/api/ts/reciters` | 200 | 178 B |
| `/api/seg/reciters` | 200 | 138 B |
| `/api/audio/sources` | 200 | 34,980 B |
| `/static/js/main.js` | 404 | — (legacy path intentionally removed) |

### Vite dev server (port 5173)
- `GET /` → 200, serves `<!DOCTYPE html>` with `/@vite/client` + `/src/main.ts` injected
- Vite ready in 525 ms
- No errors/404s in startup log

### Import-graph spot check (by verification agent)
- `segments/edit/split.ts` — all 11 relative imports resolve to existing `.ts` files
- `segments/validation/error-cards.ts` — all 7 relative imports resolve

### Smoke checklist
Full S1–S14 browser-based smoke requires user verification. Build + server + asset delivery all green; Chart.js migration verified by bundle inspection (no stale CDN refs, no `window.Chart` references, bundle includes Chart code).

## Bug-log delta

- **Rows added:** none. No new bugs surfaced during the rename — the Sonnet review flagged one concern about `registerHandler` placement that turned out to be unchanged from pre-Phase-2 (and correctly so).
- **Rows closed:** none (B08 still open, will close in Phase 3 when `shared/api.fetchJsonl` lands).
- **Status changes:** none.

## tsconfig state at phase end

No change from Phase 0/1:
- `strict`: false
- `noImplicitAny`: false
- `strictNullChecks`: false
- `noUncheckedIndexedAccess`: false
- `allowJs`: true (no longer needed but kept — no `.js` files exist under `src/` anymore)
- `checkJs`: false

## Review findings (3-agent gate)

- **Haiku coverage**: 12/12 PASS. 0 `.js` files, 45 `.ts` files, all sub-folders populated correctly, 0 stale flat files, `@ts-nocheck` on every file, 0 `.js` in import specifiers, `shared/chart.ts` bootstraps correctly, index.html references `/src/main.ts` and has 0 CDN scripts, build artifacts all present.
- **Sonnet quality**: 1 flagged concern — `registerHandler`/`registerKeyboardHandler` inside DOMContentLoaded. Verified to be a false alarm: these were inside DOMContentLoaded pre-Phase-2 (they populate a map consulted at event time, DOM-ready timing is correct for them). The "registration at import time" invariant only applies to `setClassifyFn`/`registerEditModes`/`registerEditDrawFns`/`registerWaveformHandlers` — those four ARE at module top (confirmed via grep). Other 8 checks: all clean.
- **Opus verification**: PASS across build gates, Flask prod, Vite dev, and import-graph sanity. Bundle confirmed to embed Chart.js. Strategic note for Phase 3: the `@ts-nocheck` blanket means real typing value only materializes when individual files remove their `@ts-nocheck`; recommend enabling types on `shared/api.ts` AND its direct callers simultaneously in Phase 3.

## Surprises / lessons

- `allowJs:true` did NOT protect us from TS's stricter-on-`.ts` behavior after rename — `allowJs` is only about including `.js` files, not suppressing `.ts` checks. `@ts-nocheck` is the real bridge.
- `target:"ES2022"` enables `useDefineForClassFields:true` by default — which means class fields must be explicitly declared in `.ts`, unlike `.js` (where constructor assignment is enough). Hit this with `SearchableSelect` immediately after rename. `@ts-nocheck` sidesteps it for now.
- The Python rewrite script was fast and deterministic — running it twice is a no-op (idempotent). Good candidate to keep around for future cross-project refactors.
- Chart.js npm bundle adds ~245 kB raw / ~83 kB gzipped to the initial JS. With gzip this is comparable to the CDN hit. Fewer network round trips is a small win; losing public-CDN cross-site caching is a small loss. Net neutral for this app.
- Vite auto-discovered every route as expected — no input configuration needed beyond the already-set `index.html` entry.

## Handoff to Phase 3

- **Known-good entry commit**: (this commit's SHA)
- **Prerequisites Phase 3 must not break**:
  - The `/src/main.ts` entry reference in `index.html` must stay valid.
  - The registration-pattern order in `segments/index.ts` (module-top injections, DOMContentLoaded handlers) must stay intact.
  - `@ts-nocheck` must stay in place on files that aren't being actively typed this phase; removing from `shared/api.ts` and 1-2 callers in Phase 3 is fine.
  - Chart.js must continue to be consumed via `shared/chart.ts` (no one else may `import ... from 'chart.js'` directly).
- **Phase 3 tasks per plan**:
  - Create `shared/animation.ts` (extract rAF loop from `segments/playback/index.ts` + `timestamps/playback.ts`)
  - Create `shared/accordion.ts` (extract half-state guard from validation/history)
  - Create `shared/api.ts` with `fetchJson<T>` and `fetchJsonl<T>` (the latter fixes B08 by construction)
  - Create `types/api.ts` mirroring Python routes — read each `routes/*.py` + `services/*.py`, log every drift as an API-drift bug-log row
  - Create `types/domain.ts` (Segment, Op, Ref, ValidationError, Reciter, Peaks, TimestampVerse)
  - Replace every `fetch('/api/...')` call site with `fetchJson<T>()` generic call. Grep-gate: `grep -r "fetch(" inspector/frontend/src/` returns zero matches outside `shared/api.ts`.
  - For phase 3 files (all `shared/*` + `types/*` + fetch-site callers that get typed), remove the `@ts-nocheck` line as part of the typing work.
  - Enable `noImplicitAny: true` scoped to `shared/**` + `types/**` only (or globally if clean — decide at start of Phase 3).
- **Questions / decisions for Phase 3**:
  - Zod? No (per plan). Keep types hand-written.
  - How to scope strictness increase — per-file via `// @ts-check` flags, or global tsconfig flag? Start with global `noImplicitAny:true` when Phase 3 starts; if it cascades too far, back off to per-file.
- **Risks**: `@ts-nocheck` on every file masks real type errors. As we remove `@ts-nocheck` from `shared/api.ts` and a couple of fetch-site callers (e.g. `segments/data.ts`), the cascade may force us to type more than planned for Phase 3. Monitor and split into 3a/3b if it explodes.
