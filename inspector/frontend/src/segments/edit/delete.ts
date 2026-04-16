/**
 * Delete segment operation.
 */

import { getChapterSegments } from '../../lib/stores/segments/chapter';
import { clearEdit, setEdit } from '../../lib/stores/segments/edit';
import { formatRef as _formatRefLib } from '../../lib/utils/segments/references';
import type { Segment } from '../../types/domain';
import { applyVerseFilterAndRender,computeSilenceAfter } from '../filters';
import { createOp, dom, finalizeOp, markDirty,snapshotSeg, state } from '../state';

function _vwc() {
    return state.segAllData?.verse_word_counts ?? state.segData?.verse_word_counts;
}
function formatRef(ref: Parameters<typeof _formatRefLib>[0]) { return _formatRefLib(ref, _vwc()); }
import { _fixupValIndicesForDelete, refreshOpenAccordionCards } from '../../lib/utils/segments/validation-fixups';

// ---------------------------------------------------------------------------
// deleteSegment -- remove a segment and reindex
// ---------------------------------------------------------------------------
//
// B02 fix: both branches (current-chapter display cache AND all-data) now go
// through the same splice+reindex path against `segAllData.segments`, then
// `segData.segments` is refreshed from the re-indexed `segAllData` via
// `getChapterSegments(chapter)`. Previously the current-chapter branch
// re-indexed `segData` and synced back to `segAllData`, while the other
// branch re-indexed `segAllData` directly — the two paths could persist
// mismatched chapter indices. Unifying on `segAllData` as the single source
// of truth keeps both caches consistent regardless of which chapter is
// currently displayed.

export function deleteSegment(seg: Segment, row: HTMLElement, contextCategory: string | null = null): void {
    void row;
    const chapter = seg.chapter || parseInt(dom.segChapterSelect.value);
    const currentChapter = parseInt(dom.segChapterSelect.value);
    const label = seg.chapter ? `${seg.chapter}:#${seg.index}` : `#${seg.index}`;

    const deleteOp = createOp('delete_segment', contextCategory ? { contextCategory } : undefined);
    deleteOp.targets_before = [snapshotSeg(seg)];

    if (!confirm(`Delete segment ${label} (${formatRef(seg.matched_ref) || 'no match'})?`)) return;

    // Signal delete mode to EditOverlay (confirmed — committed to executing).
    setEdit('delete', seg.segment_uid ?? null);

    deleteOp.applied_at_utc = new Date().toISOString();
    deleteOp.targets_after = [];

    // Unified splice+reindex against segAllData (single source of truth).
    if (!state.segAllData?.segments) { clearEdit(); return; }
    const globalIdx = state.segAllData.segments.findIndex(s => s.chapter === chapter && s.index === seg.index);
    if (globalIdx === -1) { clearEdit(); return; }
    state.segAllData.segments.splice(globalIdx, 1);
    let idx = 0;
    state.segAllData.segments.forEach(s => { if (s.chapter === chapter) s.index = idx++; });
    state.segAllData._byChapter = null;
    state.segAllData._byChapterIndex = null;

    // Refresh segData.segments from the re-indexed segAllData whenever the
    // delete happened in the currently-displayed chapter.
    if (chapter === currentChapter && state.segData) {
        state.segData.segments = getChapterSegments(chapter);
    }

    markDirty(chapter, undefined, true);
    _fixupValIndicesForDelete(chapter, seg.index);

    computeSilenceAfter();
    applyVerseFilterAndRender();
    refreshOpenAccordionCards();

    finalizeOp(chapter, deleteOp);
    clearEdit();
    dom.segPlayStatus.textContent = 'Segment deleted (unsaved)';
}
