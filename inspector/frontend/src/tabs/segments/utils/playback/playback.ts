/**
 * Audio playback, animation, highlight tracking, and play status.
 *
 * Boundary enforcement and rAF-driven playhead drawing live in the unified
 * `AudioRange` primitive (`lib/playback/audio-range.ts`). This module is the
 * caller — it constructs the range from the active segment + autoplay state,
 * wires `onTick` / `onBoundary` to the local stores, and explicitly disposes
 * the range on edit-mode entry and per-reciter resets.
 *
 * `startSegAnimation` / `stopSegAnimation` are UI-state-only helpers driven
 * by the audio element's `play` / `pause` DOM events; they no longer own a
 * rAF loop and never touch `_segRange`. Explicit teardown is `disposeSegRange()`.
 */

import { get } from 'svelte/store';

import { AudioRange } from '../../../../lib/playback/audio-range';
import { audioSrcMatches } from '../../../../lib/utils/audio';
import {
    getSegByChapterIndex,
    segAllData,
    segCurrentIdx,
    selectedChapter,
} from '../../stores/chapter';
import { editMode } from '../../stores/edit';
import { displayedSegments } from '../../stores/filters';
import {
    activeAudioSource,
    autoPlayEnabled,
    continuousPlay,
    isMainAudioPlaying,
    playbackSpeed,
    playButtonLabel,
    playEndMs,
    playingSegmentIndex,
    segAudioElement,
    setPlayingSegment,
} from '../../stores/playback';
import { drawSegPlayhead, drawWaveformFromPeaksForSeg } from '../waveform/draw-seg';
import { _fetchPeaksForClick } from '../waveform/utils';
import { nextDisplayedSeg, prefetchNextSegAudio } from './prefetch';
import { buildSegPolicy, buildSegRangeSpec } from './range-spec';
import { getRowEntriesFor } from './row-registry';

// ---------------------------------------------------------------------------
// Module-local state
// ---------------------------------------------------------------------------

let _segRange: AudioRange | null = null;
let _segPrefetchCache: Record<string, Promise<unknown>> = {};

/** Last drawn (chapter, index) pair so the animation loop can erase the
 *  playhead on the previous row when playback advances. Carries the chapter
 *  so cross-chapter advance (accordion -> another chapter's row) erases from
 *  the right canvas. */
let _prevPlaying: { chapter: number; index: number } | null = null;

/** Reset the per-reciter prefetch cache (called by reciter/chapter reset). */
export function clearSegPrefetchCache(): void {
    _segPrefetchCache = {};
}

/** Reset playhead draw-state refs so the draw layer does not point to nodes
 *  destroyed by the next {#each} reconciliation. Called by filters-apply.ts
 *  before re-rendering the list. The playing-row highlight is Svelte-owned
 *  now (class:playing driven by playingSegmentIndex) so only the canvas
 *  playhead draw state lives here. */
export function resetHighlightRefs(): void {
    _prevPlaying = null;
}

/** Tear down the active AudioRange. Called explicitly on edit-mode entry,
 *  per-reciter clear, and at the start of every fresh `playFromSegment`. */
export function disposeSegRange(): void {
    _segRange?.dispose();
    _segRange = null;
}

// ---------------------------------------------------------------------------
// AudioRange wiring
// ---------------------------------------------------------------------------

function _onRangeTick(): void {
    drawActivePlayhead();
    updateSegHighlight();
}

function _onRangeBoundary(ev: { reason: string }): void {
    // Stop boundary: autoplay finished its run (or single-segment play ended).
    // Flip the global UI flag so the autoplay toggle visually reflects state;
    // the audio element's 'pause' event will fire stopSegAnimation in parallel.
    if (ev.reason === 'stop') {
        playEndMs.set(0);
        // If the user toggled autoplay ON after this play started (continuousPlay
        // flipped true while the old policy had already stopped at a boundary),
        // advance to the next segment instead of just clearing the flag.
        const curIdx = get(segCurrentIdx);
        if (get(continuousPlay) && curIdx >= 0) {
            const next = nextDisplayedSeg(get(displayedSegments), curIdx);
            if (next && next.audio_url) {
                playFromSegment(next.index, next.chapter);
                return;
            }
        }
        continuousPlay.set(false);
        return;
    }
    // Advance boundary: the primitive will load the next range after the gap.
    // Update the active-pair + segCurrentIdx + prefetch+peaks NOW (before the
    // gap fires) so the UI reflects the upcoming segment immediately.
    if (ev.reason === 'advance') {
        const audioEl = get(segAudioElement);
        const active = get(playingSegmentIndex);
        const displayed = get(displayedSegments);
        if (!audioEl || !active || !displayed) return;
        const next = nextDisplayedSeg(displayed, active.index);
        if (!next || next.index !== active.index + 1) return;
        const nextChapter = next.chapter ?? active.chapter;
        setPlayingSegment({ chapter: nextChapter, index: next.index });
        segCurrentIdx.set(next.index);
        playEndMs.set(next.time_end);
        prefetchNextSegAudio(displayed, next.index, audioEl.src || '', _segPrefetchCache);
        if (nextChapter) void _fetchPeaksForClick(next, nextChapter);
    }
}

