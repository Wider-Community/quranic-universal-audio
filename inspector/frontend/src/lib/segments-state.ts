/**
 * Segments tab — DOM-references singleton + the `markDirty` shim.
 *
 * All per-tab mutable state now lives in `lib/stores/segments/*` or as
 * module-locals in the owning utility files. This module keeps only:
 *  - `dom`: the narrow DOM-element reference object populated by
 *    SegmentsTab.svelte onMount.
 *  - `markDirty`: a shim that delegates to the dirty store and also
 *    enables the save button (the DOM side-effect the pure store cannot
 *    perform).
 *  - Re-exports of the dirty-store op helpers (`createOp`, `finalizeOp`,
 *    `snapshotSeg`, `isDirty`, `isIndexDirty`, `unmarkDirty`) so the
 *    existing `from '../../segments-state'` import sites keep compiling.
 *
 * DOM refs are typed as the narrow element interface and initialised to
 * `null as unknown as T`. SegmentsTab.svelte's onMount populates them
 * before any consumer runs. Fields that may legitimately be null at call
 * sites (optional widgets, post-cleanup state) are typed `T | null` and
 * callers null-check.
 */

import {
    createOp as _createOp,
    type CreateOpOptions,
    finalizeOp as _finalizeOp,
    isDirty,
    isIndexDirty,
    markDirty as _markDirty,
    type SegSnapshot,
    snapshotSeg,
    unmarkDirty,
} from './stores/segments/dirty';

// Re-export dirty store helpers so existing callers continue to work.
export { _createOp as createOp, _finalizeOp as finalizeOp, isDirty, isIndexDirty, snapshotSeg, unmarkDirty };
export type { CreateOpOptions, SegSnapshot };

// ---------------------------------------------------------------------------
// DOM references — set by SegmentsTab.svelte onMount
// ---------------------------------------------------------------------------

/**
 * Public shape of the segments tab DOM references.
 *
 * All fields are non-nullable and narrowed to their actual element type.
 * They are initialised to `null as unknown as T` below; SegmentsTab.svelte
 * populates them before any feature code runs. The alternative would be to
 * type each as `T | null` and null-check at every call site — that would
 * add noise to many modules for a guarantee already established by the
 * ordering of import-time registration vs onMount.
 */
export interface DomRefs {
    segReciterSelect: HTMLSelectElement;
    segChapterSelect: HTMLSelectElement;
    segVerseSelect: HTMLSelectElement;
    segListEl: HTMLDivElement;
    segAudioEl: HTMLAudioElement;
    segPlayBtn: HTMLButtonElement;
    segAutoPlayBtn: HTMLButtonElement;
    segSpeedSelect: HTMLSelectElement;
    segSaveBtn: HTMLButtonElement;
    segPlayStatus: HTMLElement;
    segValidationGlobalEl: HTMLDivElement;
    segValidationEl: HTMLDivElement;
    segFilterBarEl: HTMLDivElement;
    segFilterRowsEl: HTMLDivElement;
    segFilterAddBtn: HTMLButtonElement;
    segFilterClearBtn: HTMLButtonElement;
    segFilterCountEl: HTMLElement;
    segFilterStatusEl: HTMLElement;

    // History view (imperative: #seg-history-view container + external open button).
    // Panel interior is Svelte-owned by HistoryPanel.svelte.
    segHistoryView: HTMLDivElement;
    segHistoryBtn: HTMLButtonElement;

    // Save preview (container + action buttons; interior owned by SavePreview.svelte).
    segSavePreview: HTMLDivElement;
    segSavePreviewCancel: HTMLButtonElement;
    segSavePreviewConfirm: HTMLButtonElement;
}

// Sentinel for DOM ref seeding. `never` is assignable to every field type,
// so this satisfies `DomRefs` without writing `null as unknown as HTMLXxx` at
// every slot. Populated by `document.getElementById(...)` inside the
// SegmentsTab.svelte onMount handler before any consumer runs.
const _UNSET = null as unknown as never;

export const dom: DomRefs = {
    segReciterSelect: _UNSET,
    segChapterSelect: _UNSET,
    segVerseSelect: _UNSET,
    segListEl: _UNSET,
    segAudioEl: _UNSET,
    segPlayBtn: _UNSET,
    segAutoPlayBtn: _UNSET,
    segSpeedSelect: _UNSET,
    segSaveBtn: _UNSET,
    segPlayStatus: _UNSET,
    segValidationGlobalEl: _UNSET,
    segValidationEl: _UNSET,
    segFilterBarEl: _UNSET,
    segFilterRowsEl: _UNSET,
    segFilterAddBtn: _UNSET,
    segFilterClearBtn: _UNSET,
    segFilterCountEl: _UNSET,
    segFilterStatusEl: _UNSET,

    segHistoryView: _UNSET,
    segHistoryBtn: _UNSET,

    segSavePreview: _UNSET,
    segSavePreviewCancel: _UNSET,
    segSavePreviewConfirm: _UNSET,
};

// ---------------------------------------------------------------------------
// Dirty-state helpers
// ---------------------------------------------------------------------------

/**
 * markDirty shim — delegates to the dirty store and also enables the save
 * button (DOM side effect that the pure store cannot handle).
 */
export function markDirty(chapter: number, index?: number, structural = false): void {
    _markDirty(chapter, index, structural);
    dom.segSaveBtn.disabled = false;
}
