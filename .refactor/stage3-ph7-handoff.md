# Ph7 — Delete src/shared/ + src/types/ + residual imperative DOM (App.svelte, Stats toast, Validation show-context)

Baseline (HEAD `3ffb7fb`):
- build: OK, lint: OK, py-smoke: OK
- imperative-DOM calls: 39 (Ph6f left)
- refactor-noise files: 27
- LEGACY dirs present: `src/shared/`, `src/types/`
- Branch: `inspector-refactor`

## Scope

Delete two legacy dirs + three residual imperative-DOM clusters.

### Ph7a — structural deletion (Sonnet)

Files to delete fully:
- `inspector/frontend/src/shared/accordion.ts` (0 callers; `AccordionPanel.svelte` uses none — only stale docstring references remain)
- `inspector/frontend/src/shared/dom.ts` (`mustGet<T>` is dead — state.ts singletons died Ph6c-2)
- `inspector/frontend/src/shared/searchable-select.ts` (only a type import in `lib/stores/segments/chapter.ts` for the `segChapterSS` store — the Svelte component already replaced the class)
- After file deletions, delete empty `src/shared/` dir.

Delete dead store + calls:
- `lib/stores/segments/chapter.ts`
  - Drop `import type { SearchableSelect }` line
  - Drop `export const segChapterSS = writable<SearchableSelect | null>(null)` (line 50)
- `lib/utils/segments/navigation-actions.ts`
  - Drop `segChapterSS` import
  - Drop the two `const ss = get(segChapterSS); if (ss) ss.refresh();` blocks (lines 43–44, 219–220). Svelte `SearchableSelect.svelte` is fully reactive to `value` + `options` props; no refresh call is needed.

Move types:
- `inspector/frontend/src/types/api.ts` → `inspector/frontend/src/lib/types/api.ts`
- `inspector/frontend/src/types/domain.ts` → `inspector/frontend/src/lib/types/domain.ts`
- After moves, delete empty `src/types/` dir.

Caller updates (~72 import sites across 53 + 25 files, one file may import both):
- Run `grep -rln "from.*types/domain" src` and `grep -rln "from.*types/api" src` for the full list.
- Update every relative path:
  - `'../../types/domain'` → `'../types/domain'`  (for `lib/**/*.ts` one level down from `lib/`)
  - `'../../../types/domain'` → `'../../types/domain'`  (for `lib/stores/*/*.ts`, `lib/utils/*/*.ts`, `tabs/*/*.svelte` at 3-deep)
  - `'../../../../types/domain'` → `'../../../types/domain'`  (for `tabs/segments/validation/*.svelte`, `tabs/segments/history/*.svelte`, `tabs/segments/edit/*.svelte`)
  - Same pattern for `types/api`.
  - Existing `lib/types/segments.ts` + `lib/types/segments-waveform.ts` import `'../../types/domain'` — change to `'./domain'`.
- Verify `import type` vs runtime: every current site uses `import type` (type-only). Preserve.

Strip refactor-noise comments:
- In EVERY file you touch, strip lines matching any of: `Wave \d`, `Stage \d`, `S2-D\d+`, "moved from", "previously", "bridge", "kept while", "Delete in Wave", "Ph6[a-f]", "— (Wave|Stage)".
- Specifically touch and strip:
  - `src/lib/components/AccordionPanel.svelte` docstring (refs to `shared/accordion.ts`)
  - `src/tabs/segments/validation/ValidationPanel.svelte` header docstring
  - `src/lib/components/SearchableSelect.svelte` header docstring
  - `src/lib/utils/segments/navigation-actions.ts` header docstring (mentions "compatibility shim" + "Wave 9")
  - `src/lib/types/segments.ts`, `src/lib/types/segments-waveform.ts`
  - `inspector/CLAUDE.md` is fine — out of scope here; orchestrator updates it at Ph12.

