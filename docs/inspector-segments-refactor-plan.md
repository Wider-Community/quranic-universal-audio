# Inspector Segments Refactor Plan

## Purpose

The Segments inspector has accumulated several correctness bugs around validation
categories, ignore behavior, save previews, history, undo, and JSON persistence.
The recent ignore fixes exposed a broader design issue: behavior for one domain
concept is spread across many modules that each carry a partial version of the
rules.

This document explains the root causes, the main design smells, and a practical
refactor path that can make future changes safer and easier to scale.

## Current Problem

The Segments tab does not have a single authoritative model for a segment or for
a validation issue.

The same segment can exist as:

- a live object rendered in the row list
- a chapter slice in `segData`
- an all-chapters entry in `segAllData`
- a lazily cached lookup entry
- a validation response item from the backend
- a dirty-state snapshot
- a save-preview snapshot
- a history snapshot
- a persisted object in `detailed.json`
- a derived verse entry in `segments.json`

Each layer is allowed to interpret or mutate the segment slightly differently.
That makes simple changes fragile. For example, making a validation category
ignoreable required coordinated behavior in:

- frontend classification
- backend classification
- standalone validator output
- validation accordion rendering
- edit operation metadata
- split, trim, merge, and reference edit flows
- save payload serialization
- backend save persistence
- undo reconstruction
- history and save-preview deltas

When one of those paths is missed, the UI can look correct before save but drift
after refresh, history can tell a different story than the accordion, or undo can
restore only part of the previous state.

## Root Cause

The root cause is not the ignore feature itself. It is state and rule
fragmentation.

There are multiple sources of truth for:

- segment identity
- segment ordering
- validation issue classification
- issue suppression or ignore behavior
- edit operation side effects
- dirty-state tracking
- save payload shape
- undo semantics

The code often relies on local convention instead of central enforcement. A
module may know that editing from an accordion should suppress the current issue,
another module may know that `muqattaat` should be view-only, and another module
may know that empty `ignored_categories` means "clear persisted ignores". Those
rules are domain rules, but they are currently encoded in separate call sites.

## Design Smells

### Shared mutable state

Segment objects are mutated in place, then Svelte stores are manually nudged so
subscribers recompute. This creates hidden coupling between mutation sites and
rendering. If a mutation path forgets to republish or repair a cache, the UI can
show stale data.

Examples:

- `segAllData` contains mutable cache fields such as `_byChapter` and
  `_byChapterIndex`.
- Edit utilities mutate segment objects directly.
- Rendering depends on helper calls such as `applyFiltersAndRender()` to notify
  subscribers after in-place mutations.

### Cache invalidation as business logic

Chapter lookup caches are repaired manually after structural edits. This makes
the cache part of the domain workflow instead of an implementation detail.

Structural operations such as split, merge, delete, and trim need to know not
only how to change segments, but also which cache entries to invalidate or
rebuild.

### Duplicated classification rules

Validation category logic exists in multiple places:

- frontend classification for live snapshots and history deltas
- backend classification for inspector validation responses
- standalone validator classification for CLI reports

These implementations are similar but not guaranteed to remain identical. This
was the direct cause of ignore behavior diverging between categories.

### Stale validation snapshots

Validation accordion items are returned from the backend as snapshots. After a
local edit, those items may no longer match the live segment. The frontend then
needs resolution helpers to map stale validation items back to current segments.

That is a sign that validation items and editable segment state are not modeled
around the same identity and lifecycle.

### Shotgun surgery

A single domain change requires edits across many unrelated files. This is a
classic signal that a domain rule is missing a home.

Ignore behavior should be an issue policy. Instead it is partly implemented in
card UI, classifiers, edit utilities, save serializers, backend persistence, and
undo.

### Temporal coupling

Some flows depend on operations happening in a specific order:

- create operation
- snapshot before
- mutate segment
- update ignore markers
- snapshot after
- mark dirty
- refresh caches
- republish stores

The order matters, but it is not represented as one atomic domain operation.
That makes features easy to break when a new entrypoint is added.

### Comment-enforced invariants

Several comments explain hazards that the type system or domain layer should
make hard to violate. These comments are useful, but they also show that the
system relies on developer memory.

Examples include:

- which reference field is safe for display
- when a validation item is stale
- when an edit from an accordion should suppress a category
- which operations are structural
- when a cache must be rebuilt

### Mixed identity model

Different flows identify a segment by different values:

- `segment_uid`
- `chapter:index`
- array position
- validation `seg_index`
- matched reference
- entry audio URL

Some of these are stable identities and some are derived positions. Structural
edits change positions, which makes index-based logic fragile.

### UI owns domain behavior

Some Svelte components do more than render state. They also create operations,
mutate segment fields, apply ignore behavior, and mark dirty state. This makes
behavior depend on which UI path was used.

The same edit should have the same result whether it starts from the main list,
an accordion card, a keyboard shortcut, or an auto-fix flow.

## Anti-Patterns To Remove

### Local rule patches

