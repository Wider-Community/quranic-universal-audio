/**
 * Delete segment operation.
 *
 * Both branches (current-chapter display cache AND all-data) go through the
 * same splice+reindex path against `segAllData.segments`, then
 * `segData.segments` is refreshed from the re-indexed `segAllData` via
 * `getChapterSegments(chapter)`. Unifying on `segAllData` as the single
 * source of truth keeps both caches consistent regardless of which chapter
 * is currently displayed.
 */

import { get } from 'svelte/store';

import {
    getChapterSegments,
    segAllData,
    segData,
    selectedChapter,
} from '../../stores/segments/chapter';
import {
    createOp,
    markDirty,
    snapshotSeg,
} from '../../stores/segments/dirty';
import { clearEdit, setEdit } from '../../stores/segments/edit';
import type { Segment } from '../../types/domain';
import { finalizeEdit } from './edit-common';
import { formatRef as _formatRefLib, getVerseWordCounts } from './references';
import { _fixupValIndicesForDelete } from './validation-fixups';

function formatRef(ref: Parameters<typeof _formatRefLib>[0]): string {
    return _formatRefLib(ref, getVerseWordCounts());
}

// ---------------------------------------------------------------------------
// deleteSegment — remove a segment and reindex
// ---------------------------------------------------------------------------

export function deleteSegment(seg: Segment, row: HTMLElement, contextCategory: string | null = null): void {
    void row;
    const chStr = get(selectedChapter);
    const chapter = seg.chapter || parseInt(chStr);
    const currentChapter = parseInt(chStr);
    const label = seg.chapter ? `${seg.chapter}:#${seg.index}` : `#${seg.index}`;

    const deleteOp = createOp('delete_segment', contextCategory ? { contextCategory } : undefined);
    deleteOp.targets_before = [snapshotSeg(seg)];

    if (!confirm(`Delete segment ${label} (${formatRef(seg.matched_ref) || 'no match'})?`)) return;

    // Signal delete mode to EditOverlay (confirmed — committed to executing).
    setEdit('delete', seg.segment_uid ?? null);

    // Unified splice+reindex against segAllData (single source of truth).
    const allData = get(segAllData);
    if (!allData?.segments) { clearEdit(); return; }
    const globalIdx = allData.segments.findIndex(s => s.chapter === chapter && s.index === seg.index);
    if (globalIdx === -1) { clearEdit(); return; }
    allData.segments.splice(globalIdx, 1);
    let idx = 0;
    allData.segments.forEach(s => { if (s.chapter === chapter) s.index = idx++; });
    allData._byChapter = null;
    allData._byChapterIndex = null;

    // Refresh segData.segments from the re-indexed segAllData whenever the
    // delete happened in the currently-displayed chapter.
    const curData = get(segData);
    if (chapter === currentChapter && curData) {
        curData.segments = getChapterSegments(chapter);
    }

    markDirty(chapter, undefined, true);
    _fixupValIndicesForDelete(chapter, seg.index);

    finalizeEdit(deleteOp, chapter, [], 'Segment deleted (unsaved)');
    clearEdit();
}
