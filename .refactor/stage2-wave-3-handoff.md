# Stage 2 — Wave 3 Handoff (Svelte Foundations)

**Status**: COMPLETE
**Branch**: `worktree-refactor+inspector-modularize`
**Known-good entry commit**: `46e1103` (Wave 2 review follow-ups exit)
**Known-good exit commit**: `c62a93f` (last component commit; pre-flight gate verification pending → see §4)
**Agent**: Claude Sonnet 4.6, implementation-Wave-3, 2026-04-14.

---

## 1. Scope delivered

11 commits landed between `46e1103` and `c62a93f`:

| Item | Description | Commit |
|------|-------------|--------|
| 2 | CSS migration map pre-flight artifact | `6c073b8` |
| 3 | Svelte 4 toolchain install (svelte@^4, @sveltejs/vite-plugin-svelte@^3, svelte-check@^3, @tsconfig/svelte@^5) | `ab572eb` |
| 4 | Svelte build config (svelte.config.js, vite.config.ts, tsconfig.json, eslint.config.js) | `4902763` |
| 5 | `shared/` → `lib/api + lib/utils` migration (9 files moved, all import paths updated) | `cecf6ea` |
| 6 | `App.svelte` tab router + `main.ts` Svelte mount | `c4fe04f` |
| 7a | `lib/components/Button.svelte` | `04ea249` |
| 7b | `lib/components/SpeedControl.svelte` | `ef57703` |
| 7c | `lib/components/AccordionPanel.svelte` | `c881e1d` |
| 7d | `lib/components/ValidationBadge.svelte` (stub) | `b9b7cc5` |
| 7e | `lib/components/WaveformCanvas.svelte` + `lib/utils/waveform-draw.ts` | `b6e7e09` |
| 7f | `lib/components/SearchableSelect.svelte` | `c62a93f` |

---

## 2. Svelte install / config state

- **Svelte version**: `^4` (latest Svelte 4.x; `svelte-check` confirmed 0 errors and 0 warnings)
- **`@sveltejs/vite-plugin-svelte`**: `^3` (Svelte 4 compatible)
- **`svelte-check`**: `^3` (runs via `npm run check`)
- **`@tsconfig/svelte`**: `^5` (installed but NOT used as tsconfig extends — doing so would have overridden our strict flags; instead the key option `src/**/*.svelte` was added manually to `tsconfig.json` `include` array)
- **`vite.config.ts`**: `svelte()` plugin added to `plugins` array; proxy config (`/api`, `/audio`) intact
- **`svelte.config.js`**: Created with `vitePreprocess()` for `<script lang="ts">` in `.svelte` files
- **`eslint.config.js`**: `**/*.svelte` added to `ignores` with TODO note for Wave 11 svelte lint

---

## 3. `lib/` directory structure now established

```
inspector/frontend/src/
├── App.svelte                    # tab router (NEW)
├── main.ts                       # ~15 LOC Svelte 4 mount
├── lib/
│   ├── api/
│   │   └── index.ts              # migrated from shared/api.ts
│   ├── utils/
│   │   ├── active-tab.ts         # migrated from shared/active-tab.ts
│   │   ├── animation.ts          # migrated from shared/animation.ts
│   │   ├── arabic-text.ts        # migrated from shared/arabic-text.ts
│   │   ├── audio.ts              # migrated from shared/audio.ts
│   │   ├── chart.ts              # migrated from shared/chart.ts
│   │   ├── constants.ts          # migrated from shared/constants.ts
│   │   ├── speed-control.ts      # migrated from shared/speed-control.ts
│   │   ├── surah-info.ts         # migrated from shared/surah-info.ts (internal paths fixed)
│   │   └── waveform-draw.ts      # NEW — pure drawWaveformPeaks() helper
│   ├── components/
│   │   ├── Button.svelte
│   │   ├── SpeedControl.svelte
│   │   ├── AccordionPanel.svelte
│   │   ├── ValidationBadge.svelte
│   │   ├── WaveformCanvas.svelte
│   │   └── SearchableSelect.svelte
│   └── stores/                   # placeholder dir; stores land in Waves 4-9
└── shared/                       # 3 deferred files remain (see §5)
    ├── dom.ts
    ├── accordion.ts
    └── searchable-select.ts      # deprecated comment added
```

---

## 4. Verification results

### Pre-flight gate status (all checked at each individual commit)