Adding one more `if category !== "muqattaat"` at each call site fixes an
immediate bug, but it increases the chance of the next divergence. Category
policy should live in one registry.

### Parallel models with manual sync

Keeping `segData`, `segAllData`, validation snapshots, dirty snapshots, and
history snapshots independently meaningful forces the code to synchronize them
by hand. The system should prefer one authoritative write model and derived read
models.

### Ad hoc undo

Undo currently reconstructs previous state by branching on operation type and
manually restoring selected fields. This is brittle because every new field or
operation requires a matching undo update.

Undo should be generated from the same command semantics that apply the edit, or
from complete before/after patches.

### Persistence mixed with behavior

Save code currently knows field preservation rules, clearing semantics, full
replace behavior, patch behavior, history behavior, and JSON rebuild behavior.
These are related, but they should be separated into a persistence adapter around
a clearer domain model.

### Snapshot deltas as implicit validation

History and save preview infer resolved or introduced issues from snapshots.
That can be useful, but only if snapshots are produced by one authoritative
classifier. Otherwise history can drift from the validation panel.

## Target Architecture

The goal is not a big rewrite. The goal is to give each domain concept one home.

### 1. Normalized segment store

Use a normalized client-side state shape:

```ts
interface SegmentState {
  byId: Record<string, Segment>;
  idsByChapter: Record<number, string[]>;
  selectedChapter: number | null;
}
```

Guidelines:

- `segment_uid` should be the primary identity.
- Chapter lists should store ordered IDs, not segment object copies.
- Derived stores should compute visible rows, chapter rows, and adjacent rows.
- Structural edits should update `byId` and `idsByChapter` immutably.
- Caches should be private implementation details or replaced with derived
  indexes.

Benefits:

- fewer stale object references
- fewer manual store nudges
- simpler split and merge behavior
- safer virtualization and row identity
- clearer save payload generation

### 2. Central command layer for edits

Represent edits as domain commands:

```ts
type SegmentCommand =
  | { type: "trim"; segmentId: string; start: number; end: number; contextIssue?: IssueKind }
  | { type: "split"; segmentId: string; atMs: number; contextIssue?: IssueKind }
  | { type: "merge"; firstId: string; secondId: string; contextIssue?: IssueKind }
  | { type: "editReference"; segmentId: string; ref: string; contextIssue?: IssueKind }
  | { type: "ignoreIssue"; segmentId: string; issue: IssueKind };
```

Each command should be applied through one reducer-like function:

```ts
interface CommandResult {
  nextState: SegmentState;
  operation: EditOp;
  affectedChapters: number[];
  validationDelta?: IssueDelta;
}
```

The UI should dispatch commands. It should not directly mutate segment fields,
append ignore markers, or build partial operation logs.

Benefits:

- one path for main-list edits and accordion edits
- automatic dirty tracking from command results
- consistent operation snapshots
- easier undo and redo
- fewer entrypoint-specific bugs

### 3. Issue registry

Create a central registry for validation categories:

```ts
interface IssueDefinition {
  kind: IssueKind;
  title: string;
  card: "generic" | "missingWords" | "missingVerses" | "viewOnly";
  canIgnore: boolean;
  viewOnly: boolean;
  autoSuppressOnEdit: boolean;
  persistsIgnore: boolean;
  contributesToHistoryDelta: boolean;
}
```

Example policy:

```ts
const ISSUE_DEFINITIONS = {
  low_confidence: {
    canIgnore: true,
    viewOnly: false,
    autoSuppressOnEdit: true,
    persistsIgnore: true,
  },
  repetitions: {
    canIgnore: true,
    viewOnly: false,
    autoSuppressOnEdit: true,
    persistsIgnore: true,
  },
  audio_bleeding: {
    canIgnore: true,
    viewOnly: false,
    autoSuppressOnEdit: true,
    persistsIgnore: true,
  },
  muqattaat: {
    canIgnore: false,
    viewOnly: true,
    autoSuppressOnEdit: false,
    persistsIgnore: false,
  },
};
```

The registry should drive:

- accordion ordering
- card component selection
- whether the Ignore button appears
- whether edit-from-accordion auto-suppresses an issue
- whether save preview shows resolved or introduced pills
- whether a category is filterable in history
- whether persistence accepts ignore markers for that issue

Benefits:

- category behavior is auditable in one file
- adding a category becomes a registry change plus a classifier rule
- view-only categories cannot accidentally become ignoreable

### 4. Single classification source of truth

Choose one of these approaches.

Preferred: backend-owned validation.

- Backend classifies segments and returns typed issue DTOs.
- Frontend does not reimplement classification rules.
- Save preview/history can ask the backend or use classifier output stored in
  snapshots.
- Standalone validator imports the same Python classifier used by the backend.

Alternative: shared generated rules.

- Define issue metadata and thresholds in a neutral schema.
- Generate TypeScript and Python constants from that schema.
- Keep only small runtime-specific helpers in each language.

Avoid continuing with independent frontend, backend, and CLI classifiers.

### 5. Validation items reference live segment identity

