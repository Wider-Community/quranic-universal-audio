/**
 * Segments tab — edit mode store.
 *
 * All eight edit fields (mode, segUid, mountId, segIndex, canvas, trimWindow,
 * splitState, statusText) are bundled into a single `_editState` writable
 * store and published atomically. Individual readers consume equality-gated
 * derived stores (`derivedEq`) so a write that changes only one field does
 * NOT fan out to subscribers of the other seven — critical when hundreds of
 * SegmentRows subscribe to `$editMode` and `$editingSegUid`.
 *
 * Writers call the dedicated setter functions (setMode, setEditingSegIndex,
 * etc.) which route through a single `_editState.update(...)`. The `setEdit`
 * and `clearEdit` convenience setters batch multiple fields into one update.
 *
 * Drag state stays component-local (transient UI state via plain `let`);
 * per-frame canvas overlay state lives on the SegCanvas extension fields
 * (no DOM-element caches in stores).
 *
 * Modes:
 *   - 'trim'      — persistent drag (boundary handles); backdrop shown.
 *   - 'split'     — persistent drag (split handle); backdrop shown.
 *   - 'merge'     — one-shot async; no backdrop.
 *   - 'delete'    — one-shot async; no backdrop.
 *   - 'reference' — inline input on the row; no backdrop.
 *
 * The `.seg-edit-target` class is driven by SegmentRow reactively from
 * `editingSegUid === seg.segment_uid`; edit utilities never touch
 * `classList` directly.
 */

import { writable } from 'svelte/store';

import type { Segment } from '../../../lib/types/domain';
import { derivedEq } from '../../../lib/utils/derived-eq';
import type { SegCanvas, SplitData, TrimWindow } from '../types/segments-waveform';

/** Edit modes supported by the Segments tab. Only trim + split show the
 *  `.seg-edit-overlay` backdrop in EditOverlay.svelte — merge/delete are
 *  one-shot and reference editing is inline on the row. */
export type SegEditMode = 'trim' | 'split' | 'merge' | 'delete' | 'reference' | null;

// ---------------------------------------------------------------------------
// Unified state — single writable, atomic publish
// ---------------------------------------------------------------------------

interface EditState {
    mode: SegEditMode;
    segUid: string | null;
    mountId: symbol | null;
    segIndex: number;
    canvas: SegCanvas | null;
    trimWindow: TrimWindow | null;
    splitState: SplitData | null;
    statusText: string;
}

const _INITIAL_STATE: EditState = {
    mode: null,
    segUid: null,
    mountId: null,
    segIndex: -1,
    canvas: null,
    trimWindow: null,
    splitState: null,
    statusText: '',
};

const _editState = writable<EditState>({ ..._INITIAL_STATE });

// ---------------------------------------------------------------------------
// Per-field readable views — equality-gated so unchanged fields don't fan out
// ---------------------------------------------------------------------------

/** Active edit mode for the segments tab. `null` = no edit in progress. */
export const editMode = derivedEq(_editState, ($s) => $s.mode);

/** UID of the segment currently being edited. `null` = no edit in progress.
 *  Stored as the segment's UID rather than its index so split-induced
 *  reindexing doesn't lose track of the row mid-flow. */
export const editingSegUid = derivedEq(_editState, ($s) => $s.segUid);

/** Per-mount identifier of the SegmentRow instance that initiated the
 *  currently-active edit. Disambiguates twin rows (main-list vs accordion)
 *  mounted for the same segment_uid so only the row the user actually
 *  clicked shows trim/split/reference panels and publishes `editCanvas`.
 *
 *  When an edit is initiated programmatically (post-split chain handoff,
 *  auto-fix, keyboard shortcut), `editingMountId` is left `null` so the
 *  natural owner — the main-list instance — claims the session via its
 *  `instanceRole === 'main'` gate. SegmentRow's reactives must therefore
 *  accept EITHER `editingMountId === _mountId` OR
 *  `editingMountId === null && instanceRole === 'main'`. */
export const editingMountId = derivedEq(_editState, ($s) => $s.mountId);

/** Primary index (position in the displayed list) of the segment currently
 *  being edited. Written alongside `editingSegUid` in enter-edit flows. */
export const editingSegIndex = derivedEq(_editState, ($s) => $s.segIndex);

/** Canvas element of the segment row currently in edit mode. Published by
 *  SegmentRow.svelte when `$editingSegUid === seg.segment_uid`, cleared when
 *  the row stops being the edit target. Replaces the legacy `_getEditCanvas`
 *  DOM query (`document.querySelector('.seg-row.seg-edit-target canvas')`).
 *  Edit utilities (trim/split/play-range) read this to locate the canvas
 *  without a document-wide lookup. */
export const editCanvas = derivedEq(_editState, ($s) => $s.canvas);

