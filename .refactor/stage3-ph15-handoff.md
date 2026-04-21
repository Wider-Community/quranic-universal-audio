# Ph15 — Feature colocation

Baseline: HEAD `07b8280`. Branch `inspector-refactor`. Ph14a+Ph14b landed. Ph14c cancelled — its 7-subfolder reorg is absorbed into Ph15a.

**Goal**: move feature-scoped code (currently in `lib/stores/<tab>/`, `lib/utils/<tab>/`, `lib/types/<feature>.ts`) under the tab's own directory. `lib/` shrinks to cross-tab-only.

---

## Ph15a — Segments colocation (Opus, invasive)

### Target layout

```
src/tabs/segments/
├── SegmentsTab.svelte
├── ShortcutsGuide.svelte
├── components/
│   ├── edit/        (existing dir moved here)
│   ├── history/     (existing dir moved here)
│   ├── save/        (existing dir moved here)
│   ├── validation/  (existing dir moved here)
│   ├── list/        (existing dir moved here)
│   ├── filters/     (existing dir moved here)
│   ├── stats/       (existing dir moved here)
│   └── audio/       (existing dir moved here)
├── stores/          (12 files from lib/stores/segments/)
├── utils/           (41 files from lib/utils/segments/ + stats-chart-draw.ts, reorg per below)
└── types/           (segments.ts, segments-waveform.ts, stats.ts from lib/types/)
```

### Utils 7-subfolder structure (baked into the move)

```
tabs/segments/utils/
├── constants.ts       (top-level — cross-cutting)
├── keyboard.ts        (top-level — tab entry point)
├── stats-chart-draw.ts (moved from lib/utils/ — segments-only consumer, option C)
├── edit/
│   ├── common.ts        (from edit-common.ts)
│   ├── enter.ts         (from edit-enter.ts)
│   ├── split.ts         (from edit-split.ts)
│   ├── trim.ts          (from edit-trim.ts)
│   ├── merge.ts         (from edit-merge.ts)
│   ├── delete.ts        (from edit-delete.ts)
│   └── reference.ts     (from edit-reference.ts)
├── waveform/
│   ├── draw-seg.ts      (from waveform-draw-seg.ts)
│   ├── utils.ts         (from waveform-utils.ts)
│   ├── peaks-cache.ts
│   ├── split-draw.ts
│   └── trim-draw.ts
├── playback/
│   ├── playback.ts
│   ├── play-range.ts
│   ├── prefetch.ts
│   ├── error-card-audio.ts
│   └── audio-cache-ui.ts
├── history/
│   ├── actions.ts       (from history-actions.ts)
│   ├── render.ts        (from history-render.ts)
│   ├── chains.ts        (from history-chains.ts)
│   └── items.ts         (from history-items.ts)
├── save/
│   ├── actions.ts       (from save-actions.ts)
│   ├── execute.ts       (from save-execute.ts)
│   ├── preview.ts       (from save-preview.ts)
│   └── undo.ts
├── validation/
│   ├── classify.ts
│   ├── fixups.ts        (from validation-fixups.ts)
│   ├── refresh.ts       (from validation-refresh.ts)
│   ├── missing-verse-context.ts
│   └── conf-class.ts
└── data/
    ├── chapter-actions.ts
    ├── reciter-actions.ts
    ├── reciter.ts
    ├── config-loader.ts
    ├── clear-per-reciter-state.ts
    ├── navigation-actions.ts
    ├── references.ts
    ├── filters-apply.ts
    └── filter-fields.ts
```

### All moves

**A. Components** (8 dirs, use `git mv`):
- `tabs/segments/edit/` → `tabs/segments/components/edit/`
- `tabs/segments/history/` → `tabs/segments/components/history/`
- `tabs/segments/save/` → `tabs/segments/components/save/`
- `tabs/segments/validation/` → `tabs/segments/components/validation/`
- `tabs/segments/list/` → `tabs/segments/components/list/`
- `tabs/segments/filters/` → `tabs/segments/components/filters/`
- `tabs/segments/stats/` → `tabs/segments/components/stats/`
- `tabs/segments/audio/` → `tabs/segments/components/audio/`

`SegmentsTab.svelte` + `ShortcutsGuide.svelte` stay at `tabs/segments/` root.

**B. Stores** (12 files, use `git mv`):
- `lib/stores/segments/{audio-cache,chapter,config,dirty,edit,filters,history,navigation,playback,save,stats,validation}.ts` → `tabs/segments/stores/`

**C. Utils** (41 + 1 files, use `git mv`, rename per §Utils 7-subfolder):
All files from `lib/utils/segments/` into the new 7-subfolder layout inside `tabs/segments/utils/`. Plus `lib/utils/stats-chart-draw.ts` → `tabs/segments/utils/stats-chart-draw.ts` (option C — segments-only consumer).

Verify before moving stats-chart-draw: `rg "stats-chart-draw" inspector/frontend/src` — only StatsChart + ChartFullscreen consume it.

**D. Types** (3 files, use `git mv`):
- `lib/types/segments.ts` → `tabs/segments/types/segments.ts`
- `lib/types/segments-waveform.ts` → `tabs/segments/types/segments-waveform.ts`
- `lib/types/stats.ts` → `tabs/segments/types/stats.ts`

