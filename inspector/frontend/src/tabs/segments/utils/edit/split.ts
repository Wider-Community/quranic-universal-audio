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
    selectedReciter,
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
    setEditingSegIndex,
    setEditStatusText,
    setSplitState,
    updateSplitState,
} from '../../stores/edit';
import { clearFlashForChapter, targetSegmentIndex } from '../../stores/navigation';
import { segAudioElement } from '../../stores/playback';
import type { SegCanvas } from '../../types/segments-waveform';
import { EDIT_MIN_DURATION_MS,EDIT_SNAP_MS } from '../constants';
import { _suggestSplitRefs as _suggestSplitRefsLib, getVerseWordCounts } from '../data/references';
import {
    clearPlayRangeRAF,
    getPreviewLooping,
    setPreviewJustSeeked,
    setPreviewLooping,
} from '../playback/play-range';
import { reconcilePlayingAfterMutation } from '../playback/playback';
import { _fixupValIndicesForSplit } from '../validation/fixups';
import { _ensureSplitBaseCache, drawSplitWaveform } from '../waveform/split-draw';
import { _fetchChapterPeaksIfNeeded } from '../waveform/utils';
import { _playRange, exitEditMode, finalizeEdit } from './common';
import { beginRefEdit, pickProgrammaticMountId } from './reference';

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
    canvas._splitData = { seg, currentSplit: defaultSplit, audioUrl: splitAudioUrl };
    setSplitState({ ...canvas._splitData });
    canvas._splitBaseCache = null;
    drawSplitWaveform(canvas);
    setupSplitDragHandle(canvas, seg);

    // Pre-fetch peaks for the segment being split if not available.
    if (splitAudioUrl && !getWaveformPeaks(splitAudioUrl)) {
        _fetchChapterPeaksIfNeeded(get(selectedReciter), chapter);
    }
}

// ---------------------------------------------------------------------------
// setupSplitDragHandle — mouse event handlers for split line
// ---------------------------------------------------------------------------

export function setupSplitDragHandle(canvas: SegCanvas, seg: Segment): void {
    let dragging = false;
    let didDrag = false;

    function onMousedown(e: MouseEvent): void {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const sd = canvas._splitData;
        if (!sd) return;
        const splitX = ((sd.currentSplit - seg.time_start) / (seg.time_end - seg.time_start)) * canvas.width;
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
        const splitX = ((sd.currentSplit - seg.time_start) / (seg.time_end - seg.time_start)) * canvas.width;

        if (!dragging) {
            canvas.style.cursor = Math.abs(x - splitX) < 15 ? 'col-resize' : 'pointer';
            return;
        }
        didDrag = true;
        const timeAtX = seg.time_start + (x / canvas.width) * (seg.time_end - seg.time_start);
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
            const timeAtX = seg.time_start + (x / canvas.width) * (seg.time_end - seg.time_start);
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

    const splitOp = getPendingOp();
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
    targetSegmentIndex.set({ chapter, index: firstHalf.index });

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
