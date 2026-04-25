/**
 * Split edit mode: enter, drag handle, preview, confirm.
 */

import { get } from 'svelte/store';

import { fetchJsonOrNull } from '../../../../lib/api';
import type { SegResolveRefResponse } from '../../../../lib/types/api';
import type { Segment } from '../../../../lib/types/domain';
import { getWaveformPeaks } from '../../../../lib/utils/waveform-cache';
import {
    getChapterSegments,
    invalidateChapterIndexFor,
    segAllData,
    segData,
    selectedChapter,
    syncChapterSegsToAll,
} from '../../stores/chapter';
import {
    getPendingOp,
    markDirty,
    setPendingOp,
} from '../../stores/dirty';
import {
    editCanvas,
    editMode,
    pendingChainTarget,
    setEdit,
    setEditCanvas,
    setEditingSegIndex,
    setEditStatusText,
    setSplitState,
    updateSplitState,
} from '../../stores/edit';
import { clearFlashForChapter, targetSegmentIndex } from '../../stores/navigation';
import { segAudioElement } from '../../stores/playback';
import type { SegCanvas } from '../../types/segments-waveform';
import { applyAutoSuppress } from '../../domain/registry';
import { EDIT_MIN_DURATION_MS,EDIT_SNAP_MS } from '../constants';
import { _suggestSplitRefs as _suggestSplitRefsLib, getVerseWordCounts } from '../data/references';
import {
    clearPlayRangeRAF,
    getPreviewLooping,
    setPreviewJustSeeked,
    setPreviewLooping,
} from '../playback/play-range';
import { reconcilePlayingAfterMutation } from '../playback/playback';
import { getRowEntryForMount } from '../playback/row-registry';
import { _fixupValIndicesForSplit } from '../validation/fixups';
import { _ensureSplitBaseCache, drawSplitWaveform } from '../waveform/split-draw';
import { _fetchPeaksForClick } from '../waveform/utils';
import { _playRange, exitEditMode, finalizeEdit } from './common';
import { beginRefEdit, pickProgrammaticMountId } from './reference';
import { applySplitWheelZoom } from './split-zoom';

function _suggestSplitRefs(ref: Parameters<typeof _suggestSplitRefsLib>[0]): ReturnType<typeof _suggestSplitRefsLib> {
    return _suggestSplitRefsLib(ref, getVerseWordCounts());
}

// Re-export draw functions for registration sites.
export { _ensureSplitBaseCache, drawSplitWaveform };

// ---------------------------------------------------------------------------
// enterSplitMode
// ---------------------------------------------------------------------------

export function enterSplitMode(
    seg: Segment,
    row: HTMLElement,
    prePausePlayMs: number | null = null,
    mountId: symbol | null = null,
): void {
    if (get(editMode)) {
        console.warn('[split] blocked: already in edit mode:', get(editMode));
        return;
    }
    setEdit('split', seg.segment_uid ?? null, mountId);
    setEditingSegIndex(seg.index);
    setEditStatusText('');

    const canvas = row.querySelector<SegCanvas>('canvas');
    if (!canvas) return;

    const mid = Math.round((seg.time_start + seg.time_end) / 2);
    const defaultSplit = (prePausePlayMs !== null && prePausePlayMs > seg.time_start && prePausePlayMs < seg.time_end)
        ? Math.round(prePausePlayMs)
        : mid;

    canvas._wfCache = null;

    const chapter = seg.chapter || parseInt(get(selectedChapter));
    const splitAudioUrl = seg.audio_url || get(segAllData)?.audio_by_chapter?.[String(chapter)] || '';
    // Init view = full segment range (no zoom). Reset on every entry — zoom
    // state is intentionally not preserved across edit sessions, mirroring
    // trim mode's wheel-zoom semantics.
    canvas._splitData = {
        seg, currentSplit: defaultSplit,
        viewStart: seg.time_start, viewEnd: seg.time_end,
        audioUrl: splitAudioUrl,
    };
    setSplitState({ ...canvas._splitData });
    canvas._splitBaseCache = null;
    // Populate editCanvas store synchronously so click-to-seek in the drag
    // handler (below) reads a non-null canvas on the first user click, before
    // SegmentRow's reactive setEditCanvas has fired. Same rationale as
    // enterTrimMode — avoids the rAF-on-null-canvas no-op.
    setEditCanvas(canvas);
    drawSplitWaveform(canvas);
    setupSplitDragHandle(canvas, seg);

    // Click-time peaks fetch — same pattern as enterTrimMode. Previously only
    // a chapter-level prefetch fired (_fetchChapterPeaksIfNeeded), which on a
    // cold cache left the canvas showing "No waveform data" until the full
    // chapter peaks arrived (or never, if the chapter audio URL wasn't in the
    // audio_by_chapter map). `_fetchPeaksForClick` grabs peaks for this one
    // seg's padded range quickly, then we redraw the split canvas in place.
    // Guarded against the user exiting split mode mid-fetch.
    if (splitAudioUrl && !getWaveformPeaks(splitAudioUrl)) {
        void _fetchPeaksForClick(seg, chapter).then(() => {
            if (!canvas._splitData) return;
            canvas._splitBaseCache = null;
            drawSplitWaveform(canvas);
        });
    }
}

