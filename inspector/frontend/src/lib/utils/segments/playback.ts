/**
 * Audio playback, animation, highlight tracking, and play status.
 */

import { get } from 'svelte/store';

import {
    getSegByChapterIndex,
    segAllData,
    segCurrentIdx,
    selectedChapter,
} from '../../stores/segments/chapter';
import { editingSegIndex, editMode } from '../../stores/segments/edit';
import { displayedSegments } from '../../stores/segments/filters';
import {
    activeAudioSource,
    autoPlayEnabled,
    continuousPlay,
    isMainAudioPlaying,
    playbackSpeed,
    playButtonLabel,
    playEndMs,
    playingSegmentIndex,
    playStatusText,
    segAudioElement,
    segListElement,
} from '../../stores/segments/playback';
import type { RafHandle } from '../../types/segments';
import type { SegCanvas } from '../../types/segments-waveform';
import { createAnimationLoop } from '../animation';
import { audioSrcMatches, safePlay } from '../audio';
import { getValCardAudioOrNull, stopErrorCardAudio } from './error-card-audio';
import { nextDisplayedSeg, prefetchNextSegAudio } from './prefetch';
import { formatTimeMs } from './references';
import { drawSegPlayhead, drawWaveformFromPeaksForSeg } from './waveform-draw-seg';
import { _fetchPeaksForClick } from './waveform-utils';

// ---------------------------------------------------------------------------
// Module-local state
// ---------------------------------------------------------------------------

let _segAnimId: RafHandle | null = null;
let _segPrefetchCache: Record<string, Promise<unknown>> = {};
let _prevPlayheadIdx = -1;
let _currentPlayheadRow: Element | null = null;

/** Reset the per-reciter prefetch cache (called by reciter/chapter reset). */
export function clearSegPrefetchCache(): void {
    _segPrefetchCache = {};
}

/** Reset playhead DOM refs so the draw layer does not point to nodes
 *  destroyed by the next {#each} reconciliation. Called by filters-apply.ts
 *  before re-rendering the list. The playing-row highlight is Svelte-owned
 *  now (class:playing driven by playingSegmentIndex) so only the canvas
 *  playhead draw state lives here. */
export function resetHighlightRefs(): void {
    _currentPlayheadRow = null;
    _prevPlayheadIdx = -1;
}

export function playFromSegment(
    segIndex: number,
    chapterOverride?: number | null,
    seekToMs?: number | null,
): void {
    const allData = get(segAllData);
    if (!allData) return;
    const audioEl = get(segAudioElement);
    if (!audioEl) return;
    stopErrorCardAudio();
    activeAudioSource.set('main');
    const _chStr = get(selectedChapter);
    const chapter = chapterOverride ?? (_chStr ? parseInt(_chStr) : null);
    const displayed = get(displayedSegments);
    const seg = chapter != null
        ? getSegByChapterIndex(chapter, segIndex)
        : (displayed ? displayed.find(s => s.index === segIndex) : null);
    if (!seg) return;

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
    updateSegPlayStatus();

    prefetchNextSegAudio(displayed, segIndex, audioEl.src || '', _segPrefetchCache);

    // Fetch waveform peaks on-demand via ffmpeg HTTP Range (brief delay expected).
    const chapterForPeaks = chapter ?? parseInt(get(selectedChapter));
    void _fetchPeaksForClick(seg, chapterForPeaks);
}

/** Thin wrapper binding state to the extracted nextDisplayedSeg. */
function _nextDisplayedSeg(afterIndex: number) {
    return nextDisplayedSeg(get(displayedSegments), afterIndex);
}

