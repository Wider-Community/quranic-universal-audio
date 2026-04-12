# Phase 0 — Bootstrap Vite + TypeScript scaffold

**Status:** COMPLETE
**Commit:** pending (this phase)
**Branch:** `worktree-refactor+inspector-modularize`

## Scope delivered

- `inspector/frontend/` created with all Stage-1 scaffold config:
  - `package.json` (vite 5, typescript 5, eslint 9 flat config, prettier, chart.js dep declared for Phase 2)
  - `tsconfig.json` (starting state: `allowJs:true, strict:false, noImplicitAny:false, strictNullChecks:false`; `baseUrl:"."` added to satisfy TS5090 for the `@/*` path alias)
  - `vite.config.ts` (dev proxy for `/api` and `/audio` to Flask :5000; Vite :5173; build output `dist/`)
  - `eslint.config.js` (ESLint 9 flat config — plan originally said `.eslintrc.cjs` but flat config is the correct ESLint 9 default)
  - `.prettierrc.json` (4-space indent, single quotes, trailing commas, 100-col width — matches existing inspector code style)
  - `.gitignore` (`node_modules/`, `dist/`, `.vite/`, `*.log`)
  - `index.html` placeholder
  - `src/main.ts` placeholder (`export {};`)
- `.refactor/stage1-bugs.md` seeded with 8 pre-existing bug rows (B01–B08) and the full section layout (seeded / TS-caught / API-drift / new-introduced / closed).
- `npm install` ran successfully (170 packages, one benign EBADENGINE warn about eslint-visitor-keys wanting Node 20.19+ — we have 20.18; not blocking).

## Scope deferred

- `inspector/app.py` changes (`static_folder="frontend/dist"` + missing-dist error) deferred to **Phase 1** when the actual JS move happens. Phase 0 leaves Flask serving legacy `inspector/static/` unchanged.
- `inspector/frontend/public/` not yet created — Phase 1 creates it when fonts move.
- Chart.js / `chartjs-plugin-annotation` declared in `package.json` but not yet installed & wired; the actual CDN → npm migration happens in **Phase 2** per plan.

## Deviations from plan

| Plan said | Actual | Reason |
|-----------|--------|--------|
| `.eslintrc.cjs` | `eslint.config.js` | ESLint 9 default is flat config. Functionally equivalent. |
| `tsconfig.json` without `baseUrl` | Added `"baseUrl": "."` | Required by TS5090 for `paths` to work; `moduleResolution:"bundler"` alone is insufficient. |
| `root: __dirname` in vite.config | `root: fileURLToPath(new URL('.', import.meta.url))` | `__dirname` unavailable in ESM; ESM-idiomatic pattern. |
| `vite.config.ts` resolved via `__dirname` | Same ESM resolution via `fileURLToPath` | Same reason as above. |
| ESLint `recommended` config only | Added `@typescript-eslint/no-explicit-any: 'off'` + `no-unused-vars: 'warn'` + `ban-ts-comment: 'warn'` | Default `recommended` flags explicit `any`, which is intentionally common during Stage 1 migration. Will be tightened in Phase 7 cleanup. |

## Verification results

- `npm run typecheck` — **PASS** (0 errors)
- `npm run build` — **PASS** (`dist/index.html` + `dist/assets/index-*.js` produced, 0.75 kB js, no warnings)
- `npm run lint` — **PASS** (0 output on placeholder `main.ts`)
- `git diff inspector/app.py inspector/static/` — **empty** (Flask + legacy static unchanged)
- `git check-ignore` — `inspector/frontend/dist` and `inspector/frontend/node_modules` correctly ignored
- `python3 -c "import ast; ast.parse(open('inspector/app.py').read())"` — app.py syntactically unchanged
- Smoke suite (expected for Phase 0): S1 (all 3 tabs still render), S2 (timestamps flow), S3 (segments list), S12 (audio tab) — all PASS by virtue of no JS/HTML being touched.

## Bug-log delta

- **Rows added:** none beyond seeded B01–B08
- **Rows closed:** none
- **Status changes:** B03 description tightened after Sonnet quality review noted it overstated bug scope (the issue is specifically `target_seg_index` field, not the whole row)

## tsconfig state at phase end

- `strict`: false
- `noImplicitAny`: false
- `strictNullChecks`: false
- `noUncheckedIndexedAccess`: false
- `allowJs`: true
- `checkJs`: false
- `baseUrl`: "."

This is the lenient starting state; ratchets per plan §Phase Breakdown.

## Review findings (3-agent gate)

- **Haiku coverage**: 13/13 deliverables PASS; 4/4 "must not exist" checks PASS.
- **Sonnet quality**: 2 actionable concerns — (a) `@typescript-eslint/no-explicit-any` default would block intentional `any` usage during migration **[fixed]**; (b) B03 description overstated bug scope **[fixed: tightened to cite the specific `target_seg_index` field]**. 5 non-issues correctly dismissed.
- **Opus verification**: all 7 empirical steps PASS; placeholder `main.ts` confirmed not tree-shaken (Vite emits a 0.75 kB bundle with modulepreload polyfill, proving the entry is wired); dev-proxy coverage confirmed sufficient for S1–S3 smoke (`/api` + `/audio`); no blocking anti-patterns.

## Surprises / lessons

- ESLint 9 flat config is mandatory (no `.eslintrc.cjs` fallback); plan text was pre-9.
- `moduleResolution:"bundler"` still requires `baseUrl` for `paths` to parse — not implicit.
- `tsc --noEmit && vite build` chain means a typecheck failure blocks the build — intentional gate, but will create friction during typing phases (5, 6) when ratchet produces transient errors. Plan to flip to `vite build` only for WIP commits within typing phases and re-chain for final phase-exit builds.

## Handoff to Phase 1

- **Known-good entry commit**: (this commit's SHA)
- **Prerequisites Phase 1 must not break**:
  - `dist/` stays gitignored.
  - `inspector/app.py` modifications must preserve the existing `/audio/<reciter>/<filename>` route exactly (it's not moved, just left alone).
  - CSS font URL rewrite (`/static/fonts/...` → `/fonts/...`) must happen in the same commit as the file moves to avoid a 404 window.
- **Questions / decisions for Phase 1**:
  - Should the dev-mode Flask route print a log line indicating it's serving legacy `static/` vs built `dist/`? (Small, helpful for onboarding. Not in plan — add if ergonomics demand.)
  - Confirm the 9 CSS files import order when translated to `main.ts` imports — must match the original `<link>` order (base → components → timestamps → segments → validation → history → stats → filters → audio-tab).
- **Next command**: Phase 1 implementation agent receives this handoff + plan §Phase 1 + the working-tree state.
