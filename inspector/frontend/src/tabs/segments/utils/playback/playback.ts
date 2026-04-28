/**
 * Audio playback, animation, highlight tracking, and play status.
 */

import { get } from 'svelte/store';

import { createAnimationLoop } from '../../../../lib/utils/animation';
import { audioSrcMatches, safePlay } from '../../../../lib/utils/audio';
import {
    getSegByChapterIndex,
    segAllData,
    segCurrentIdx,
    selectedChapter,
} from '../../stores/chapter';
import { editingSegIndex, editMode } from '../../stores/edit';
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
import type { RafHandle } from '../../types/segments';
import { AUTOPLAY_GAP_PAUSE_MS } from '../constants';
import { drawSegPlayhead, drawWaveformFromPeaksForSeg } from '../waveform/draw-seg';
import { _fetchPeaksForClick } from '../waveform/utils';
import { resolveAutoplayGapAdvance } from './autoplay-gap';
import { nextDisplayedSeg, prefetchNextSegAudio } from './prefetch';
import { getRowEntriesFor } from './row-registry';

// ---------------------------------------------------------------------------
// Module-local state
// ---------------------------------------------------------------------------

let _segAnimId: RafHandle | null = null;
let _segPrefetchCache: Record<string, Promise<unknown>> = {};
/** Pending autoplay inter-segment gap timeout id, or null when no gap is
 *  scheduled. Tracked so that manual pause / manual play / edit-mode entry
 *  can cancel a pending resume (otherwise audio would resume mid-action). */
let _autoplayGapTimeout: ReturnType<typeof setTimeout> | null = null;

/** Suppress the next auto-clear triggered by our OWN `audioEl.pause()` inside
 *  the gap-advance branch. The 'pause' DOM event is async, and the pause
 *  listener (`el.addEventListener('pause', stopSegAnimation)` in
 *  SegmentsAudioControls.svelte) routes through `stopSegAnimation` which
 *  calls `_clearAutoplayGap`. Without this flag, our own gap-initiated pause
 *  would immediately cancel the resume timer we just set. */
let _suppressNextGapClear = false;

/** Cancel a pending autoplay gap resume. Safe to call when none is pending.
 *  Honors the one-shot suppress flag set by the gap-advance branch so the
 *  very pause event our branch triggered doesn't kill the pending resume. */
function _clearAutoplayGap(): void {
    if (_suppressNextGapClear) { _suppressNextGapClear = false; return; }
    if (_autoplayGapTimeout !== null) {
        clearTimeout(_autoplayGapTimeout);
        _autoplayGapTimeout = null;
    }
}

/** Force-cancel a pending autoplay gap resume regardless of suppress flags.
 *  Used when a fresh user-initiated action takes ownership of playback and any
 *  queued auto-resume would be stale. */
function _cancelAutoplayGap(): void {
    _suppressNextGapClear = false;
    if (_autoplayGapTimeout !== null) {
        clearTimeout(_autoplayGapTimeout);
        _autoplayGapTimeout = null;
    }
}
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

export function playFromSegment(
    segIndex: number,
    chapterOverride?: number | null,
    seekToMs?: number | null,
): void {
    _cancelAutoplayGap();
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

    continuousPlay.set(get(autoPlayEnabled));
    playEndMs.set(seg.time_end);

    const segAudioUrl = seg.audio_url || '';
    if (segAudioUrl && !audioEl.src.endsWith(segAudioUrl)) {
        audioEl.src = segAudioUrl;
    }

    audioEl.playbackRate = get(playbackSpeed);
    audioEl.currentTime = (seekToMs != null ? seekToMs : seg.time_start) / 1000;
    safePlay(audioEl);
    segCurrentIdx.set(segIndex);
    // Authoritative (chapter, index) for the active play — every downstream
    // reader (onSegTimeUpdate, drawActivePlayhead, SegmentRow's class:playing)
    // consults this instead of inferring chapter from selectedChapter.
    setPlayingSegment({ chapter: resolvedChapter, index: segIndex });

    prefetchNextSegAudio(displayed, segIndex, audioEl.src || '', _segPrefetchCache);

    // Fetch waveform peaks on-demand via ffmpeg HTTP Range (brief delay expected).
    void _fetchPeaksForClick(seg, resolvedChapter);
}

