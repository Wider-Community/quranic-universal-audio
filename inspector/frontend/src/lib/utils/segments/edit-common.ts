/**
 * Shared edit-mode cleanup: exitEditMode + _playRange passthrough.
 *
 * Entry-point logic (enterEditWithBuffer) lives in `edit-enter.ts` so
 * that file — not this one — owns the edges into `edit-trim` / `edit-split`.
 * That keeps `edit-common` a dependency-leaf of those modules (they import
 * `_playRange` and `exitEditMode` from here).
 */

import { get } from 'svelte/store';

import { getSegByChapterIndex } from '../../stores/segments/chapter';
import { setPendingOp } from '../../stores/segments/dirty';
import {
    accordionOpCtx,
    clearEdit,
    editCanvas,
} from '../../stores/segments/edit';
import { segAudioElement } from '../../stores/segments/playback';
import {
    _playRange as _playRangeImpl,
    clearPlayRangeRAF,
    getPreviewStopHandler,
    setPreviewJustSeeked,
    setPreviewLooping,
    setPreviewStopHandler,
} from './play-range';
import { stopSegAnimation } from './playback';
import { drawWaveformFromPeaksForSeg } from './waveform-draw-seg';

// ---------------------------------------------------------------------------
// exitEditMode — shared cleanup for trim/split
// ---------------------------------------------------------------------------

export function exitEditMode(): void {
    setPendingOp(null);
    accordionOpCtx.set(null);

    const canvas = get(editCanvas);
    const editRow = canvas?.closest<HTMLElement>('.seg-row') ?? null;
    if (canvas) {
        canvas._editCleanup?.();
        delete canvas._trimWindow; delete canvas._splitData;
        delete canvas._editCleanup;
        canvas._wfCache = null;
        canvas.style.cursor = '';
        if (editRow) {
            const idx = parseInt(editRow.dataset.segIndex ?? '-1');
            const chapter = parseInt(editRow.dataset.segChapter ?? '-1');
            const seg = chapter >= 0 ? getSegByChapterIndex(chapter, idx) : null;
            if (seg) drawWaveformFromPeaksForSeg(canvas, seg, seg.chapter ?? 0);
        }
    }

    clearEdit();
    setPreviewLooping(false);
    setPreviewJustSeeked(false);
    clearPlayRangeRAF();
    const stopHandler = getPreviewStopHandler();
    if (stopHandler) {
        const audioEl = get(segAudioElement);
        if (audioEl) audioEl.removeEventListener('timeupdate', stopHandler);
        setPreviewStopHandler(null);
    }
    const audioEl2 = get(segAudioElement);
    if (audioEl2 && !audioEl2.paused) { audioEl2.pause(); stopSegAnimation(); }
}

// Re-export play-range implementation so existing callers still work.
export const _playRange = _playRangeImpl;
