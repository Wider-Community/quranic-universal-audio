# Inspector Segments Refactor — Plan

**Branch:** `inspiring-ramanujan-2d4e7e`
**Source doc:** [docs/inspector-segments-refactor-plan.md](../docs/inspector-segments-refactor-plan.md)
**Sidecar:** [`.refactor/plan.yaml`](plan.yaml)
**Test inventory:** [`.refactor/test-inventory.md`](test-inventory.md)
**Orchestration log:** [`.refactor/orchestration-log.md`](orchestration-log.md)

---

## Purpose

The Segments inspector has accumulated correctness bugs around validation
categories, ignore behavior, save previews, history, undo, and JSON persistence
because domain rules are scattered across many modules. The source-of-truth doc
(`docs/inspector-segments-refactor-plan.md`) details the problem and the
target architecture.

This plan operationalizes that doc into six sequential phases, gated by an
upfront test suite that describes the **target** behavior (not the current
behavior). Tests are written first, with xfail markers per phase, and flip to
passing as each phase lands. Adding a new validation category in the future
must require only:

1. A new row in the issue registry.
2. A new classifier rule in the unified backend classifier.

No edits to edit utilities, save serializer, undo, history, accordion,
frontend classifier, or CLI validator. The test suite must auto-cover the new
category from the registry alone (parametrized tests).

---

## Interview Summary

### 0a Orientation

- Agents dispatched: 3 (rationale: medium codebase × medium prompt specificity; user named the doc and TDD strategy)
- Findings (compressed):
  - **Frontend** is Svelte 4 + TS + Vite; Segments tab at `inspector/frontend/src/tabs/segments/`. Stores at `stores/`; edit utils at `utils/edit/`; validation utils at `utils/validation/`. Existing Vitest tests are 7 files, ~280 LOC, none cover the segments domain.
  - **Backend** is Flask, Python 3.11, flat-import style. Routes at `inspector/routes/segments_*.py`; services at `inspector/services/`; classifier at `inspector/services/validation/_classify.py`. Existing pytest is 2 files (smoke + utils), no segments coverage.
  - **CLI validator** at `validators/validate_segments.py` is a near-copy of the backend classifier with its own thresholds and helpers. No tests.
  - Both vitest and pytest are wired up. Conventions: small files (200–500 LOC), no dead code, validators are load-bearing.

### 0b Questions asked

1. **Q**: How should tests behave when current code is buggy but the refactor will fix it?
   **A**: Target behavior. Tests describe the post-refactor target. Xfail until each phase clears them.

2. **Q**: What test layers should the upfront suite cover?
   **A**: Backend pytest (routes + services + classifier) + Frontend vitest (stores + edit utils + command layer). No Svelte component tests, no Playwright.

3. **Q**: Test fixtures structure?
   **A**: Shared JSON fixtures under `inspector/tests/fixtures/`, consumed by both pytest and vitest.

4. **Q**: Scope of upfront test suite?
   **A**: All 6 phases up front; many xfails initially; each phase clears its bucket.

5. **Q**: Issue policy matrix for the 11 categories?
   **A**: Locked (see §Invariants below).

6. **Q**: Classifier consolidation target?
   **A**: Backend-owned, CLI imports backend, frontend stops classifying live segments. Frontend reads backend DTOs.

7. **Q**: Identity & save semantics?
   **A**: `segment_uid` always present; empty `ignored_categories` array clears persisted ignores; stale validation items hidden post-structural-edit; patch-based undo is forward-only.

8. **Q**: Process / autonomy?
   **A**: Pause after test suite + plan; autonomous through phases; final pre-merge gate.

9. **Q (follow-up)**: What if `segment_uid` missing in legacy `detailed.json`?
   **A**: Backfill deterministically on load from `(chapter, original_index, start_ms)`; persist on next save.

10. **Q (follow-up)**: `viewOnly` registry flag?
    **A**: Drop it. Edit actions are always available; only `canIgnore` controls the Ignore button.

11. **Additional ask**: Tests should read the policy matrix from the registry so flag flips don't break them.
    **A**: Use parametrized behavioral tests (read registry → assert consequences) + a single policy-snapshot test that pins the matrix verbatim. Flag flip = one-line, deliberate, reviewed diff.

### Derived intent

- **Motivation**: Eliminate domain-rule fragmentation that has caused recurring bugs around ignore behavior, classifier divergence, undo gaps, and save/history drift. Make adding new categories cheap.
- **Subtype (primary)**: monolith-split / responsibility-consolidation (multiple subtype composition).
- **Subtype (secondary)**: pattern-replacement (ad-hoc mutation → command dispatch); classifier-consolidation; identity-stabilization (positional → uid).

### Seed for §2a Invariants

- MUST: HTTP route shapes, save payload acceptance, detailed.json on-disk schema (additive only), segment_uid stability, classifier parity across stacks (post-phase-2).
- MAY: Internal module organization, store internals, private helper signatures, log wording, comment placement.
- IS-changing: Eleven specific items below.

### Seed for §2f Review allocation

- Phase 1 (registry): Sonnet quality (mechanical-ish + small surface).
- Phase 2 (classifier consolidation): Sonnet + Haiku coverage + Opus verification (logic preservation across 3 stacks).
- Phase 3 (command layer): Sonnet + Opus verification (judgment calls likely).
- Phase 4 (normalize state): Sonnet + Haiku coverage (large file count).
- Phase 5 (patch undo): Sonnet + Opus verification (undo correctness is risk).
- Phase 6 (issue identity): Sonnet + Opus verification (DTO change has cross-stack impact).

### Seed for §2i Stop-points

- After Stage 2 plan finalized + Stage 4a test suite landed: pause for user approval before Phase 1 dispatches. **(S1)**
- Pre-merge: pause for user smoke-test. **(S7, always active)**
- Systemic S2–S6 active.

### Seed for §2g Shared-doc choice

- **Bug log**: yes. Reason: classifier divergence is documented but not exhaustive; further surprises likely surface during Phase 2 cross-stack reconciliation. Append-only log captures any divergences found mid-implementation that aren't pre-cataloged.
- **Decision log**: implicit in plan; not separate.

---

## §2a-pre Invariants

### MUST stay true

