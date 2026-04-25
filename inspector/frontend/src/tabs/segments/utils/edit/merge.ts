/**
 * Merge adjacent segments operation.
 */

import { get } from 'svelte/store';

import { fetchJson } from '../../../../lib/api';
import type { SegResolveRefResponse } from '../../../../lib/types/api';
import type { Segment } from '../../../../lib/types/domain';
import {
    getChapterSegments,
    invalidateChapterIndexFor,
    segAllData,
    segData,
    selectedChapter,
    syncChapterSegsToAll,
} from '../../stores/chapter';
import {
    createOp,
    markDirty,
    snapshotSeg,
} from '../../stores/dirty';
import {
    clearEdit,
    setEdit,
} from '../../stores/edit';
import { applyCommand } from '../../domain/apply-command';
import { clearFlashForChapter } from '../../stores/navigation';
import { reconcilePlayingAfterMutation } from '../playback/playback';
import { _fixupValIndicesForMerge } from '../validation/fixups';
import { finalizeEdit } from './common';

// ---------------------------------------------------------------------------
// mergeAdjacent — combine two adjacent segments
// ---------------------------------------------------------------------------

export async function mergeAdjacent(
    seg: Segment,
    direction: 'prev' | 'next',
    contextCategory: string | null = null,
    mountId: symbol | null = null,
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
    // actually committed to executing. `mountId` pins the initiating row
    // so accordion twins stay passive; omit (null) for programmatic calls.
    setEdit('merge', seg.segment_uid ?? null, mountId);

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

    // UID preservation: the merged seg inherits `first`'s UID so the row-registry
    // entry and accordion twins that were bound to first stay bound. The
    // consumed side's UID is simply dropped.
    const merged: Segment = {
        ...first,
        segment_uid: first.segment_uid,
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
    if (mergedIc.size) merged.ignored_categories = [...mergedIc];
    if (contextCategory && merged.segment_uid) {
        // Defer the auto-suppress decision to the registry-driven reducer.
        const r = applyCommand(
            {
                byId: { [merged.segment_uid]: merged },
                idsByChapter: { [chapter]: [merged.segment_uid] },
                selectedChapter: chapter,
            },
            { type: 'editFromCard', segmentUid: merged.segment_uid, category: contextCategory },
        );
        const updated = r.nextState.byId[merged.segment_uid];
        if (updated?.ignored_categories) {
            merged.ignored_categories = [...updated.ignored_categories];
        }
    }

    const keptOldIdx = first.index;
    const consumedOldIdx = second.index;

    // Capture pre-mutation UIDs for playing-pair reconciliation. The playing
    // seg might be either side of the merge; try whichever survives post-merge.
    const firstUid = first.segment_uid ?? null;
    const secondUid = second.segment_uid ?? null;

    if (chapter === currentChapter && curData?.segments) {
        const spliceIdx = Math.min(idx, otherIdx);
        curData.segments.splice(spliceIdx, 2, merged);
        curData.segments.forEach((s, i) => { s.index = i; });
        syncChapterSegsToAll();
    } else if (allData?.segments) {
        // Identity via UID (not object reference) — safer across store refreshes.
        const globalFirst = allData.segments.findIndex(s => s.segment_uid === first.segment_uid);
        const globalSecond = allData.segments.findIndex(s => s.segment_uid === second.segment_uid);
        const spliceStart = Math.min(globalFirst, globalSecond);
        allData.segments.splice(spliceStart, 2, merged);
        let reIdx = 0;
        allData.segments.forEach(s => { if (s.chapter === chapter) s.index = reIdx++; });
        invalidateChapterIndexFor(chapter);
    }

    // Try both sides for the playing seg — whichever preserves a hit resolves
    // to the merged kept-UID (first), whichever doesn't is the consumed side
    // which now legitimately clears.
    reconcilePlayingAfterMutation(chapter, firstUid);
    reconcilePlayingAfterMutation(chapter, secondUid);
    clearFlashForChapter(chapter);

    markDirty(chapter, undefined, true);
    _fixupValIndicesForMerge(chapter, keptOldIdx, consumedOldIdx);
    if (chapter === currentChapter && curData) {
        curData.segments = getChapterSegments(chapter);
    }
    finalizeEdit(mergeOp, chapter, [merged]);
    clearEdit();
}