/** Trim-mode window state — mirror of `canvas._trimWindow` so TrimPanel.svelte
 *  can render the duration/handles reactively. Drag handlers write to both the
 *  canvas field (for the draw pipeline) and this store (for Svelte). `null` =
 *  not in trim mode. */
export const trimWindow = derivedEq(_editState, ($s) => $s.trimWindow);

/** Split-mode state — mirror of `canvas._splitData` so SplitPanel.svelte can
 *  render the L/R duration reactively. `null` = not in split mode. */
export const splitState = derivedEq(_editState, ($s) => $s.splitState);

/** Short status text shown in trim/split panels (e.g. 'Invalid time range',
 *  'Start overlaps with previous segment'). Cleared on panel mount. */
export const editStatusText = derivedEq(_editState, ($s) => $s.statusText);

// ---------------------------------------------------------------------------
// Pending split-chain target — standalone writable (not part of edit state).
// ---------------------------------------------------------------------------

/** Pending split-chain target — stashed by `confirmSplit` after kicking off
 *  the first half's ref-edit, so that `commitRefEdit` can hand off directly to
 *  the second half without any reactive-store intermediary. The consumer
 *  (`commitRefEdit` success path) reads-and-clears; cancel/Escape paths call
 *  `pendingChainTarget.set(null)` to abort the chain.
 *
 *  Direct handoff replaces the prior reactive two-store chain pattern —
 *  eliminates a subscriber race where the secondHalf's SegmentRow would
 *  sometimes observe the chain store settling before `$editMode` dropped to
 *  null, dropping the chained edit entirely. */
export const pendingChainTarget = writable<{ seg: Segment; category: string | null } | null>(null);

// ---------------------------------------------------------------------------
// Setters — all writes route through a single `_editState.update(...)`.
// ---------------------------------------------------------------------------

/** Reset the edit store to the "no edit in progress" baseline. Called by
 *  exitEditMode() / cancel paths. All 8 fields published in ONE store write
 *  — the prior implementation called `.set()` on 8 separate writables,
 *  fanning out to every subscriber 8x per clearEdit. */
export function clearEdit(): void {
    _editState.set({ ..._INITIAL_STATE });
}

/** Convenience setter — call when entering any edit mode. The optional
 *  `mountId` pins the initiating SegmentRow instance so its twins stay
 *  passive; omit (or pass `null`) for programmatic entries that should
 *  route to the main-list instance. Publishes mode/segUid/mountId in one
 *  atomic update (previously three sequential .set() calls). */
export function setEdit(
    mode: Exclude<SegEditMode, null>,
    segUid: string | null,
    mountId: symbol | null = null,
): void {
    _editState.update((s) => ({ ...s, mode, segUid, mountId }));
}

/** Write `editingSegIndex`. Kept as a standalone setter because the three
 *  enter-edit call sites (trim / split / reference) set it just after
 *  `setEdit` — rolling it in would require a bigger setEdit signature. */
export function setEditingSegIndex(index: number): void {
    _editState.update((s) => (s.segIndex === index ? s : { ...s, segIndex: index }));
}

/** Write `editCanvas`. SegmentRow publishes when it becomes the edit target;
 *  exitEditMode / clearEdit clear it. Identity gate: skip if already set to
 *  the same canvas (common during reactive re-runs). */
export function setEditCanvas(canvas: SegCanvas | null): void {
    _editState.update((s) => (s.canvas === canvas ? s : { ...s, canvas }));
}

/** Write `trimWindow`. Called by enterTrimMode (fresh window) and during
 *  drag (drag handler produces a new window object each mousemove). */
export function setTrimWindow(tw: TrimWindow | null): void {
    _editState.update((s) => ({ ...s, trimWindow: tw }));
}

/** Update `trimWindow` in place — mirrors `writable.update` but routes
 *  through the unified state. */
export function updateTrimWindow(fn: (tw: TrimWindow | null) => TrimWindow | null): void {
    _editState.update((s) => ({ ...s, trimWindow: fn(s.trimWindow) }));
}

/** Write `splitState`. Called by enterSplitMode (fresh data) and during
 *  drag. */
export function setSplitState(sd: SplitData | null): void {
    _editState.update((s) => ({ ...s, splitState: sd }));
}

/** Update `splitState` in place. */
export function updateSplitState(fn: (sd: SplitData | null) => SplitData | null): void {
    _editState.update((s) => ({ ...s, splitState: fn(s.splitState) }));
}

/** Write `editStatusText`. Skip update when the value is identical to avoid
 *  pointless fan-out (`editStatusText.set('')` is called on every enter and
 *  confirm, often when the text is already ''). */
export function setEditStatusText(text: string): void {
    _editState.update((s) => (s.statusText === text ? s : { ...s, statusText: text }));
}