/** Thin wrapper binding state to the extracted nextDisplayedSeg. */
function _nextDisplayedSeg(afterIndex: number) {
    return nextDisplayedSeg(get(displayedSegments), afterIndex);
}

export function onSegPlayClick(): void {
    _cancelAutoplayGap();
    const audioEl = get(segAudioElement);
    if (!audioEl) return;
    const displayed = get(displayedSegments);
    const curIdx = get(segCurrentIdx);
    if (audioEl.paused) {
        if (displayed && displayed.length > 0 && curIdx < 0) {
            const first = displayed[0];
            if (first) playFromSegment(first.index, first.chapter);
        } else {
            continuousPlay.set(get(autoPlayEnabled));
            activeAudioSource.set('main');
            if (curIdx >= 0 && displayed) {
                const curSeg = displayed.find(s => s.index === curIdx);
                if (curSeg) playEndMs.set(curSeg.time_end);
            }
            audioEl.playbackRate = get(playbackSpeed);
            safePlay(audioEl);
        }
    } else {
        continuousPlay.set(false);
        audioEl.pause();
    }
}

export function onSegTimeUpdate(): void {
    // During trim/split preview, the edit-preview rAF (animatePlayhead in
    // play-range.ts) owns loop-boundary enforcement. Letting the main
    // time-update logic run can spuriously pause the preview audio when
    // it reads past the seg.time_end that `lastSegOnAudio` points at.
    // Mirrors the editMode gate in startSegAnimation.
    if (get(editMode)) return;
    const audioEl = get(segAudioElement);
    if (!audioEl) return;
    const timeMs = audioEl.currentTime * 1000;
    const currentSrc = audioEl.src || '';
    const displayed = get(displayedSegments);

    // Authoritative (chapter, index) set at playFromSegment() time — covers
    // cross-chapter accordion plays, where the playing segment is NOT in
    // `displayed` (the main-list filtered slice of the currently-viewed
    // chapter). When present, we trust it for highlight/segCurrentIdx and
    // only fall back to searching `displayed` when absent (e.g. user
    // manually dragged the toolbar audio element mid-seek).
    const active = get(playingSegmentIndex);

    let lastSegOnAudio = null;
    if (displayed && displayed.length > 0) {
        for (let i = displayed.length - 1; i >= 0; i--) {
            const s = displayed[i];
            if (s && audioSrcMatches(s.audio_url, currentSrc)) {
                lastSegOnAudio = s;
                break;
            }
        }
        if (!lastSegOnAudio) lastSegOnAudio = displayed[displayed.length - 1] ?? null;
    }

    if (lastSegOnAudio && timeMs >= lastSegOnAudio.time_end) {
        const nextSeg = _nextDisplayedSeg(lastSegOnAudio.index);
        const isConsecutive = nextSeg && nextSeg.index === lastSegOnAudio.index + 1;
        if (get(continuousPlay) && isConsecutive && nextSeg && !audioSrcMatches(nextSeg.audio_url, currentSrc)) {
            playFromSegment(nextSeg.index, nextSeg.chapter);
            return;
        }
        // Only stop playback when the audio we're advancing PAST belongs to the
        // same segment the active pair points to. On cross-chapter accordion
        // plays `lastSegOnAudio` is synthesized from the main-list filtered
        // slice and has no bearing on the actually-playing segment — stopping
        // here would kill accordion playback. The check below cross-references
        // with the active pair so we only pause when the "last on audio"
        // actually matches what's playing.
        if (!active || (lastSegOnAudio.chapter === active.chapter && lastSegOnAudio.index === active.index)) {
            audioEl.pause();
            stopSegAnimation();
            continuousPlay.set(false);
            playEndMs.set(0);
            return;
        }
    }

    const curPlayEnd = get(playEndMs);
    const autoplayGapAdvance = get(continuousPlay)
        ? resolveAutoplayGapAdvance({
            active,
            currentSrc,
            displayedSegments: displayed,
            playEndMs: curPlayEnd,
            timeMs,
        })
        : null;
    if (autoplayGapAdvance && _autoplayGapTimeout === null) {
        const { justEnded, next } = autoplayGapAdvance;
        const activeBeforePause = active ?? {
            chapter: justEnded.chapter ?? 0,
            index: justEnded.index,
        };

        // Flip the controls into their paused state immediately so the user sees
        // the segment boundary before the timed resume starts.
        stopSegAnimation();
        _suppressNextGapClear = true;
        audioEl.pause();

        const nextStartMs = next.time_start;
        const nextEndMs = next.time_end;
        const nextChapter = next.chapter ?? activeBeforePause.chapter;
        _autoplayGapTimeout = setTimeout(() => {
            _autoplayGapTimeout = null;
            if (!get(continuousPlay) || get(editMode)) return;
            const aEl = get(segAudioElement);
            if (!aEl || !aEl.paused) return;
            const currentActive = get(playingSegmentIndex);
            if (!currentActive
                    || currentActive.index !== activeBeforePause.index
                    || currentActive.chapter !== activeBeforePause.chapter) {
                return;
            }
            setPlayingSegment({ chapter: nextChapter, index: next.index });
            segCurrentIdx.set(next.index);
            playEndMs.set(nextEndMs);
            prefetchNextSegAudio(displayed, next.index, aEl.src || '', _segPrefetchCache);
            if (nextChapter) void _fetchPeaksForClick(next, nextChapter);
            aEl.currentTime = nextStartMs / 1000;
            startSegAnimation();
            void safePlay(aEl);
        }, AUTOPLAY_GAP_PAUSE_MS);
        return;
    }

    // A trailing timeupdate can still arrive after we've paused and scheduled
    // the resume. Ignore it so the generic end-of-range branch below does not
    // disable continuousPlay before the timeout fires.
    if (_autoplayGapTimeout !== null) return;

    const prevIdx = get(segCurrentIdx);
    // Fast path: the active pair (written by playFromSegment) is the authority
    // for the currently-playing segment. Use it directly so cross-chapter
    // accordion plays keep segCurrentIdx correct even though the playing
    // segment isn't in `displayed`. The inner search below still runs so that
    // continuous-play auto-advance within the same chapter detects when the
    // audio has crossed into the NEXT segment and updates the pair/index.
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
    // instead of clobbering it with -1. Only clear when there's genuinely no
    // authoritative source AND no match in displayed.
    if (nextCurrentIdx === -1 && active) {
        // Active pair is known — check if audio is still within that segment's
        // window; if so, keep it. If audio has advanced past it, fall through
        // to the end-of-range logic below.
        const activeSeg = getSegByChapterIndex(active.chapter, active.index);
        if (activeSeg && audioSrcMatches(activeSeg.audio_url, currentSrc)
                && timeMs >= activeSeg.time_start && timeMs < activeSeg.time_end) {
            nextCurrentIdx = active.index;
            nextCurrentChapter = active.chapter;
        }
    }
    segCurrentIdx.set(nextCurrentIdx);

    if (nextCurrentIdx === -1 && curPlayEnd > 0 && timeMs >= curPlayEnd) {
        audioEl.pause();
        stopSegAnimation();
        continuousPlay.set(false);
        playEndMs.set(0);
        return;
    }

    if (nextCurrentIdx !== prevIdx) {
        if (!get(continuousPlay) && prevIdx >= 0 && nextCurrentIdx >= 0) {
            audioEl.pause();
            stopSegAnimation();
            playEndMs.set(0);
            return;
        }
        if (nextCurrentIdx >= 0 && displayed) {
            const curSeg = displayed.find(s => s.index === nextCurrentIdx);
            if (curSeg) playEndMs.set(curSeg.time_end);
        }
        // Update the authoritative pair so drawActivePlayhead / class:playing
        // follow the auto-advance (continuous play within the displayed slice).
        if (nextCurrentIdx >= 0 && nextCurrentChapter != null) {
            setPlayingSegment({ chapter: nextCurrentChapter, index: nextCurrentIdx });
        }
        if (nextCurrentIdx >= 0) {
            prefetchNextSegAudio(displayed, nextCurrentIdx, audioEl.src || '', _segPrefetchCache);
            // Trigger on-demand peaks fetch for the segment we just entered during
            // continuous play (auto-advance on same audio file doesn't go through
            // playFromSegment, so peaks would otherwise never load here).
            const curSeg = displayed?.find(s => s.index === nextCurrentIdx);
            if (curSeg) {
                const chapterForPeaks = curSeg.chapter ?? (get(selectedChapter) ? parseInt(get(selectedChapter)) : 0);
                if (chapterForPeaks) void _fetchPeaksForClick(curSeg, chapterForPeaks);
            }
        }
    }
}