| ID | Statement | Testable via |
|---|---|---|
| MUST-1 | All inspector HTTP routes accept the same request shapes and return the same response field set as before the refactor. New optional fields may be added (additive only); no field is removed or renamed. | `test_routes_*.py` schema snapshot tests on every route. Frozen baseline captured before Phase 1. |
| MUST-2 | `detailed.json` on-disk schema is additive-only. `segment_uid`, `ignored_categories`, `wrap_word_ranges`, `confidence`, `time_start`/`time_end`, `matched_ref`/`matched_text` retain shape and semantics. New fields are optional. | `test_persistence_schema.py`: write fixture → read → assert known fields equal; assert no removed keys. |
| MUST-3 | `segments.json` on-disk format unchanged: nested `{verse_key: [[w_from, w_to, t_from, t_to], ...]}` with `_meta`. | `test_segments_json_rebuild.py`: round-trip a fixture; bytewise key-set parity. |
| MUST-4 | `segment_uid` is stable across reload + save cycles. UUIDs already present are never regenerated; missing UIDs are deterministically backfilled from `(chapter, original_index, start_ms)` and stable on subsequent reloads. | `test_uid_stability.py`: load → save → load → assert UIDs equal. |
| MUST-5 | The Ignore button's visibility on every category card matches `IssueRegistry[category].canIgnore`. | Parametrized vitest: every category, assert button presence/absence. |
| MUST-6 | After Phase 2 lands, the backend classifier and the CLI classifier produce identical category sets for any given fixture. The frontend does not classify live segments; it reads backend DTOs. | Cross-stack parity test: pytest hits route, vitest reads same fixture's expected; assert equal. |
| MUST-7 | Empty `ignored_categories` array on save = clear persisted ignores. Omitted key = preserve existing. `["_all"]` legacy marker continues to mean "ignore everything". | `test_save_clears_ignores.py`: 3 explicit cases. |
| MUST-8 | After Phase 5, undo applies a complete inverse patch (full before-segment restoration including all fields). Forward-only: pre-Phase-5 history batches keep current per-field undo path. | `test_patch_undo.py`: every command type, snapshot before, mutate, undo, assert deep equality. |
| MUST-9 | After Phase 6, validation issues reference segments by `segment_uid` (with `seg_index` retained as display-only fallback). Stale items (uid no longer present) are hidden in the accordion, not rendered as ghosts. | `test_validation_identity.py`: structural edit on fixture; assert stale issues filtered. |
| MUST-10 | Adding a new category requires changes in exactly two files: `IssueRegistry` row + classifier rule. The test suite picks up the new category through registry parametrization without further edits. | Manual exercise documented in plan §2a Success Criteria SC-3. |
| MUST-11 | After Phase 6 commits, no code or doc artifact in the repo carries **refactor-trace breadcrumbs** — comments / file headers / commit-message subjects that describe THIS refactor's history rather than the code's behavior. Specifically forbidden (case-insensitive substrings inside comments and doc-strings): `// refactored`, `// removed`, `# refactored`, `# removed`, `(was X before)`, `previously this`, `previously did`, `now uses the new`, `now dispatches via`, `migrated from`, `replaced by`, `superseded by Phase`, `before this refactor`, `as of Phase N`, `legacy <Foo> handling`. **Permitted**: pre-existing technical comments using historical phrasing to explain WHY (e.g. "previously rendered every row, so we virtualize" — explains the optimization, not the refactor); deliberate `legacy_` identifier names where the legacy-vs-modern distinction is part of the runtime contract (e.g. `apply_legacy_undo_record` in `services/undo.py`). Test fixtures, `.refactor/` directory, `docs/inspector-segments-refactor-plan.md`, and git history are exempt. Sonnet quality reviewer flags every new violation on every phase; Stage 5 final verification runs an explicit `git diff main...HEAD` grep limited to LINES INTRODUCED by the refactor. | Stage 5 grep on diff: `git diff main...HEAD --no-color \| grep -E '^\+' \| grep -inE '(// refactored\|// removed\|# refactored\|# removed\|previously this\|now uses the new\|now dispatches via\|migrated from\|replaced by\|superseded by Phase\|before this refactor\|as of Phase)'` returns empty. |

### MAY change

| ID | Statement |
|---|---|
| MAY-1 | Internal module organization within `inspector/services/validation/`, `inspector/frontend/src/tabs/segments/`, and `validators/`. |
| MAY-2 | Private helper signatures and call-site narrowing style. |
| MAY-3 | Comment wording and placement; doc-strings. |
| MAY-4 | `_byChapter` / `_byChapterIndex` cache fields — replaced or hidden in Phase 4. |
| MAY-5 | Frontend `_classifySegCategories` — removed in Phase 2 (or reduced to an internal helper for snapshot classification only, used until Phase 5 supersedes it). |
| MAY-6 | Internal store layout (denormalized → normalized) so long as compat selectors preserve `$segData` / `$segAllData` read shape. |
| MAY-7 | Operation-log entry shape on disk can grow new optional fields (e.g., `before_patch`, `after_patch` in Phase 5) but cannot remove existing. |
| MAY-8 | History record can grow new fields (e.g., `classified_issues` snapshot in Phase 2) but cannot remove existing. |
| MAY-9 | CLI validator output formatting; only category counts must match backend. |
| MAY-10 | Validation API responses gain `classified_issues: string[]` per snapshot; this field is **NEVER** persisted into `detailed.json` itself (only on validation responses + history snapshots). MUST-2 still holds for detailed.json. |

### IS being intentionally changed (phase-scoped)

| ID | Statement | Phase |
|---|---|---|
| IS-1 | Introduce `IssueRegistry` (Python + TS twins, schema-pinned) as the single source of truth for category metadata. Replace scattered category checks. | 1 |
| IS-2 | CLI validator (`validators/validate_segments.py`) imports backend classifier from `inspector.services.validation`. Duplicated helpers (`_strip_diacritics`, `_last_arabic_letter`, `_is_ignored_for`, manual `seg_belongs_to_entry`) deleted from CLI. | 2 |
| IS-3 | Frontend `_classifySegCategories` removed. Live-segment classification comes only from backend. Snapshot classification (history delta) reads backend-stored `classified_issues` field on snapshots. | 2 |
| IS-4 | Validation API responses gain a `classified_issues` field on each snapshot. History records persist this field with snapshots. | 2 |
| IS-5 | Introduce `SegmentCommand` union and `applyCommand()` reducer. UI dispatches commands; commands compute next state, op-log entry, affected chapters, and validation delta in one atomic operation. | 3 |
| IS-6 | Trim, split, merge, edit-reference, delete, ignore-issue, auto-fix flows migrated to dispatch through `applyCommand()`. UI components stop mutating segments directly. | 3 |
| IS-7 | Introduce `SegmentState{byId, idsByChapter, selectedChapter}` normalized store. Compat selectors preserve `$segData` / `$segAllData` read shape so older components keep working. `_byChapter` / `_byChapterIndex` retired. | 4 |
| IS-8 | Loader (`loadDetailedToDomain`) backfills `segment_uid` deterministically when absent. Backfill persists on next save. | 4 |
| IS-9 | Commands produce a `SegmentPatch{before, after, removedIds, insertedIds, affectedChapterIds}`. History records gain optional `patch` field. Backend `undo_batch` route applies inverse patch when patch is present. | 5 |
| IS-10 | Validation DTO gains `segment_uid` field on every issue. Frontend resolution uses uid first, falls back to `seg_index` for legacy issues. Stale issues (uid not in current state) are filtered, not rendered as ghosts. | 6 |
| IS-11 | `_fixupValIndicesForSplit/Merge/Delete` removed once all issues carry uid. Index fixups are no longer required. | 6 |

---

## §2a-pre Success Criteria

