# Phase 1 — Move JS/CSS/fonts into frontend/ + wire Vite+Flask prod/dev

**Status:** COMPLETE
**Commit:** pending (this phase)
**Branch:** `worktree-refactor+inspector-modularize`

## Scope delivered

### File moves (all via `git mv` — preserves history)

| From | To | Files |
|------|-----|-------|
| `inspector/static/js/main.js` | `inspector/frontend/src/main.js` | 1 |
| `inspector/static/js/shared/` | `inspector/frontend/src/shared/` | 5 |
| `inspector/static/js/segments/` | `inspector/frontend/src/segments/` | 27 |
| `inspector/static/js/timestamps/` | `inspector/frontend/src/timestamps/` | 8 |
| `inspector/static/js/audio/` | `inspector/frontend/src/audio/` | 1 |
| `inspector/static/css/` | `inspector/frontend/src/styles/` | 9 |
| `inspector/static/fonts/DigitalKhattV2.otf` | `inspector/frontend/public/fonts/DigitalKhattV2.otf` | 1 |
| `inspector/static/index.html` | `inspector/frontend/index.html` (rewritten) | 1 |

- `inspector/static/` directory fully deleted.
- Phase 0 placeholder `inspector/frontend/src/main.ts` deleted (replaced by the moved `main.js`; Phase 2 renames to `.ts`).
- Total: 53 JS + 9 CSS + 1 font + 1 HTML = 64 files moved.

### Content changes (minimal, per Phase 1 anti-goal "pure moves")

- `inspector/frontend/src/main.js`: prepended 9 `import './styles/<file>.css'` lines in original `<link>` tag order (base → components → timestamps → segments → validation → history → stats → filters → audio-tab). No other JS content changed anywhere.
- `inspector/frontend/src/styles/base.css`: font URL `/static/fonts/DigitalKhattV2.otf` → `/fonts/DigitalKhattV2.otf`.
- `inspector/frontend/index.html` (rewritten from `static/index.html`):
  - Removed 9 `<link rel="stylesheet" href="/static/css/*.css">` (CSS now imported from `main.js`).
  - Module entry `<script type="module" src="/static/js/main.js">` → `<script type="module" src="/src/main.js">` (matches Vite convention; will become `main.ts` in Phase 2).
  - Chart.js + chartjs-plugin-annotation CDN `<script>` tags kept verbatim (migrate to npm in Phase 2).
- `inspector/app.py`:
  - `Flask(__name__, static_folder="static")` → `Flask(__name__, static_folder=str(FRONTEND_DIST), static_url_path="")` with `FRONTEND_DIST = Path(__file__).parent.resolve() / "frontend" / "dist"`.
  - `/` route now serves `frontend/dist/index.html`; returns a 500 with a clear build-hint message if dist is missing.
  - `/static/<path:filename>` route removed — Flask's built-in static handler now serves `dist/*` at the site root (`/assets/<hash>.js`, `/fonts/DigitalKhattV2.otf`).
  - `extra_files` list removed from `app.run()` — Vite owns frontend file-watching; Flask reloader natively watches Python.
  - Added startup stderr warning if `dist/index.html` is missing, with both build and `npm run dev` commands.

## Scope deferred

- **Chart.js CDN → npm**: deferred to Phase 2 (still loaded via `<script>` tags in `index.html`).
- **`.js` → `.ts` rename + sub-foldering (`edit/`, `history/`, `validation/`, `waveform/`, `playback/`)**: Phase 2.
- **`inspector/CLAUDE.md` frontend section update**: Phase 6/7 — keeping scope tight; the CLAUDE.md still documents the old `static/js/` layout.

## Deviations from plan

| Plan said | Actual | Reason |
|-----------|--------|--------|
| `static_folder="frontend/dist"` relative | `static_folder=str(FRONTEND_DIST)` absolute via `Path(__file__).parent.resolve()` | Flask resolves `static_folder` relative to app.root_path, but the current directory behavior during `python inspector/app.py` depends on cwd. Using an absolute path derived from `__file__` is unambiguous and WSL-safe. |
| CSS imports added to `main.ts` | CSS imports added to `main.js` | Phase 1 deliberately keeps `.js` extension; Phase 2 renames. Functionally identical. |
| Remove `/static/<path>` route | Removed | No deviation. |
| `extra_files` stripped | Removed entirely | Simpler than selectively stripping JS/CSS entries. |

## Verification results

### Build gates
- `npm run typecheck` — **PASS** (0 errors; `allowJs:true` tolerates legacy `.js`)
- `npm run build` — **PASS** (55 modules transformed, 2.17s). Output:
  - `dist/index.html` — 16.88 kB
  - `dist/assets/index-<hash>.css` — 28.43 kB (all 9 CSS files bundled)
  - `dist/assets/index-<hash>.js` — 189.36 kB (44 JS modules bundled; 50.13 kB gzipped)
  - `dist/fonts/DigitalKhattV2.otf` — 521 kB (copied from `public/fonts/`)
- `grep /static/ dist/assets/*.js` — **0 matches** (no legacy paths leaked into bundle)
- `grep /static/ inspector/frontend/src/` — **0 matches** (no legacy paths in source)