// ---------------------------------------------------------------------------
// Animation loop
// ---------------------------------------------------------------------------
// Each frame calls updateSegHighlight + drawActivePlayhead, and returns
// `false` to self-stop when continuous-play has ended. `_segAnimId` is
// tracked so external checks (truthy means "running") behave identically.
const _segAnimLoop = createAnimationLoop(() => {
    updateSegHighlight();
    drawActivePlayhead();
    const audioEl = get(segAudioElement);
    const curPlayEnd = get(playEndMs);
    if (!get(continuousPlay) && curPlayEnd > 0 && audioEl && !audioEl.paused
            && audioEl.currentTime * 1000 >= curPlayEnd) {
        audioEl.pause();
        // stopSegAnimation will set _segAnimId=null and update UI; return false
        // so the loop itself cancels cleanly.
        stopSegAnimation();
        playEndMs.set(0);
        return false;
    }
    return;
});

export function startSegAnimation(): void {
    // Edit-mode preview owns all canvas writes on the edit row; if we let the
    // main loop run in parallel, its `drawActivePlayhead` pair-change erase
    // branch can clobber the trim handles by drawing plain peaks onto the
    // edit canvas when onSegTimeUpdate transiently flips `playingSegmentIndex`
    // during the seek-to-trim-start.
    if (get(editMode)) return;
    playButtonLabel.set('Pause');
    activeAudioSource.set('main');
    isMainAudioPlaying.set(true);
    _segAnimLoop.start();
    _segAnimId = 1;
}

