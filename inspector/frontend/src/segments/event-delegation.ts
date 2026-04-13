/**
 * Unified event delegation for segment card clicks.
 * Uses registerHandler pattern for edit operations (Phase 7 modules register handlers).
 */

import { jumpToSegment } from './navigation';
import { playFromSegment } from './playback/index';
import type { SegEventHandlerRegistry } from './registry';
import { resolveSegFromRow } from './rendering';
import { dom,state } from './state';
import type { SegCanvas } from './waveform/types';

// Handler registry — populated exactly once from segments/index.ts during
// DOMContentLoaded, after which every slot is guaranteed non-null.
let _handlers: SegEventHandlerRegistry = null as unknown as SegEventHandlerRegistry;
export function registerAllSegEventHandlers(handlers: SegEventHandlerRegistry): void {
    _handlers = handlers;
}

// ---------------------------------------------------------------------------
// Canvas click-to-seek / drag-to-scrub
// ---------------------------------------------------------------------------

function _seekFromCanvasEvent(e: MouseEvent, canvas: SegCanvas, row: HTMLElement): void {
    const seg = resolveSegFromRow(row);
    if (!seg) return;

    const rect = canvas.getBoundingClientRect();
    const progress = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const splitHL = canvas._splitHL;
    const tStart = splitHL ? splitHL.wfStart : seg.time_start;
    const tEnd   = splitHL ? splitHL.wfEnd   : seg.time_end;
    const timeMs = tStart + progress * (tEnd - tStart);

    if (dom.segListEl.contains(row)) {
        const idx = parseInt(row.dataset.segIndex ?? '');
        const chapter = parseInt(row.dataset.segChapter ?? '');
        if (idx === state.segCurrentIdx && !dom.segAudioEl.paused) {
            dom.segAudioEl.currentTime = timeMs / 1000;
        } else {
            playFromSegment(idx, chapter, timeMs);
        }
    } else {
        const playBtn = row.querySelector<HTMLElement>('.seg-card-play-btn');
        if (!playBtn) return;
        if (state.valCardPlayingBtn === playBtn && state.valCardAudio && !state.valCardAudio.paused) {
            state.valCardAudio.currentTime = timeMs / 1000;
        } else {
            _handlers.playErrorCardAudio(seg, playBtn, timeMs);
        }
    }
}

