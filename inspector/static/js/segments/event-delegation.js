/**
 * Unified event delegation for segment card clicks.
 * Uses registerHandler pattern for edit operations (Phase 7 modules register handlers).
 */

import { state, dom } from './state.js';
import { resolveSegFromRow } from './rendering.js';
import { playFromSegment } from './playback.js';
import { jumpToSegment } from './navigation.js';
import { applyFiltersAndRender } from './filters.js';

// Handler registry -- edit modules register via registerHandler()
const _handlers = {};
export function registerHandler(name, fn) { _handlers[name] = fn; }

// ---------------------------------------------------------------------------
// Canvas click-to-seek / drag-to-scrub
// ---------------------------------------------------------------------------

function _seekFromCanvasEvent(e, canvas, row) {
    const seg = resolveSegFromRow(row);
    if (!seg) return;

    const rect = canvas.getBoundingClientRect();
    const progress = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const splitHL = canvas._splitHL;
    const tStart = splitHL ? splitHL.wfStart : seg.time_start;
    const tEnd   = splitHL ? splitHL.wfEnd   : seg.time_end;
    const timeMs = tStart + progress * (tEnd - tStart);

    if (dom.segListEl.contains(row)) {
        const idx = parseInt(row.dataset.segIndex);
        const chapter = parseInt(row.dataset.segChapter);
        if (idx === state.segCurrentIdx && !dom.segAudioEl.paused) {
            dom.segAudioEl.currentTime = timeMs / 1000;
        } else {
            playFromSegment(idx, chapter, timeMs);
        }
    } else {
        const playBtn = row.querySelector('.seg-card-play-btn');
        if (!playBtn) return;
        if (state.valCardPlayingBtn === playBtn && state.valCardAudio && !state.valCardAudio.paused) {
            state.valCardAudio.currentTime = timeMs / 1000;
        } else {
            _handlers.playErrorCardAudio?.(seg, playBtn, timeMs);
        }
    }
}

export function _handleSegCanvasMousedown(e) {
    const canvas = e.target.closest('canvas');
    if (!canvas) return;
    const row = canvas.closest('.seg-row');
    if (!row || state.segEditMode) return;

    e.preventDefault();
    state._segScrubActive = true;
    _seekFromCanvasEvent(e, canvas, row);

    function onMove(ev) {
        _seekFromCanvasEvent(ev, canvas, row);
    }
    function onUp() {
        state._segScrubActive = false;
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
    }
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
}