// ---------------------------------------------------------------------------
// Public play API
// ---------------------------------------------------------------------------

export function playFromSegment(
    segIndex: number,
    chapterOverride?: number | null,
    seekToMs?: number | null,
    opts?: { isAccordionPlay?: boolean },
): void {
    disposeSegRange();
    const allData = get(segAllData);
    if (!allData) return;
    const audioEl = get(segAudioElement);
    if (!audioEl) return;
    activeAudioSource.set('main');
    const _chStr = get(selectedChapter);
    const chapter = chapterOverride ?? (_chStr ? parseInt(_chStr) : null);
    const displayed = get(displayedSegments);
    const seg = chapter != null
        ? getSegByChapterIndex(chapter, segIndex)
        : (displayed ? displayed.find(s => s.index === segIndex) : null);
    if (!seg) return;
    // Resolve chapter from the segment itself when still unknown; playingSegment
    // must always carry a concrete chapter so SegmentRow's class:playing match
    // disambiguates same-index rows in other chapters.
    const resolvedChapter = chapter ?? seg.chapter ?? 0;
    const isAccordionPlay = opts?.isAccordionPlay ?? false;

    // Autoplay is intentionally main-list only: accordion plays always stop
    // at time_end regardless of the global autoplay toggle.
    continuousPlay.set(get(autoPlayEnabled) && !isAccordionPlay);
    playEndMs.set(seg.time_end);

    const range = buildSegRangeSpec(seg, seekToMs);
    const policy = buildSegPolicy({
        getAutoPlayEnabled: () => get(autoPlayEnabled),
        isAccordionPlay,
        // Lazy: AudioRange reuses the same policy across N consecutive
        // boundary fires during an autoplay run. Read the live active-pair
        // index each time so the resolver sees the segment we just advanced
        // INTO, not the one we originally started on. Falls back to segIndex
        // for the very first boundary (before _onRangeBoundary has updated
        // playingSegmentIndex) and for cross-chapter accordion plays where
        // the active pair is set elsewhere.
        getCurrentIndex: () => get(playingSegmentIndex)?.index ?? segIndex,
        getDisplayed: () => get(displayedSegments),
    });

    _segRange = new AudioRange({
        audioEl,
        range,
        policy,
        onTick: _onRangeTick,
        onBoundary: _onRangeBoundary,
        playbackRate: () => get(playbackSpeed),
    });
    _segRange.start();

    segCurrentIdx.set(segIndex);
    // Authoritative (chapter, index) for the active play — every downstream
    // reader (drawActivePlayhead, SegmentRow's class:playing) consults this
    // instead of inferring chapter from selectedChapter. `origin` lets the
    // main-list autoscroll (and any future follow-the-playhead UI) stay put
    // when the play came from an accordion-mounted row.
    setPlayingSegment({
        chapter: resolvedChapter,
        index: segIndex,
        origin: isAccordionPlay ? 'accordion' : 'main',
    });

    prefetchNextSegAudio(displayed, segIndex, audioEl.src || '', _segPrefetchCache);

    // Fetch waveform peaks on-demand via ffmpeg HTTP Range (brief delay expected).
    void _fetchPeaksForClick(seg, resolvedChapter);
}

export function onSegPlayClick(): void {
    const audioEl = get(segAudioElement);
    if (!audioEl) return;
    const displayed = get(displayedSegments);
    const curIdx = get(segCurrentIdx);
    if (audioEl.paused) {
        if (displayed && displayed.length > 0 && curIdx < 0) {
            const first = displayed[0];
            if (first) playFromSegment(first.index, first.chapter);
        } else if (_segRange) {
            // Resume an existing run — the range's pause-resilient frame loop
            // ticks idly while audio was paused, no rebuild needed.
            audioEl.playbackRate = get(playbackSpeed);
            void audioEl.play();
        } else if (curIdx >= 0 && displayed) {
            // No range alive (e.g. user manually paused before any play) —
            // rebuild from the segCurrentIdx pointer.
            const curSeg = displayed.find(s => s.index === curIdx);
            if (curSeg) playFromSegment(curSeg.index, curSeg.chapter);
        }
    } else {
        continuousPlay.set(false);
        audioEl.pause();
    }
}