Sanity gates:
- `cd inspector/frontend && npm run lint && npm run build`
- `bash .refactor/stage3-checks.sh` — expect `LEGACY dir still exists` lines gone for `src/shared` and `src/types`; noise count drops a bit; DOM calls unchanged (Ph7b handles those).

Commit format: `refactor(inspector): Ph7a delete src/shared + src/types + dead segChapterSS`

### Ph7b — residual imperative DOM (Sonnet)

**App.svelte tab-switch audio pauses (5 calls)**:
- 5 `document.getElementById(...).pause()` lines in `switchTab()`.
- Introduce 3 per-tab audio element writable stores (check if any already exist — `lib/stores/segments/playback.ts` already has `segAudioElement`; likely need `tsAudioElement` in `lib/stores/timestamps/playback.ts` and `audAudioElement` in a new `lib/stores/audio.ts` or at the AudioTab level).
- In each tab's root, `<audio bind:this>` → setter into the store on mount; on destroy set to null.
- In `App.svelte::switchTab()`, replace the 5 DOM calls with `get(tsAudioElement)?.pause()`, `get(segAudioElement)?.pause()`, `get(audAudioElement)?.pause()`. The extra "pause every `<audio>` nested in #segments-panel" loop exists because validation ErrorCard had its own audio (stopErrorCardAudio handles it); call `stopErrorCardAudio()` instead of the DOM loop.
- Remove `id="segments-panel"` / `id="audio-panel"` from `App.svelte` (no longer used anywhere — verify with grep first).

**StatsChart + ChartFullscreen "Saved" toast (4 calls × 2 sites)**:
- 2× `document.createElement('span')`, `document.body.appendChild`, `tip.remove()`.
- Replace with component-local `let showSavedTip = false; setTimeout(() => showSavedTip = false, 1200);` and `{#if showSavedTip}<span class="seg-stats-saved-tip">Saved</span>{/if}` inside the component's root div. Works for both components identically — consider a tiny shared helper if obvious but DO NOT prematurely abstract.

**ValidationPanel show-all-context buttons (4 calls)**:
- `containerEl.querySelectorAll('.val-ctx-toggle-btn')` + `b.textContent?.trim() === 'Hide Context'` + `b.click()` in `handleShowAllContext()` and `handleShowAllContextClick()`.
- Replace with `bind:this` onto each `<ErrorCard>` in the `{#each cat.visibleItems}` loop, storing refs in a `Map<type, ErrorCard[]>` keyed by category (or by item via `WeakMap`). Iterate that category's refs, check `getIsContextShown()` to determine `anyShown`, then call `showContextForced()` / `hideContextForced()` on each.
- Delete `val-ctx-toggle-btn` querySelector code and the two helper functions.
- The `Show/Hide All Context` button's click handler inside `{#each categories}` must scope to ONLY that category's ErrorCards, not all categories. Use closure over `cat.type`.
- ErrorCard's public 3-method API (`getIsContextShown`, `showContextForced`, `hideContextForced`) exists already — keep it, just consume via `bind:this` instead of DOM scan.

Sanity gates:
- `cd inspector/frontend && npm run lint && npm run build`
- `bash .refactor/stage3-checks.sh` — DOM calls: 39 → expected <30 (App.svelte 5 + Stats 4 + ValidationPanel 4 = 13 removed)
- Manually click through: reciter switch (Timestamps audio pauses), chapter select + tab switch, StatsChart save (toast shows), ValidationPanel show/hide-all-context per category.

Commit format: `refactor(inspector): Ph7b audio pause stores + stats toast + val show-context`

## Constraints

- Svelte 4 only. No runes.
- Strict TS. No `@ts-ignore` / `@ts-nocheck`.
- No shim files, no re-export facades, no "moved from X" comments.
- When updating imports, adjust depths carefully. If a file has `import type` from `types/domain` AND is moved relative to the new `lib/types/` path, recompute per-file — don't just do a global sed.
- NEVER add `// removed in Wave X` markers. Just delete.
- Never invoke the old class API anywhere.
