/**
 * Delete segment operation.
 */

import { state, dom, createOp, snapshotSeg, finalizeOp, markDirty } from './state.js';
import { formatRef } from './references.js';
import { getChapterSegments, syncChapterSegsToAll } from './data.js';
import { computeSilenceAfter, applyVerseFilterAndRender } from './filters.js';
import { _fixupValIndicesForDelete, refreshOpenAccordionCards } from './validation.js';

// ---------------------------------------------------------------------------
// deleteSegment -- remove a segment and reindex
// ---------------------------------------------------------------------------

export function deleteSegment(seg, row, contextCategory = null) {
    const chapter = seg.chapter || parseInt(dom.segChapterSelect.value);
    const currentChapter = parseInt(dom.segChapterSelect.value);
    const label = seg.chapter ? `${seg.chapter}:#${seg.index}` : `#${seg.index}`;

    const deleteOp = createOp('delete_segment', contextCategory ? { contextCategory } : undefined);
    deleteOp.targets_before = [snapshotSeg(seg)];

    if (!confirm(`Delete segment ${label} (${formatRef(seg.matched_ref) || 'no match'})?`)) return;

    deleteOp.applied_at_utc = new Date().toISOString();
    deleteOp.targets_after = [];

    if (chapter === currentChapter && state.segData?.segments) {
        const segIdx = state.segData.segments.findIndex(s => s.index === seg.index);
        if (segIdx === -1) return;
        state.segData.segments.splice(segIdx, 1);
        state.segData.segments.forEach((s, i) => { s.index = i; });
        syncChapterSegsToAll();
    } else if (state.segAllData?.segments) {
        const globalIdx = state.segAllData.segments.findIndex(s => s.chapter === chapter && s.index === seg.index);
        if (globalIdx === -1) return;
        state.segAllData.segments.splice(globalIdx, 1);
        let idx = 0;
        state.segAllData.segments.forEach(s => { if (s.chapter === chapter) s.index = idx++; });
        state.segAllData._byChapter = null; state.segAllData._byChapterIndex = null;
    }

    markDirty(chapter, undefined, true);
    _fixupValIndicesForDelete(chapter, seg.index);

    if (chapter === currentChapter && state.segData) {
        state.segData.segments = getChapterSegments(chapter);
    }

    computeSilenceAfter();
    applyVerseFilterAndRender();
    refreshOpenAccordionCards();

    finalizeOp(chapter, deleteOp);
    dom.segPlayStatus.textContent = 'Segment deleted (unsaved)';
}