export function stopSegAnimation(): void {
    playButtonLabel.set('Play');
    if (get(activeAudioSource) === 'main') activeAudioSource.set(null);
    isMainAudioPlaying.set(false);
    _segAnimLoop.stop();
    _segAnimId = null;
    // Any pending autoplay-gap resume would fire after the user has already
    // paused/stopped. Cancel here so the timer doesn't silently restart audio.
    _clearAutoplayGap();
}

export function onSegAudioEnded(): void {
    const curIdx = get(segCurrentIdx);
    if (get(continuousPlay) && curIdx >= 0) {
        const next = _nextDisplayedSeg(curIdx);
        if (next && next.audio_url) {
            playFromSegment(next.index, next.chapter);
            return;
        }
    }
    continuousPlay.set(false);
    stopSegAnimation();
    // Audio actually finished — clear the active-pair highlight. This is the
    // genuine "nothing is playing" signal (distinct from cross-chapter accordion
    // plays, which must NOT clear the pair on a displayed-slice miss).
    setPlayingSegment(null);
}

export function updateSegHighlight(): void {
    // setPlayingSegment() is identity-guarded — a same-value rAF tick is a
    // no-op for subscribers. The active pair (chapter, index) is set by
    // playFromSegment and maintained by onSegTimeUpdate for auto-advance; this
    // function bridges segCurrentIdx changes back to the pair when they
    // originate outside the time-update path (e.g. manual seek handler).
    const curIdx = get(segCurrentIdx);
    const active = get(playingSegmentIndex);
    if (curIdx < 0) {
        // Don't null the active pair on a momentary displayed-slice miss —
        // only explicit stop paths (stopSegAnimation on end, clearPerReciter-
        // State) clear it.
        return;
    }
    if (!active || active.index !== curIdx) {
        // segCurrentIdx moved forward via path other than onSegTimeUpdate.
        // Resolve chapter from whichever source is closest: the existing
        // active pair first (keeps cross-chapter plays intact), then the
        // playing segment in the displayed slice.
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
 * or merge consumed it), we clear the pair and stop the animation so the UI
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
        stopSegAnimation();
    }
}

export function drawActivePlayhead(): void {
    // Hoist above the pair-change erase branch (below): during any edit mode
    // the preview rAF owns the edit canvas, and the erase branch iterates
    // `getRowEntriesFor(_prevPlaying)` — which includes the edit canvas when
    // adjusting the previously-active segment — and clobbers trim handles
    // with plain peaks via `drawWaveformFromPeaksForSeg`. The old guard was
    // checked AFTER the erase branch and only matched on index equality, so
    // a transient `setPlayingSegment` flip in `onSegTimeUpdate` let the
    // erase fire once. Gating the whole function on editMode removes the
    // race entirely.
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
