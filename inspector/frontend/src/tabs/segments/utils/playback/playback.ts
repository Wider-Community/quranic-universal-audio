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
 *
 * Coordinate space: every `timeMs` value flowing through this module is
 * **file-absolute milliseconds**. The `segPort` port translates to / from
 * the `<audio>.currentTime` clip-relative space internally for VBR clips.
 * Callers never see clip offsets.
 */

import { get } from 'svelte/store';

import { AudioRange } from '../../../../lib/playback/audio-range';
import type { Segment } from '../../../../lib/types/domain';
import { audioSrcMatches } from '../../../../lib/utils/audio';
import {
    getSegByChapterIndex,
    segAllData,
    segCurrentIdx,
    segData,
    selectedChapter,
    selectedReciter,
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
    playStartMs,
    segPort,
    setPlayingSegment,
} from '../../stores/playback';
import { drawSegPlayhead, drawWaveformFromPeaksForSeg } from '../waveform/draw-seg';
import { _fetchPeaksForClick } from '../waveform/utils';
import { buildSegPolicy } from './range-spec';
import { nextDisplayedSeg, nextSiblingSeg } from './resolvers';
import { getRowEntriesFor } from './row-registry';
import { resolveSegSource } from './source';
import { warmSeg } from './warmup';

// ---------------------------------------------------------------------------
// Module-local state
// ---------------------------------------------------------------------------

let _segRange: AudioRange | null = null;

/** Last drawn (chapter, index) pair so the animation loop can erase the
 *  playhead on the previous row when playback advances. Carries the chapter
 *  so cross-chapter advance (accordion -> another chapter's row) erases from
 *  the right canvas. */
let _prevPlaying: { chapter: number; index: number } | null = null;

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

/** Active-chapter audio URL — independent of which segment's source the
 *  port is currently bound to. Used by `onSegTimeUpdate`'s cross-segment
 *  scan (filters `displayed` to active-chapter rows by URL match) and by
 *  prefetch's "skip if next seg shares chapter audio" gate. Reads from
 *  `segData.audio_url` (the active chapter's canonical CDN URL set by
 *  `loadChapterData`) rather than `segPort.source.audioUrl` so per-row
 *  source rebinding doesn't break either consumer when an accordion row
 *  from another chapter is the most recent thing the port loaded. */
function _curChapterUrl(): string {
    return get(segData)?.audio_url ?? '';
}

// ---------------------------------------------------------------------------
// AudioRange wiring
// ---------------------------------------------------------------------------

function _onRangeTick(timeMs: number): void {
    drawActivePlayhead(timeMs);
    updateSegHighlight();
}