| ID | Metric | Baseline | Target | Tolerance |
|---|---|---|---|---|
| SC-1 | Backend classifier ↔ CLI classifier divergence count (categories disagreeing on a shared fixture) | 5 (low_confidence_detail tier; repetitions input set; boundary_adj phoneme tail; audio_bleeding algorithm; +duplicated helpers) | 0 | 0 |
| SC-2 | Frontend classifier files (live-segment classification) | 1 (`utils/validation/classify.ts`) | 0 (file removed; snapshot-only helper retained until Phase 5) | 0 |
| SC-3 | Adding a hypothetical new category `tashkeel_drift` requires edits to: | unknown (untested) | exactly 2 files (registry + classifier rule) + zero test edits (parametrized tests pick it up) | 0 |
| SC-4 | Total test cases in inspector test suite | ~9 thin tests | ≥ 150 (estimated; final count adjusts during Stage 4a) | -10% |
| SC-5 | Test pass rate at end of refactor | n/a | 100% (zero xfail remaining; all phase-target tests passing) | 0 |
| SC-6 | Number of sites mutating segments directly (across edit utilities + Svelte components) | ~12 (mostly in `utils/edit/*.ts` for trim/split/merge/reference/delete; one in `MissingWordsCard.svelte`'s auto-fix flow) | 0 (all dispatch through `applyCommand()`) | 0 |
| SC-7 | Cache repair sites (`_byChapter` / `_byChapterIndex` invalidate/rebuild) | 4 (in `chapter.ts`) | 0 (caches replaced with derived selectors) | 0 |
| SC-8 | Validation issue identity scheme | positional `seg_index` | stable `segment_uid` (with `seg_index` as display-only fallback) | binary |
| SC-9 | Total file count in `inspector/services/validation/` | 5 (`__init__.py`, `_classify.py`, `_detail.py`, `_missing.py`, `_structural.py`) | ≤ 7 (registry, schema, classifier, detail, missing, structural, snapshot_classifier — small, single-responsibility files) | +2 |

---

## §2a-pre Testing Strategy

**Branch: 4d → "Recommended" path with characterization elements.**

The user explicitly chose **target-behavior TDD**. Tests describe the
post-refactor target; currently-broken cases use `xfail`/`skip` with explicit
"flips in Phase N" markers. Each phase removes its xfails. The test suite
itself is the bug inventory.

Practical structure:

1. **Upfront suite landed before Phase 1** (Stage 4a). All test files written;
   most tests xfail-marked. Suite runs on every commit (existing CI assumed,
   or user runs locally; orchestrator runs at every phase boundary).

2. **Per-phase contract**: when Phase N completes, every test marked `xfail
   reason="phase-N"` must now pass without the marker. Removing the markers is
   part of the phase commit. Sonnet quality reviewer verifies no markers
   remain for the just-completed phase.

3. **Two-tier registry tests**:
   - **Parametrized behavioral tests** read the registry and assert consequences.
     Loop over `ALL_CATEGORIES`. Examples:
     - "for category C: if `registry[C].canIgnore`, the Ignore button is rendered on its card; else it isn't" — vitest helper test against the card props builder.
     - "for category C: if `registry[C].autoSuppress`, edit-from-card adds C to `ignored_categories`" — pytest + vitest, parametrized.
   - **Policy-snapshot test** pins the literal matrix (one assertion per backend, one per frontend). Flag flip = visible diff.

4. **Cross-stack parity tests**: pytest serializes a fixture detailed.json,
   hits the validation route, captures the response. Vitest loads the same
   fixture (same JSON file, both sides), asserts the response shape and
   contents match the saved expected output. Phase 2 makes these pass.

5. **Round-trip fixture tests**: per the source doc's `load detailed →
   classify → edit → save → reload → classify` cycle. Pytest end-to-end against
   the Flask test client.

Reviewer prompt addendum:
> *"The test suite is the source of truth for behavior. A test marked xfail
> with `reason='phase-N'` must pass without the marker after Phase N commits.
> Sonnet quality reviewer must flag any phase-N xfail still present in HEAD
> after the phase commit."*

> *"MUST-11: every phase. Flag any new comment, doc-string, or file-header
> string that references the refactor itself or the prior code shape:
> 'refactor', 'refactored', 'previously', 'used to be', 'old version', 'now is',
> 'migrated from', '// removed', '# removed', 'legacy X handling', 'before the
> refactor'. The clean-code rule from the project's collaboration guidelines is
> already 'no comments unless WHY is non-obvious' — this addendum strengthens
> it for refactor-context phrasing specifically. Code that was deleted should
> be deleted cleanly, not annotated as 'was X before'."*

---

## §2a Target Structure

### Backend (`inspector/`)

```
inspector/
├── services/
│   └── validation/
│       ├── __init__.py            # public API: validate_reciter_segments, validate_chapter
│       ├── registry.py            # NEW Phase 1: ISSUE_REGISTRY (single source of truth)
│       ├── classifier.py          # was _classify.py — single classifier, used by routes + CLI + history
│       ├── detail.py              # was _detail.py — builds per-category detail lists from classifier output
│       ├── missing.py             # was _missing.py — coverage-derived missing words
│       ├── structural.py          # was _structural.py — chapter-level structural errors
│       └── snapshot_classifier.py # NEW Phase 2: classifies SegSnapshot dicts (used by history endpoint)
├── domain/                        # NEW Phase 4: domain types shared with adapters
│   ├── segment.py                 # Segment dataclass
│   ├── command.py                 # SegmentCommand, CommandResult, SegmentPatch
│   └── identity.py                # uid backfill, deterministic generator
├── adapters/                      # NEW Phase 4: persistence adapters
│   ├── detailed_json.py           # load_detailed_to_domain, domain_to_detailed_json
│   ├── segments_json.py           # domain_to_segments_json (was rebuild_segments_json)
│   └── save_payload.py            # parse_save_payload (route-level deserializer)
├── services/
│   ├── save.py                    # uses adapters; persistence-only logic
│   ├── undo.py                    # Phase 5: applies inverse patches if present, falls back to legacy field-restore
│   └── history_query.py           # unchanged shape; record format gains optional fields per IS-4 / IS-9
├── routes/
│   ├── segments_data.py           # unchanged
│   ├── segments_edit.py           # unchanged contract
│   └── segments_validation.py     # response gains classified_issues + segment_uid (Phase 2 + Phase 6)
└── constants.py                   # legacy constants moved to registry.py over Phase 1
```

### Frontend (`inspector/frontend/src/tabs/segments/`)

```
src/tabs/segments/
├── domain/                        # NEW Phase 3
│   ├── registry.ts                # IssueRegistry (TS twin of backend registry, schema-derived)
│   ├── command.ts                 # SegmentCommand union, CommandResult, SegmentPatch
│   ├── apply-command.ts           # the reducer; takes (state, command) → result
│   └── identity.ts                # uid backfill mirror (in case fixtures are loaded client-side; primarily server-side)
├── stores/
│   ├── segments.ts                # NEW Phase 4: SegmentState{byId, idsByChapter, selectedChapter}
│   ├── chapter.ts                 # compat layer — derives $segData / $segAllData from segments.ts
│   ├── dirty.ts                   # unchanged externally; createOp now invoked by applyCommand internally
│   ├── validation.ts              # unchanged
│   ├── edit.ts                    # unchanged
│   ├── history.ts                 # unchanged
│   ├── save.ts                    # unchanged
│   ├── filters.ts                 # silence_after derived (not in-place mutation) per Phase 4 risk hotspot
│   └── navigation.ts              # unchanged
├── utils/
│   ├── edit/                      # Phase 3: each file becomes a thin command-dispatcher
│   │   ├── trim.ts                # confirmTrim → applyCommand({type:'trim', ...})
│   │   ├── split.ts               # confirmSplit → applyCommand({type:'split', ...})
│   │   ├── merge.ts               # mergeAdjacent → applyCommand({type:'merge', ...})
│   │   ├── reference.ts           # commitRefEdit → applyCommand({type:'editReference', ...})
│   │   ├── delete.ts              # deleteSegment → applyCommand({type:'delete', ...})
│   │   ├── ignore.ts              # NEW Phase 3 (extracted from GenericIssueCard.handleIgnore)
│   │   └── common.ts              # finalizeEdit, exitEditMode unchanged
│   ├── validation/
│   │   ├── resolve-issue.ts       # Phase 6: uid-first resolution
│   │   ├── stale.ts               # NEW Phase 6: filterStaleIssues helper
│   │   └── (classify.ts removed in Phase 2; snapshot helper retained until Phase 5 replaces it)
│   ├── save/
│   │   ├── execute.ts             # Phase 5: includes patch in payload when applyCommand produces one
│   │   ├── undo.ts                # Phase 5: dispatches /api/seg/undo-batch with patch fallback path
│   │   └── actions.ts             # unchanged
│   └── history/
│       ├── items.ts               # Phase 2: reads stored classified_issues; no local classification
│       └── chains.ts              # unchanged
└── components/                    # render-only: no segment mutations
    └── validation/
        ├── ValidationPanel.svelte # accordion order from registry (Phase 1)
        ├── GenericIssueCard.svelte # canIgnore from registry (Phase 1); editFromCard dispatches command (Phase 3)
        ├── MissingWordsCard.svelte
        ├── MissingVersesCard.svelte
        └── ErrorCard.svelte        # card-type dispatch from registry (Phase 1)
```

### CLI (`validators/`)

```
validators/
├── validate_segments.py           # Phase 2: imports inspector.services.validation.classifier
└── (deleted: _MUQATTAAT_VERSES, _QALQALA_LETTERS, _STANDALONE_REFS, _STANDALONE_WORDS, _is_ignored_for, _strip_diacritics, _last_arabic_letter — all replaced by backend imports)
```

### Tests (`inspector/tests/`)

```
inspector/tests/
├── conftest.py                                      # Phase 0: load_fixture helper, Flask client, shared registry fixture
├── fixtures/
│   └── segments/
│       ├── README.md                                # fixture schema, redaction rules
│       ├── 112-ikhlas.detailed.json                 # real Minshawi slice, audio URLs redacted
│       ├── 113-falaq.detailed.json                  # synthetic + real mix
│       ├── synthetic-structural.detailed.json       # missing_verses / missing_words / structural_errors injection
│       ├── synthetic-classifier.detailed.json       # one segment exhibiting each per-segment category
│       └── expected/                                # generated expected outputs (snapshot test artifacts)
│           ├── 112-ikhlas.classify.json
│           └── ...
├── registry/
│   ├── test_registry_policy.py                      # policy-snapshot test (pins matrix verbatim)
│   ├── test_registry_behavior.py                    # parametrized: registry → behavior consequences
│   └── test_registry_extensibility.py               # SC-3: synthetic new-category fixture
├── classifier/
│   ├── test_classify_per_category.py                # parametrized over 11 categories × N fixtures
│   ├── test_classify_parity.py                      # backend ↔ CLI parity (Phase 2)
│   └── test_classify_ignored_filter.py              # is_ignored_for honored uniformly
├── routes/
│   ├── test_route_validate.py                       # GET /api/seg/validate response shape (MUST-1)
│   ├── test_route_save.py                           # POST /api/seg/save accept + persist (MUST-1, MUST-7)
│   ├── test_route_undo.py                           # POST /api/seg/undo-batch (MUST-8)
│   ├── test_route_history.py                        # GET /api/seg/edit-history (MUST-1)
│   └── test_route_data.py                           # GET /api/seg/data response shape
├── persistence/
│   ├── test_detailed_schema.py                      # MUST-2: detailed.json round-trip + additive-only
│   ├── test_segments_json.py                        # MUST-3: segments.json rebuild parity
│   ├── test_uid_backfill.py                         # IS-8: deterministic + stable
│   └── test_save_clears_ignores.py                  # MUST-7
├── command/
│   ├── test_apply_command.py                        # IS-5: command → CommandResult deterministic
│   ├── test_command_per_op.py                       # IS-6: every op type produces consistent state
│   └── test_auto_suppress.py                        # parametrized: registry.autoSuppress drives behavior
├── undo/
│   └── test_patch_undo.py                           # IS-9: forward-only patch application
├── identity/
│   └── test_validation_identity.py                  # IS-10: uid-first; stale items filtered
└── parity/
    ├── test_classifier_parity_backend_cli.py        # MUST-6: backend ↔ CLI on shared fixture
    └── snapshot_expected_outputs.py                 # regenerator script (run when classifier intentionally changes)
```

### Tests (`inspector/frontend/src/tabs/segments/__tests__/`)

```
src/tabs/segments/__tests__/
├── helpers/
│   ├── fixtures.ts                                  # imports same JSON files as pytest (resolved via Vite)
│   └── make-segment.ts                              # builder used across tests
├── registry/
│   ├── policy.test.ts                               # policy-snapshot test (TS side)
│   ├── behavior.test.ts                             # parametrized behavioral tests
│   └── parity.test.ts                               # TS registry === Python registry (loaded from generated artifact)
├── command/
│   ├── apply-command.test.ts                        # reducer behavior
│   ├── trim.test.ts                                 # IS-6
│   ├── split.test.ts                                # IS-6
│   ├── merge.test.ts                                # IS-6
│   ├── reference.test.ts                            # IS-6
│   ├── delete.test.ts                               # IS-6
│   ├── ignore.test.ts                               # IS-6 (new helper)
│   └── auto-suppress.test.ts                        # parametrized over registry
├── normalized-state/
│   ├── selectors.test.ts                            # derived selectors return correct slices
│   ├── compat.test.ts                               # $segData / $segAllData shape preserved
│   └── uid-backfill.test.ts                         # IS-8 mirror (frontend loader)
├── save/
│   ├── payload-shape.test.ts                        # save payload matches MUST-1 contract
│   └── patch-included.test.ts                       # Phase 5: payload includes patch
├── identity/
│   ├── resolve-issue.test.ts                        # IS-10: uid-first resolution
│   └── stale-filter.test.ts                         # IS-10: stale items hidden
├── parity/
│   └── classifier-output.test.ts                    # frontend reads backend DTO; no local classification
└── existing/                                        # legacy tests, unchanged
    └── ... (SegmentsList, TimeEdit, autoplay-gap)
```

---

## §2b Phase Breakdown

| Phase | Name | Risk | Behavior surface | Wall-clock estimate |
|---|---|---|---|---|
| 0 | Test infrastructure + fixtures | low | pure additions | 25 min |
| 1 | Issue registry (backend + frontend twins) | low | content edits, preserve semantics | 35 min |
| 2 | Classifier consolidation (CLI imports backend; frontend stops classifying live) | high | judgment calls expected | 50 min |
| 3 | Command application layer | high | judgment calls expected | 60 min |
| 4 | Normalize segment state + uid backfill | medium | content edits + structural moves | 50 min |
| 5 | Patch-based undo (forward-only) | medium | content edits, preserve undo correctness | 35 min |
| 6 | Stable validation issue identity | low | content edits | 30 min |

Phase 0 is the upfront test suite. Phases 1–6 each clear their xfail bucket.

---

## §2c Per-Phase Detail

### Phase 0 — Test Infrastructure + Fixtures

**Scope files**
- `inspector/tests/conftest.py` (extend existing)
- `inspector/tests/fixtures/segments/*.detailed.json` (new)
- `inspector/tests/fixtures/segments/expected/*.json` (new)
- `inspector/tests/fixtures/segments/README.md` (new)
- `inspector/frontend/src/tabs/segments/__tests__/helpers/fixtures.ts` (new)
- `inspector/frontend/src/tabs/segments/__tests__/helpers/make-segment.ts` (new)
- All test files listed in §2a Target Structure under `inspector/tests/` and `inspector/frontend/src/tabs/segments/__tests__/`

**What lands**
- All ~150 test cases as files. Each test file has its full xfail markers per phase. Tests describe target behavior throughout.
- Shared JSON fixtures under `inspector/tests/fixtures/segments/`. Frontend imports them via Vite's `?json` or relative path resolution.
- Generated expected-output snapshots under `expected/`. A regenerator script at `inspector/tests/parity/snapshot_expected_outputs.py` is included but its outputs use the post-Phase-2 unified classifier (so initially the parity tests xfail until Phase 2).

**Migration order within phase**
1. `conftest.py` extension (fixture loader, registry placeholder fixture).
2. Fixture JSON files (real Minshawi 112 slice + 3 synthetic).
3. Test helpers (vitest side).
4. Test files: registry → classifier → routes → persistence → command → undo → identity → parity.
5. Run full suite; count xfails; record in handoff.

**Invariant impact**: none directly. This phase establishes the gate that subsequent phases must pass through.

**Verification**: `pytest -v inspector/tests/ && cd inspector/frontend && npm test`. Expected: many xfails, zero unexpected pass-or-fail. Record xfail count per phase bucket.

### Phase 1 — Issue Registry

**Scope files**
- `inspector/services/validation/registry.py` (new)
- `inspector/constants.py` (modify; some constants move into registry)
- `inspector/services/validation/__init__.py` (re-export registry)
- `inspector/frontend/src/tabs/segments/domain/registry.ts` (new — manually mirrored from Python; Phase 2 introduces codegen if needed)
- `inspector/frontend/src/tabs/segments/utils/constants.ts` (modify; re-export from registry)
- `inspector/frontend/src/tabs/segments/components/validation/ValidationPanel.svelte` (modify; accordion order from registry)
- `inspector/frontend/src/tabs/segments/components/validation/GenericIssueCard.svelte` (modify; canIgnore + autoSuppress from registry)
- `inspector/frontend/src/tabs/segments/components/validation/ErrorCard.svelte` (modify; card-type dispatch from registry)
- `inspector/frontend/src/tabs/segments/utils/edit/trim.ts` (modify; autoSuppress check via registry)
- `inspector/frontend/src/tabs/segments/utils/edit/reference.ts` (same)
- `inspector/frontend/src/tabs/segments/utils/edit/split.ts` (same — registry decides if inherited)
- `inspector/frontend/src/tabs/segments/utils/edit/merge.ts` (same)
- `inspector/services/save.py` (modify; persistsIgnore from registry — controls whether ignored_categories serializes)

**What lands**
- `IssueRegistry` Python module with the 11-category matrix locked in §Invariants below. Each row carries: `kind`, `card_type`, `severity`, `accordion_order`, `can_ignore`, `auto_suppress_on_edit`, `persists_ignore`, `scope` ('per_segment' | 'per_verse' | 'per_chapter'), `display_title`, `description`.
- TS twin at `domain/registry.ts` with identical schema. Phase 1 mirrors manually; if drift surfaces, Phase 2 introduces a generator.
- Open design question (resolved in Phase 1 implementation): for chapter-level / per-verse categories (`missing_verses`, `missing_words`, `structural_errors`), `auto_suppress_on_edit` semantics — when no segment is the target, auto-suppress fires by storing the suppression on the affected verse-level metadata block instead. Registry adds a `scope` field that the suppression code branches on.
- Replacement of every category-list literal with `Array.from(REGISTRY.keys())`.
- Removal of duplicate accordion-order arrays (currently in `ValidationPanel.svelte:210-222` and CLI's documentation comment).

**Invariant impact**
- IS-1 enacted.
- Tests for MUST-5 (Ignore button visibility) flip green.
- `test_registry_policy.py` (snapshot test) becomes the load-bearing artifact for the matrix.

**Verification**: registry tests + behavior tests in vitest pass; existing tests still pass; manual smoke: open inspector, expand each accordion category, verify Ignore button visibility matches matrix.

### Phase 2 — Classifier Consolidation

**Scope files**
- `inspector/services/validation/classifier.py` (renamed from `_classify.py`; merge in helper exports)
- `inspector/services/validation/snapshot_classifier.py` (new — accepts a SegSnapshot dict, returns classified categories list)
- `inspector/services/validation/__init__.py` (export `classify_segment`, `classify_snapshot`)
- `inspector/services/validation/_detail.py` → `detail.py` (renamed; consumes classifier output, no internal classification)
- `inspector/routes/segments_validation.py` (modify; embed `classified_issues` in each issue snapshot)
- `inspector/routes/segments_edit.py` (modify; save endpoint stores classified_issues alongside snapshots in history record)
- `inspector/services/save.py` (modify; history record save includes classified_issues per snapshot)
- `validators/validate_segments.py` (modify; delete duplicated helpers, import from `inspector.services.validation`)
- `inspector/frontend/src/tabs/segments/utils/validation/classify.ts` (DELETE — moved or removed entirely)
- `inspector/frontend/src/tabs/segments/utils/history/items.ts` (modify; reads `classified_issues` from snapshots; no local classification)
- **`inspector/frontend/src/tabs/segments/stores/dirty.ts` (modify — `snapshotSeg` calls `_classifySegCategories` to populate `snap.categories`; this caller migrates to read `classified_issues` from the live segment's last validation response, or drops `snap.categories` if not yet validated. See Plan-Review C-1.)**
- **`inspector/frontend/src/tabs/segments/components/history/SplitChainRow.svelte` and any history components consuming `_classifySnapIssues` (audit via grep; usually 2-3 files)**
- All other call sites of `_classifySegCategories` (audit via grep — `split.ts`, `merge.ts`, validation/* — replace with calls to a getter that reads backend DTO or stored snapshot field)
- **NOT in scope (preserved unchanged)**: `inspector/frontend/src/tabs/segments/utils/validation/refresh.ts`, `split-group.ts`, `conf-class.ts`, `missing-verse-context.ts`, `fixups.ts` (the latter retired in Phase 6).
- **No `index.ts` barrel exists** under `utils/validation/` today; consumers import classify.ts directly. Phase 2 deletes `classify.ts` and updates direct imports — no barrel update needed.
- **No `history-delta.ts` file exists** under `utils/save/` today; the Phase 1 plan-review identified this as a stale reference. The history-delta logic lives in `utils/history/items.ts` already (in scope above). The Phase 2 narrative previously hedged "if exists" — confirmed not to exist; remove.

**What lands**
- `_classify_segment` becomes the single classifier. Audio-bleeding algorithm uses backend's `seg_belongs_to_entry`. Repetitions check is `wrap_word_ranges` only (frontend's `has_repeated_words` extension dropped — surface in the bug log if any production fixture has `has_repeated_words` set without `wrap_word_ranges`; assumption is they're paired). Boundary-adj phoneme tail check stays optional (uses canonical when available).
- `low_confidence_detail` (1.0 cutoff) accessible from registry; CLI uses backend module's constant.
- CLI `validate_segments.py` shrinks: helper imports, no duplicate classification, output formatting unchanged.
- Frontend stops classifying live segments. The single remaining frontend classification path (snapshot delta in history) reads `classified_issues` field that's now embedded in saved snapshots.
- Validation API responses gain `classified_issues: string[]` per snapshot (new field, MAY add).

**Invariant impact**
- IS-2, IS-3, IS-4 enacted.
- MUST-6 satisfied (cross-stack parity).
- Bug log open if any classifier-input divergence surfaces during reconciliation (e.g., `has_repeated_words` segments).

**Verification**: classifier-parity tests pass; CLI test (`python validators/validate_segments.py <reciter>`) produces same counts as backend route; frontend tests for history-delta pass without local classifier; SC-1 = 0; SC-2 = 0.

**Rationale for Opus verification reviewer**: 3 classifiers being merged into 1 with subtle algorithm differences (audio_bleeding, boundary_adj, repetitions). Logic preservation is the primary risk; Opus reads the diff and confirms each merged predicate matches one of the source predicates (or matches the chosen tie-breaker, with the divergence noted in the bug log).

### Phase 3 — Command Application Layer

**Scope files**
- `inspector/frontend/src/tabs/segments/domain/command.ts` (new)
- `inspector/frontend/src/tabs/segments/domain/apply-command.ts` (new)
- `inspector/frontend/src/tabs/segments/utils/edit/trim.ts` (modify; thin dispatcher)
- `inspector/frontend/src/tabs/segments/utils/edit/split.ts` (same)
- `inspector/frontend/src/tabs/segments/utils/edit/merge.ts` (same)
- `inspector/frontend/src/tabs/segments/utils/edit/reference.ts` (same)
- `inspector/frontend/src/tabs/segments/utils/edit/delete.ts` (same)
- `inspector/frontend/src/tabs/segments/utils/edit/ignore.ts` (new — extracted from `GenericIssueCard.handleIgnore`)
- `inspector/frontend/src/tabs/segments/components/validation/GenericIssueCard.svelte` (modify; calls `applyCommand({type: 'ignoreIssue', ...})` instead of mutating directly)
- **`inspector/frontend/src/tabs/segments/components/validation/MissingWordsCard.svelte` (modify; the `auto_fix_missing_word` flow currently dispatches `markDirty` directly — migrate to `applyCommand({type: 'autoFixMissingWord', ...})` or fold into the existing trim command. See Plan-Review W-3.)**
- `inspector/frontend/src/tabs/segments/stores/dirty.ts` (modify; `createOp` invoked internally by `applyCommand`)
- `inspector/frontend/src/tabs/segments/utils/edit/common.ts` (modify; `finalizeEdit` accepts `CommandResult`)

**What lands**
- `SegmentCommand` discriminated union: `Trim`, `Split`, `Merge`, `EditReference`, `Delete`, `IgnoreIssue`, `AutoFixMissingWord`.
- `applyCommand(state, command, ctx)` returns `CommandResult{nextState, operation, affectedChapters, validationDelta?, patch?}`. The `patch` field is a stub here; Phase 5 fills it.
- **State shape during Phase 3**: `applyCommand` operates on a *transient* `state` view — `{ getChapterSegments, segAllData snapshot, ignoredCategoriesIndex }` — derived from the existing `segData` / `segAllData` stores. It does NOT yet operate on `SegmentState{byId, idsByChapter}`; that comes in Phase 4. The `nextState` returned by Phase 3's `applyCommand` is a slice of mutated segments + chapter id, NOT a full normalized state. Phase 4 narrows the signature to operate on `SegmentState`. **Phase 3's `apply-command.test.ts:applyCommand returns CommandResult with nextState` flips green at Phase 3 against the transient shape; the same test bucket adds normalized-state assertions at Phase 4 (see Plan-Review C-2).**
- Edit utilities become thin dispatchers: input validation (canvas state, refs) lives at the edge; mutation logic moves into `applyCommand`. The `_mountId` stays at the dispatcher edge — it's a UI binding, not a domain concern. **One Phase 3 store-level test asserts `targetSegmentIndex` is correctly set with chapter+index for both main-list and accordion mount paths (Plan-Review I-4).**
- `IgnoreIssue` is the first command implemented in full (it's small but touches UI, dirty, save, history, undo). Migration order within the phase: (1) `applyCommand` skeleton + `IgnoreIssue`. (2) `EditReference`. (3) `Trim`. (4) `Split`. (5) `Merge`. (6) `Delete`. (7) `AutoFixMissingWord` (extracted from `MissingWordsCard.svelte`).

**Invariant impact**
- IS-5, IS-6 enacted.
- SC-6 → 0 sites mutating segments directly from UI components.
- Phase 3 tests in `command/` flip green.

**Verification**: every command-test file passes; existing edit-flow integration paths (manual smoke) still work; dirty store still emits the same shape of operations.

### Phase 4 — Normalized State + UID Backfill

**Scope files**
- `inspector/domain/segment.py` (new — Python Segment dataclass)
- `inspector/domain/identity.py` (new — uid backfill)
- `inspector/adapters/detailed_json.py` (new)
- `inspector/adapters/segments_json.py` (new — extracted from `services/save.py:rebuild_segments_json`)
- `inspector/adapters/save_payload.py` (new)
- `inspector/services/save.py` (modify; uses adapters)
- `inspector/services/data_loader.py` (modify; calls uid backfill)
- `inspector/frontend/src/tabs/segments/domain/identity.ts` (new mirror)
- `inspector/frontend/src/tabs/segments/stores/segments.ts` (new — `SegmentState`)
- `inspector/frontend/src/tabs/segments/stores/chapter.ts` (modify — compat layer derives from segments.ts; `_byChapter` / `_byChapterIndex` retired)
- `inspector/frontend/src/tabs/segments/stores/filters.ts` (modify — `silence_after_ms` becomes derived, not in-place)
- `inspector/frontend/src/tabs/segments/utils/edit/*.ts` (modify — read from `segments.ts`, write via commands)
- `inspector/frontend/src/tabs/segments/domain/apply-command.ts` (modify — operates on `SegmentState`, returns nextState slice)

**What lands**
- Backend `Segment` dataclass: `segment_uid`, `chapter`, `index`, `time_start`, `time_end`, `matched_ref`, `matched_text`, `display_text`, `confidence`, `phonemes_asr`, `wrap_word_ranges`, `has_repeated_words`, `ignored_categories`, `entry_ref`, `audio_url`. Adapters convert to/from `detailed.json` and save payloads.
- Deterministic uid backfill: `uid = uuid5(NAMESPACE_INSPECTOR, f"{chapter}:{original_index}:{start_ms}")`. Stable across reload + save cycles.
- Frontend `SegmentState{byId: Record<uid, Segment>, idsByChapter: Record<chapter, uid[]>, selectedChapter: number | null}`.
- Compat selectors: `getChapterSegments(ch)`, `getSegByChapterIndex(ch, idx)`, `getAdjacentSegments(ch, idx)` — all become derived against `byId` + `idsByChapter`. Caches retired.
- `silence_after_ms` becomes a derived field in a separate store (`derivedTimings`), not a mutable field on Segment.
- `$segData` and `$segAllData` exported from `chapter.ts` are now derived stores. Subscriber contract preserved.

**Invariant impact**
- IS-7, IS-8 enacted.
- SC-7 → 0.
- MUST-4 verifiable.
- Phase 4 tests in `normalized-state/` and `persistence/test_uid_backfill.py` flip green.

**Cache interaction note (Plan-Review W-5)**: backend `services/cache.py` memoizes `load_detailed`. Phase 4's uid-backfill on load means the cached entry list now contains UIDs that the on-disk file does not (until next save). Phase 4 implementation must:
1. Confirm `cache.invalidate_seg_caches` is called whenever the cached entries are saved (so the next load re-reads from disk and observes the freshly-persisted UIDs).
2. Document via `test_uid_deterministic_across_processes` that two cold processes loading the same legacy fixture produce identical UIDs (deterministic backfill).

**Verification**: existing component tests pass unchanged; uid stability test passes; cache-repair sites grep returns 0.

### Phase 5 — Patch-Based Undo (Forward-Only)

**Scope files**
- `inspector/domain/command.py` (new — Python `SegmentPatch` shape, mirrors TS)
- `inspector/frontend/src/tabs/segments/domain/command.ts` (modify — `patch` field becomes required output of `applyCommand`)
- `inspector/frontend/src/tabs/segments/domain/apply-command.ts` (modify — fills `patch` for every command)
- `inspector/frontend/src/tabs/segments/utils/save/execute.ts` (modify — includes `patch` in op record sent to server)
- `inspector/services/save.py` (modify — persists `patch` field on history record op)
- `inspector/services/undo.py` (modify — applies inverse patch when present; falls back to legacy field-by-field undo for legacy records)
- `inspector/frontend/src/tabs/segments/utils/save/undo.ts` (modify — request shape unchanged; reconstruction reads new response if present)

**What lands**
- `SegmentPatch{before: Segment[], after: Segment[], removedIds: string[], insertedIds: string[], affectedChapterIds: number[]}`.
- Forward-only: pre-Phase-5 history batches lack `patch` field; `services/undo.py` keeps the existing field-restore path for those, uses inverse-patch for new ones. Detection: `if "patch" in op: apply_inverse_patch(...) else: legacy_field_restore(...)`.
- Test coverage: every command type produces a patch that round-trips through `applyInversePatch` to recover the pre-command state exactly.

**Invariant impact**
- IS-9 enacted.
- MUST-8 satisfied.
- Phase 5 tests in `undo/test_patch_undo.py` flip green.

**Verification**: `test_patch_undo.py` passes for every command; manual smoke: trigger an edit, save, undo, assert UI returns to pre-edit state including ignored_categories.

### Phase 6 — Stable Validation Issue Identity

**Scope files**
- `inspector/routes/segments_validation.py` (modify — embed `segment_uid` on every issue item; `seg_index` retained)
- `inspector/services/validation/detail.py` (modify — `_build_detail_lists` emits uid)
- `inspector/frontend/src/lib/types/api.ts` (modify — issue interfaces gain `segment_uid?: string`)
- `inspector/frontend/src/tabs/segments/utils/validation/resolve-issue.ts` (modify — uid-first resolution)
- `inspector/frontend/src/tabs/segments/utils/validation/stale.ts` (new — `filterStaleIssues(issues, state)`)
- `inspector/frontend/src/tabs/segments/utils/validation/fixups.ts` (DELETE — `_fixupValIndicesFor*` removed; index fixups no longer required since uid is stable through structural edits)
- All call sites of `_fixupValIndicesFor*` in edit utilities (split, merge, delete) — removed
- `inspector/frontend/src/tabs/segments/components/validation/ValidationPanel.svelte` (modify — uses `filterStaleIssues` before render)

**What lands**
- Validation DTO field addition.
- Resolution algorithm: try uid → return seg if found; else null (stale).
- Stale filter: drops items whose uid is not in current state. Optional UI: count "stale" badge could surface in accordion header.
- Fixups deleted; affected commands (split, merge, delete) no longer call them.

**Invariant impact**
- IS-10, IS-11 enacted.
- SC-8 → uid-based.
- Phase 6 tests in `identity/` flip green.

**Verification**: validation-identity tests pass; structural-edit smoke: split a segment with an active validation issue, assert issue resolves to the correct half (the one inheriting the uid).

---

## §2d Import/Export Strategy

### Phase 1
- `inspector/constants.py` re-exports from `inspector/services/validation/registry` for backward compat (until Phase 2 sweeps consumers).
- Frontend `utils/constants.ts` re-exports from `domain/registry.ts`.
- All consumers grep-confirmed; no orphan imports.

### Phase 2
- `inspector/services/validation/__init__.py` re-exports `classify_segment` (canonical name) and a deprecation alias `_classify_segment` (private name retained for one phase).
- `validators/validate_segments.py` adds `from inspector.services.validation import classify_segment, classify_snapshot, ISSUE_REGISTRY`. Sys-path manipulation may be needed depending on CLI invocation; verified during phase.
- Frontend `utils/validation/index.ts` removes `_classifySegCategories` export; consumers (`split.ts`, `merge.ts`, `validation/*`) updated.

### Phase 3
- `domain/command.ts` and `domain/apply-command.ts` are the new Phase 3 surface; existing `utils/edit/*` files become thin dispatchers and re-export their entrypoints unchanged.

### Phase 4
- `stores/segments.ts` is the new write seam. `stores/chapter.ts` continues to export `$segData`, `$segAllData`, `getChapterSegments`, etc., now as derived from `segments.ts`. No consumer needs to update import paths.
- Backend: `inspector/domain/segment.py` is the new write seam. `inspector/services/save.py` continues to export `save_seg_data`, etc., now using adapters internally. Routes don't change.

### Phase 5
- No new public exports; `applyCommand` already exports `CommandResult.patch` (added in Phase 3 stub, filled in Phase 5).
- `inspector/services/undo.py` keeps the same route surface.

### Phase 6
- `inspector/lib/types/api.ts` schema additive. `inspector/frontend/src/tabs/segments/utils/validation/fixups.ts` removed; consumers grep-confirmed.

---

## §2e Phase Sizing

| Phase | Files touched | LOC churn | Risk | Behavior surface | Wall-clock est |
|---|---|---|---|---|---|
| 0 | ~50 (test files + fixtures, all new) | ~1500 | low | pure additions | 25 min |
| 1 | ~12 | ~400 | low | content edits, preserve semantics | 35 min |
| 2 | ~17 (added stores/dirty.ts + history components per Plan-Review C-1) | ~550 (heavy deletes from CLI + frontend classifier; net: −300) | high | judgment calls expected | 55 min |
| 3 | ~13 (added MissingWordsCard.svelte per Plan-Review W-3) | ~520 | high | judgment calls expected | 60 min |
| 4 | ~14 | ~600 (new domain modules + adapter extraction) | medium | content edits + structural moves | 50 min |
| 5 | ~7 | ~250 | medium | content edits, preserve undo correctness | 35 min |
| 6 | ~10 (path correction surfaced edit utility call sites: split/merge/delete remove fixup calls) | ~200 (deletes ≥ adds) | low | content edits | 30 min |

**Split criteria** (per-phase): if implementation agent exceeds ~25 files, ~400 LOC churn in a single file, or projects ~45 minutes wall-clock, split. Phase 3 and Phase 4 are the most likely to split — the orchestrator re-estimates at §4a-pre.

---

## §2f Review Allocation

| Phase | Sonnet (quality) | Haiku (coverage) | Opus (verification) | Rationale |
|---|---|---|---|---|
| 0 | ✓ | ✓ | — | Test code; coverage check confirms every test file lists xfails consistently with plan. |
| 1 | ✓ | — | — | Mechanical-ish: extract registry, replace literal lists. Sonnet catches duplication. |
| 2 | ✓ | ✓ | ✓ | Logic preservation across 3 stacks. Opus reads diffs of every classifier rule against the source. Haiku verifies no consumer left unmigrated. |
| 3 | ✓ | — | ✓ | Command-layer migration touches semantics (auto-suppress, ordering, mountId). Opus verifies no regression in op-log shape. |
| 4 | ✓ | ✓ | — | Large file count (~14); Haiku catches missed consumers. Sonnet quality on derived-store patterns. Compat-shim makes logic risk lower. |
| 5 | ✓ | — | ✓ | Undo correctness is the risk. Opus verifies inverse patch covers all field types. |
| 6 | ✓ | — | ✓ | DTO change is cross-stack; Opus verifies stale-filter doesn't drop legitimate issues. |

---

## §2g Shared Document — Bug Log

**Path**: `.refactor/bug-log.md`
**ID prefix**: `B`
**Reason**: Phase 2 reconciles 3 classifiers with documented divergence (5+ items in SC-1) and likely-undocumented divergence. Append-only log captures any case where the chosen tie-breaker produces unexpected behavior, plus any data-shape surprises (e.g., `has_repeated_words` segments, malformed `ignored_categories` markers).

**Format** (per `references/shared-documents.md`):

```markdown
## B<id> — <short title>

**Surfaced in:** Phase N
**Status:** OPEN | RESOLVED-fix-<sha> | DEFERRED

**Symptom**
<what the orchestrator or agent saw>

**Root cause**
<analysis>

**Fix**
<what was done; references commit sha>

**Test coverage**
<test file:case that prevents regression>
```

Seeded entries from exploration:
- `B-1` (Phase 2): Frontend `_classifySegCategories` checks `has_repeated_words || wrap_word_ranges`; backend + CLI check `wrap_word_ranges` only. Tie-breaker: backend wins. If production fixtures contain `has_repeated_words=true` without `wrap_word_ranges`, those segments lose `repetitions` classification post-Phase-2. Mitigation: data audit in Phase 2 implementation prompt.
- `B-2` (Phase 2): `boundary_adj` phoneme tail check is backend-only (CLI + frontend skip). Tie-breaker: backend wins (additional check is opt-in via `canonical` parameter). No behavioral change for callers without canonical phonemes.
- `B-3` (Phase 2): `audio_bleeding` algorithm differs across 3 stacks. Tie-breaker: backend's `seg_belongs_to_entry` (most precise; reads `entry_ref` parsed structure).

The bug log is appended by implementation agents and reviewers. Pre-phase check (§4a-pre) verifies no unsubstituted fix-SHA placeholders in Section 5.

---

## §2h Pre-flight Automations

Drafted in `.refactor/checks.sh` (created at Phase 0 commit). Phase handoffs append new checks.

```bash
#!/usr/bin/env bash
# .refactor/checks.sh — pre-phase automation

set -e

# 1. Plan paths still valid: every scope_files entry exists
python3 -c "import yaml, sys, pathlib; \
  plan = yaml.safe_load(open('.refactor/plan.yaml')); \
  missing = [f for ph in plan['phases'] for f in (ph.get('scope_files') or []) if not pathlib.Path(f).exists() and not f.endswith('(new)')]; \
  print('STALE PATHS:', missing) if missing else print('paths ok')"

# 2. Backend test collection (no execution; just collection sanity)
pytest --collect-only inspector/tests/ -q | tail -3

# 3. Frontend test collection
(cd inspector/frontend && npx vitest --reporter=basic --run --no-coverage 2>&1 | tail -5) || true

# 4. Bug log placeholder check
grep -n "_(this commit's SHA)_" .refactor/bug-log.md && echo "UNRESOLVED PLACEHOLDERS" || echo "bug-log clean"

# 5. xfail count by phase (sanity: should decrease monotonically as phases complete)
echo "xfail count by phase reason:"
grep -rh 'xfail.*reason="phase-' inspector/tests/ inspector/frontend/src/**/__tests__/ 2>/dev/null \
  | sed -E 's/.*reason="(phase-[0-9]+)".*/\1/' | sort | uniq -c

# 6. Plan vs sidecar sync
python3 -c "import yaml; \
  plan = yaml.safe_load(open('.refactor/plan.yaml')); \
  md = open('.refactor/plan.md').read(); \
  for ph in plan['phases']: \
      assert f'### Phase {ph[\"id\"]}' in md, f'Phase {ph[\"id\"]} in YAML not in MD'; \
  print('plan/sidecar in sync')"
```

---

## §2i Stop-points

| Stop | Trigger | Action | What to check / decide |
|---|---|---|---|
| **S1** | After Phase 0 lands (test suite committed, fixtures in place) | pause | User reviews test inventory, confirms target behavior matches intent, approves Phase 1 dispatch. |
| S2 | Context-window ≥ 75% utilization | pause + cold-start handoff | Default systemic. |
| S3 | Review disagreement orchestrator can't reconcile | pause | Default systemic. |
| S4 | Plan deviation: implementation agent edits files outside `scope_files` | pause | Default systemic. |
| S5 | Unexpected logic edit on a "mechanical" phase | pause | Default systemic. |
| S6 | Cumulative token budget exceeded — currently no budget declared | n/a | Not active for this refactor. |
| **S7** | Pre-merge after Stage 5 | manual smoke-test | Always active. User exercises every accordion category, every edit op from main + accordion, save + reload + undo, then merges. |

**No per-phase pauses requested** beyond S1. User chose mode 4c (autonomous through phases) per Stage 0 Q4.

---

## §2j Plan Sidecar

See [`.refactor/plan.yaml`](plan.yaml).

---

## §2k Test Inventory

See [`.refactor/test-inventory.md`](test-inventory.md) — file-by-file test cases with xfail/phase markers.

---

## Appendix A — Locked Issue Policy Matrix

| Category | canIgnore | autoSuppress | persistsIgnore | scope | card_type | severity |
|---|---|---|---|---|---|---|
| failed | N | Y | N | per_segment | generic | error |
| missing_verses | N | Y | N | per_verse | missingVerses | error |
| missing_words | N | N | N | per_verse | missingWords | error |
| structural_errors | N | Y | N | per_chapter | error | error |
| low_confidence | Y | Y | Y | per_segment | generic | warning |
| repetitions | Y | Y | Y | per_segment | generic | warning |
| audio_bleeding | Y | Y | Y | per_segment | generic | warning |
| boundary_adj | Y | Y | Y | per_segment | generic | warning |
| cross_verse | Y | Y | Y | per_segment | generic | warning |
| qalqala | Y | Y | Y | per_segment | generic | info |
| muqattaat | N | N | N | per_segment | generic | info |

Notes:
- `failed` is `scope=per_segment` (a segment without a `matched_ref` is the unit of failure); it writes to `seg.ignored_categories` like any per-segment category when `autoSuppress` fires.
- For `scope=per_verse` and `scope=per_chapter` categories (`missing_verses`, `missing_words`, `structural_errors`): the `autoSuppress` flag is **a no-op for persistence**. There is no per-verse `ignored_categories` field, no session flag, no special target. User edits from the card → save → backend re-validates → the issue is either gone (because the edit addressed it) or still present (because it didn't). The `autoSuppress=Y` value on these rows is purely declarative: it says "edits launched from this card are intent-fixing edits, not unrelated work" — but since revalidation is the source of truth, no suppression is recorded anywhere. Test coverage for these rows asserts that no `ignored_categories` write happens (a negative assertion).
- The matrix in this appendix is the source of truth for `test_registry_policy.py`.

---

## Appendix B — Open Design Questions (resolved during implementation)

| Q | Phase | Notes |
|---|---|---|
| OQ-1 | 1 | TS registry mirror: hand-written initially. If drift surfaces during Phase 2 parity tests, introduce codegen from Python registry to TS. |
| OQ-2 | 2 | Frontend snapshot classifier (`_classifySnapIssues` in history-delta path): keep until Phase 5 makes patches authoritative, then remove. |
| OQ-3 | 4 | `silence_after_ms` derivation cost: if recomputing on every state change is too slow on large chapters, memoize per chapter. Benchmark in Phase 4. |
| OQ-4 | 5 | Op-record disk size growth from embedded patches. If disk usage becomes a concern, gzip the patch field. Defer to post-refactor. |
| OQ-5 | 6 | Stale-issue UI: silent filter vs visible "N stale issues" badge. Default: silent filter. Reconsider post-merge if users want visibility. |
