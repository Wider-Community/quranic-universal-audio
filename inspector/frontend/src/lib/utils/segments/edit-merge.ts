/**
 * Merge adjacent segments operation.
 */

import { get } from 'svelte/store';

import { fetchJson } from '../../api';
import {
    getChapterSegments,
    segAllData,
    segData,
    selectedChapter,
    syncChapterSegsToAll,
} from '../../stores/segments/chapter';
import {
    createOp,
    markDirty,
    snapshotSeg,
} from '../../stores/segments/dirty';
import {
    accordionOpCtx,
    clearEdit,
    setEdit,
} from '../../stores/segments/edit';
import type { SegResolveRefResponse } from '../../types/api';
import type { Segment } from '../../types/domain';
import { finalizeEdit } from './edit-common';
import { _fixupValIndicesForMerge } from './validation-fixups';

// ---------------------------------------------------------------------------
// mergeAdjacent — combine two adjacent segments
// ---------------------------------------------------------------------------

export async function mergeAdjacent(
    seg: Segment,
    direction: 'prev' | 'next',
    contextCategory: string | null = null,
): Promise<void> {
    const chStr = get(selectedChapter);
    const chapter = seg.chapter || parseInt(chStr);
    const currentChapter = parseInt(chStr);
    const curData = get(segData);
    const allData = get(segAllData);

    let chapterSegs: Segment[] | undefined;
    if (chapter === currentChapter && curData?.segments) {
        chapterSegs = curData.segments;
    } else if (allData?.segments) {
        chapterSegs = getChapterSegments(chapter);
    }
    if (!chapterSegs) return;

    const idx = chapterSegs.findIndex(s => s.index === seg.index);
    if (idx === -1) return;
    const otherIdx = direction === 'prev' ? idx - 1 : idx + 1;
    if (otherIdx < 0 || otherIdx >= chapterSegs.length) return;
    const other = chapterSegs[otherIdx];
    if (!other) return;

    const first = direction === 'prev' ? other : seg;
    const second = direction === 'prev' ? seg : other;

    // Signal merge mode to EditOverlay (and future MergePanel) only after all
    // pure guard checks pass, so the store only reflects merge while we're
    // actually committed to executing.
    setEdit('merge', seg.segment_uid ?? null);

    const mergeOp = createOp('merge_segments', contextCategory ? { contextCategory } : undefined);
    mergeOp.merge_direction = direction;
    mergeOp.targets_before = [snapshotSeg(first), snapshotSeg(second)];

    const firstAudio = first.audio_url || '';
    const secondAudio = second.audio_url || '';
    if (firstAudio !== secondAudio) { clearEdit(); return; }

    let mergedRef = '';
    const refs = [first.matched_ref, second.matched_ref].filter(Boolean);
    if (refs.length > 0) {
        const firstRef = refs[0]!;
        const lastRef = refs[refs.length - 1]!;
        const s = firstRef.includes('-') ? firstRef.split('-')[0] : firstRef;
        const e = lastRef.includes('-') ? lastRef.split('-')[1] : lastRef;
        mergedRef = `${s}-${e}`;
    }

    let mergedText = [first.matched_text, second.matched_text].filter(Boolean).join(' ');
    let mergedDisplay = [first.display_text, second.display_text].filter(Boolean).join(' ');
    if (mergedRef) {
        try {
            const data = await fetchJson<SegResolveRefResponse>(
                `/api/seg/resolve_ref?ref=${encodeURIComponent(mergedRef)}`,
            );
            if (data.text) {
                mergedText = data.text;
                mergedDisplay = data.display_text || data.text;
            }
        } catch (e) {
            console.warn('Failed to resolve merged ref, using concatenated text:', e);
        }
    }

    const merged: Segment = {
        ...first,
        segment_uid: crypto.randomUUID(),
        index: first.index,
        time_start: first.time_start,
        time_end: second.time_end,
        matched_ref: mergedRef,
        matched_text: mergedText,
        display_text: mergedDisplay,
        confidence: 1.0,
    };
    const mergedIc = new Set<string>([
        ...(first.ignored_categories || []),
        ...(second.ignored_categories || []),
    ]);
    if (contextCategory) mergedIc.add(contextCategory);
    if (mergedIc.size) merged.ignored_categories = [...mergedIc];

    const keptOldIdx = first.index;
    const consumedOldIdx = second.index;

    if (chapter === currentChapter && curData?.segments) {
        const spliceIdx = Math.min(idx, otherIdx);
        curData.segments.splice(spliceIdx, 2, merged);
        curData.segments.forEach((s, i) => { s.index = i; });
        syncChapterSegsToAll();
    } else if (allData?.segments) {
        const globalFirst = allData.segments.indexOf(first);
        const globalSecond = allData.segments.indexOf(second);
        const spliceStart = Math.min(globalFirst, globalSecond);
        allData.segments.splice(spliceStart, 2, merged);
        let reIdx = 0;
        allData.segments.forEach(s => { if (s.chapter === chapter) s.index = reIdx++; });
        allData._byChapter = null; allData._byChapterIndex = null;
    }

    markDirty(chapter, undefined, true);
    _fixupValIndicesForMerge(chapter, keptOldIdx, consumedOldIdx);
    if (chapter === currentChapter && curData) {
        curData.segments = getChapterSegments(chapter);
    }
    accordionOpCtx.set(null);
    finalizeEdit(mergeOp, chapter, [merged], 'Segments merged (unsaved)');
    clearEdit();
}