function _onRangeBoundary(ev: { reason: string }): void {
    // Stop boundary: autoplay finished its run (or single-segment play ended).
    // Flip the global UI flag so the autoplay toggle visually reflects state;
    // the audio element's 'pause' event will fire stopSegAnimation in parallel.
    if (ev.reason === 'stop') {
        playEndMs.set(0);
        playStartMs.set(0);
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
        const active = get(playingSegmentIndex);
        const displayed = get(displayedSegments);
        if (!segPort.element || !active || !displayed) return;
        const next = nextDisplayedSeg(displayed, active.index);
        if (!next || next.index !== active.index + 1) return;
        // Rebind the port to the next seg's source BEFORE the gap timer
        // fires `_startWithPort(next)` → `port.loadCovering(next.start, next.end)`
        // — otherwise the port still has the prior seg's chapter source and
        // the clip URL builds against the wrong audio. setSource is a no-op
        // when the source is unchanged (same-chapter advance).
        const nextChapter = next.chapter ?? active.chapter;
        const nextSource = resolveSegSource(next, nextChapter);
        if (nextSource) segPort.setSource(nextSource);
        setPlayingSegment({ chapter: nextChapter, index: next.index });
        segCurrentIdx.set(next.index);
        playStartMs.set(next.time_start);
        playEndMs.set(next.time_end);
        // Warm next-next so a subsequent auto-advance is also instant.
        const nextNext = nextDisplayedSeg(displayed, next.index);
        warmSeg(nextNext, get(selectedReciter), next);
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
    opts?: {
        isAccordionPlay?: boolean,
        /** Rendered sibling list of the accordion card that initiated this
         *  play. When supplied (only by accordion rows), prefetch warms the
         *  next sibling's clip URL by *list position* rather than chapter
         *  mode's `displayedSegments` + `index + 1` resolver. May span
         *  chapters; the per-reciter VBR map decides clip-vs-chapter URL
         *  per sibling. */
        accordionSiblings?: Segment[] | null,
    },
): void {
    const _playClickAt = performance.now();
    const _trace = (typeof localStorage !== 'undefined'
        && localStorage.getItem('insp_warmup_log') === 'true');
    if (_trace) {
        // eslint-disable-next-line no-console
        console.log(`[play] click seg=${segIndex} ch=${chapterOverride} readyState=${segPort.element?.readyState} reused=${segPort.window != null ? 'window-exists' : 'fresh'}`);
        const el = segPort.element;
        if (el) {
            const onPlaying = (): void => {
                // eslint-disable-next-line no-console
                console.log(`[play] FIRST audible frame ${Math.round(performance.now() - _playClickAt)}ms after click`);
                el.removeEventListener('playing', onPlaying);
            };
            el.addEventListener('playing', onPlaying);
        }
    }
    disposeSegRange();
    const allData = get(segAllData);
    if (!allData) return;
    if (!segPort.element) return;
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

    // Bind the port to THIS seg's source. Cross-chapter accordion rows
    // (validation cards mounting rows from other chapters) and main-list
    // rows in the active chapter both flow through here. setSource is a
    // no-op for the active chapter; for cross-chapter rows it invalidates
    // `_window` so the next `loadCovering` issues a fresh swap against
    // the row's chapter URL.
    const segSource = resolveSegSource(seg, resolvedChapter);
    if (segSource) segPort.setSource(segSource);

    // Autoplay is intentionally main-list only: accordion plays always stop
    // at time_end regardless of the global autoplay toggle.
    continuousPlay.set(get(autoPlayEnabled) && !isAccordionPlay);
    playStartMs.set(seg.time_start);
    playEndMs.set(seg.time_end);

    // File-absolute spec — port owns CBR-vs-VBR transport and offset
    // bookkeeping. The seek target defaults to the segment start.
    const range = {
        startMs: seekToMs ?? seg.time_start,
        endMs: seg.time_end,
    };
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
        port: segPort,
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

    // Accordion plays warm their card's next *sibling* (list position,
    // possibly cross-chapter); main-list plays warm the next displayed
    // segment by `Segment.index + 1`. Warmup no-ops on VBR + missing-kbps
    // (the segment-clip route handles VBR per-seg separately).
    const reciter = get(selectedReciter);
    const nextSeg = isAccordionPlay && opts?.accordionSiblings
        ? nextSiblingSeg(opts.accordionSiblings, resolvedChapter, segIndex)
        : nextDisplayedSeg(displayed, segIndex);
    warmSeg(nextSeg, reciter, seg);

    // Fetch waveform peaks on-demand via ffmpeg HTTP Range (brief delay expected).
    void _fetchPeaksForClick(seg, resolvedChapter);
}

export function onSegPlayClick(): void {
    if (!segPort.element) return;
    const displayed = get(displayedSegments);
    const curIdx = get(segCurrentIdx);
    if (segPort.paused) {
        if (displayed && displayed.length > 0 && curIdx < 0) {
            const first = displayed[0];
            if (first) playFromSegment(first.index, first.chapter);
        } else if (_segRange) {
            // Resume an existing run — the range's pause-resilient frame loop
            // ticks idly while audio was paused, no rebuild needed.
            segPort.setPlaybackRate(get(playbackSpeed));
            segPort.play();
        } else if (curIdx >= 0 && displayed) {
            // No range alive (e.g. user manually paused before any play) —
            // rebuild from the segCurrentIdx pointer.
            const curSeg = displayed.find(s => s.index === curIdx);
            if (curSeg) playFromSegment(curSeg.index, curSeg.chapter);
        }
    } else {
        continuousPlay.set(false);
        segPort.pause();
    }
}

// ---------------------------------------------------------------------------
// Audio event handlers
// ---------------------------------------------------------------------------

export function onSegTimeUpdate(fileMs?: number): void {
    // Edit-preview's rAF owns boundary enforcement on the edit canvas.
    if (get(editMode)) return;
    // VBR clip mode plays a one-segment clip from byte 0, so audioEl.src is
    // the clip URL, not the chapter audio URL. Cross-segment-within-shared-
    // audio detection (the body of this function) keys off matching the
    // chapter URL — useless in clip mode. Segment switches in VBR mode come
    // through `_onRangeBoundary('advance')` and explicit `playFromSegment`
    // calls instead.
    if (segPort.window?.isClip) return;
    if (!segPort.element) return;
    // Cross-chapter accordion plays keep the port bound to the row's chapter
    // (via `playFromSegment`'s setSource), but `displayedSegments` and
    // `playingSegmentIndex` describe the ACTIVE chapter's view. The
    // file-absolute `timeMs` below would be interpreted in the ACCORDION
    // chapter's coordinate space, but compared against ACTIVE-chapter rows
    // whose `time_start/time_end` are in their own chapter's space —
    // false-positive matches happen when the numeric ms range overlaps
    // by coincidence. Skip the scan entirely whenever the port isn't
    // playing the active chapter; the playing pair set by `playFromSegment`
    // already points at the right (cross-chapter) row, and the rAF tick's
    // `drawActivePlayhead` keeps the cursor on that row's canvas.
    const portUrl = segPort.source?.audioUrl;
    const activeUrl = _curChapterUrl();
    if (!portUrl || !activeUrl || !audioSrcMatches(portUrl, activeUrl)) return;
    // `fileMs` comes from the port's `onTimeUpdate` subscription (file-
    // absolute). Fall back to a fresh read for direct callers (none today,
    // but the public export shape allows it).
    const timeMs = fileMs ?? segPort.currentTimeMs();
    const currentSrc = _curChapterUrl();
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
            const curSeg = displayed.find(s => s.index === nextCurrentIdx);
            const nextSeg = nextDisplayedSeg(displayed, nextCurrentIdx);
            warmSeg(nextSeg, get(selectedReciter), curSeg ?? null);
            if (curSeg) {
                const chapterForPeaks = curSeg.chapter ?? (get(selectedChapter) ? parseInt(get(selectedChapter)) : 0);
                if (chapterForPeaks) void _fetchPeaksForClick(curSeg, chapterForPeaks);
                playStartMs.set(curSeg.time_start);
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
    //
    // Mirror the `editMode` gate from `startSegAnimation`. During edit-mode
    // preview, `_playRange`'s loop seek-back issues a transient
    // `pauseAndFlush()` to drain the OS audio sink — that fires a 'pause'
    // DOM event whose only intent is to silence the sink, not to surface
    // a paused state to the user. Without this gate the main play-button
    // label flickered to 'Play' on every loop iteration during Adjust /
    // Split preview.
    if (get(editMode)) return;
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

export function drawActivePlayhead(timeMs?: number): void {
    // Hoist above the pair-change erase branch (below): during any edit mode
    // the preview rAF owns the edit canvas, and the erase branch iterates
    // `getRowEntriesFor(_prevPlaying)` — which includes the edit canvas when
    // adjusting the previously-active segment — and clobbers trim handles
    // with plain peaks via `drawWaveformFromPeaksForSeg`.
    if (get(editMode)) return;
    const allData = get(segAllData);
    const active = get(playingSegmentIndex);
    if (!allData) return;
    if (!segPort.element) return;
    // `timeMs` is the file-absolute time supplied by AudioRange's rAF tick.
    // For direct callers (manual seek handler) fall back to the live port
    // reading — the port owns offset translation so file-absolute is
    // identical regardless of CBR vs VBR transport.
    const time = timeMs ?? segPort.currentTimeMs();

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
