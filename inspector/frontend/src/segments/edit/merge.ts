/**
 * Merge adjacent segments operation.
 */

import { fetchJson } from '../../lib/api';
import { clearEdit, setEdit } from '../../lib/stores/segments/edit';
import type { SegResolveRefResponse } from '../../types/api';
import type { Segment } from '../../types/domain';
import { getChapterSegments, syncChapterSegsToAll } from '../data';
import { applyVerseFilterAndRender,computeSilenceAfter } from '../filters';
import { createOp, dom, finalizeOp, markDirty,snapshotSeg, state } from '../state';
import { _rebuildAccordionAfterMerge } from '../validation/error-cards';
import { _fixupValIndicesForMerge, refreshOpenAccordionCards } from '../validation/index';

// ---------------------------------------------------------------------------
// mergeAdjacent -- combine two adjacent segments
// ---------------------------------------------------------------------------

export async function mergeAdjacent(
    seg: Segment,
    direction: 'prev' | 'next',
    contextCategory: string | null = null,
): Promise<void> {
    const chapter = seg.chapter || parseInt(dom.segChapterSelect.value);
    const currentChapter = parseInt(dom.segChapterSelect.value);

    let chapterSegs: Segment[] | undefined;
    if (chapter === currentChapter && state.segData?.segments) {
        chapterSegs = state.segData.segments;
    } else if (state.segAllData?.segments) {
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

    // Signal merge mode to EditOverlay (and future MergePanel).
    // Placed after all pure guard checks so the store only reflects merge
    // while we're actually committed to executing.
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

    mergeOp.applied_at_utc = new Date().toISOString();
    mergeOp.targets_after = [snapshotSeg(merged)];

    const keptOldIdx = first.index;
    const consumedOldIdx = second.index;

    if (chapter === currentChapter && state.segData?.segments) {
        const spliceIdx = Math.min(idx, otherIdx);
        state.segData.segments.splice(spliceIdx, 2, merged);
        state.segData.segments.forEach((s, i) => { s.index = i; });
        syncChapterSegsToAll();
    } else if (state.segAllData?.segments) {
        const globalFirst = state.segAllData.segments.indexOf(first);
        const globalSecond = state.segAllData.segments.indexOf(second);
        const spliceStart = Math.min(globalFirst, globalSecond);
        state.segAllData.segments.splice(spliceStart, 2, merged);
        let reIdx = 0;
        state.segAllData.segments.forEach(s => { if (s.chapter === chapter) s.index = reIdx++; });
        state.segAllData._byChapter = null; state.segAllData._byChapterIndex = null;
    }

    markDirty(chapter, undefined, true);
    _fixupValIndicesForMerge(chapter, keptOldIdx, consumedOldIdx);
    if (chapter === currentChapter && state.segData) {
        state.segData.segments = getChapterSegments(chapter);
    }
    computeSilenceAfter();
    applyVerseFilterAndRender();

    const accCtx = state._accordionOpCtx;
    state._accordionOpCtx = null;
    const accCategory = accCtx?.wrapper?.closest<HTMLElement>('details[data-category]')?.dataset?.category;

    refreshOpenAccordionCards();

    if (accCtx && accCategory) {
        const freshDetails = document.querySelector(`details[data-category="${accCategory}"]`);
        const mergedCard = freshDetails?.querySelector<HTMLElement>(`.seg-row[data-seg-uid="${merged.segment_uid}"]`);
        const freshWrapper = mergedCard?.closest<HTMLElement>('.val-card-wrapper');
        if (freshWrapper) {
            _rebuildAccordionAfterMerge(freshWrapper, chapter, merged, accCtx.direction);
        }
    }

    finalizeOp(chapter, mergeOp);
    clearEdit();
    dom.segPlayStatus.textContent = 'Segments merged (unsaved)';
}
