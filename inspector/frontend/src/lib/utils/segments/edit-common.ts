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
import {
    finalizeOp,
    setPendingOp,
    snapshotSeg,
} from '../../stores/segments/dirty';
import {
    accordionOpCtx,
    clearEdit,
    editCanvas,
} from '../../stores/segments/edit';
import { playStatusText, segAudioElement } from '../../stores/segments/playback';
import type { EditOp, Segment } from '../../types/domain';
import { applyVerseFilterAndRender, computeSilenceAfter } from './filters-apply';
import {
    _playRange as _playRangeImpl,
    clearPlayRangeRAF,
    getPreviewStopHandler,
    setPreviewJustSeeked,
    setPreviewLooping,
    setPreviewStopHandler,
} from './play-range';
import { stopSegAnimation } from './playback';
import { refreshOpenAccordionCards } from './validation-fixups';
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

// ---------------------------------------------------------------------------
// finalizeEdit — post-mutation scaffolding shared by edit-merge/split/delete/trim
// ---------------------------------------------------------------------------

/**
 * Finalize an edit op and refresh the UI after a segment mutation.
 *
 * Stamps the op (applied_at + targets_after), appends it to the chapter op
 * log via `finalizeOp` (which also clears the pending-op ref), recomputes
 * silence gaps, re-renders the filtered list, refreshes open accordion
 * cards, and publishes the completion status message.
 *
 * Callers still own `markDirty` (timing varies) and whichever exit path
 * they need (`clearEdit` for merge/delete, `exitEditMode` for trim/split
 * which also has canvas-level cleanup). Each step is skippable via `opts`
 * so the helper also fits the few sites that don't need the full refresh.
 */
export function finalizeEdit(
    op: EditOp,
    chapter: number,
    targetsAfter: Segment[],
    statusMsg: string,
    opts?: {
        skipSilence?: boolean;
        skipFilterRender?: boolean;
        skipAccordion?: boolean;
        skipStatus?: boolean;
    },
): void {
    op.applied_at_utc = new Date().toISOString();
    op.targets_after = targetsAfter.map(snapshotSeg);
    if (!opts?.skipSilence) computeSilenceAfter();
    if (!opts?.skipFilterRender) applyVerseFilterAndRender();
    if (!opts?.skipAccordion) refreshOpenAccordionCards();
    finalizeOp(chapter, op);
    if (!opts?.skipStatus) playStatusText.set(statusMsg);
}