export function _handleSegCanvasMousedown(e: MouseEvent): void {
    const target = e.target as Element | null;
    const canvas = target?.closest<SegCanvas>('canvas');
    if (!canvas) return;
    const row = canvas.closest<HTMLElement>('.seg-row');
    if (!row || state.segEditMode) return;

    e.preventDefault();
    state._segScrubActive = true;
    _seekFromCanvasEvent(e, canvas, row);

    function onMove(ev: MouseEvent): void {
        _seekFromCanvasEvent(ev, canvas!, row!);
    }
    function onUp(): void {
        state._segScrubActive = false;
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
}

export function handleSegRowClick(e: MouseEvent): void {
    const target = e.target as Element | null;
    if (!target) return;

    // Canvas click-to-seek
    const clickedCanvas = target.closest<SegCanvas>('canvas');
    if (clickedCanvas) {
        e.stopPropagation();
        const row = clickedCanvas.closest<HTMLElement>('.seg-row');
        if (row && !state.segEditMode) _seekFromCanvasEvent(e, clickedCanvas, row);
        return;
    }

    // Ref edit
    const refSpan = target.closest<HTMLElement>('.seg-text-ref');
    if (refSpan) {
        e.stopPropagation();
        const row = refSpan.closest<HTMLElement>('.seg-row');
        if (row && row.dataset.histTimeStart !== undefined) return;
        const seg = resolveSegFromRow(row);
        if (seg && row) {
            const refCat = row.closest<HTMLElement>('details[data-category]')?.dataset?.category || null;
            _handlers.startRefEdit(refSpan, seg, row, refCat);
        }
        return;
    }

    // Play button
    const playBtn = target.closest<HTMLElement>('.seg-card-play-btn');
    if (playBtn) {
        e.stopPropagation();
        const row = playBtn.closest<HTMLElement>('.seg-row');
        if (!row) return;
        if (dom.segListEl.contains(row)) {
            const idx = parseInt(row.dataset.segIndex ?? '');
            if (idx === state.segCurrentIdx && !dom.segAudioEl.paused) {
                dom.segAudioEl.pause();
            } else {
                playFromSegment(idx, parseInt(row.dataset.segChapter ?? ''));
            }
        } else {
            const seg = resolveSegFromRow(row);
            if (seg) _handlers.playErrorCardAudio(seg, playBtn);
        }
        return;
    }

    // Go To button
    const gotoBtn = target.closest<HTMLElement>('.seg-card-goto-btn');
    if (gotoBtn) {
        e.stopPropagation();
        const row = gotoBtn.closest<HTMLElement>('.seg-row');
        const seg = resolveSegFromRow(row);
        if (!seg || !row) return;
        if (row.closest('#seg-list') && state.segActiveFilters.some(f => f.value !== null)) {
            state._segSavedFilterView = {
                filters: JSON.parse(JSON.stringify(state.segActiveFilters)),
                chapter: dom.segChapterSelect.value,
                verse: dom.segVerseSelect.value,
                scrollTop: dom.segListEl.scrollTop,
            };
        }
        jumpToSegment(seg.chapter ?? 0, seg.index);
        return;
    }

    // Adjust button
    const adjustBtn = target.closest<HTMLElement>('.btn-adjust');
    if (adjustBtn) {
        e.stopPropagation();
        const row = adjustBtn.closest<HTMLElement>('.seg-row');
        const seg = resolveSegFromRow(row);
        if (seg && row) {
            const cat = row.closest<HTMLElement>('details[data-category]')?.dataset?.category || null;
            _handlers.enterEditWithBuffer(seg, row, 'trim', cat);
        }
        return;
    }

    // Split button
    const splitBtn = target.closest<HTMLElement>('.btn-split');
    if (splitBtn) {
        e.stopPropagation();
        const row = splitBtn.closest<HTMLElement>('.seg-row');
        const seg = resolveSegFromRow(row);
        if (!seg || !row) return;
        const splitCat = row.closest<HTMLElement>('details[data-category]')?.dataset?.category || null;
        if (!dom.segListEl.contains(row)) {
            const wrapper = row.closest<HTMLElement>('.val-card-wrapper');
            if (wrapper) state._accordionOpCtx = { wrapper };
            _handlers.enterEditWithBuffer(seg, row, 'split', splitCat);
            return;
        }
        _handlers.enterEditWithBuffer(seg, row, 'split', splitCat);
        return;
    }

    // Merge prev/next buttons
    const mergePrev = target.closest<HTMLElement>('.btn-merge-prev');
    if (mergePrev) {
        e.stopPropagation();
        const row = mergePrev.closest<HTMLElement>('.seg-row');
        const seg = resolveSegFromRow(row);
        if (!seg || !row) return;
        const mergePrevCat = row.closest<HTMLElement>('details[data-category]')?.dataset?.category || null;
        if (!dom.segListEl.contains(row)) {
            const wrapper = row.closest<HTMLElement>('.val-card-wrapper');
            if (wrapper) state._accordionOpCtx = { wrapper, direction: 'prev' };
            _handlers.mergeAdjacent(seg, 'prev', mergePrevCat);
            return;
        }
        _handlers.mergeAdjacent(seg, 'prev', mergePrevCat);
        return;
    }
    const mergeNext = target.closest<HTMLElement>('.btn-merge-next');
    if (mergeNext) {
        e.stopPropagation();
        const row = mergeNext.closest<HTMLElement>('.seg-row');
        const seg = resolveSegFromRow(row);
        if (!seg || !row) return;
        const mergeNextCat = row.closest<HTMLElement>('details[data-category]')?.dataset?.category || null;
        if (!dom.segListEl.contains(row)) {
            const wrapper = row.closest<HTMLElement>('.val-card-wrapper');
            if (wrapper) state._accordionOpCtx = { wrapper, direction: 'next' };
            _handlers.mergeAdjacent(seg, 'next', mergeNextCat);
            return;
        }
        _handlers.mergeAdjacent(seg, 'next', mergeNextCat);
        return;
    }

    // Delete button
    const deleteBtn = target.closest<HTMLElement>('.btn-delete');
    if (deleteBtn) {
        e.stopPropagation();
        const row = deleteBtn.closest<HTMLElement>('.seg-row');
        const seg = resolveSegFromRow(row);
        if (seg && row) {
            const delCat = row.closest<HTMLElement>('details[data-category]')?.dataset?.category || null;
            _handlers.deleteSegment(seg, row, delCat);
        }
        return;
    }

    // Edit Ref button
    const editRefBtn = target.closest<HTMLElement>('.btn-edit-ref');
    if (editRefBtn) {
        e.stopPropagation();
        const row = editRefBtn.closest<HTMLElement>('.seg-row');
        const seg = resolveSegFromRow(row);
        if (seg && row) {
            const refSpan2 = row.querySelector<HTMLElement>('.seg-text-ref');
            if (refSpan2) {
                const editRefCat = row.closest<HTMLElement>('details[data-category]')?.dataset?.category || null;
                _handlers.startRefEdit(refSpan2, seg, row, editRefCat);
            }
        }
        return;
    }

    // Row click to play
    const row = target.closest<HTMLElement>('.seg-row');
    if (row && !target.closest('.seg-play-col') && !target.closest('.seg-actions')) {
        if (state.segEditMode) return;
        if (dom.segListEl.contains(row)) {
            const idx = parseInt(row.dataset.segIndex ?? '');
            playFromSegment(idx, parseInt(row.dataset.segChapter ?? ''));
        } else {
            const seg = resolveSegFromRow(row);
            const playBtn2 = row.querySelector<HTMLElement>('.seg-card-play-btn');
            if (seg && playBtn2) _handlers.playErrorCardAudio(seg, playBtn2);
        }
    }
}