export function onSegPlayClick(): void {
    const audioEl = get(segAudioElement);
    if (!audioEl) return;
    const valAudio = getValCardAudioOrNull();
    if (valAudio && !valAudio.paused) {
        stopErrorCardAudio();
        return;
    }
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
    const audioEl = get(segAudioElement);
    if (!audioEl) return;
    const timeMs = audioEl.currentTime * 1000;
    const currentSrc = audioEl.src || '';
    const displayed = get(displayedSegments);

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
        audioEl.pause();
        stopSegAnimation();
        continuousPlay.set(false);
        playEndMs.set(0);
        return;
    }

    const prevIdx = get(segCurrentIdx);
    let nextCurrentIdx = -1;
    if (displayed) {
        for (const seg of displayed) {
            if (timeMs >= seg.time_start && timeMs < seg.time_end) {
                if (currentSrc && !audioSrcMatches(seg.audio_url, currentSrc)) continue;
                nextCurrentIdx = seg.index;
                break;
            }
        }
    }
    segCurrentIdx.set(nextCurrentIdx);

    const curPlayEnd = get(playEndMs);
    if (nextCurrentIdx === -1 && curPlayEnd > 0 && timeMs >= curPlayEnd) {
        if (get(continuousPlay) && displayed) {
            const justEnded = displayed.find(s => s.time_end === curPlayEnd
                && audioSrcMatches(s.audio_url, currentSrc));
            if (justEnded) {
                const nextSeg2 = _nextDisplayedSeg(justEnded.index);
                if (nextSeg2 && audioSrcMatches(nextSeg2.audio_url, currentSrc)) {
                    return;
                }
            }
        }
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
        updateSegHighlight();
        updateSegPlayStatus();
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
    playButtonLabel.set('Pause');
    activeAudioSource.set('main');
    isMainAudioPlaying.set(true);
    _segAnimLoop.start();
    _segAnimId = 1;
}

export function stopSegAnimation(): void {
    const valAudio = getValCardAudioOrNull();
    if (!valAudio || valAudio.paused) {
        playButtonLabel.set('Play');
    }
    if (get(activeAudioSource) === 'main') activeAudioSource.set(null);
    isMainAudioPlaying.set(false);
    _segAnimLoop.stop();
    _segAnimId = null;
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
}

export function updateSegHighlight(): void {
    // Svelte's safe_not_equal check makes same-value sets a no-op — safe to
    // call every rAF frame. SegmentRow subscribes via class:playing and
    // re-renders only when the matched index changes.
    playingSegmentIndex.set(get(segCurrentIdx));
}

export function drawActivePlayhead(): void {
    const _chStr = get(selectedChapter);
    const allData = get(segAllData);
    const curIdx = get(segCurrentIdx);
    if (!allData || !_chStr) return;
    if (get(editMode) && curIdx === get(editingSegIndex)) return;
    const chapter = parseInt(_chStr);
    const audioEl = get(segAudioElement);
    if (!audioEl) return;
    const time = audioEl.currentTime * 1000;
    const listEl = get(segListElement);

    const indexChanged = _prevPlayheadIdx !== curIdx;

    // On index change: clear playhead on the previous segment's canvas by
    // redrawing its waveform. _currentPlayheadRow at frame start still points
    // to last frame's current row -- which IS this frame's previous row.
    if (_prevPlayheadIdx >= 0 && indexChanged) {
        const prevRow = _currentPlayheadRow
            || listEl?.querySelector<HTMLElement>(`.seg-row[data-seg-index="${_prevPlayheadIdx}"]`)
            || null;
        if (prevRow) {
            const canvas = prevRow.querySelector<SegCanvas>('canvas');
            const seg = getSegByChapterIndex(chapter, _prevPlayheadIdx);
            if (canvas && seg) {
                drawWaveformFromPeaksForSeg(canvas, seg, chapter);
            }
        }
    }

    if (indexChanged) {
        _currentPlayheadRow = curIdx >= 0
            ? (listEl?.querySelector<HTMLElement>(`.seg-row[data-seg-index="${curIdx}"]`) ?? null)
            : null;
    }
    _prevPlayheadIdx = curIdx;

    if (curIdx >= 0) {
        const row = _currentPlayheadRow;
        if (row) {
            const canvas = row.querySelector<SegCanvas>('canvas');
            const seg = getSegByChapterIndex(chapter, curIdx);
            if (canvas && seg) {
                const audioUrl = seg.audio_url || allData?.audio_by_chapter?.[String(chapter)] || '';
                drawSegPlayhead(canvas, seg.time_start, seg.time_end, time, audioUrl);
            }
        }
    }
}

export function updateSegPlayStatus(): void {
    const _chStr = get(selectedChapter);
    const curIdx = get(segCurrentIdx);
    const allData = get(segAllData);
    const audioEl = get(segAudioElement);
    if (curIdx >= 0 && allData && _chStr && audioEl) {
        const chapter = parseInt(_chStr);
        const seg = getSegByChapterIndex(chapter, curIdx);
        if (seg) {
            playStatusText.set(`Segment #${seg.index} -- ${formatTimeMs(audioEl.currentTime * 1000)}`);
        }
    } else {
        playStatusText.set('');
    }
}