Validation items should carry stable IDs:

```ts
interface SegmentIssue {
  issueId: string;
  segmentId: string | null;
  chapter: number;
  kind: IssueKind;
  severity: "info" | "warning" | "error";
  snapshot?: SegmentIssueSnapshot;
}
```

The accordion should render an issue by resolving `segmentId` against the
normalized segment store. If the segment no longer exists, the issue can be
marked stale or hidden intentionally.

Avoid using `seg_index` as the primary link after structural edits.

### 6. Persistence adapters

Create explicit adapters:

- `loadDetailedToDomain()`
- `domainToDetailedJson()`
- `domainToSegmentsJson()`
- `domainToSavePayload()`
- `historyRecordFromCommandResult()`

The adapters should not decide category behavior. They should serialize the
domain state and preserve only fields that the domain model owns.

Benefits:

- clearing `ignored_categories` becomes unambiguous
- `detailed.json` and `segments.json` behavior is documented in code
- history records are generated consistently

### 7. Patch-based undo

Undo should restore complete before/after patches rather than hand-selected
fields.

For each command, store:

```ts
interface SegmentPatch {
  before: Segment[];
  after: Segment[];
  removedIds: string[];
  insertedIds: string[];
  affectedChapterIds: number[];
}
```

Undo applies the inverse patch:

- remove inserted segments
- restore removed segments
- replace modified segments with complete `before` snapshots
- restore chapter ordering

This avoids missing fields such as `ignored_categories`, future metadata, or
category-specific state.

## Suggested Migration Plan

### Phase 1: Stabilize category policy

Create an issue registry and replace scattered category capability checks with
registry reads.

Scope:

- accordion category definitions
- generic issue card Ignore button visibility
- auto-suppress-on-edit checks in trim, split, merge, and reference edit flows
- history filter labels and save-preview labels

This is the smallest refactor with the highest immediate payoff because it
prevents another ignore-style divergence.

### Phase 2: Consolidate classifiers

Make the standalone validator import the backend classifier instead of carrying
its own copy. Then decide whether the frontend classifier should be removed or
limited to display-only fallback behavior.

Scope:

- move thresholds and category constants into one backend module
- make CLI validation call the same backend classification functions
- ensure history snapshots store classifier output from the same source

### Phase 3: Introduce command application

Add a command service for one operation first, preferably `ignoreIssue` because
it is small but touches UI, dirty state, save, history, and undo.

Then migrate:

1. reference edit
2. trim
3. split
4. merge
5. delete
6. auto-fix flows

Each migrated operation should stop mutating segments directly from UI
components.

### Phase 4: Normalize segment state

Introduce `SegmentState` while preserving the existing Svelte store API through
compatibility selectors.

Scope:

- store segments by `segment_uid`
- derive chapter segment arrays
- derive displayed/filter results
- replace manual chapter cache invalidation
- update edit utilities to use command results

This phase should be incremental. The first goal is to make new code use the
normalized state while older components continue to read derived arrays.

### Phase 5: Replace ad hoc undo

Once commands produce complete patches, update backend history records to store
enough information to reverse the patch generically.

Scope:

- full before/after snapshots for touched segments
- inserted and removed IDs
- affected chapter order before/after
- generic inverse patch application

### Phase 6: Make validation issue identity stable

Change validation responses so issue items reference `segment_uid` where
possible. Keep `seg_index` as display or fallback metadata, not as the primary
identity.

Scope:

- backend validation DTOs
- accordion resolution
- stale issue handling
- post-edit issue refresh behavior

## Testing Strategy

Add domain tests around invariants instead of only UI behavior.

Important cases:

- ignoring `low_confidence`, `repetitions`, or `audio_bleeding` hides the issue
  after save and validation refresh
- `muqattaat` never shows Ignore and is never auto-suppressed by accordion edits
- split from an accordion applies the same issue policy to both resulting
  segments
- clearing `ignored_categories` removes persisted ignore state
- undo restores all segment fields, including ignore markers
- history and save preview deltas match validation classifier output
- standalone validator and inspector backend report the same categories for the
  same detailed segment

Add regression fixtures that start from `detailed.json` snippets and assert the
full round trip:

```text
load detailed -> classify -> edit command -> save payload -> persist -> reload -> classify
```

This catches the class of bugs where pre-save UI and post-save validation behave
differently.

## Practical Design Rules Going Forward

- A category capability belongs in the issue registry, not in a component.
- A segment edit should go through a command, not direct object mutation.
- A validation issue should reference `segment_uid` whenever possible.
- A save serializer should serialize state, not infer business policy.
- Undo should restore complete domain snapshots or inverse patches.
- Derived views should be derived from the normalized store, not manually synced.
- Frontend, backend, and CLI validation must share one classifier or one
  generated rule source.

## Expected Outcome

After this refactor, adding or changing a validation category should usually
require:

1. adding or editing one issue definition
2. adding or editing one classifier rule
3. adding focused tests for that category

It should not require auditing every edit utility, save path, undo branch,
history component, and validator script by hand.

