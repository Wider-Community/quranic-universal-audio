/**
 * Trim (boundary adjustment) edit mode: enter, drag handles, preview, confirm.
 */

import { get } from 'svelte/store';

import {
    getChapterSegments,
    getCurrentChapterSegs,
    refreshSegInStore,
    segAllData,
    segData,
    selectedChapter,
    syncChapterSegsToAll,
} from '../../stores/segments/chapter';
import { segConfig } from '../../stores/segments/config';
import {
    finalizeOp,
    getPendingOp,
    markDirty,
    setPendingOp,
    snapshotSeg,
} from '../../stores/segments/dirty';
import {
    editCanvas,
    editingSegIndex,
    editMode,
    editStatusText,
    setEdit,
    trimWindow,
} from '../../stores/segments/edit';
import {
    playStatusText,
    segAudioElement,
} from '../../stores/segments/playback';
import type { Segment } from '../../types/domain';
import type { SegCanvas } from '../../types/segments-waveform';
import { getWaveformPeaks } from '../waveform-cache';
import { _playRange, exitEditMode } from './edit-common';
import { applyVerseFilterAndRender, computeSilenceAfter } from './filters-apply';
import {
    clearPlayRangeRAF,
    getPreviewLooping,
    setPreviewJustSeeked,
    setPreviewLooping,
} from './play-range';
import { _ensureTrimBaseCache, drawTrimWaveform } from './trim-draw';

// Re-export draw functions so registration sites and other callers still work.
export { _ensureTrimBaseCache, drawTrimWaveform };

// ---------------------------------------------------------------------------
// enterTrimMode
// ---------------------------------------------------------------------------

export function enterTrimMode(seg: Segment, row: HTMLElement): void {
    if (get(editMode)) {
        console.warn('[trim] blocked: already in edit mode:', get(editMode));
        return;
    }
    setEdit('trim', seg.segment_uid ?? null);
    editingSegIndex.set(seg.index);
    editStatusText.set('');

    const canvas = row.querySelector<SegCanvas>('canvas');
    if (!canvas) return;

    const chStr = get(selectedChapter);
    const chapter = seg.chapter || parseInt(chStr);
    const currentChapter = parseInt(chStr);
    const chapterSegs = (chapter === currentChapter) ? getCurrentChapterSegs() : getChapterSegments(chapter);
    const segIdx = chapterSegs.findIndex(s => s.index === seg.index);
    const prevEnd = segIdx > 0 ? (chapterSegs[segIdx - 1]?.time_end ?? 0) : 0;
    const audioUrl = seg.audio_url || get(segAllData)?.audio_by_chapter?.[String(chapter)] || '';
    const peaksDuration = getWaveformPeaks(audioUrl)?.duration_ms;
    const nextStart = segIdx >= 0 && segIdx < chapterSegs.length - 1
        ? (chapterSegs[segIdx + 1]?.time_start ?? seg.time_end + 1000)
        : (peaksDuration || seg.time_end + 1000);
    const cfg = get(segConfig);
    const windowStart = Math.max(prevEnd, seg.time_start - cfg.trimPadLeft);
    const windowEnd = Math.min(nextStart, seg.time_end + cfg.trimPadRight);
    canvas._trimWindow = { windowStart, windowEnd, currentStart: seg.time_start, currentEnd: seg.time_end, audioUrl };
    trimWindow.set({ ...canvas._trimWindow });
    canvas._wfCache = null;
    canvas._trimBaseCache = null;

    drawTrimWaveform(canvas);
    setupTrimDragHandles(canvas, seg);
}

// ---------------------------------------------------------------------------
// setupTrimDragHandles — mouse event handlers for trim handles
// ---------------------------------------------------------------------------