### Import path update strategy

Every move changes depth. Use this mental model:

- A file at `tabs/segments/components/<subdir>/<file>.svelte` importing:
  - A sibling in the same subdir: `./X.svelte`
  - A peer subdir in components: `../<peerdir>/X.svelte`
  - Another tab's feature: should NOT happen (cross-tab leak) — escalate.
  - Tab-local stores: `../../../stores/X.ts` (3 levels up to tabs/segments/, then stores/)
  - Tab-local utils: `../../../utils/<subdir>/X.ts` (same structure)
  - Tab-local types: `../../../types/X.ts`
  - Cross-tab lib/api: `../../../../../lib/api/X.ts` (5 levels up — tabs/segments/components/subdir → up to src/)
  - Cross-tab lib/utils/animation etc.: `../../../../../lib/utils/X.ts`
  - Cross-tab lib/types/api or domain: `../../../../../lib/types/api.ts`
  - Cross-tab lib/components (SearchableSelect, AudioPlayer, etc.): `../../../../../lib/components/X.svelte`

- A file at `tabs/segments/stores/X.ts` importing:
  - Another store: `./Y.ts`
  - Utils: `../utils/<sub>/Y.ts`
  - Types: `../types/X.ts`
  - Cross-tab lib/utils: `../../../lib/utils/X.ts`

- A file at `tabs/segments/utils/<sub>/X.ts` importing:
  - Sibling in same subdir: `./Y.ts`
  - Peer subdir util: `../<peer>/Y.ts`
  - Top-level util (constants, keyboard): `../X.ts`
  - Stores: `../../stores/X.ts`
  - Types: `../../types/X.ts`
  - Cross-tab lib/: `../../../../lib/X/Y.ts`

- A file at `tabs/segments/utils/X.ts` (top-level — constants.ts, keyboard.ts, stats-chart-draw.ts):
  - Subfolder util: `./<sub>/Y.ts`
  - Stores: `../stores/X.ts`
  - Types: `../types/X.ts`
  - Cross-tab lib/: `../../../lib/X/Y.ts`

- A file at `tabs/segments/types/X.ts` importing:
  - Cross-tab `lib/types`: `../../../lib/types/X.ts`
  - No tab-local imports (types should be acyclic)

**External importers** (everything outside `tabs/segments/`):
- `src/App.svelte` — imports from `tabs/segments/stores/playback.ts` for `segAudioElement`. Path: `./tabs/segments/stores/playback.ts`.
- `src/lib/**` — SHOULD NOT import from `tabs/segments/` after this. Verify: `rg "from ['\"].*tabs/segments" inspector/frontend/src/lib` → 0 hits. `stats-chart-draw` move handles the one known case.

### Implementation approach

1. **Dry-run on paper first**: enumerate every file to move, its new location, and the import edges that ripple. Work out the cross-subfolder utils imports that are most likely to break (edit/split → validation/fixups etc).

2. **Move in dependency order, deepest first**:
   a. Move types first (leaf — no imports from other moved files).
   b. Move utils, subfolder by subfolder, starting with leaves:
      - `validation/` (imports constants only)
      - `data/` (imports types, constants)
      - `waveform/` (imports types, references)
      - `playback/` (imports waveform, data)
      - `edit/` (imports common, waveform, validation, data, playback)
      - `history/` (imports classify, types)
      - `save/` (imports history, validation, playback)
      - top-level (constants, keyboard, stats-chart-draw)
   c. Move stores (they import utils).
   d. Move components (they import everything).

3. **One `git mv` at a time, update imports, then verify build compiles**. Don't batch moves — each broken import state wastes minutes in error-message triage.

4. **Cross-subfolder import auditing**: run `rg "from ['\"]\\.\\./edit-" tabs/segments/utils` etc. after each subfolder migration to catch stale paths.

5. **`rg "from ['\"].*lib/(stores|utils)/segments" inspector/frontend/src` after Ph15a must return 0 hits.**

### Constraints

- Svelte 4, strict TS, no @ts-ignore, no noise comments.
- Use `git mv` for every move so renames show in `git log --follow`.
- ONE commit: `refactor(inspector): Ph15a colocate segments feature under tabs/segments/`.
- DO NOT create re-export facades/shims.
- If a circular import surfaces that didn't exist before, STOP and report — the file organization probably needs a tweak.
- CLAUDE.md File Structure section — update only the `src/tabs/segments/` + `src/lib/` portions. Ph15b does the final sweep.

### Acceptance gates