// ---------------------------------------------------------------------------
// Audio event handlers
// ---------------------------------------------------------------------------

export function onSegTimeUpdate(): void {
    // Edit-preview's rAF owns boundary enforcement on the edit canvas.
    if (get(editMode)) return;
    const audioEl = get(segAudioElement);
    if (!audioEl) return;
    const timeMs = audioEl.currentTime * 1000;
    const currentSrc = audioEl.src || '';
    const displayed = get(displayedSegments);
    const active = get(playingSegmentIndex);

    // Cross-segment-within-same-audio detection. AudioRange owns per-segment
    // boundary fires, but a manual seek (user dragging the audio scrubber
    // across multiple segment windows) bypasses the rAF — this branch keeps
    // segCurrentIdx and the active pair in sync with the audio's actual
    // position. Also runs as a safety net if rAF is throttled.
    const prevIdx = get(segCurrentIdx);
    let nextCurrentIdx = -1;
    let nextCurrentChapter = active?.chapter ?? null;
    if (displayed) {
        for (const seg of displayed) {
            if (timeMs >= seg.time_start && timeMs < seg.time_end) {
                if (currentSrc && !audioSrcMatches(seg.audio_url, currentSrc)) continue;
                nextCurrentIdx = seg.index;
                nextCurrentChapter = seg.chapter ?? nextCurrentChapter;
                break;
            }
        }
    }
    // Fallback: when the displayed-slice search missed (accordion playback
    // targeting a chapter other than the displayed one), hold the active pair
    // instead of clobbering it with -1.
    if (nextCurrentIdx === -1 && active) {
        const activeSeg = getSegByChapterIndex(active.chapter, active.index);
        if (activeSeg && audioSrcMatches(activeSeg.audio_url, currentSrc)
                && timeMs >= activeSeg.time_start && timeMs < activeSeg.time_end) {
            nextCurrentIdx = active.index;
            nextCurrentChapter = active.chapter;
        }
    }
    segCurrentIdx.set(nextCurrentIdx);

    if (nextCurrentIdx !== prevIdx && nextCurrentIdx >= 0 && nextCurrentChapter != null) {
        // Auto-advanced into a new segment via shared-audio playback (no
        // boundary fire — the segments share an audio file). Update the
        // active pair so the playhead and class:playing follow.
        setPlayingSegment({ chapter: nextCurrentChapter, index: nextCurrentIdx });
        if (displayed) {
            prefetchNextSegAudio(displayed, nextCurrentIdx, audioEl.src || '', _segPrefetchCache);
            const curSeg = displayed.find(s => s.index === nextCurrentIdx);
            if (curSeg) {
                const chapterForPeaks = curSeg.chapter ?? (get(selectedChapter) ? parseInt(get(selectedChapter)) : 0);
                if (chapterForPeaks) void _fetchPeaksForClick(curSeg, chapterForPeaks);
                playEndMs.set(curSeg.time_end);
            }
        }
    }
}

export function startSegAnimation(): void {
    // UI state only — AudioRange owns the rAF. The editMode gate keeps the
    // segment-row playhead off the edit canvas while the preview rAF runs.
    if (get(editMode)) return;
    playButtonLabel.set('Pause');
    activeAudioSource.set('main');
    isMainAudioPlaying.set(true);
}

export function stopSegAnimation(): void {
    // UI state only — does NOT dispose the AudioRange. The 'pause' DOM event
    // fires this both for user pauses (range stays alive, ready to resume)
    // and the autoplay-gap pause (range scheduled the resume internally).
    // Explicit teardown is `disposeSegRange()`.
    playButtonLabel.set('Play');
    if (get(activeAudioSource) === 'main') activeAudioSource.set(null);
    isMainAudioPlaying.set(false);
}

export function onSegAudioEnded(): void {
    // Audio element fired 'ended' — the underlying file finished. AudioRange's
    // boundary fires before this in the normal autoplay flow; we only get
    // here when the file ended without a boundary advance taking over.
    const curIdx = get(segCurrentIdx);
    if (get(continuousPlay) && curIdx >= 0) {
        const next = nextDisplayedSeg(get(displayedSegments), curIdx);
        if (next && next.audio_url) {
            playFromSegment(next.index, next.chapter);
            return;
        }
    }
    continuousPlay.set(false);
    disposeSegRange();
    // Audio actually finished — clear the active-pair highlight. This is the
    // genuine "nothing is playing" signal (distinct from cross-chapter accordion
    // plays, which must NOT clear the pair on a displayed-slice miss).
    setPlayingSegment(null);
}