export function setupTrimDragHandles(canvas: SegCanvas, seg: Segment): void {
    void seg; // reserved for future per-seg snap tuning
    let dragging: 'start' | 'end' | null = null;
    let didDrag = false;
    const HANDLE_THRESHOLD = 12;

    function _getHandleXs(): { startX: number; endX: number } {
        const tw = canvas._trimWindow!;
        const w = canvas.width;
        return {
            startX: ((tw.currentStart - tw.windowStart) / (tw.windowEnd - tw.windowStart)) * w,
            endX: ((tw.currentEnd - tw.windowStart) / (tw.windowEnd - tw.windowStart)) * w,
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
        const timeAtX = tw.windowStart + (x / width) * (tw.windowEnd - tw.windowStart);
        const snapped = Math.round(timeAtX / 10) * 10;

        if (dragging === 'start') {
            tw.currentStart = Math.max(tw.windowStart, Math.min(snapped, tw.currentEnd - 50));
        } else {
            tw.currentEnd = Math.max(tw.currentStart + 50, Math.min(snapped, tw.windowEnd));
        }
        trimWindow.update(w => w ? { ...w, currentStart: tw.currentStart, currentEnd: tw.currentEnd } : w);
        drawTrimWaveform(canvas);
    }

    function onMouseup(e: MouseEvent): void {
        if (!dragging && !didDrag) {
            const rect = canvas.getBoundingClientRect();
            const x = (e.clientX - rect.left) * (canvas.width / rect.width);
            const tw = canvas._trimWindow;
            if (!tw) return;
            const timeAtX = tw.windowStart + (x / canvas.width) * (tw.windowEnd - tw.windowStart);
            const snapped = Math.round(timeAtX / 10) * 10;
            _playRange(snapped, tw.currentEnd);
        }
        dragging = null;
        canvas.style.cursor = '';
    }
    function onMouseleave(): void { dragging = null; canvas.style.cursor = ''; }

    canvas.addEventListener('mousedown', onMousedown);
    canvas.addEventListener('mousemove', onMousemove);
    canvas.addEventListener('mouseup', onMouseup);
    canvas.addEventListener('mouseleave', onMouseleave);

    canvas._editCleanup = (): void => {
        canvas.removeEventListener('mousedown', onMousedown);
        canvas.removeEventListener('mousemove', onMousemove);
        canvas.removeEventListener('mouseup', onMouseup);
        canvas.removeEventListener('mouseleave', onMouseleave);
    };
}

// ---------------------------------------------------------------------------
// confirmTrim — apply the trim and finalize
// ---------------------------------------------------------------------------

export function confirmTrim(seg: Segment, canvas?: SegCanvas | null): void {
    const c = canvas ?? get(editCanvas);
    const tw = c?._trimWindow;
    const newStart = tw?.currentStart;
    const newEnd = tw?.currentEnd;
    if (newStart == null || newEnd == null || newStart >= newEnd) {
        editStatusText.set('Invalid time range');
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
        editStatusText.set('Start overlaps with previous segment');
        return;
    }
    if (nextSeg && nextSeg.audio_url === seg.audio_url && newEnd > nextSeg.time_start) {
        editStatusText.set('End overlaps with next segment');
        return;
    }

    seg.time_start = newStart;
    seg.time_end = newEnd;
    seg.confidence = 1.0;
    const pending = getPendingOp();
    if (pending?.op_context_category) {
        if (!seg.ignored_categories) seg.ignored_categories = [];
        if (!seg.ignored_categories.includes(pending.op_context_category))
            seg.ignored_categories.push(pending.op_context_category);
    }
    markDirty(chapter, undefined, true);

    const trimOp = pending;
    setPendingOp(null);
    if (trimOp) {
        trimOp.applied_at_utc = new Date().toISOString();
        trimOp.targets_after = [snapshotSeg(seg)];
    }

    const curData = get(segData);
    if (chapter !== currentChapter || !curData?.segments) {
        const allData = get(segAllData);
        if (allData) {
            allData._byChapter = null;
            allData._byChapterIndex = null;
        }
    } else {
        syncChapterSegsToAll();
    }

    computeSilenceAfter();
    exitEditMode();
    applyVerseFilterAndRender();
    refreshSegInStore(seg);

    if (trimOp) finalizeOp(chapter, trimOp);

    playStatusText.set('Adjusted (unsaved)');
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
