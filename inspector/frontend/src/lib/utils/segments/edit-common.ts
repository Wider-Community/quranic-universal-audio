/**
 * Shared edit-mode cleanup: exitEditMode + _playRange passthrough.
 *
 * Entry-point logic (enterEditWithBuffer) lives in `edit-enter.ts` so
 * that file — not this one — owns the edges into `edit-trim` / `edit-split`.
 * That keeps `edit-common` a dependency-leaf of those modules (they import
 * `_playRange` and `exitEditMode` from here).
 */

import { get } from 'svelte/store';

import { setPendingOp } from '../../stores/segments/dirty';
import {
    accordionOpCtx,
    clearEdit,
} from '../../stores/segments/edit';
import { segAudioElement } from '../../stores/segments/playback';
import type { SegCanvas } from '../../types/segments-waveform';
import {
    _playRange as _playRangeImpl,
    clearPlayRangeRAF,
    getPreviewStopHandler,
    setPreviewJustSeeked,
    setPreviewLooping,
    setPreviewStopHandler,
} from './play-range';
import { stopSegAnimation } from './playback';
import { resolveSegFromRow } from './resolve-seg-from-row';
import { drawWaveformFromPeaksForSeg } from './waveform-draw-seg';

// ---------------------------------------------------------------------------
// exitEditMode — shared cleanup for trim/split
// ---------------------------------------------------------------------------

export function exitEditMode(): void {
    setPendingOp(null);
    accordionOpCtx.set(null);

    const editRow = document.querySelector<HTMLElement>('.seg-row.seg-edit-target');
    if (editRow) {
        editRow.querySelector('.seg-edit-inline')?.remove();
        const actions = editRow.querySelector<HTMLElement>('.seg-actions');
        if (actions) actions.hidden = false;
        const playCol = editRow.querySelector<HTMLElement>('.seg-play-col');
        if (playCol) playCol.hidden = false;

        const canvas = editRow.querySelector<SegCanvas>('canvas');
        if (canvas) {
            canvas._editCleanup?.();
            delete canvas._trimWindow; delete canvas._splitData;
            delete canvas._trimEls; delete canvas._splitEls;
            delete canvas._editCleanup;
            canvas._wfCache = null;
            canvas.style.cursor = '';
            const seg = resolveSegFromRow(editRow);
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
    editRow?.classList.remove('seg-edit-target');
}

// Re-export play-range implementation so existing callers still work.
export const _playRange = _playRangeImpl;