export function handleSegRowClick(e) {
    // Canvas click-to-seek
    const clickedCanvas = e.target.closest('canvas');
    if (clickedCanvas) {
        e.stopPropagation();
        const row = clickedCanvas.closest('.seg-row');
        if (row && !state.segEditMode) _seekFromCanvasEvent(e, clickedCanvas, row);
        return;
    }

    // Ref edit
    const refSpan = e.target.closest('.seg-text-ref');
    if (refSpan) {
        e.stopPropagation();
        const row = refSpan.closest('.seg-row');
        if (row && row.dataset.histTimeStart !== undefined) return;
        const seg = resolveSegFromRow(row);
        if (seg && row) {
            const refCat = row.closest('details[data-category]')?.dataset?.category || null;
            _handlers.startRefEdit?.(refSpan, seg, row, refCat);
        }
        return;
    }

    // Play button
    const playBtn = e.target.closest('.seg-card-play-btn');
    if (playBtn) {
        e.stopPropagation();
        const row = playBtn.closest('.seg-row');
        if (dom.segListEl.contains(row)) {
            const idx = parseInt(row.dataset.segIndex);
            if (idx === state.segCurrentIdx && !dom.segAudioEl.paused) {
                dom.segAudioEl.pause();
            } else {
                playFromSegment(idx, parseInt(row.dataset.segChapter));
            }
        } else {
            const seg = resolveSegFromRow(row);
            if (seg) _handlers.playErrorCardAudio?.(seg, playBtn);
        }
        return;
    }

    // Go To button
    const gotoBtn = e.target.closest('.seg-card-goto-btn');
    if (gotoBtn) {
        e.stopPropagation();
        const row = gotoBtn.closest('.seg-row');
        const seg = resolveSegFromRow(row);
        if (!seg) return;
        if (row.closest('#seg-list') && state.segActiveFilters.some(f => f.value !== null)) {
            state._segSavedFilterView = {
                filters: JSON.parse(JSON.stringify(state.segActiveFilters)),
                chapter: dom.segChapterSelect.value,
                verse: dom.segVerseSelect.value,
                scrollTop: dom.segListEl.scrollTop,
            };
        }
        jumpToSegment(seg.chapter, seg.index);
        return;
    }

    // Adjust button
    const adjustBtn = e.target.closest('.btn-adjust');
    if (adjustBtn) {
        e.stopPropagation();
        const row = adjustBtn.closest('.seg-row');
        const seg = resolveSegFromRow(row);
        if (seg && row) {
            const cat = row.closest('details[data-category]')?.dataset?.category || null;
            _handlers.enterEditWithBuffer?.(seg, row, 'trim', cat);
        }
        return;
    }

    // Split button
    const splitBtn = e.target.closest('.btn-split');
    if (splitBtn) {
        e.stopPropagation();
        const row = splitBtn.closest('.seg-row');
        const seg = resolveSegFromRow(row);
        if (!seg || !row) return;
        const splitCat = row.closest('details[data-category]')?.dataset?.category || null;
        if (!dom.segListEl.contains(row)) {
            const wrapper = row.closest('.val-card-wrapper');
            state._accordionOpCtx = { wrapper };
            _handlers.enterEditWithBuffer?.(seg, row, 'split', splitCat);
            return;
        }
        _handlers.enterEditWithBuffer?.(seg, row, 'split', splitCat);
        return;
    }

    // Merge prev/next buttons
    const mergePrev = e.target.closest('.btn-merge-prev');
    if (mergePrev) {
        e.stopPropagation();
        const row = mergePrev.closest('.seg-row');
        const seg = resolveSegFromRow(row);
        if (!seg) return;
        const mergePrevCat = row.closest('details[data-category]')?.dataset?.category || null;
        if (!dom.segListEl.contains(row)) {
            const wrapper = row.closest('.val-card-wrapper');
            state._accordionOpCtx = { wrapper, direction: 'prev' };
            _handlers.mergeAdjacent?.(seg, 'prev', mergePrevCat);
            return;
        }
        _handlers.mergeAdjacent?.(seg, 'prev', mergePrevCat);
        return;
    }
    const mergeNext = e.target.closest('.btn-merge-next');
    if (mergeNext) {
        e.stopPropagation();
        const row = mergeNext.closest('.seg-row');
        const seg = resolveSegFromRow(row);
        if (!seg) return;
        const mergeNextCat = row.closest('details[data-category]')?.dataset?.category || null;
        if (!dom.segListEl.contains(row)) {
            const wrapper = row.closest('.val-card-wrapper');
            state._accordionOpCtx = { wrapper, direction: 'next' };
            _handlers.mergeAdjacent?.(seg, 'next', mergeNextCat);
            return;
        }
        _handlers.mergeAdjacent?.(seg, 'next', mergeNextCat);
        return;
    }

    // Delete button
    const deleteBtn = e.target.closest('.btn-delete');
    if (deleteBtn) {
        e.stopPropagation();
        const row = deleteBtn.closest('.seg-row');
        const seg = resolveSegFromRow(row);
        if (seg) {
            const delCat = row.closest('details[data-category]')?.dataset?.category || null;
            _handlers.deleteSegment?.(seg, row, delCat);
        }
        return;
    }

    // Edit Ref button
    const editRefBtn = e.target.closest('.btn-edit-ref');
    if (editRefBtn) {
        e.stopPropagation();
        const row = editRefBtn.closest('.seg-row');
        const seg = resolveSegFromRow(row);
        if (seg && row) {
            const refSpan = row.querySelector('.seg-text-ref');
            if (refSpan) {
                const editRefCat = row.closest('details[data-category]')?.dataset?.category || null;
                _handlers.startRefEdit?.(refSpan, seg, row, editRefCat);
            }
        }
        return;
    }

    // Row click to play
    const row = e.target.closest('.seg-row');
    if (row && !e.target.closest('.seg-play-col') && !e.target.closest('.seg-actions')) {
        if (state.segEditMode) return;
        if (dom.segListEl.contains(row)) {
            const idx = parseInt(row.dataset.segIndex);
            playFromSegment(idx, parseInt(row.dataset.segChapter));
        } else {
            const seg = resolveSegFromRow(row);
            const playBtn = row.querySelector('.seg-card-play-btn');
            if (seg && playBtn) _handlers.playErrorCardAudio?.(seg, playBtn);
        }
    }
}
