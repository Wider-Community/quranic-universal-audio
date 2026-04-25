/**
 * Trim (boundary adjustment) edit mode: enter, drag handles, preview, confirm.
 */

import { get } from 'svelte/store';

import type { Segment } from '../../../../lib/types/domain';
import { getWaveformPeaks } from '../../../../lib/utils/waveform-cache';
import {
    getChapterSegments,
    getCurrentChapterSegs,
    invalidateChapterIndexFor,
    refreshSegInStore,
    segAllData,
    segData,
    selectedChapter,
    syncChapterSegsToAll,
} from '../../stores/chapter';
import { segConfig } from '../../stores/config';
import {
    getPendingOp,
    markDirty,
    setPendingOp,
} from '../../stores/dirty';
import {
    editCanvas,
    editMode,
    setEdit,
    setEditCanvas,
    setEditingSegIndex,
    setEditStatusText,
    setTrimWindow,
    updateTrimWindow,
} from '../../stores/edit';
import { segAudioElement } from '../../stores/playback';
import type { SegCanvas } from '../../types/segments-waveform';
import { applyCommand } from '../../domain/apply-command';
import { EDIT_MIN_DURATION_MS, EDIT_SNAP_MS, TRIM_HANDLE_HIT_RADIUS_PX } from '../constants';
import {
    clearPlayRangeRAF,
    getPreviewLooping,
    setPreviewJustSeeked,
    setPreviewLooping,
} from '../playback/play-range';
import { _ensureTrimBaseCache, drawTrimWaveform } from '../waveform/trim-draw';
import { _fetchPeaksForClick } from '../waveform/utils';
import { _playRange, exitEditMode, finalizeEdit } from './common';
import { applyWheelZoom } from './trim-zoom';

// Re-export draw functions so registration sites and other callers still work.
export { _ensureTrimBaseCache, drawTrimWaveform };

// ---------------------------------------------------------------------------
// enterTrimMode
// ---------------------------------------------------------------------------

/**
 * Compute the trim clamp bounds for a segment — the hard min/max the user
 * can move time_start/time_end to. Bounds are `max(prevSegEnd, seg.time_start - trimPadLeft)`
 * and `min(nextSegStart, seg.time_end + trimPadRight)`, i.e. pad outward from
 * the current boundary but never cross a neighbor. `peaksDurationMs` caps the
 * right bound for the last seg in a chapter (no next seg to clamp against).
 *
 * Exposed so the row time-edit widget can reason about editability without
 * duplicating the neighbor-lookup logic. Pure — no store writes, no side
 * effects on `seg`.
 */
export function computeTrimBounds(
    seg: Segment,
    chapterSegs: Segment[],
    cfg: { trimPadLeft: number; trimPadRight: number },
    peaksDurationMs?: number,
): { windowStart: number; windowEnd: number; audioUrl: string } {
    const segIdx = chapterSegs.findIndex((s) => s.index === seg.index);
    const prevEnd = segIdx > 0 ? (chapterSegs[segIdx - 1]?.time_end ?? 0) : 0;
    const audioUrl = seg.audio_url || get(segAllData)?.audio_by_chapter?.[String(seg.chapter ?? 0)] || '';
    const nextStart = segIdx >= 0 && segIdx < chapterSegs.length - 1
        ? (chapterSegs[segIdx + 1]?.time_start ?? seg.time_end + 1000)
        : (peaksDurationMs || seg.time_end + 1000);
    const windowStart = Math.max(prevEnd, seg.time_start - cfg.trimPadLeft);
    const windowEnd = Math.min(nextStart, seg.time_end + cfg.trimPadRight);
    return { windowStart, windowEnd, audioUrl };
}