- `cd inspector/frontend && npm run lint && npm run build` green.
- `python3 -c "from inspector.app import create_app; create_app()"` green (if factory exists; else `import app`).
- `ls src/tabs/segments/*.svelte` → 2 files (SegmentsTab, ShortcutsGuide).
- `ls src/tabs/segments/components/ -d */` → 8 subdirs.
- `ls src/tabs/segments/stores/*.ts | wc -l` → 12 files.
- `ls src/tabs/segments/utils/ -d */ | wc -l` → 7 subdirs.
- `ls src/tabs/segments/utils/*.ts | wc -l` → 3 files (constants.ts, keyboard.ts, stats-chart-draw.ts).
- `ls src/tabs/segments/types/*.ts | wc -l` → 3 files.
- `test -d src/lib/stores/segments` → must NOT exist.
- `test -d src/lib/utils/segments` → must NOT exist.
- `test -f src/lib/types/segments.ts` → must NOT exist.
- `test -f src/lib/utils/stats-chart-draw.ts` → must NOT exist.
- `rg "from ['\"].*lib/(stores|utils)/segments" inspector/frontend/src` → 0 hits.
- `rg "from ['\"].*lib/types/(segments|stats)" inspector/frontend/src` → 0 hits.
- `rg "from ['\"].*lib/utils/stats-chart-draw" inspector/frontend/src` → 0 hits.
- `rg "from ['\"]\\.\\./\\.\\./tabs/" inspector/frontend/src/lib` → 0 hits (no layer inversions).
- `git log --follow --oneline src/tabs/segments/utils/edit/split.ts | head -3` shows the move chain.

### Report (under 500 words)

- Subdirs created (count + list)
- Files moved per category (components, stores, utils, types, stats-chart-draw)
- Import sites updated (count, grouped by file kind)
- Any cross-subfolder renames in utils that revealed dependency surprises
- Gate results
- Commit SHA
- Any items you had to defer with reason

---

## Ph15b — Timestamps + audio colocation + lib/ cleanup (Sonnet)

Must land AFTER Ph15a.

### Moves

**Timestamps**:
- `lib/stores/timestamps/verse.ts` → `tabs/timestamps/stores/verse.ts`
- `lib/stores/timestamps/display.ts` → `tabs/timestamps/stores/display.ts`
- `lib/stores/timestamps/playback.ts` → `tabs/timestamps/stores/playback.ts`
- Tab subcomponents move to `tabs/timestamps/components/`:
  - `tabs/timestamps/UnifiedDisplay.svelte` → `tabs/timestamps/components/UnifiedDisplay.svelte`
  - `tabs/timestamps/AnimationDisplay.svelte` → `tabs/timestamps/components/AnimationDisplay.svelte`
  - `tabs/timestamps/TimestampsWaveform.svelte` → `tabs/timestamps/components/TimestampsWaveform.svelte`
  - `tabs/timestamps/TimestampsValidationPanel.svelte` → `tabs/timestamps/components/TimestampsValidationPanel.svelte`
  - `tabs/timestamps/TimestampsControls.svelte` → `tabs/timestamps/components/TimestampsControls.svelte`
  - `tabs/timestamps/TimestampsAudio.svelte` → `tabs/timestamps/components/TimestampsAudio.svelte`
  - `tabs/timestamps/TimestampsShortcutsGuide.svelte` (if exists) → `tabs/timestamps/components/`
- `TimestampsTab.svelte` stays at `tabs/timestamps/` root.

**Audio**:
- `lib/stores/audio.ts` → `tabs/audio/stores/audio.ts`
- `tabs/audio/AudioTab.svelte` stays at root (only file in the dir — no components/ subdir needed).

**lib/ cleanup**:
- After moves, `lib/stores/` should be empty → delete.
- `lib/types/` should retain only `api.ts`, `domain.ts`, `ui.ts`.
- Verify `lib/components/`, `lib/utils/`, `lib/api/` all genuinely cross-tab.

### CLAUDE.md rewrite

The **File Structure** section needs full rewrite of:
- `src/tabs/segments/` subtree — reflect new components/stores/utils/types colocation + 7-subfolder utils.
- `src/tabs/timestamps/` subtree — new components/ + stores/.
- `src/tabs/audio/` subtree — new stores/.
- `src/lib/` subtree — shrink: only `api/`, `components/`, `types/` (3 files), `utils/` (tab-agnostic only).

Update **Architecture — Frontend Layers** section to reflect the feature-colocated layout.

### Constraints

- Same as Ph15a. ONE commit: `refactor(inspector): Ph15b colocate timestamps + audio + shrink lib/ to cross-tab-only`.
- Update any remaining references to old `lib/stores/timestamps` / `lib/stores/audio` paths in CLAUDE.md or elsewhere.

### Acceptance gates

- Build + lint + py-smoke green.
- `ls src/tabs/timestamps/*.svelte` → 1 file (TimestampsTab).
- `ls src/tabs/timestamps/components/` → 6–7 files.
- `ls src/tabs/timestamps/stores/*.ts | wc -l` → 3 files.
- `ls src/tabs/audio/*.svelte` → 1 file (AudioTab).
- `ls src/tabs/audio/stores/*.ts | wc -l` → 1 file.
- `test -d src/lib/stores` → must NOT exist.
- `rg "from ['\"].*lib/stores" inspector/frontend/src` → 0 hits.
- `ls src/lib/types/*.ts | wc -l` → 3 (api.ts, domain.ts, ui.ts only).
- `rg "from ['\"].*tabs/" inspector/frontend/src/lib` → 0 hits.
- CLAUDE.md File Structure + Frontend Layers sections reflect new layout.
