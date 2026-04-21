# Ph12 — Final comment sweep + CLAUDE.md refresh + dead audio-player kill

Baseline HEAD: `7e312a6`. Branch: `inspector-refactor`.

## Scope (3 clusters)

### 1. Strip refactor-process comments from 18 files

Grep target: `(Wave \d|Stage \d|Stage-\d|S2-D\d|Wave-\d|pre-Wave|moved from|bridge|kept while|Delete in Wave)` anywhere in `inspector/frontend/src/`.

Files identified (from current grep):
- `src/tabs/timestamps/UnifiedDisplay.svelte`
- `src/tabs/timestamps/TimestampsWaveform.svelte`
- `src/tabs/timestamps/TimestampsValidationPanel.svelte`
- `src/tabs/timestamps/AnimationDisplay.svelte`
- `src/lib/stores/timestamps/display.ts`
- `src/lib/stores/segments/filters.ts`
- `src/lib/stores/segments/navigation.ts`
- `src/tabs/segments/history/HistoryFilters.svelte`
- `src/tabs/segments/history/HistoryArrows.svelte`
- `src/tabs/segments/edit/DeletePanel.svelte`
- `src/lib/utils/segments/filters-apply.ts`
- `src/tabs/segments/save/SavePreview.svelte`
- `src/tabs/segments/Navigation.svelte`
- `src/styles/timestamps.css` — "Crossword bridge" is a DOMAIN term (cross-word phoneme bridges in Arabic recitation), NOT a refactor-bridge. **Do not strip** this one; confirm by reading lines 163–177. If the class name is used functionally in UnifiedDisplay.svelte, the CSS comment stays.
- `src/lib/types/ui.ts`
- `src/lib/components/ValidationBadge.svelte`
- `src/lib/components/Button.svelte`
- `src/lib/components/AudioElement.svelte`

**Rule**: when you strip a noise docstring, KEEP any substantive WHY comment. Rewrite the docstring to describe current behavior only. Example:

BEFORE:
```ts
/**
 * Foo — does X.
 *
 * Port of Stage-1 timestamps/foo.ts. Like Bar.svelte in Wave 4, hybrid pattern
 * #8 per locked §D6 / S2-D21: ...
 */
```

AFTER:
```ts
/**
 * Foo — does X. Hybrid pattern: Svelte owns structural render; imperative
 * code owns the 60fps overlay via getCanvas().
 */
```

Also strip inline noise: `// Wave 7 adopted`, `// per S2-D23`, `// Stage-1 behavior`, etc.

`inspector/CLAUDE.md` is **out of scope here** — cluster 3 handles that file.

### 2. Kill dead `getElementById('audio-player')` calls (6 sites)

The id `audio-player` has not existed on any HTMLAudioElement since Ph2 — these calls ALWAYS return null. They are harmless no-ops but count against imperative-DOM gate.

Replace all 6 sites with store reads from `tsAudioElement` (already exists — `src/lib/stores/timestamps/playback.ts`):

- `src/tabs/timestamps/UnifiedDisplay.svelte:300` + `:315`
- `src/tabs/timestamps/TimestampsWaveform.svelte:138` + `:189`
- `src/tabs/timestamps/AnimationDisplay.svelte:289` + `:391`

Replacement pattern (adjust for the local idiom):
```ts
import { get } from 'svelte/store';
import { tsAudioElement } from '../../lib/stores/timestamps/playback';
// ...
const audio = get(tsAudioElement);
if (!audio) return;
// ... existing logic
```

If the call site is inside a reactive `$:` block or a function called at rAF rate, prefer subscribing via `$tsAudioElement` or passing the element in as a prop rather than calling `get()` per frame. Use judgment.

Verify with grep afterward: `rg "document\.getElementById\('audio-player'\)" src` returns 0 hits.

### 3. Refresh `inspector/CLAUDE.md`

The current doc is accurate in spirit but has stale sections after the refactor:

- **State object pattern** section — DELETE. `src/segments/state.ts` and the `dom` singleton both died in Ph6c-2/Ph6b.
- **Registration pattern** section — partially obsolete. The `registerHandler` pattern died with the segments imperative dir; only `WaveformCanvas`'s getCanvas escape hatch remains. Rewrite or remove as appropriate.
- **File Structure** tree — rewrite to reflect current layout:
  - `src/shared/` gone
  - `src/types/` gone (moved to `src/lib/types/`)
  - `src/segments/` gone (fully absorbed into `tabs/segments/` + `lib/stores/segments/` + `lib/utils/segments/`)
  - `src/lib/stores/segments/` has new files (dirty.ts, history.ts, save.ts, playback.ts, navigation.ts, filters.ts, config.ts, cache-status.ts)
  - `src/lib/utils/segments/` is now a rich directory — list each file with a one-line purpose (consult actual tree via `ls`)
  - `src/tabs/segments/` now hosts the full Svelte component set (edit/, history/, save/, validation/ subdirs)
  - `src/lib/components/` + `src/lib/stores/audio.ts` are new
- **Segments Editing Operations** table — still accurate, but update the module paths (e.g., `segments/edit/trim.ts` → `lib/utils/segments/edit-trim.ts`).
- **Save Flow** / **Edit History** — verify module paths.
- **Frontend Layers** diagram — update to reflect Svelte-first (no more imperative segments subdir).
- **Segments Validation Categories** table — module paths (e.g., `segments/validation/categories.ts` → `lib/utils/segments/classify.ts`).
- Keep domain knowledge sections verbatim (Conventions, Confidence colors, Save Flow narrative, Dependencies, etc.).

Treat CLAUDE.md as a living doc — describe the PRESENT system. Do not reference "Wave N" or "Stage N" anywhere. Keep phrases like "hybrid pattern" only where the pattern is still in use.

## Constraints

- Svelte 4 only. Strict TS. No `@ts-ignore`.
- One commit per cluster OR one commit for all three — either is fine. If one commit, message should be `refactor(inspector): Ph12 final comment sweep + CLAUDE.md refresh + kill dead audio-player refs`.
- Do not push.
- Gates: build + lint + py-smoke green. `imperative-DOM` metric drops by ~6. `refactor-noise files` → ≤ 1 (maybe 0 — CSS domain-term exempt).

## Report format

- Files modified (count + grouped list)
- Noise metric: before → after
- DOM metric: before → after
- CLAUDE.md changes summary
- Commit SHA(s)
- Any surprises
