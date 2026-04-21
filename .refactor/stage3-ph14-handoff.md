# Ph14 — Directory hygiene: layer inversion fix + tabs/segments reorg + lib/utils/segments reorg

Baseline HEAD: `00ba2df`. Branch: `inspector-refactor`.

Ph14 addresses two review findings from the Stage 5 Opus/Sonnet architectural reviews:
- **HIGH** layer inversion (`lib/` importing from `tabs/`)
- **HIGH** dead component
- **LOW** `tabs/segments/` top-level imbalance (13 files)
- **LOW** `lib/utils/segments/` flat 41-file directory

---

## Ph14a — HIGH surgical fixes (Sonnet)

### A1. Move `tabs/segments/stats-types.ts` → `lib/types/stats.ts`

**Why**: `lib/utils/stats-chart-draw.ts:11` imports from `tabs/segments/stats-types` — the only `lib/→tabs/` layer inversion in the tree.

Current file content defines: `ChartCfg`, `Distribution`. Move the file wholesale to `src/lib/types/stats.ts`.

Update importers. Run `rg -l "tabs/segments/stats-types|from.*stats-types" inspector/frontend/src` first to get the list — expect 4 files:
- `lib/utils/stats-chart-draw.ts` (the inversion)
- `tabs/segments/StatsPanel.svelte`
- `tabs/segments/StatsChart.svelte`
- `tabs/segments/ChartFullscreen.svelte`

New import per-file depth:
- `lib/utils/stats-chart-draw.ts` (at `lib/utils/`): `../types/stats` or `../../lib/types/stats` depending on current path style.
- `tabs/segments/*` (at `tabs/segments/`): `../../lib/types/stats`.

Preserve `import type` qualifiers where used.

### A2. Delete `lib/components/Button.svelte`

**Why**: zero importers. Verify before deleting: `rg "from.*components/Button|import Button from" inspector/frontend/src` returns zero hits.

Delete the file cleanly. Do NOT leave a comment referencing its removal anywhere. If `inspector/CLAUDE.md` currently enumerates `Button.svelte` in its file-tree, update CLAUDE.md to drop that line.

### Acceptance

- `cd inspector/frontend && npm run lint && npm run build` green.
- `rg "tabs/segments/stats-types" inspector/frontend/src` → 0 hits.
- `rg "lib/components/Button" inspector/frontend/src inspector/CLAUDE.md` → 0 hits.
- `test -f inspector/frontend/src/lib/types/stats.ts` → exists.
- `test -f inspector/frontend/src/lib/components/Button.svelte` → gone.
- `rg "from ['\"]\\.\\./\\.\\./tabs/" inspector/frontend/src/lib` → 0 hits (layer inversion cleared).

Commit: `refactor(inspector): Ph14a move stats-types to lib/types + delete dead Button.svelte`.

---

## Ph14b — `tabs/segments/` reorg (Sonnet)

**Goal**: cut `tabs/segments/` top-level from 13 `.svelte` files to 2, matching the existing `edit/`, `history/`, `save/`, `validation/` subfolder pattern.

### New subfolders (create under `src/tabs/segments/`)

```
tabs/segments/
├── SegmentsTab.svelte          (top-level, stays — tab shell)
├── ShortcutsGuide.svelte       (top-level, stays — keyboard ref)
├── edit/                       (existing, untouched)
├── history/                    (existing, untouched)
├── save/                       (existing, untouched)
├── validation/                 (existing, untouched)
├── list/                       NEW
│   ├── SegmentsList.svelte     (moved from top-level)
│   ├── SegmentRow.svelte       (moved)
│   ├── SegmentWaveformCanvas.svelte  (moved)
│   └── Navigation.svelte       (moved — back-to-results banner, part of list UI)
├── filters/                    NEW
│   ├── FiltersBar.svelte       (moved)
│   └── FilterCondition.svelte  (moved)
├── stats/                      NEW
│   ├── StatsPanel.svelte       (moved)
│   ├── StatsChart.svelte       (moved)
│   └── ChartFullscreen.svelte  (moved)
└── audio/                      NEW
    ├── SegmentsAudioControls.svelte  (moved)
    └── AudioCacheBar.svelte    (moved)
```

### Implementation notes

1. **Create the 4 subdirs first**: `mkdir -p src/tabs/segments/{list,filters,stats,audio}`.
2. **Use `git mv`** (or filesystem move + `git add`) for each file so Git detects renames cleanly.
3. **After moving each file, update import paths**:
   - Internal imports that stayed the same depth (file A was in top-level `tabs/segments/` and imported from `../../lib/...` — after moving to `tabs/segments/list/`, the depth increases: `../../../lib/...`).
   - Sibling imports between the moved files: e.g. if `SegmentRow.svelte` imported `SegmentWaveformCanvas.svelte` from the same folder, the relative path stays `./SegmentWaveformCanvas.svelte`.
   - Imports OF these files from outside (e.g. `SegmentsTab.svelte` imports `SegmentsList.svelte`): paths change from `./SegmentsList.svelte` to `./list/SegmentsList.svelte`.