### Flask prod serving (smoke, port 5055)
| Endpoint | Status | Body size |
|----------|-------:|----------:|
| `GET /` | 200 | 16,883 B (index.html) |
| `GET /assets/index-<hash>.css` | 200 | 28,432 B |
| `GET /assets/index-<hash>.js` | 200 | 189,489 B |
| `GET /fonts/DigitalKhattV2.otf` | 200 | 521,832 B |
| `GET /api/surah-info` | 200 | 20,867 B |
| `GET /api/ts/reciters` | 200 | 178 B |
| `GET /api/seg/reciters` | 200 | 138 B |
| `GET /api/audio/sources` | 200 | 34,980 B |
| `GET /static/js/main.js` | 404 | — (legacy path correctly removed) |
| `GET /audio/fake-reciter/fake.mp3` | 404 | — (`/audio/` route still alive; missing-file 404) |

### Vite dev server sanity (port 5173)
- `npm run dev` — starts cleanly in 865 ms, no errors
- `GET http://localhost:5173/` → 200, serves `index.html` with `/@vite/client` injected
- No 404s in `/tmp/vite.log`

### Smoke checklist (plan §Verification)
Full S1–S14 smoke requires a browser; verification agent confirmed build + server can serve every asset. Actual browser smoke (S1 tabs render, S2 timestamps flow, S3 segments, S12 audio, S14 font renders) pending first in-browser test by the user. All prerequisites for those tests are green.

## Bug-log delta

- **Rows added:** none (no new bugs surfaced in this phase).
- **Rows closed:** none.
- **Status changes:** none.
- **Foreshadowing:** B08 (`/api/seg/edit-history` JSONL-vs-`r.json()` mismatch) will be closed in Phase 3 via `shared/api.fetchJsonl`.

## tsconfig state at phase end

No change from Phase 0:
- `strict`: false
- `noImplicitAny`: false
- `strictNullChecks`: false
- `noUncheckedIndexedAccess`: false
- `allowJs`: true (still required; Phase 2 renames to `.ts`)
- `checkJs`: false

## Review findings (3-agent gate)

- **Haiku coverage**: 6/6 PASS. All 60+ moves verified at destinations; `inspector/static/` gone; app.py references `FRONTEND_DIST` 7× and has no `/static/<path>` route.
- **Sonnet quality**: 10 findings — items 1–5 were artifacts of reviewing the repo before the Phase 1 commit lands (they all distilled to "these changes are staged but not committed"). Items 6–7 were aesthetic (double-stringified Path, plain-text 500 body) and left as-is. Items 8–10 confirmed CSS import order is safe, no `/static/` leaks, and anti-goal preserved (JS content unchanged). No blocking issues.
- **Opus verification**: PASS across 4 parts (build gates, Flask prod, Vite dev, strategic). Confirmed Vite emits hashed asset refs in built `index.html`; dev server works; missing-dist warning prints correctly. Phase 2 risk notes: `registerHandler`/`event-delegation` indirection must stay intact during typing; Chart.js global needs ambient declare until npm migration; `state.js` registry pattern will need typed interfaces.

## Surprises / lessons

- `tsconfig.json`'s `allowJs:true` transparently handles the entire JS tree — zero source edits required for the move.
- Vite `publicDir:'public'` works identically in dev and prod — `/fonts/DigitalKhattV2.otf` resolves in both modes without additional proxy config.
- `static_url_path=""` lets Flask serve both `/assets/*` and `/fonts/*` from a single `static_folder`, eliminating the need for a second route.
- Build time is 2.17s — fast enough that we can realistically require `npm run build` in the dev loop for Python-only contributors, per plan §Decisions.

## Handoff to Phase 2

- **Known-good entry commit**: (this commit's SHA)
- **Prerequisites Phase 2 must not break**:
  - `public/fonts/DigitalKhattV2.otf` stays at that path.
  - `/src/main.js` entry reference in `index.html` must become `/src/main.ts` atomically with the main.js→main.ts rename.
  - The injection/registration patterns (`registerHandler`, `registerEditModes`, `registerEditDrawFns`, `registerWaveformHandlers`, `registerKeyboardHandler`, `setClassifyFn`) must keep running at import time before DOMContentLoaded — this is what breaks circular deps today. TS rename must preserve import ordering.
  - Chart.js migration (CDN → npm) happens in Phase 2, but per plan, it can be a separate commit within the phase for bisect-ability.
- **Questions / decisions for Phase 2**:
  - Sub-folder `edit-*.js` → `segments/edit/`, `history-*.js` → `segments/history/`, `validation.js`+`categories.js`+`error-cards.js`+`error-card-audio.js` → `segments/validation/`, `waveform.js`+`waveform-draw.js` → `segments/waveform/`, `playback.js`+`audio-cache.js` → `segments/playback/` per plan §Target Folder Structure. Import path rewrites touch every consumer.
  - `tsc --noEmit` should still pass after rename (`allowJs:true`, no type annotations added).
  - `registerHandler` registry type: use `Record<string, (...args: unknown[]) => unknown>` or keep untyped? Start untyped (Phase 2 is pure rename) and type in Phase 4.
- **Next command**: Phase 2 kicks off with `git mv` per module, then batch import-path rewrite, then `npm run build` + smoke.