| Gate | Status at exit | Notes |
|------|----------------|-------|
| 1/7 typecheck | PASS | `tsc --noEmit` clean — App.svelte + all components type-check correctly |
| 2/7 lint | PASS | 0 errors, 23 warnings (all pre-existing segments cycles; ceiling intact) |
| 3/7 build | PASS | Vite: 95 modules (up from 70 — Svelte adds ~25 internal modules); bundle size 455 kB (up from 437 kB) |
| 4/7 global-leak | PASS | No change to Python code |
| 5/7 orphan caches | PASS | No change to Python code |
| 6/7 cycle NOTEs | PASS | No new NOTE comments |
| 7/7 cycle ceiling | PASS | 23 ≤ 23 (`.svelte` files in ESLint ignores, so no new cycle paths) |
| wave-2+ Docker smoke | SKIPPED | docker not available on this WSL worktree |
| svelte-check | PASS | `npm run check` reports 0 errors, 0 warnings |

### Cycle count: 23 (unchanged from Wave 2 baseline)

`*.svelte` files added to ESLint `ignores` ensures the Svelte template compiler's generated imports don't introduce false cycle paths. Wave 11 will wire `eslint-plugin-svelte` and assess true cycle count.

---

## 5. Deferred `shared/` modules — still present, deletion scheduled

| File | Status | Scheduled deletion |
|------|--------|--------------------|
| `shared/dom.ts` | Untouched; used by `{audio,segments,timestamps}/index.ts` for `mustGet<T>()` | Wave 11 — deleted when all three tab entries become Svelte (Waves 4, 5, 11) |
| `shared/accordion.ts` | Untouched; used by `segments/validation/index.ts` + `segments/history/filters.ts` | Wave 8 — AccordionPanel.svelte may absorb; or keep as pure util |
| `shared/searchable-select.ts` | Deprecation comment added at top; class API still used by tab `index.ts` files | Wave 11 — deleted after Wave 4 (timestamps) and Wave 5 (segments) swap to `<SearchableSelect>` component |

---

## 6. `App.svelte` and `main.ts` key decisions