// ---------------------------------------------------------------------------
// Highlight + playhead helpers
// ---------------------------------------------------------------------------

export function updateSegHighlight(): void {
    // setPlayingSegment() is identity-guarded — a same-value rAF tick is a
    // no-op for subscribers. The active pair (chapter, index) is set by
    // playFromSegment and maintained by onSegTimeUpdate for auto-advance; this
    // function bridges segCurrentIdx changes back to the pair when they
    // originate outside the time-update path (e.g. manual seek handler).
    const curIdx = get(segCurrentIdx);
    const active = get(playingSegmentIndex);
    if (curIdx < 0) return;
    if (!active || active.index !== curIdx) {
        const chapter = active?.chapter
            ?? (get(displayedSegments).find((s) => s.index === curIdx)?.chapter)
            ?? (get(selectedChapter) ? parseInt(get(selectedChapter)) : null);
        if (chapter != null) setPlayingSegment({ chapter, index: curIdx });
    }
}

/**
 * Reconcile the `playingSegmentIndex` pair after a structural mutation
 * (split/merge/delete) has re-indexed a chapter's segments.
 *
 * Callers capture `seg.segment_uid` BEFORE the mutation and pass it in.
 * Because split/merge preserve UIDs on the firstHalf / kept side, the playing
 * segment usually still exists under the same UID with a new index — we look
 * it up and update the active pair. If the playing seg was removed (delete,
 * or merge consumed it), we clear the pair and dispose the range so the UI
 * doesn't keep drawing a playhead on a stale (chapter, index) pointer.
 */
export function reconcilePlayingAfterMutation(
    chapter: number,
    prePlayingUid: string | null,
): void {
    const active = get(playingSegmentIndex);
    if (!active || active.chapter !== chapter || !prePlayingUid) return;
    const allData = get(segAllData);
    if (!allData?.segments) return;
    const found = allData.segments.find(
        (s) => s.segment_uid === prePlayingUid && s.chapter === chapter,
    );
    if (found) {
        setPlayingSegment({ chapter, index: found.index });
    } else {
        setPlayingSegment(null);
        disposeSegRange();
    }
}

export function drawActivePlayhead(): void {
    // Hoist above the pair-change erase branch (below): during any edit mode
    // the preview rAF owns the edit canvas, and the erase branch iterates
    // `getRowEntriesFor(_prevPlaying)` — which includes the edit canvas when
    // adjusting the previously-active segment — and clobbers trim handles
    // with plain peaks via `drawWaveformFromPeaksForSeg`.
    if (get(editMode)) return;
    const allData = get(segAllData);
    const active = get(playingSegmentIndex);
    if (!allData) return;
    const audioEl = get(segAudioElement);
    if (!audioEl) return;
    const time = audioEl.currentTime * 1000;

    const prev = _prevPlaying;
    const pairChanged = !prev || !active
        || prev.chapter !== active.chapter
        || prev.index !== active.index;

    // On pair change: erase the previous playhead by redrawing the waveform on
    // EVERY mounted twin for the old (chapter, index). Both the main-list row
    // and any accordion row showing the same segment must be cleaned up.
    if (prev && pairChanged) {
        const prevSeg = getSegByChapterIndex(prev.chapter, prev.index);
        if (prevSeg) {
            for (const entry of getRowEntriesFor(prev.chapter, prev.index)) {
                if (entry.canvas) drawWaveformFromPeaksForSeg(entry.canvas, prevSeg, prev.chapter);
            }
        }
    }

    _prevPlaying = active ? { chapter: active.chapter, index: active.index } : null;

    if (!active) return;

    const seg = getSegByChapterIndex(active.chapter, active.index);
    if (!seg) return;
    const audioUrl = seg.audio_url || allData?.audio_by_chapter?.[String(active.chapter)] || '';

    // Draw the playhead on EVERY mounted twin for this (chapter, index) — main
    // list row and any accordion rows showing the same segment. Both need the
    // synchronized playhead per spec.
    for (const entry of getRowEntriesFor(active.chapter, active.index)) {
        if (entry.canvas) drawSegPlayhead(entry.canvas, seg.time_start, seg.time_end, time, audioUrl);
    }
}