export function enterTrimMode(seg: Segment, row: HTMLElement, mountId: symbol | null = null): void {
    if (get(editMode)) {
        console.warn('[trim] blocked: already in edit mode:', get(editMode));
        return;
    }
    setEdit('trim', seg.segment_uid ?? null, mountId);
    setEditingSegIndex(seg.index);
    setEditStatusText('');

    const canvas = row.querySelector<SegCanvas>('canvas');
    if (!canvas) return;

    const chStr = get(selectedChapter);
    const chapter = seg.chapter || parseInt(chStr);
    const currentChapter = parseInt(chStr);
    const chapterSegs = (chapter === currentChapter) ? getCurrentChapterSegs() : getChapterSegments(chapter);
    const cfg = get(segConfig);
    const peaksDuration = getWaveformPeaks(seg.audio_url || get(segAllData)?.audio_by_chapter?.[String(chapter)] || '')?.duration_ms;
    const { windowStart, windowEnd, audioUrl } = computeTrimBounds(
        { ...seg, chapter },
        chapterSegs,
        cfg,
        peaksDuration,
    );
    // Init view = full clamp window (no zoom). Reset on every entry — zoom
    // state is intentionally not preserved across edit sessions (req #9).
    canvas._trimWindow = {
        windowStart, windowEnd,
        viewStart: windowStart, viewEnd: windowEnd,
        currentStart: seg.time_start, currentEnd: seg.time_end,
        audioUrl,
    };
    setTrimWindow({ ...canvas._trimWindow });
    canvas._wfCache = null;
    canvas._trimBaseCache = null;
    // Populate the editCanvas store synchronously. SegmentRow.svelte publishes
    // it too via a reactive block, but that fires on the next microtask — and
    // `previewTrimAudio` below kicks off `_playRange` immediately, which reads
    // `editCanvas` via `get(editCanvas)` to thread the canvas into the rAF
    // loop. Without this explicit set, `_playRange`'s `canvas` is null on the
    // auto-start path and `animatePlayhead` short-circuits on its first frame
    // (no playhead, no loop enforcement, no live boundary updates on drag).
    setEditCanvas(canvas);

    drawTrimWaveform(canvas);
    setupTrimDragHandles(canvas, seg);

    // Fire the preview loop SYNCHRONOUSLY so the audio.play() call stays
    // inside the user-gesture context of the Adjust click. An async IIFE
    // with `await _fetchPeaksForClick` breaks that context (browsers drop
    // the transient activation across microtasks in some cases), and Chrome
    // silently rejects the play promise — leaving the play/pause button in
    // the "stop" state with no audio. `animatePlayhead` is resilient to
    // paused state now, so it's fine for the playhead rAF to run before
    // peaks arrive. Then kick off the peaks fetch in the background; when
    // peaks land, `redrawPeaksWaveforms` repaints the edit canvas, or we
    // redraw here after the fetch completes.
    previewTrimAudio(canvas);
    void _fetchPeaksForClick(seg, chapter).then(() => {
        if (!canvas._trimWindow) return; // user exited trim mode mid-fetch
        drawTrimWaveform(canvas);
    });
}

// ---------------------------------------------------------------------------
// setupTrimDragHandles — mouse event handlers for trim handles
// ---------------------------------------------------------------------------

export function setupTrimDragHandles(canvas: SegCanvas, seg: Segment): void {
    void seg; // reserved for future per-seg snap tuning
    let dragging: 'start' | 'end' | null = null;
    let didDrag = false;
    const HANDLE_THRESHOLD = TRIM_HANDLE_HIT_RADIUS_PX;

    /** Visible x-coords of the start + end cursors, with strict per-side
     *  clipping when the cursor's actual time is outside the visible window:
     *  start clips to LEFT edge (x=0), end clips to RIGHT edge (x=width).
     *  Drag/click hit-detection uses these clipped coords so a clamped
     *  cursor at the canvas edge is still grabbable. */
    function _getHandleXs(): { startX: number; endX: number } {
        const tw = canvas._trimWindow!;
        const w = canvas.width;
        const span = tw.viewEnd - tw.viewStart;
        const sxRaw = ((tw.currentStart - tw.viewStart) / span) * w;
        const exRaw = ((tw.currentEnd - tw.viewStart) / span) * w;
        const startOff = tw.currentStart < tw.viewStart || tw.currentStart > tw.viewEnd;
        const endOff   = tw.currentEnd   < tw.viewStart || tw.currentEnd   > tw.viewEnd;
        return {
            startX: startOff ? 0 : sxRaw,
            endX:   endOff   ? w : exRaw,
        };
    }

    function onMousedown(e: MouseEvent): void {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const { startX, endX } = _getHandleXs();
        didDrag = false;

        if (Math.abs(x - startX) < HANDLE_THRESHOLD) dragging = 'start';
        else if (Math.abs(x - endX) < HANDLE_THRESHOLD) dragging = 'end';
        if (dragging) canvas.style.cursor = 'col-resize';
    }

    function onMousemove(e: MouseEvent): void {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const tw = canvas._trimWindow;
        if (!tw) return;
        const width = canvas.width;

        if (!dragging) {
            const { startX, endX } = _getHandleXs();
            canvas.style.cursor = (Math.abs(x - startX) < HANDLE_THRESHOLD || Math.abs(x - endX) < HANDLE_THRESHOLD) ? 'col-resize' : 'pointer';
            return;
        }
        didDrag = true;
        // Pixel→time uses the VISIBLE window (so dragging a clamped cursor
        // jumps the actual time to the dragged pixel's time, per req #6).
        // Final boundary still clamps to [windowStart, windowEnd].
        const timeAtX = tw.viewStart + (x / width) * (tw.viewEnd - tw.viewStart);
        const snapped = Math.round(timeAtX / EDIT_SNAP_MS) * EDIT_SNAP_MS;

        if (dragging === 'start') {
            tw.currentStart = Math.max(tw.windowStart, Math.min(snapped, tw.currentEnd - EDIT_MIN_DURATION_MS));
        } else {
            tw.currentEnd = Math.max(tw.currentStart + EDIT_MIN_DURATION_MS, Math.min(snapped, tw.windowEnd));
        }
        updateTrimWindow((w) => w ? { ...w, currentStart: tw.currentStart, currentEnd: tw.currentEnd } : w);
        drawTrimWaveform(canvas);
    }

    function onMouseup(e: MouseEvent): void {
        if (!dragging && !didDrag) {
            const rect = canvas.getBoundingClientRect();
            const x = (e.clientX - rect.left) * (canvas.width / rect.width);
            const tw = canvas._trimWindow;
            if (!tw) return;
            // Click-to-seek also uses the visible window for pixel→time.
            const timeAtX = tw.viewStart + (x / canvas.width) * (tw.viewEnd - tw.viewStart);
            const snapped = Math.round(timeAtX / EDIT_SNAP_MS) * EDIT_SNAP_MS;
            _playRange(snapped, tw.currentEnd);
        }
        dragging = null;
        canvas.style.cursor = '';
    }
    function onMouseleave(): void { dragging = null; canvas.style.cursor = ''; }

    /** Wheel zoom on the trim canvas. Suppressed mid-drag (req #8) so a
     *  user can't accidentally rescale the time-axis underneath an in-flight
     *  cursor drag. `passive: false` is required so `preventDefault()` can
     *  stop the page from scrolling while the wheel is over the canvas. */
    function onWheel(e: WheelEvent): void {
        if (dragging) return;
        e.preventDefault();
        applyWheelZoom(canvas, e.clientX, e.deltaY);
    }

    canvas.addEventListener('mousedown', onMousedown);
    canvas.addEventListener('mousemove', onMousemove);
    canvas.addEventListener('mouseup', onMouseup);
    canvas.addEventListener('mouseleave', onMouseleave);
    canvas.addEventListener('wheel', onWheel, { passive: false });

    canvas._editCleanup = (): void => {
        canvas.removeEventListener('mousedown', onMousedown);
        canvas.removeEventListener('mousemove', onMousemove);
        canvas.removeEventListener('mouseup', onMouseup);
        canvas.removeEventListener('mouseleave', onMouseleave);
        canvas.removeEventListener('wheel', onWheel);
    };
}