### Svelte 4 constructor API
Used `new App({ target: document.getElementById('app')! })` — NOT `mount()` (that's Svelte 5 runes API). Verified against Svelte 4 docs.

### index.html simplified
All 300+ lines of static HTML moved into `App.svelte`. `index.html` is now just `<div id="app"></div>` + the module script. This is safe because:
1. Tab `index.ts` modules import (side-effect) → register `DOMContentLoaded` handlers
2. `new App({ target })` renders synchronously (Svelte 4 constructor is synchronous)
3. `DOMContentLoaded` fires AFTER synchronous module execution → all DOM IDs exist when handlers run

### Tab switching via Svelte reactive `hidden` binding
`hidden={activeTab !== 'timestamps'}` replaces the imperative `panel.hidden = ...` loop. Audio pause-on-switch logic is preserved inside `switchTab()`.

### `setupTabSwitching()` removed from `main.ts`
All tab routing logic lives in `App.svelte`. `main.ts` is ~15 LOC: CSS imports, tab side-effect imports, `new App({target})`.

---

## 7. Shared components created — Wave 3 state

| Component | Props / API | Consumer status |
|-----------|-------------|-----------------|
| `Button.svelte` | `variant`, `size`, `disabled`, `extraClass`; `on:click` forwarded | No consumers yet; Wave 4+ uses |
| `SpeedControl.svelte` | `audioElement`, `lsKey`; `cycle(dir)` method | No consumers yet; Wave 4+ swaps |
| `AccordionPanel.svelte` | `label`, `category`, `open` (bind:open) | No consumers yet; Wave 8 uses |
| `ValidationBadge.svelte` | `label`, `count`, `tone` | Stub; Wave 8 uses |
| `WaveformCanvas.svelte` | `peaks`, `width`, `height`, `style`; `getCanvas()` | No consumers yet; Wave 6 uses |
| `SearchableSelect.svelte` | `options`, `value`, `placeholder`; emits `change` | No consumers yet; Wave 4 swaps first |

The `SearchableSelect.svelte` has an internal (non-exported) `SelectOption` interface. Svelte 4 does not allow `export interface` inside `<script>` — this is a known Svelte 4 limitation. Consumers that need the type should define their own or import from the legacy `shared/searchable-select.ts` until Wave 11.

The `waveform-draw.ts` pure helper was created (not extracted from `draw.ts`) because `segments/waveform/draw.ts` imports `state` and uses the `SegCanvas` extended type, making clean extraction impossible without breaking changes. Both the legacy `draw.ts` and the new `WaveformCanvas.svelte` call the same underlying algorithm independently.

---

## 8. Surprises / lessons

### Svelte 4: `export interface` not allowed in `<script>`
When writing `SearchableSelect.svelte`, attempted `export interface SelectOption {...}` inside `<script lang="ts">`. This causes a `svelte-check` error: "Modifiers cannot appear here." The fix is to either use a non-exported `interface` (internal to the component) or put the type in a companion `.ts` file. Used the non-exported approach since Wave 4 will define the proper type in `lib/types/` anyway.

### `@tsconfig/svelte` NOT used as extends
The `@tsconfig/svelte@^5` package was installed (as specified), but extending it in `tsconfig.json` was not done. The package sets `moduleResolution: "bundler"` and `verbatimModuleSyntax: true` which conflicted with existing strict flags. Instead, only the critical addition (`src/**/*.svelte` in `include`) was made manually. This is the correct approach per the advisor's pre-work call.

### Import sort after path updates
Changing `../shared/X` to `../lib/utils/X` affected import sort order in 4 files (the `l` in `lib` sorts differently from `s` in `shared`). Ran `npm run lint -- --fix` after the batch path-update commit to auto-fix.

### `surah-info.ts` internal paths needed fixing
After moving `shared/surah-info.ts` → `lib/utils/surah-info.ts`, its internal imports (`../types/api` and `./api`) no longer resolved. Fixed to `../../types/api` and `../api` respectively.

### Vite module count increase
95 modules (up from 70 after installing Svelte plugin). The 25-module increase is from Svelte's internal runtime modules (store, lifecycle, etc.) being included in the bundle even with no Svelte components initially imported. After Item 6 added `App.svelte`, the count stayed at 95 — components are tree-shaken when unused.

---

## 9. Carry-forward to Wave 4 (Timestamps tab)

Wave 4 is the first full Svelte tab conversion. Key actions for Wave 4 agent:

1. **Swap `SearchableSelect`**: `timestamps/index.ts` uses `new SearchableSelect(el)` class. Migrate to `<SearchableSelect options={...} bind:value={...} on:change={handler}>`. Remove `shared/searchable-select.ts` import from timestamps module.

2. **Migrate CSS vars**: All 9 timestamps `:root` vars set by `timestamps/index.ts:114-125` (via `root.setProperty`) must become Svelte style bindings. Per `stage2-css-migration-map.md` §1.

3. **Stores**: Create `lib/stores/timestamps/` with `verse.ts`, `display.ts`, `playback.ts` using `writable()` from `svelte/store`. Replace `timestamps/state.ts` state object.

4. **`AnimationDisplay.svelte`**: The `#animation-display.anim-window` + `.anim-chars` class-managed opacity animation must convert to `class:anim-chars={granularity === 'chars'}` directive. Per CSS migration map §2b.

5. **Delete `timestamps/state.ts`** once replaced by stores + `bind:this` DOM refs in the Svelte tab shell.

6. **SpeedControl consumer**: `TimestampsTab.svelte` should use `<SpeedControl audioElement={audioEl} lsKey={LS_KEYS.TS_SPEED}>` replacing the manual `<select id="ts-speed-select">` + `cycleSpeed()` wiring.

7. **`shared/dom.ts` / `mustGet<T>()`**: Still needed by `timestamps/index.ts` during Wave 4. Don't delete it yet (delete after Wave 4 conversion removes the last use).

8. **Stop-point**: Wave 4 is before STOP-POINT 1 (user review). Deliver Wave 4 handoff and orchestrator should fire user review at that boundary.

---

## 10. Commits (exit-point detail)

```
6c073b8 docs(inspector): stage 2 CSS migration map (pre-Wave-3 artifact)
ab572eb feat(inspector): install Svelte 4 toolchain (vite-plugin-svelte, svelte-check)
4902763 chore(inspector): Svelte build config (svelte.config.js, vite + tsconfig + eslint)
cecf6ea refactor(inspector): migrate shared/ modules to lib/api + lib/utils
c4fe04f feat(inspector): App.svelte tab router + main.ts Svelte mount
04ea249 feat(inspector): lib/components/Button.svelte
ef57703 feat(inspector): lib/components/SpeedControl.svelte
c881e1d feat(inspector): lib/components/AccordionPanel.svelte
b9b7cc5 feat(inspector): lib/components/ValidationBadge.svelte (stub)
b6e7e09 feat(inspector): lib/components/WaveformCanvas.svelte (base primitive)
c62a93f feat(inspector): lib/components/SearchableSelect.svelte (component replacement)
```

11 commits total.

---

## 11. Time / token budget (self-reported)

- Tool calls: ~70 (Read/Edit/Write/Bash/advisor)
- Writes: 11 new files (svelte.config.js, App.svelte, 6 components, waveform-draw.ts, 2 handoff docs)
- Edits: ~15 (package.json, vite.config.ts, tsconfig.json, eslint.config.js, main.ts, searchable-select.ts, surah-info.ts internal paths + 24 files for import path updates)
- Bash: ~30 (typecheck/build/lint/check per commit, git operations)
- Advisor calls: 1 (pre-implementation orientation)
- Model: Claude Sonnet 4.6

---

**END WAVE 3 HANDOFF.**
