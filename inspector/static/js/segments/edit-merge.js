/**
 * Merge adjacent segments operation.
 */

import { state, dom, createOp, snapshotSeg, finalizeOp, markDirty } from './state.js';
import { getChapterSegments, syncChapterSegsToAll } from './data.js';
import { computeSilenceAfter, applyVerseFilterAndRender } from './filters.js';
import { _fixupValIndicesForMerge, refreshOpenAccordionCards } from './validation.js';
import { _rebuildAccordionAfterMerge } from './error-cards.js';

// ---------------------------------------------------------------------------
// mergeAdjacent -- combine two adjacent segments
// ---------------------------------------------------------------------------

export async function mergeAdjacent(seg, direction, contextCategory = null) {
    const chapter = seg.chapter || parseInt(dom.segChapterSelect.value);
    const currentChapter = parseInt(dom.segChapterSelect.value);

    let chapterSegs;
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

    const first = direction === 'prev' ? other : seg;
    const second = direction === 'prev' ? seg : other;

    const mergeOp = createOp('merge_segments', contextCategory ? { contextCategory } : undefined);
    mergeOp.merge_direction = direction;
    mergeOp.targets_before = [snapshotSeg(first), snapshotSeg(second)];

    const firstAudio = first.audio_url || '';
    const secondAudio = second.audio_url || '';
    if (firstAudio !== secondAudio) return;

    let mergedRef = '';
    const refs = [first.matched_ref, second.matched_ref].filter(Boolean);
    if (refs.length > 0) {
        const s = refs[0].includes('-') ? refs[0].split('-')[0] : refs[0];
        const e = refs[refs.length - 1].includes('-') ? refs[refs.length - 1].split('-')[1] : refs[refs.length - 1];
        mergedRef = `${s}-${e}`;
    }

    let mergedText = [first.matched_text, second.matched_text].filter(Boolean).join(' ');
    let mergedDisplay = [first.display_text, second.display_text].filter(Boolean).join(' ');
    if (mergedRef) {
        try {
            const resp = await fetch(`/api/seg/resolve_ref?ref=${encodeURIComponent(mergedRef)}`);
            const data = await resp.json();
            if (data.text) {
                mergedText = data.text;
                mergedDisplay = data.display_text || data.text;
            }
        } catch (e) {
            console.warn('Failed to resolve merged ref, using concatenated text:', e);
        }
    }

    const merged = {
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
    const mergedIc = new Set([
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
    const accCategory = accCtx?.wrapper?.closest('details[data-category]')?.dataset?.category;

    refreshOpenAccordionCards();

    if (accCtx && accCategory) {
        const freshDetails = document.querySelector(`details[data-category="${accCategory}"]`);
        const mergedCard = freshDetails?.querySelector(`.seg-row[data-seg-uid="${merged.segment_uid}"]`);
        const freshWrapper = mergedCard?.closest('.val-card-wrapper');
        if (freshWrapper) {
            _rebuildAccordionAfterMerge(freshWrapper, chapter, merged, accCtx.direction);
        }
    }

    finalizeOp(chapter, mergeOp);
    dom.segPlayStatus.textContent = 'Segments merged (unsaved)';
}
