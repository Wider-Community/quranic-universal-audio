# Stage 2 — Wave 8a.2 Handoff (ValidationPanel + ErrorCard Svelte migration)

**Status**: COMPLETE — Wave 8a scope fully delivered.
**Branch**: `worktree-refactor+inspector-modularize`
**Known-good entry commit**: `048d604` (Wave 8a.1 bridge-lag fix)
**Known-good exit commit**: `f04d135` (cycle ceiling decrement to 18)
**Agent**: Claude Sonnet 4.6 (implementation-Wave-8a.2), 2026-04-14.

---

## 0. At-a-glance

- 4 source commits + this handoff = 5 commits.
- 2 new files (`ValidationPanel.svelte`, `ErrorCard.svelte`), 4 modified, 0 deleted.
- 7/7 pre-flight gates GREEN. svelte-check 0/0. Lint 0 errors / **14 warnings** (cycle count
  dropped from 19→14; ceiling decremented 19→18).
- Bundle: 131 modules (+2 from 8a's 129), ~514 kB.
- All Wave 8a scope delivered: ValidationPanel.svelte, ErrorCard.svelte, SegmentsTab
  integration, dead code deletion from `validation/index.ts` and `error-cards.ts`.

---

## 1. Scope delivered

### 1.1 `ValidationPanel.svelte` — new (commit `a284c6e`)

Path: `inspector/frontend/src/tabs/segments/validation/ValidationPanel.svelte`

- Props: `chapter: number | null` (null = all chapters), `label: string | null`.
- `buildCategories(data, lcThreshold, activeQalqalaLetter, qalqalaEndOfVerse)` — pure
  function mapping `$segValidation` to 11-category descriptor list; filters empty ones.
- `$: categories = buildCategories($segValidation, lcThreshold, activeQalqalaLetter, qalqalaEndOfVerse)`.
- Component-local `openCategory: string | null` — one-at-a-time accordion. Resets on chapter
  change via `$: { void chapter; openCategory = null; }`.
- LC slider: `bind:value={lcThreshold}` range 50–99; drives `visibleItems` filter.
- Qalqala filter: `activeQalqalaLetter` + `qalqalaEndOfVerse` toggles.
- Both `{#each}` loops (nav buttons + ErrorCards) use `(issue)` key to prevent stale
  `onMount` data in ErrorCard instances when LC slider or qalqala filter changes.
- `handleAccordionToggle` and `handleShowAllContextClick` extracted to `<script>` block
  to avoid TypeScript cast errors in Svelte template inline handlers.
- `<!-- svelte-ignore a11y-label-has-associated-control -->` on LC slider label.

### 1.2 `ErrorCard.svelte` — new (commit `a284c6e`)

Path: `inspector/frontend/src/tabs/segments/validation/ErrorCard.svelte`

- Props: `category: string`, `item: SegValAnyItem`.
- Three rendering branches: `missing_words`, `missing_verses`, catch-all (8 categories).
- Show/Hide Context: component-local `showContext: boolean` + `contextEls: HTMLElement[]`.
  Context elements injected imperatively into `cardsContainerEl` via `onMount`.
- Ignore button: wires into `createOp`/`finalizeOp`/`markDirty` flow for applicable categories.
- Auto-fix button: calls `commitRefEdit()` for `missing_words` with `auto_fix`.
- `val-ctx-toggle-btn` class on Show/Hide Context button — targeted by `handleShowAllContext`
  in ValidationPanel (Show/Hide All Context button).
- `onDestroy` removes injected context elements.

### 1.3 SegmentsTab integration (commit `94161e1`)

- Removed imports: `captureValPanelState`, `renderValidationPanel`, `restoreValPanelState`
  from `validation/index`.
- Added: `import ValidationPanel from './validation/ValidationPanel.svelte'`.
- Template: two `<div id="seg-validation*">` wrappers preserved (so `mustGet()` in
  `segments/index.ts` still resolves), each containing a `<ValidationPanel>` instance:
  - `#seg-validation-global`: `chapter={null} label="All Chapters"` (shown only when a
    chapter is selected, so it renders the reciter-wide panel).
  - `#seg-validation`: `chapter={parseInt($selectedChapter)}` (chapter-scoped) or
    `chapter={null}` when no chapter selected.
- `onReciterChange`: removed `renderValidationPanel(valResult.value)` call.
- `clearPerReciterState`: replaced `valG.hidden = true; valG.innerHTML = ''` with `clearValidation()`.

### 1.4 Dead code deletion from `validation/index.ts` (commit `6352b40`)

Deleted:
- `renderValidationPanel` (~420 LOC, imperative DOM builder with stateful closures).
- `captureValPanelState`, `restoreValPanelState` (thin accordion wrappers, now unused).
- `_collapseAccordionExcept` (thin collapseSiblingDetails wrapper, now unused).
- `ValCategoryDescriptor`, `ValDetailsElement`, `ValCtxToggleButton` interfaces.
- All narrowed domain type imports (`SegValFailedItem`, `SegValMissingVerseItem`, etc.).
- `renderCategoryCards` import from `./error-cards`.
- `AccordionOpenState` / `capturePanelOpenState` / `restorePanelOpenState` imports from
  `shared/accordion` (no longer needed).

Retained:
- `refreshValidation()`, `invalidateLoadedErrorCards()` (no-op stub), `refreshOpenAccordionCards()`
  (no-op stub), and all three `_fixupValIndicesFor*` helpers (unchanged).

### 1.5 Dead code deletion from `error-cards.ts` (commit `6352b40`)

Deleted:
- `renderCategoryCards` (export, ~170 LOC batch-RAF renderer; only called by deleted
  `renderValidationPanel`).
- `resolveIssueToSegment` (export, only used inside `renderCategoryCards`).
- `addContextToggle` (export, only used inside `renderCategoryCards`).
- `ContextToggleOptions`, `CtxToggleButton`, `SegInWrapper` interfaces.
- Imports that were only used by the deleted functions:
  `SegValAnyItem`, `SegValMissingVerseItem`, `SegValMissingWordsItem`,
  `getChapterSegments`, `getSegByChapterIndex`, `commitRefEdit`,
  `findMissingVerseBoundarySegments`, `createOp`, `dom`, `finalizeOp`,
  `isDirty`, `isIndexDirty`, `markDirty`, `snapshotSeg`, `unmarkDirty`,
  `_isIgnoredFor`.

Fixed and retained:
- `ensureContextShown` — rewritten to use `btn.textContent?.trim() === 'Show Context'`
  instead of defunct `btn._showContext` property (which ErrorCard.svelte never set).
- `_isWrapperContextShown` — rewritten to use `btn.textContent?.trim() === 'Hide Context'`.
- `_rebuildAccordionAfterSplit`, `_rebuildAccordionAfterMerge`, `_refreshStaleSegIndices`,
  `_refreshSiblingCardIndices` — all retained (still called from `edit/split.ts`,
  `edit/merge.ts`). These do imperative DOM manipulation inside validation accordion
  wrappers; the Svelte `{#each}` will overwrite their changes on the next `$segValidation`
  update (e.g., after `segValidation.update(v => v)`), which is cosmetically fine until
  the next save+revalidate.
- `renderErrorCard` (module-private) — retained; called by `_rebuildAccordionAfterSplit/Merge`.
- `ErrorCardOptions` interface — retained; used by `renderErrorCard`.

### 1.6 Cycle ceiling decrement (commit `f04d135`)

`stage2-checks.sh` `CYCLE_CEILING` changed from `19` to `18`.

Actual cycle warning count dropped from 19 (Wave 8a.1 exit) to **14** — the
SegmentsTab→validation/index.ts import cycle was dissolved (5 warnings removed, since
multiple files in the segments→validation sub-graph shared that cycle path).

---

## 2. Scope deferred

### 2.1 Stats panel Svelte migration — deferred to Wave 8b or 9

`renderStatsPanel` in `segments/stats.ts` is still imperative. Simple migration
(no rebuild helpers, no context toggles). Optional for Wave 8b.

### 2.2 `_rebuildAccordionAfterSplit/Merge` — full reactive migration deferred to Wave 11

These imperative DOM manipulators directly modify `.val-card-wrapper` elements that
Svelte's `{#each}` also renders. They work today because the Svelte reconciler
tolerates DOM mutations between `$segValidation` updates. They are an NB (not blocking)
but should be converted to pure data mutations + `segValidation.update(v => v)` in a
later wave to eliminate the imperative/reactive conflict.

### 2.3 ReferenceEditor autocomplete, deleteSegment confirm() UI — unchanged from Wave 7b

### 2.4 All other Wave 7b deferred items — unchanged

---

## 3. Key decisions / lessons

### 3.1 `{#each}` key expressions are mandatory for component-with-`onMount`

When `{#each}` contains a Svelte component that runs `onMount`, each item **must**
have a key expression. Without it, Svelte diffs by index: when the list changes
(LC slider, qalqala filter), Svelte may reuse an existing component instance and
skip re-running `onMount`, leaving stale data in the component. Fix: `(issue)` using
the object reference as key.

### 3.2 TypeScript casts in Svelte template inline handlers error

`(e.currentTarget as HTMLDetailsElement).open` in an `on:toggle={(e) => { ... }}`
inline handler causes svelte-check "Unexpected token". Fix: extract the handler to
the `<script>` block where TypeScript's full syntax is supported.

### 3.3 `ensureContextShown` / `_isWrapperContextShown` must use button text

The legacy `addContextToggle` function attached `_showContext`/`_isContextShown`
properties directly to the button element (DOM property augmentation). ErrorCard.svelte
does not do this. The rewrite using `btn.textContent?.trim()` comparisons works for
both the old imperative buttons (which set text to 'Show Context'/'Hide Context') and
the new Svelte-rendered buttons (which also set the same text content).

### 3.4 `resolveSegFromRow` is in `rendering.ts`, not `data.ts`

The import correction was needed after deleting the old `renderCategoryCards` import
cluster (which had the correct source) and rewriting the header imports. Always verify
export locations when restructuring imports.

---

## 4. Verification results

### 4.1 Pre-flight gates (final run, commit `f04d135`)

| Gate | Result | Detail |
|------|--------|--------|
| [1/7] tsc typecheck | PASS | 0 errors |
| [2/7] eslint | PASS | 0 errors, **14 warnings** (was 19) |
| [3/7] vite build | PASS | 131 modules (+2 from 8a's 129), 514 kB |
| [4/7] no-global-keyword | PASS | Backend unchanged |
| [5/7] no-orphan-cache-vars | PASS | Backend unchanged |
| [6/7] no-cycle-NOTEs | PASS | Zero |
| [7/7] cycle-ceiling | PASS | 14/18 |
| `npx svelte-check` | PASS | 0 errors, 0 warnings |

---

## 5. Handoff to Wave 8b / 9

### Prerequisites the next agent must respect

1. **All Wave 8a.1 prerequisites still apply** (segValidation store is source of truth,
   `state.segValidation` is a read bridge, bridge-lag pattern for async handlers).
2. **ValidationPanel.svelte open-state**: Component-local (`openCategory`). No store
   or imperative capture/restore needed. Resets on chapter change automatically.
3. **`{#each}` keys on Svelte components with `onMount`**: Always use keyed `{#each}`.
4. **`_rebuildAccordionAfterSplit/Merge`**: These still do imperative DOM on the
   validation accordion wrappers. They are compatible with the current `{#each}` approach
   but should be converted to data mutations in a future wave.
5. **Cycle ceiling at 18.** Next wave should target further reduction.

### Queued tasks (Wave 8b / 9)

- [ ] **Stats panel Svelte migration** — `renderStatsPanel` in `segments/stats.ts`.
- [ ] **`_rebuildAccordionAfterSplit/Merge` → reactive** (Wave 11) — convert to
  data-only mutations + `segValidation.update(v => v)` + rely on Svelte {#each}
  reconciliation for DOM updates.
- [ ] **`error-cards.ts` shrink further** — once rebuild helpers also converted,
  the file may reduce to ~50 LOC (just `ensureContextShown`/`_isWrapperContextShown`
  + `_refreshStaleSegIndices`).

---

## 6. Commits (exit-point detail)

```
a284c6e feat(inspector): add ErrorCard.svelte and ValidationPanel.svelte (Wave 8a.2)
94161e1 refactor(inspector): mount ValidationPanel in SegmentsTab; remove imperative val calls
6352b40 refactor(inspector): delete dead code from validation/index.ts and error-cards.ts
f04d135 chore(inspector): decrement import/no-cycle ceiling to 18 (Wave 8a.2)
```

4 source commits + this handoff = 5 commits.

---

## 7. Review findings + disposition

### Sonnet (pattern review) — **APPROVE-WITH-CHANGES**

**Blocker:**

| ID | Item | Disposition |
|---|---|---|
| B1 | `segments/data.ts::onSegReciterChange` bypasses the new `segValidation` store: writes `state.segValidation = null/value` (lines 112, 155) AND clobbers Svelte-owned DOM via `dom.segValidationGlobalEl.innerHTML = ''` + `.hidden = true` (lines 108-111). Callers `save.ts:173` and `history/index.ts:77` would corrupt `<ValidationPanel>` on save/undo. | **Fixed** by orchestrator in follow-up commit: replaced state writes with `clearValidation()` / `setValidation()`; removed 4 DOM-clobber lines. |

**Non-blockers** (4): handoff §6.3 shape (7 sections vs 11 required — this §7+§8 restores); global panel open-state reset inconsistency (Wave 11); `_rebuildAccordionAfterMerge` innerHTML nuke (Wave 11 carry); cycle ceiling 18 vs actual 14 slack (Wave 8b tighten).

**Validated:** S2-D17 faithful (3 branches with catch-all covering 9 similar categories, all <100 LOC — per S2-D17 rationale), S2-D33 open-state persistence (component-local), Wave 7a.1 NB-3 4-of-4 sites post-fix, dead-code grep (7 deleted symbols: zero live callers), pattern notes #1/#3/#4, D2 + S2-B07 greps clean, LC slider + qalqala reactive.

### Opus (judgment review) — **REQUEST-CHANGES (pre-fix) → APPROVE (post-fix)**

Independent confirmation of B1 as live regression at exit `0d3252d`. All 10 judgment questions (A-J) reasoned through:

- **A (S2-D17 3-branch)** FAITHFUL — catch-all legitimately covers 9 structurally-similar categories; `canIgnore` gating, phoneme-tail for `boundary_adj` only, `failed` special-case all preserved.
- **B (930 LOC deletion)** SAFE — zero live references to deleted exports; retained `_rebuildAccordionAfterSplit/Merge`, `_refreshStaleSegIndices`, `ensureContextShown`, `_isWrapperContextShown`, `refreshValidation`, `_fixupValIndicesFor*` all have live callers.
- **C (B1)** BLOCKER confirmed — working-tree fix correct, matches SegmentsTab.svelte:295 precedent.
- **D (auto-fix asymmetry)** NOT A BUG — auto-fix mutates segment data, not validation; post-save `refreshValidation()` replaces whole value.
- **E (open-state local-let)** CORRECT — chapter reset intentional; global-panel immutable `chapter=null` → no spurious reset.
- **F (dual-write)** NEEDED today — `_forEachValItem` reads `state.segValidation` from `.ts` context where `$:` bridge doesn't fire synchronously; remove once fixup helpers migrate to pure store ops (Wave 9/10).
- **G (innerHTML nuke)** cosmetic-only window; next `segValidation.update(v=>v)` re-runs `{#each}`; NB carried to Wave 11.
- **H (7 vs 11 sections)** ACCEPTABLE process drift; this §7 restores.
- **I (LC slider semantics)** CORRECT — strict `<` matches Stage-1 label ("Show confidence < X%"); qalqala set-membership + `end_of_verse === true` boolean-strict; no off-by-one.
- **J (ceiling 14/18 slack)** defensive — Wave 8b tighten to 16 (2-warning buffer) recommended.

**Observation — `{#each as issue (issue)}` object-identity keying**: works today because `buildCategories` preserves item object references through filter paths. If any future validation pipeline clones items, ErrorCard `onMount` will re-run and re-inject cards. Document as carry-forward.

### Orchestrator disposition

- **B1 fixed** in orchestrator follow-up commit (4 source edits to `segments/data.ts`): import `clearValidation`/`setValidation`, replace `state.segValidation = null` with `clearValidation()`, replace `state.segValidation = valResult.value` with `setValidation(valResult.value)`, remove 4 `dom.segValidation*.hidden/.innerHTML` clobbers.
- **Opus recommendation #4** (manual-QA regression test for save → `_segDataStale` → `onSegReciterChange` re-hydration): carry to Wave 8b smoke checklist.
- **Wave 8b tighten cycle ceiling to 16** (not 14 — 2-warning buffer per Opus J).
- All other NBs deferred to Wave 9/10/11 as noted.

## 8. Handoff to Wave 8b (stats)

**Prerequisites Wave 8b must respect:**

1. Pattern notes #1-#8.
2. `state.segStatsData` → `Writable<SegStatsResponse | null>` in `lib/stores/segments/stats.ts`. Mirror 8a.1 promotion pattern.
3. Migrate write sites: `segments/data.ts` (reciter load + clear). AUDIT for the same B1 class of bug — ensure no `dom.segStatsPanel.innerHTML` / `.hidden` clobbers post-migration.
4. Tighten cycle ceiling from 18 → 16 (14 actual + 2 defensive buffer per Opus).
5. Optional: refactor `error-card-audio.ts` to `<AudioElement>`-based component if cheap.
6. Carry 4 unresolved Wave 8a NBs (NB-2 global panel reset; NB-3 `_rebuildAccordionAfterMerge` innerHTML; NB-4 ceiling tighten; auto-fix notification asymmetry).
7. **Manual-QA smoke item** (Opus rec): after save dirty edit + history undo, confirm ValidationPanel re-populates correctly (regression test for B1).

---

**END WAVE 8a.2 HANDOFF.**