// ---------------------------------------------------------------------------
// setupSplitDragHandle — mouse event handlers for split line
// ---------------------------------------------------------------------------

export function setupSplitDragHandle(canvas: SegCanvas, seg: Segment): void {
    let dragging = false;
    let didDrag = false;

    /** Visual x-coord of the split cursor. When the cursor's actual time falls
     *  outside the visible window, it visually clamps to the canvas MIDDLE so
     *  the user can still grab + drag it. (Trim clamps to edges because it has
     *  paired cursors with distinct start/end semantics; split has one cursor,
     *  and middle-clamping keeps both stepper directions productive — mid +
     *  delta lands inside the view going either way.) */
    function _getSplitX(): number {
        const sd = canvas._splitData!;
        const w = canvas.width;
        const span = sd.viewEnd - sd.viewStart;
        if (sd.currentSplit < sd.viewStart || sd.currentSplit > sd.viewEnd) return w / 2;
        return ((sd.currentSplit - sd.viewStart) / span) * w;
    }

    function onMousedown(e: MouseEvent): void {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const sd = canvas._splitData;
        if (!sd) return;
        const splitX = _getSplitX();
        didDrag = false;
        if (Math.abs(x - splitX) < 15) {
            dragging = true;
            canvas.style.cursor = 'col-resize';
        }
    }

    function onMousemove(e: MouseEvent): void {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const sd = canvas._splitData;
        if (!sd) return;
        const splitX = _getSplitX();

        if (!dragging) {
            canvas.style.cursor = Math.abs(x - splitX) < 15 ? 'col-resize' : 'pointer';
            return;
        }
        didDrag = true;
        // Pixel→time uses the VISIBLE window so dragging a middle-clamped
        // cursor jumps actual to the dragged pixel's time. Final boundary
        // still clamps to [seg.time_start + minDur, seg.time_end - minDur].
        const timeAtX = sd.viewStart + (x / canvas.width) * (sd.viewEnd - sd.viewStart);
        const snapped = Math.round(timeAtX / EDIT_SNAP_MS) * EDIT_SNAP_MS;
        sd.currentSplit = Math.max(seg.time_start + EDIT_MIN_DURATION_MS, Math.min(snapped, seg.time_end - EDIT_MIN_DURATION_MS));
        updateSplitState((s) => s ? { ...s, currentSplit: sd.currentSplit } : s);
        drawSplitWaveform(canvas);
    }

    function onMouseup(e: MouseEvent): void {
        if (!dragging && !didDrag) {
            const rect = canvas.getBoundingClientRect();
            const x = (e.clientX - rect.left) * (canvas.width / rect.width);
            const sd = canvas._splitData;
            if (!sd) return;
            // Click-to-seek also uses the visible window for pixel→time.
            const timeAtX = sd.viewStart + (x / canvas.width) * (sd.viewEnd - sd.viewStart);
            if (timeAtX < sd.currentSplit) {
                _playRange(timeAtX, sd.currentSplit);
            } else {
                _playRange(timeAtX, seg.time_end);
            }
        }
        dragging = false;
        canvas.style.cursor = '';
    }
    function onMouseleave(): void { dragging = false; canvas.style.cursor = ''; }

    /** Wheel zoom on the split canvas. Suppressed mid-drag to avoid surprising
     *  rescaling underneath an in-flight drag. `passive: false` lets us call
     *  `preventDefault()` so the wheel doesn't scroll the page. */
    function onWheel(e: WheelEvent): void {
        if (dragging) return;
        e.preventDefault();
        applySplitWheelZoom(canvas, e.clientX, e.deltaY);
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
// nudgeSplitBoundary — step the split cursor by ±deltaMs (called by SplitPanel)
// ---------------------------------------------------------------------------

/**
 * Move the split cursor by `deltaMs`, clamped to
 * `[seg.time_start + EDIT_MIN_DURATION_MS, seg.time_end - EDIT_MIN_DURATION_MS]`.
 * Mirrors the live drag flow: writes both the store (for Svelte subscribers —
 * SplitPanel L/R readout) and the canvas-local `_splitData` (for the
 * imperative draw + drag-handle math), then redraws.
 *
 * **Snap-to-visual-middle** (zoom complement): when the cursor is currently
 * OFF-VIEW (`currentSplit` outside `[viewStart, viewEnd]` because the user
 * zoomed in past it), the step is anchored at the cursor's *visual* clamp
 * position — the middle of the view — rather than its actual time. So
 * pressing `>` on an off-view cursor lands at `(viewStart+viewEnd)/2 + 50`
 * regardless of how far off-view the actual time was, popping the cursor
 * back into view. Mirrors trim's snap-to-edge semantics; differs only in
 * the anchor location (middle for split's single cursor, edges for trim's
 * paired cursors).
 *
 * Returns the new split position (or the unchanged value if clamping
 * prevented motion). UI uses the bounds arithmetic directly to decide when
 * to disable the corresponding stepper button.
 */
export function nudgeSplitBoundary(deltaMs: number): number | null {
    const canvas = get(editCanvas);
    const sd = canvas?._splitData;
    if (!canvas || !sd) return null;
    const { seg } = sd;
    const minDur = EDIT_MIN_DURATION_MS;
    const onView = sd.currentSplit >= sd.viewStart && sd.currentSplit <= sd.viewEnd;
    const anchor = onView ? sd.currentSplit : (sd.viewStart + sd.viewEnd) / 2;
    const next = Math.max(
        seg.time_start + minDur,
        Math.min(anchor + deltaMs, seg.time_end - minDur),
    );
    if (next === sd.currentSplit) return next;
    sd.currentSplit = next;
    updateSplitState((s) => s ? { ...s, currentSplit: next } : s);
    drawSplitWaveform(canvas);
    return next;
}

// ---------------------------------------------------------------------------
// confirmSplit — apply the split and chain ref editing
// ---------------------------------------------------------------------------

export async function confirmSplit(
    seg: Segment,
    canvas?: SegCanvas | null,
    mountId: symbol | null = null,
): Promise<void> {
    const c = canvas ?? get(editCanvas);
    const splitTime = c?._splitData?.currentSplit;
    if (splitTime == null || splitTime <= seg.time_start || splitTime >= seg.time_end) {
        return;
    }

    const chStr = get(selectedChapter);
    const chapter = seg.chapter || parseInt(chStr);
    const currentChapter = parseInt(chStr);
    const curData = get(segData);
    const useSegData = chapter === currentChapter && curData?.segments;
    const initiatingEntry = mountId
        ? getRowEntryForMount(chapter, seg.index, mountId)
        : null;

    // Capture the pre-mutation playing UID so reconcilePlayingAfterMutation can
    // refresh the active pair if the playing seg's index shifts due to reindex.
    const prePlayingUid = seg.segment_uid ?? null;

    // UID preservation: firstHalf inherits the parent's UID so accordion twins
    // (keyed by UID) stay bound; secondHalf gets a fresh one. Deep-copy the
    // ignored_categories array on both halves so later mutations (e.g. Ignore
    // button on one half) don't alias and bleed into the other.
    const firstHalf: Segment = {
        ...seg,
        segment_uid: seg.segment_uid,
        time_end: splitTime,
        ignored_categories: [...(seg.ignored_categories || [])],
    };
    const secondHalf: Segment = {
        ...seg,
        segment_uid: crypto.randomUUID(),
        index: seg.index + 1,
        time_start: splitTime,
        ignored_categories: [...(seg.ignored_categories || [])],
    };
    const splitOp = getPendingOp();
    const ctxCat = splitOp?.op_context_category;
    if (ctxCat) {
        applyAutoSuppress(firstHalf, ctxCat, 'card');
        applyAutoSuppress(secondHalf, ctxCat, 'card');
    }

    // Auto-suggest per-verse refs for cross-verse splits.
    //
    // Invariant: `matched_ref` and `matched_text` / `display_text` MUST be
    // updated together. If resolve_ref fails for a half, we clear the text
    // fields instead of leaving them to inherit the pre-split cross-verse
    // text via the `...seg` spread — otherwise the row would render the new
    // (per-verse) ref with the original cross-verse body text, which is the
    // exact kind of divergence we're trying to eliminate.
    const suggested = _suggestSplitRefs(seg.matched_ref);
    if (suggested) {
        firstHalf.matched_ref = suggested.first;
        secondHalf.matched_ref = suggested.second;
        const [r1, r2] = await Promise.allSettled([
            fetchJsonOrNull<SegResolveRefResponse>(`/api/seg/resolve_ref?ref=${encodeURIComponent(suggested.first)}`),
            fetchJsonOrNull<SegResolveRefResponse>(`/api/seg/resolve_ref?ref=${encodeURIComponent(suggested.second)}`),
        ]);
        if (r1.status === 'fulfilled' && r1.value?.text) {
            firstHalf.matched_text = r1.value.text;
            firstHalf.display_text = r1.value.display_text || r1.value.text;
        } else {
            firstHalf.matched_text = '';
            firstHalf.display_text = '';
        }
        if (r2.status === 'fulfilled' && r2.value?.text) {
            secondHalf.matched_text = r2.value.text;
            secondHalf.display_text = r2.value.display_text || r2.value.text;
        } else {
            secondHalf.matched_text = '';
            secondHalf.display_text = '';
        }
    }

    setPendingOp(null);

    if (useSegData && curData) {
        const segIdx = curData.segments.findIndex(s => s.index === seg.index);
        curData.segments.splice(segIdx, 1, firstHalf, secondHalf);
        curData.segments.forEach((s, i) => { s.index = i; });
        syncChapterSegsToAll();
        curData.segments = getChapterSegments(chapter);
    } else {
        const allData = get(segAllData);
        if (allData) {
            // Identity via UID (not object reference) — a prior mutation can
            // have replaced the seg object with a structurally-equal clone,
            // making indexOf miss. UID lookup is stable across refreshes.
            const globalIdx = allData.segments.findIndex(s => s.segment_uid === seg.segment_uid);
            if (globalIdx !== -1) {
                allData.segments.splice(globalIdx, 1, firstHalf, secondHalf);
            }
            let reIdx = 0;
            allData.segments.forEach(s => { if (s.chapter === chapter) s.index = reIdx++; });
            invalidateChapterIndexFor(chapter);
        }
    }

    // Post-reindex reconciliation: playing pair (if any) + flash keys must be
    // recomputed against the new indices before finalizeEdit runs.
    reconcilePlayingAfterMutation(chapter, prePlayingUid);
    clearFlashForChapter(chapter);

    markDirty(chapter, undefined, true);
    _fixupValIndicesForSplit(chapter, seg.index);

    exitEditMode();
    if (splitOp) {
        finalizeEdit(splitOp, chapter, [firstHalf, secondHalf]);
    }

    const chainCat = splitOp?.op_context_category || null;

    // Scroll to the first half via the store-driven path. The main-list
    // SegmentRow reactive (`instanceRole === 'main'`) observes
    // `targetSegmentIndex` and calls scrollIntoView post-flush without
    // needing a querySelector — accordion / history / preview twins for
    // the same index are gated out by their `instanceRole` so only the
    // real main-list row reacts.
    if (initiatingEntry?.instanceRole !== 'accordion') {
        targetSegmentIndex.set({ chapter, index: firstHalf.index });
    }

    // Resolve the initiating mount. When the caller passed one (click on a
    // row's Split button, SplitPanel confirm forwarding $editingMountId),
    // that's the one to claim. For keyboard-initiated confirm or any other
    // path with mountId=null, look up firstHalf's currently-mounted rows
    // and prefer an accordion mount, falling back to main. If NO row is
    // mounted (user navigated away mid-edit) we must not fire beginRefEdit
    // — an unclaimed setEdit('reference', ...) leaves editMode stuck and
    // silently swallows the next Split/Adjust/Edit Ref click. In that case
    // skip the chain queue too so commitRefEdit (which will never run for
    // firstHalf here) doesn't also attempt a stale secondHalf handoff.
    const resolvedMountId = mountId ?? pickProgrammaticMountId(chapter, firstHalf.index);
    if (!resolvedMountId) return;

    // Chain the second-half ref edit via direct handoff. `pendingChainTarget`
    // is consumed by `commitRefEdit` after the firstHalf edit resolves —
    // replaces the prior reactive-store chain that raced with `$editMode`
    // settling in SegmentRow.
    pendingChainTarget.set({ seg: secondHalf, category: chainCat });
    beginRefEdit(firstHalf, chainCat, resolvedMountId);
}

// ---------------------------------------------------------------------------
// previewSplitAudio — toggle looping preview of left/right half
// ---------------------------------------------------------------------------

export function previewSplitAudio(side: 'left' | 'right', canvas?: SegCanvas | null): void {
    const c = canvas ?? get(editCanvas);
    const sd = c?._splitData;
    if (!sd || !c) return;
    const loopKey = `split-${side}` as const;
    const audioEl = get(segAudioElement);
    if (getPreviewLooping() === loopKey && audioEl && !audioEl.paused) {
        setPreviewLooping(false);
        setPreviewJustSeeked(false);
        audioEl.pause();
        clearPlayRangeRAF();
        if (c._splitData) drawSplitWaveform(c);
        return;
    }
    setPreviewLooping(loopKey);
    const splitTime = sd.currentSplit;
    _playRange(
        side === 'left' ? sd.seg.time_start : splitTime,
        side === 'left' ? splitTime : sd.seg.time_end
    );
}