// ---------------------------------------------------------------------------
// nudgeTrimBoundary — step a cursor by ±deltaMs (called by TrimPanel steppers)
// ---------------------------------------------------------------------------

/**
 * Move one trim cursor by `deltaMs`, clamped to `[windowStart, windowEnd]`
 * AND respecting `EDIT_MIN_DURATION_MS` against the opposite handle. Mirrors
 * the live drag/typed-edit flow: writes both the store (for Svelte
 * subscribers — TrimPanel duration, TimeRange display) and the canvas-local
 * `_trimWindow` (for the imperative draw + drag-handle math), then redraws.
 *
 * **Snap-to-visual-border** (req #7): when the cursor is currently OFF-VIEW
 * (its actual time falls outside `[viewStart, viewEnd]` because the user
 * zoomed in past it), the step is anchored at the cursor's *visual* clamp
 * position rather than its actual time. Per strict clipping: start cursor
 * always clamps to LEFT (anchor = `viewStart`); end cursor always clamps
 * to RIGHT (anchor = `viewEnd`). So pressing `>` on a left-clamped start
 * with `viewStart=1000, deltaMs=50` lands at `1050` regardless of the
 * cursor's current actual time — making it pop back into view.
 *
 * The TrimPanel disable gates separately suppress the "away from view"
 * presses (e.g. `<` on a left-clamped start) since those produce no visible
 * feedback.
 *
 * Returns the new boundary position (or the unchanged value if the step
 * couldn't move because of clamping). UI uses this return + the bounds
 * arithmetic to decide whether the corresponding stepper button should be
 * disabled.
 */
export function nudgeTrimBoundary(side: 'start' | 'end', deltaMs: number): number | null {
    const canvas = get(editCanvas);
    const tw = canvas?._trimWindow;
    if (!canvas || !tw) return null;
    const minDur = EDIT_MIN_DURATION_MS;

    let next: number;
    if (side === 'start') {
        const onView = tw.currentStart >= tw.viewStart && tw.currentStart <= tw.viewEnd;
        const anchor = onView ? tw.currentStart : tw.viewStart; // strict-clip LEFT
        next = Math.max(tw.windowStart, Math.min(anchor + deltaMs, tw.currentEnd - minDur));
        if (next === tw.currentStart) return next;
        tw.currentStart = next;
    } else {
        const onView = tw.currentEnd >= tw.viewStart && tw.currentEnd <= tw.viewEnd;
        const anchor = onView ? tw.currentEnd : tw.viewEnd; // strict-clip RIGHT
        next = Math.max(tw.currentStart + minDur, Math.min(anchor + deltaMs, tw.windowEnd));
        if (next === tw.currentEnd) return next;
        tw.currentEnd = next;
    }
    updateTrimWindow((w) => w ? { ...w, currentStart: tw.currentStart, currentEnd: tw.currentEnd } : w);
    drawTrimWaveform(canvas);
    return next;
}