4. **External importers** to update after the reorg:
   - `src/tabs/segments/SegmentsTab.svelte` is the primary consumer (imports SegmentsList, FiltersBar, Navigation, SegmentsAudioControls, StatsPanel, AudioCacheBar, maybe others).
   - `src/tabs/segments/edit/*.svelte` may import SegmentRow.
   - `src/tabs/segments/history/*.svelte` may import SegmentRow.
   - `src/tabs/segments/validation/*.svelte` may import SegmentRow.
   - `src/tabs/segments/save/*.svelte` may import ValidationPanel or SegmentRow.
   - `src/App.svelte` imports SegmentsTab only (no direct children), so likely unaffected.

5. **Grep before-each-move**: for every file being moved, run `rg -l "from.*['\"]\\./$(basename)['\"]\\|from.*['\"].*\\./$(basename without .svelte)['\"]" src` to find importers; adjust their paths.

6. **No renames, just relocations.** File names stay identical; only their parent directory changes.

### Acceptance

- `npm run lint && npm run build` green.
- `ls src/tabs/segments/*.svelte` shows exactly 2 files: `SegmentsTab.svelte` and `ShortcutsGuide.svelte`.
- `ls src/tabs/segments/list/` contains 4 files (SegmentsList, SegmentRow, SegmentWaveformCanvas, Navigation).
- `ls src/tabs/segments/filters/` contains 2 files.
- `ls src/tabs/segments/stats/` contains 3 files.
- `ls src/tabs/segments/audio/` contains 2 files.
- Git history preserves renames (check with `git log --follow --oneline src/tabs/segments/list/SegmentRow.svelte | head -3`).
- `inspector/CLAUDE.md` file-tree section updated to reflect the new layout.

Commit: `refactor(inspector): Ph14b tabs/segments reorg — list/filters/stats/audio subfolders`.

---

## Ph14c — `lib/utils/segments/` reorg (Sonnet)

**Goal**: group 41 flat files into 7 subfolders + 2 top-level leftovers. Drop verbose prefixes (`edit-*`, `history-*`) inside their subfolders where the subfolder name already carries the concept.

### New layout

```
lib/utils/segments/
├── constants.ts                (top-level — cross-cutting dict)
├── keyboard.ts                 (top-level — tab keyboard dispatcher)
├── edit/
│   ├── common.ts               (from edit-common.ts)
│   ├── enter.ts                (from edit-enter.ts)
│   ├── split.ts                (from edit-split.ts)
│   ├── trim.ts                 (from edit-trim.ts)
│   ├── merge.ts                (from edit-merge.ts)
│   ├── delete.ts               (from edit-delete.ts)
│   └── reference.ts            (from edit-reference.ts)
├── waveform/
│   ├── draw-seg.ts             (from waveform-draw-seg.ts)
│   ├── utils.ts                (from waveform-utils.ts)
│   ├── peaks-cache.ts          (unchanged name)
│   ├── split-draw.ts           (unchanged name — consider renaming to `draw-split.ts` for consistency? your call)
│   └── trim-draw.ts            (unchanged name)
├── playback/
│   ├── playback.ts             (unchanged name — yes, `playback/playback.ts`)
│   ├── play-range.ts           (unchanged)
│   ├── prefetch.ts             (unchanged)
│   ├── error-card-audio.ts     (unchanged)
│   └── audio-cache-ui.ts       (unchanged — by_surah cache UI, lives with audio concerns)
├── history/
│   ├── actions.ts              (from history-actions.ts)
│   ├── render.ts               (from history-render.ts)
│   ├── chains.ts               (from history-chains.ts)
│   └── items.ts                (from history-items.ts)
├── save/
│   ├── actions.ts              (from save-actions.ts)
│   ├── execute.ts              (from save-execute.ts)
│   ├── preview.ts              (from save-preview.ts)
│   └── undo.ts                 (unchanged — no prefix to drop)
├── validation/
│   ├── classify.ts             (unchanged)
│   ├── fixups.ts               (from validation-fixups.ts)
│   ├── refresh.ts              (from validation-refresh.ts)
│   ├── missing-verse-context.ts  (unchanged)
│   └── conf-class.ts           (unchanged)
└── data/
    ├── chapter-actions.ts      (unchanged)
    ├── reciter-actions.ts      (unchanged)
    ├── reciter.ts              (unchanged)
    ├── config-loader.ts        (unchanged)
    ├── clear-per-reciter-state.ts  (unchanged)
    ├── navigation-actions.ts   (unchanged)
    ├── references.ts           (unchanged)
    ├── filters-apply.ts        (unchanged)
    └── filter-fields.ts        (unchanged)
```

### Renames (prefix-drop) — 13 files

Only the files inside `edit/`, `history/`, `save/` (partial), `validation/` (partial) get their prefix dropped:

