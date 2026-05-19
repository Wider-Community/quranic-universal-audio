/**
 * Split edit mode: enter, drag handle, preview, confirm.
 *
 * Supports N cursors (length≥1). N=1 = today's binary split (one cursor → two
 * pieces, with Play L/R + click-to-seek). N≥2 = auto-split for repetitions
 * (N cursors → N+1 pieces, with per-region playback and no click-to-seek so
 * cursor drag is unambiguous).
 */

import { get } from 'svelte/store';

import { quranRefs } from '../../../../lib/refs/quran-refs';
import type { Segment } from '../../../../lib/types/domain';
import { getWaveformPeaks } from '../../../../lib/utils/waveform-cache';
import { applyCommand } from '../../domain/apply-command';
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
} from '../../stores/dirty';
import {
    editCanvas,
    editMode,
    pendingChainTargets,
    setEdit,
    setEditCanvas,
    setEditingSegIndex,
    setEditStatusText,
    setSplitPreviewSelection,
    setSplitState,
    splitPreviewSelection,
    updateSplitState,
} from '../../stores/edit';
import { clearFlashForChapter, targetSegmentIndex } from '../../stores/navigation';
import { segPort } from '../../stores/playback';
import type { SegCanvas } from '../../types/segments-waveform';
import { EDIT_MIN_DURATION_MS,EDIT_SNAP_MS } from '../constants';
import {
    _suggestSplitRefs as _suggestSplitRefsLib,
    dkTextForRef,
    getVerseWordCounts,
    parseSegRef,
} from '../data/references';
import { previewLooping, setPreviewLooping } from '../playback/play-range';
import { reconcilePlayingAfterMutation } from '../playback/playback';
import { getRowEntryForMount } from '../playback/row-registry';
import { _ensureSplitBaseCache, drawSplitWaveform } from '../waveform/split-draw';
import { _fetchPeaksForClick } from '../waveform/utils';
import { _playRange, exitEditMode, finalizeEdit } from './common';
import { beginRefEdit, pickProgrammaticMountId } from './reference';
import { applySplitWheelZoom } from './split-zoom';
import { getAudioEndMsForSeg } from './trim';

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
    initialSplits: number[] | null = null,
    initialRefs: string[] | null = null,
): void {
    if (get(editMode)) {
        console.warn('[split] blocked: already in edit mode:', get(editMode));
        return;
    }
    setEdit('split', seg.segment_uid ?? null, mountId);
    setEditingSegIndex(seg.index);
    setEditStatusText('');
    // Default preview selection: left half for binary, first region for
    // multi-cursor. The centralized footer play button loops this range.
    setSplitPreviewSelection(
        initialSplits && initialSplits.length >= 2
            ? { kind: 'region', index: 0 }
            : { kind: 'left' },
    );

    const canvas = row.querySelector<SegCanvas>('canvas');
    if (!canvas) return;

    const mid = Math.round((seg.time_start + seg.time_end) / 2);
    const inSeg = (t: number): boolean => t > seg.time_start && t < seg.time_end;
    // Cursor seed precedence:
    //  - backend-provided initialSplits (auto-split) wins, after clamping
    //    + ascending-sort so two MFA cuts that landed close together don't
    //    inherit a crossed order;
    //  - else paused-playhead at a single midpoint (today's manual flow);
    //  - else seg midpoint.
    let currentSplits: number[];
    if (initialSplits && initialSplits.length > 0) {
        const cleaned = initialSplits
            .map((t) => Math.round(t))
            .filter(inSeg)
            .sort((a, b) => a - b);
        currentSplits = cleaned.length > 0 ? cleaned : [mid];
    } else if (prePausePlayMs !== null && inSeg(prePausePlayMs)) {
        currentSplits = [Math.round(prePausePlayMs)];
    } else {
        currentSplits = [mid];
    }

    canvas._wfCache = null;

    const chapter = seg.chapter || parseInt(get(selectedChapter));
    const splitAudioUrl = seg.audio_url || get(segAllData)?.audio_by_chapter?.[String(chapter)] || '';
    // Cap viewEnd against the authoritative audio EOF — extraction sometimes
    // leaves the last seg's time_end past actual audio EOF, and then asking
    // for peaks for that range returns truncated/empty data and the canvas
    // paints blank. Mirrors the trim-window clamp.
    const audioEndMs = getAudioEndMsForSeg({ ...seg, chapter });
    const cappedViewEnd = audioEndMs && audioEndMs > seg.time_start
        ? Math.min(seg.time_end, audioEndMs)
        : seg.time_end;
    // Init view = full segment range (no zoom). Reset on every entry — zoom
    // state is intentionally not preserved across edit sessions, mirroring
    // trim mode's wheel-zoom semantics.
    canvas._splitData = {
        seg, currentSplits,
        refs: initialRefs && initialRefs.length === currentSplits.length + 1
            ? initialRefs.slice()
            : undefined,
        viewStart: seg.time_start, viewEnd: cappedViewEnd,
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

    if (splitAudioUrl && !getWaveformPeaks(splitAudioUrl)) {
        void _fetchPeaksForClick(seg, chapter).then(() => {
            if (!canvas._splitData) return;
            canvas._splitBaseCache = null;
            drawSplitWaveform(canvas);
        });
    }

    // Auto-split: when MFA pre-placed cursor(s), kick off a region preview
    // so the user hears the boundary without an extra click.
    //  - 1 cursor (binary): play the right half (matches today's cross-verse).
    //  - N≥2 cursors (repetitions): play region 1 (the forward pass).
    const autoSeeded = initialSplits && initialSplits.length > 0;
    if (autoSeeded) {
        if (currentSplits.length === 1) {
            previewSplitAudio('right', canvas);
        } else {
            previewSplitRegion(0, canvas);
        }
    }
}

// ---------------------------------------------------------------------------
// setupSplitDragHandle — mouse event handlers for cursor lines
// ---------------------------------------------------------------------------

/** Per-cursor visual x. Off-view cursors collapse to canvas middle so they
 *  remain grab-targetable; only valid in N=1 (single cursor has no neighbour
 *  to dodge). In N≥2 mode the cursor stays on-canvas by construction (its
 *  neighbour clamp keeps it inside the seg span). */
function _splitXFor(canvas: SegCanvas, idx: number): number {
    const sd = canvas._splitData!;
    const t = sd.currentSplits[idx]!;
    const w = canvas.width;
    const span = sd.viewEnd - sd.viewStart;
    if (sd.currentSplits.length === 1
            && (t < sd.viewStart || t > sd.viewEnd)) {
        return w / 2;
    }
    return ((t - sd.viewStart) / span) * w;
}

export function setupSplitDragHandle(canvas: SegCanvas, seg: Segment): void {
    let dragging = false;
    let didDrag = false;
    let dragIdx: number | null = null;

    function _pickCursorIdx(x: number): number | null {
        const sd = canvas._splitData;
        if (!sd) return null;
        let best: number | null = null;
        let bestDist = 15;
        for (let i = 0; i < sd.currentSplits.length; i++) {
            const d = Math.abs(x - _splitXFor(canvas, i));
            if (d < bestDist) { bestDist = d; best = i; }
        }
        return best;
    }

    function onMousedown(e: MouseEvent): void {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const sd = canvas._splitData;
        if (!sd) return;
        didDrag = false;
        const idx = _pickCursorIdx(x);
        if (idx !== null) {
            dragging = true;
            dragIdx = idx;
            canvas.style.cursor = 'col-resize';
        }
    }

    function onMousemove(e: MouseEvent): void {
        const rect = canvas.getBoundingClientRect();
        const x = (e.clientX - rect.left) * (canvas.width / rect.width);
        const sd = canvas._splitData;
        if (!sd) return;

        if (!dragging) {
            canvas.style.cursor = _pickCursorIdx(x) !== null ? 'col-resize' : 'pointer';
            return;
        }
        if (dragIdx === null) return;
        didDrag = true;
        // Pixel→time uses the visible window; clamp the dragged cursor so it
        // can't cross its neighbours (the previous/next cursor — or the seg
        // start/end at the array ends).
        const timeAtX = sd.viewStart + (x / canvas.width) * (sd.viewEnd - sd.viewStart);
        const snapped = Math.round(timeAtX / EDIT_SNAP_MS) * EDIT_SNAP_MS;
        const minDur = EDIT_MIN_DURATION_MS;
        const lo = (dragIdx > 0 ? sd.currentSplits[dragIdx - 1]! : seg.time_start) + minDur;
        const hi = (dragIdx < sd.currentSplits.length - 1
                    ? sd.currentSplits[dragIdx + 1]!
                    : seg.time_end) - minDur;
        const next = Math.max(lo, Math.min(snapped, hi));
        sd.currentSplits[dragIdx] = next;
        // Force a new array reference so derivedEq subscribers re-fire.
        const cursors = sd.currentSplits.slice();
        updateSplitState((s) => s ? { ...s, currentSplits: cursors } : s);
        drawSplitWaveform(canvas);
    }

    function onMouseup(e: MouseEvent): void {
        if (!dragging && !didDrag) {
            const sd = canvas._splitData;
            // Click-to-seek only meaningful in single-cursor mode; in multi
            // mode the per-region buttons own playback and a stray canvas
            // click is intentionally inert.
            if (sd && sd.currentSplits.length === 1) {
                const rect = canvas.getBoundingClientRect();
                const x = (e.clientX - rect.left) * (canvas.width / rect.width);
                const timeAtX = sd.viewStart + (x / canvas.width) * (sd.viewEnd - sd.viewStart);
                const split = sd.currentSplits[0]!;
                if (timeAtX < split) _playRange(timeAtX, split);
                else _playRange(timeAtX, seg.time_end);
            }
        }
        dragging = false;
        dragIdx = null;
        canvas.style.cursor = '';
    }
    function onMouseleave(): void { dragging = false; dragIdx = null; canvas.style.cursor = ''; }

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
// nudgeSplitBoundary — step the single-cursor by ±deltaMs (SplitPanel only)
// ---------------------------------------------------------------------------

/**
 * Move the single split cursor by `deltaMs`, clamped to
 * `[seg.time_start + EDIT_MIN_DURATION_MS, seg.time_end - EDIT_MIN_DURATION_MS]`.
 *
 * Only meaningful in N=1 (binary) mode — N≥2 mode hides the stepper
 * controls because there's no obvious "the cursor" to step. Callers that
 * invoke this in multi-mode get a no-op return of `null`.
 */
export function nudgeSplitBoundary(deltaMs: number): number | null {
    const canvas = get(editCanvas);
    const sd = canvas?._splitData;
    if (!canvas || !sd || sd.currentSplits.length !== 1) return null;
    const { seg } = sd;
    const minDur = EDIT_MIN_DURATION_MS;
    const cur = sd.currentSplits[0]!;
    const onView = cur >= sd.viewStart && cur <= sd.viewEnd;
    const anchor: number = onView ? cur : (sd.viewStart + sd.viewEnd) / 2;
    const next = Math.max(
        seg.time_start + minDur,
        Math.min(anchor + deltaMs, seg.time_end - minDur),
    );
    if (next === cur) return next;
    sd.currentSplits[0] = next;
    const cursors = sd.currentSplits.slice();
    updateSplitState((s) => s ? { ...s, currentSplits: cursors } : s);
    drawSplitWaveform(canvas);
    return next;
}

// ---------------------------------------------------------------------------
// confirmSplit — apply the split and chain ref editing
// ---------------------------------------------------------------------------

export function confirmSplit(
    seg: Segment,
    canvas?: SegCanvas | null,
    mountId: symbol | null = null,
): void {
    const c = canvas ?? get(editCanvas);
    const sd = c?._splitData;
    if (!c || !sd) return;
    const cursors = sd.currentSplits;
    if (!cursors.length) return;
    // Reject any cursor that crept outside the seg span. Should be impossible
    // given the drag clamp, but guard anyway.
    for (let i = 0; i < cursors.length; i++) {
        const ci = cursors[i]!;
        if (ci <= seg.time_start || ci >= seg.time_end) return;
        if (i > 0 && ci <= cursors[i - 1]!) return;
    }

    const chStr = get(selectedChapter);
    const chapter = seg.chapter || parseInt(chStr);
    const currentChapter = parseInt(chStr);
    const curData = get(segData);
    const useSegData = chapter === currentChapter && curData?.segments;
    const initiatingEntry = mountId
        ? getRowEntryForMount(chapter, seg.index, mountId)
        : null;

    const prePlayingUid = seg.segment_uid ?? null;

    const splitOp = getPendingOp();
    const ctxCat = splitOp?.op_context_category ?? null;
    const uid = seg.segment_uid;
    if (!uid) return;

    // Resolve per-section refs + text. Auto-split provides refs[] directly
    // (cross-verse N=2 or repetition N≥2); otherwise fall back to today's
    // cross-verse N=2 suggestion (single cursor case). Refs and texts have
    // the same length as the produced segment list (= cursors.length + 1).
    const dk = get(quranRefs)?.dk_words;
    const vwc = getVerseWordCounts();
    let refs: (string | undefined)[] = new Array(cursors.length + 1).fill(undefined);
    let texts: (string | undefined)[] = new Array(cursors.length + 1).fill(undefined);
    if (sd.refs && sd.refs.length === cursors.length + 1) {
        refs = sd.refs.slice();
        texts = refs.map((r) => r ? dkTextForRef(r, dk, vwc) : undefined);
    } else if (cursors.length === 1) {
        const suggested = _suggestSplitRefs(seg.matched_ref);
        if (suggested) {
            refs[0] = suggested.first;
            refs[1] = suggested.second;
            texts[0] = dkTextForRef(suggested.first, dk, vwc);
            texts[1] = dkTextForRef(suggested.second, dk, vwc);
        }
    }

    const newUids = cursors.map(() => crypto.randomUUID());
    const result = applyCommand(
        {
            byId: { [uid]: seg },
            idsByChapter: { [chapter]: [uid] },
            selectedChapter: chapter,
        },
        {
            type: 'split',
            segmentUid: uid,
            splitMs: cursors.slice(),
            newUids,
            refs,
            texts,
            sourceCategory: ctxCat ?? undefined,
            contextCategory: ctxCat ?? undefined,
        },
    );

    // Reducer produces N+1 segments. The first reuses `uid` (first half);
    // subsequent halves use `newUids[i-1]`. Pull them all out in order.
    const pieces: Segment[] = [];
    pieces.push(result.nextState.byId[uid] as Segment);
    for (const u of newUids) {
        pieces.push(result.nextState.byId[u] as Segment);
    }
    if (pieces.some((p) => !p)) return;

    if (useSegData && curData) {
        const segIdx = curData.segments.findIndex(s => s.index === seg.index);
        curData.segments.splice(segIdx, 1, ...pieces);
        curData.segments.forEach((s, i) => { s.index = i; });
        syncChapterSegsToAll();
        curData.segments = getChapterSegments(chapter);
    } else {
        const allData = get(segAllData);
        if (allData) {
            const globalIdx = allData.segments.findIndex(s => s.segment_uid === seg.segment_uid);
            if (globalIdx !== -1) {
                allData.segments.splice(globalIdx, 1, ...pieces);
            }
            let reIdx = 0;
            allData.segments.forEach(s => { if (s.chapter === chapter) s.index = reIdx++; });
            invalidateChapterIndexFor(chapter);
        }
    }

    reconcilePlayingAfterMutation(chapter, prePlayingUid);
    clearFlashForChapter(chapter);

    markDirty(chapter, undefined, true);

    exitEditMode();
    finalizeEdit(result.operation, chapter, pieces, { patch: result.patch });

    const chainCat = ctxCat;

    if (initiatingEntry?.instanceRole !== 'accordion') {
        targetSegmentIndex.set({ chapter, index: pieces[0]!.index });
    }

    const resolvedMountId = mountId ?? pickProgrammaticMountId(chapter, pieces[0]!.index);
    if (!resolvedMountId) return;

    // Chain ref edits for every piece after the first. Each one shifts the
    // queue head and seeds `beginRefEdit` with the next segment + its own
    // per-piece originalEnd anchor (used for the trailing endpoint when the
    // user edits the prior piece's ref).
    //
    // Use each piece's OWN matched_ref end as its anchor — not the parent
    // seg's full end. For binary cross-verse (N+1=2 pieces) the second piece's
    // ref ends at the parent's end, so the two coincide. For N+1≥3 (auto-split
    // across 3+ verses), each non-final piece's correct anchor is the end of
    // its own verse — otherwise the chain prefill spans `verse_i_start -
    // last_verse_end` instead of `verse_i_start - verse_i_end`, breaking the
    // per-verse-resolution pattern the binary case already has.
    // For cross-verse splits, attach a waslFlashForLeftUid pointer on each
    // chain entry. _handoffPendingChain reads this to briefly flash the
    // WaslGap chip between the previous piece and this one — drawing the
    // reviewer's eye to the new inter-piece boundary as the ref-edit chain
    // walks through. No modal; the chip is the toggle. Non-CV splits leave
    // the field unset.
    const isCrossVerseSplit = chainCat === 'cross_verse';
    const queue = pieces.slice(1).map((p, i) => {
        const pParsed = parseSegRef(p.matched_ref);
        const originalEndRef = pParsed
            ? `${pParsed.surah}:${pParsed.ayah_to}:${pParsed.word_to}`
            : null;
        const prevPiece = pieces[i]!;
        return {
            seg: p,
            category: chainCat,
            originalEndRef,
            ...(isCrossVerseSplit && prevPiece.segment_uid
                ? { waslFlashForLeftUid: prevPiece.segment_uid }
                : {}),
        };
    });
    pendingChainTargets.set(queue);
    beginRefEdit(pieces[0]!, chainCat, resolvedMountId);
}

// ---------------------------------------------------------------------------
// previewSplitAudio — toggle looping preview of left/right half (N=1 only)
// ---------------------------------------------------------------------------

export function previewSplitAudio(side: 'left' | 'right', canvas?: SegCanvas | null): void {
    const c = canvas ?? get(editCanvas);
    const sd = c?._splitData;
    if (!sd || !c || sd.currentSplits.length !== 1) return;
    setPreviewLooping(`split-${side}` as const);
    const splitTime = sd.currentSplits[0]!;
    _playRange(
        side === 'left' ? sd.seg.time_start : splitTime,
        side === 'left' ? splitTime : sd.seg.time_end,
    );
}

// ---------------------------------------------------------------------------
// previewSplitRegion — loop a single region for the N≥2 multi-cursor flow
// ---------------------------------------------------------------------------

/** Loop region ``i`` (0-indexed) of the split. Region ``i`` runs from
 *  ``currentSplits[i-1] ?? seg.time_start`` to ``currentSplits[i] ?? seg.time_end``,
 *  so for N cursors there are N+1 regions. Sets the play-range loop key to
 *  ``'split-region-{i}'`` so the play-range RAF re-seeks correctly across
 *  cursor edits while looping. */
export function previewSplitRegion(idx: number, canvas?: SegCanvas | null): void {
    const c = canvas ?? get(editCanvas);
    const sd = c?._splitData;
    if (!sd || !c) return;
    const n = sd.currentSplits.length;
    if (idx < 0 || idx > n) return;
    const start = idx === 0 ? sd.seg.time_start : sd.currentSplits[idx - 1]!;
    const end = idx === n ? sd.seg.time_end : sd.currentSplits[idx]!;
    setPreviewLooping(`split-region-${idx}` as `split-region-${number}`);
    _playRange(start, end);
}

// ---------------------------------------------------------------------------
// previewSplitFromSelection — dispatch from the centralized footer play
// ---------------------------------------------------------------------------

/** Toggle the split-mode preview loop based on the current
 *  `splitPreviewSelection`. Acts as a play/pause for the selected range —
 *  pressing while the same range is already looping pauses; pressing again
 *  resumes. Called by the footer's `handlePlayClick` when `editMode ===
 *  'split'`, replacing the per-side / per-region play buttons that used to
 *  live in `SplitPanel.svelte`. */
export function previewSplitFromSelection(canvas?: SegCanvas | null): void {
    const c = canvas ?? get(editCanvas);
    const sd = c?._splitData;
    if (!sd || !c) return;
    const sel = get(splitPreviewSelection);
    const isBinary = sd.currentSplits.length === 1;

    // Toggle: if already looping the SAME selection, pause and clear.
    // Otherwise start (or switch to) the selected range loop.
    const curLoop = get(previewLooping);
    const desiredKey: string = sel.kind === 'region'
        ? `split-region-${sel.index}`
        : `split-${sel.kind}`;
    if (curLoop === desiredKey && !segPort.paused) {
        segPort.pause();
        return;
    }

    if (isBinary) {
        const side: 'left' | 'right' = sel.kind === 'region'
            ? (sel.index === 0 ? 'left' : 'right')
            : sel.kind;
        previewSplitAudio(side, c);
        return;
    }

    // Multi-cursor: normalize a left/right selection to region 0 / last.
    const n = sd.currentSplits.length;
    const idx = sel.kind === 'region'
        ? Math.max(0, Math.min(n, sel.index))
        : (sel.kind === 'left' ? 0 : n);
    previewSplitRegion(idx, c);
}