// ---------------------------------------------------------------------------
// confirmTrim — apply the trim and finalize
// ---------------------------------------------------------------------------

export function confirmTrim(seg: Segment, canvas?: SegCanvas | null): void {
    const c = canvas ?? get(editCanvas);
    // Block Apply when a TimeEdit has an open, invalid typed value. The user
    // pressed Enter on an out-of-range value and got a whole-widget red
    // border; we must not silently exit edit mode and persist the LAST VALID
    // `canvas._trimWindow` value — that'd discard their typed input without
    // feedback. Keep the edit open so they can fix or Cancel.
    const editRow = c?.closest('.seg-row');
    if (editRow?.querySelector('.seg-text-time-editing.invalid')) {
        setEditStatusText('Fix invalid time first');
        return;
    }
    const tw = c?._trimWindow;
    const newStart = tw?.currentStart;
    const newEnd = tw?.currentEnd;
    if (newStart == null || newEnd == null || newStart >= newEnd) {
        setEditStatusText('Invalid time range');
        return;
    }

    const chStr = get(selectedChapter);
    const chapter = seg.chapter || parseInt(chStr);
    const currentChapter = parseInt(chStr);
    const chapterSegs = chapter === currentChapter ? getCurrentChapterSegs() : getChapterSegments(chapter);
    const segIdx = chapterSegs.findIndex(s => s.index === seg.index);
    const prevSeg = segIdx > 0 ? chapterSegs[segIdx - 1] : null;
    const nextSeg = (segIdx >= 0 && segIdx < chapterSegs.length - 1) ? chapterSegs[segIdx + 1] : null;

    if (prevSeg && prevSeg.audio_url === seg.audio_url && newStart < prevSeg.time_end) {
        setEditStatusText('Start overlaps with previous segment');
        return;
    }
    if (nextSeg && nextSeg.audio_url === seg.audio_url && newEnd > nextSeg.time_start) {
        setEditStatusText('End overlaps with next segment');
        return;
    }

    const pending = getPendingOp();
    const ctxCat = pending?.op_context_category ?? null;
    const uid = seg.segment_uid;
    if (uid) {
        const result = applyCommand(
            {
                byId: { [uid]: seg },
                idsByChapter: { [chapter]: [uid] },
                selectedChapter: chapter,
            },
            {
                type: 'trim',
                segmentUid: uid,
                delta: { time_start: newStart, time_end: newEnd },
                sourceCategory: ctxCat ?? undefined,
                contextCategory: ctxCat ?? undefined,
            },
        );
        const updated = result.nextState.byId[uid];
        if (updated) {
            seg.time_start = updated.time_start;
            seg.time_end = updated.time_end;
            seg.confidence = updated.confidence;
            if (updated.ignored_categories) {
                seg.ignored_categories = [...updated.ignored_categories];
            }
        }
    } else {
        seg.time_start = newStart;
        seg.time_end = newEnd;
        seg.confidence = 1.0;
    }
    markDirty(chapter, undefined, true);

    const trimOp = pending;
    setPendingOp(null);

    const curData = get(segData);
    if (chapter !== currentChapter || !curData?.segments) {
        // Non-current chapter trim: seg identity replaced via refreshSegInStore
        // below patches the cache surgically. Drop only the affected chapter's
        // entries as a safety net for the rare case where the seg is newly
        // added to the chapter (cache miss rebuild).
        invalidateChapterIndexFor(chapter);
    } else {
        syncChapterSegsToAll();
    }

    exitEditMode();
    refreshSegInStore(seg);
    if (trimOp) {
        finalizeEdit(trimOp, chapter, [seg], { skipAccordion: true });
    }
}

// ---------------------------------------------------------------------------
// previewTrimAudio — toggle looping preview of trimmed region
// ---------------------------------------------------------------------------

export function previewTrimAudio(canvas?: SegCanvas | null): void {
    const c = canvas ?? get(editCanvas);
    const tw = c?._trimWindow;
    if (!tw || !c) return;
    const audioEl = get(segAudioElement);
    if (getPreviewLooping() && audioEl && !audioEl.paused) {
        setPreviewLooping(false);
        setPreviewJustSeeked(false);
        audioEl.pause();
        clearPlayRangeRAF();
        if (c._trimWindow) drawTrimWaveform(c);
        return;
    }
    setPreviewLooping('trim');
    _playRange(tw.currentStart, tw.currentEnd);
}