- edit-common.ts → edit/common.ts
- edit-enter.ts → edit/enter.ts
- edit-split.ts → edit/split.ts
- edit-trim.ts → edit/trim.ts
- edit-merge.ts → edit/merge.ts
- edit-delete.ts → edit/delete.ts
- edit-reference.ts → edit/reference.ts
- history-actions.ts → history/actions.ts
- history-render.ts → history/render.ts
- history-chains.ts → history/chains.ts
- history-items.ts → history/items.ts
- save-actions.ts → save/actions.ts
- save-execute.ts → save/execute.ts
- save-preview.ts → save/preview.ts
- validation-fixups.ts → validation/fixups.ts
- validation-refresh.ts → validation/refresh.ts
- waveform-draw-seg.ts → waveform/draw-seg.ts
- waveform-utils.ts → waveform/utils.ts

**Do NOT rename** `play-range.ts`, `playback.ts`, `prefetch.ts`, `error-card-audio.ts`, `audio-cache-ui.ts`, `classify.ts`, `conf-class.ts`, `missing-verse-context.ts`, `references.ts`, `reciter.ts`, `reciter-actions.ts`, `chapter-actions.ts`, `filters-apply.ts`, `filter-fields.ts`, `config-loader.ts`, `clear-per-reciter-state.ts`, `navigation-actions.ts`, `constants.ts`, `keyboard.ts`, `split-draw.ts`, `trim-draw.ts`, `peaks-cache.ts`, `undo.ts` — their names already describe themselves without relying on a prefix.

### Implementation plan

1. **Create 7 subdirs**: `mkdir -p src/lib/utils/segments/{edit,waveform,playback,history,save,validation,data}`.

2. **For each file, in this order** (edit → waveform → playback → history → save → validation → data):
   - `git mv <old> <new>`.
   - Update intra-folder imports in the moved file (if it imports from sibling files in the same new subfolder, path becomes `./X.ts` — likely stays `./X`).
   - Update cross-subfolder imports: e.g., `edit/split.ts` importing `validation/fixups.ts` becomes `../validation/fixups`.

3. **External importers (outside `lib/utils/segments/`)**:
   - `src/lib/stores/segments/*.ts` — several stores import from `lib/utils/segments/*.ts` (e.g., `dirty.ts` imports `finalizeOp`, `snapshotSeg`? Verify).
   - `src/tabs/segments/**/*.svelte` — many consumers.
   - `src/App.svelte` — minimal, if any.

4. **Order of operations**: move files AND update imports in a single pass per file — don't leave the tree in a broken state for long. OR: use a two-pass strategy where phase 1 moves all files then phase 2 updates all imports. Either works; pick whichever is cleaner.

5. **Rename-aware import updates**: for the 18 renamed files, the import path loses the prefix:
   - `import { enterEditWithBuffer } from '../../lib/utils/segments/edit-enter'` becomes `... '../../lib/utils/segments/edit/enter'`.
   - Double-check each renamed file's importers carefully.

### Cross-subfolder edge audit (post-reorg)

After the reorg, verify imports still compile and there are no circular dependencies:
- `npm run build` runs `tsc --noEmit` which will surface any broken import chain.
- If Strict TS flags a circular import warning, escalate rather than suppress.

### Acceptance

- `npm run lint && npm run build` green.
- `ls src/lib/utils/segments/ -d */` shows 7 subdirectories.
- `ls src/lib/utils/segments/*.ts` shows exactly 2 files: `constants.ts`, `keyboard.ts`.
- Each subfolder file count matches plan (edit=7, waveform=5, playback=5, history=4, save=4, validation=5, data=9).
- `git log --follow --oneline src/lib/utils/segments/edit/split.ts | head -3` shows the rename chain back to `edit-split.ts`.
- `rg "from.*lib/utils/segments/edit-" inspector/frontend/src` → 0 hits (all prefix-drop renames propagated).
- `inspector/CLAUDE.md` file-tree section updated to reflect new layout. The existing CLAUDE.md file-tree already has placeholders / partial listings — align to new layout.

Commit: `refactor(inspector): Ph14c lib/utils/segments reorg — 7 subfolders + prefix-drop renames`.

---

## Global constraints (all sub-phases)

- Svelte 4, strict TS, no @ts-ignore, no comment noise.
- Use `git mv` for every file move so renames show up in `git log --follow`.
- ONE commit per sub-phase. No push. No amend of prior commits.
- If any move introduces a circular import that didn't exist before, STOP and report — don't work around it with a shim file.
- After each sub-phase, run `bash .refactor/stage3-checks.sh` (may exit non-zero on the shell script's `wc -l` edge case — check build+lint+py-smoke lines independently).

## Report per sub-phase

- Files moved (list or count, grouped by subfolder)
- Import sites updated (count)
- Gate results (build, lint, py-smoke)
- Commit SHA
- Any surprises (circular imports, CLAUDE.md drift, etc.)
