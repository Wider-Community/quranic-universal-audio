/**
 * Audio playback, animation, highlight tracking, and play status.
 */

import { get } from 'svelte/store';

import { dom } from '../../segments-state';
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
    playEndMs,
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
// Module-local state (was state.segAnimId / _segPrefetchCache / highlight refs)
// ---------------------------------------------------------------------------

let _segAnimId: RafHandle | null = null;
let _segPrefetchCache: Record<string, Promise<unknown>> = {};
let _prevHighlightedRow: Element | null = null;
let _prevHighlightedIdx = -1;
let _prevPlayheadIdx = -1;
let _currentPlayheadRow: Element | null = null;

/** Reset the per-reciter prefetch cache (called by reciter/chapter reset). */
export function clearSegPrefetchCache(): void {
    _segPrefetchCache = {};
}

/** Reset highlight / playhead DOM refs so the highlight layer does not point
 *  to nodes destroyed by the next {#each} reconciliation. Called by
 *  filters-apply.ts before re-rendering the list. */
export function resetHighlightRefs(): void {
    _prevHighlightedRow = null;
    _prevHighlightedIdx = -1;
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
    if (segAudioUrl && !dom.segAudioEl.src.endsWith(segAudioUrl)) {
        dom.segAudioEl.src = segAudioUrl;
    }

    dom.segAudioEl.playbackRate = parseFloat(dom.segSpeedSelect.value);
    dom.segAudioEl.currentTime = (seekToMs != null ? seekToMs : seg.time_start) / 1000;
    safePlay(dom.segAudioEl);
    segCurrentIdx.set(segIndex);
    updateSegPlayStatus();

    prefetchNextSegAudio(displayed, segIndex, dom.segAudioEl.src || '', _segPrefetchCache);

    // Fetch waveform peaks on-demand via ffmpeg HTTP Range (brief delay expected).
    const chapterForPeaks = chapter ?? parseInt(get(selectedChapter));
    void _fetchPeaksForClick(seg, chapterForPeaks);
}

/** Thin wrapper binding state to the extracted nextDisplayedSeg. */
function _nextDisplayedSeg(afterIndex: number) {
    return nextDisplayedSeg(get(displayedSegments), afterIndex);
}

export function onSegPlayClick(): void {
    const valAudio = getValCardAudioOrNull();
    if (valAudio && !valAudio.paused) {
        stopErrorCardAudio();
        return;
    }
    const displayed = get(displayedSegments);
    const curIdx = get(segCurrentIdx);
    if (dom.segAudioEl.paused) {
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
            dom.segAudioEl.playbackRate = parseFloat(dom.segSpeedSelect.value);
            safePlay(dom.segAudioEl);
        }
    } else {
        continuousPlay.set(false);
        dom.segAudioEl.pause();
    }
}

export function onSegTimeUpdate(): void {
    const timeMs = dom.segAudioEl.currentTime * 1000;
    const currentSrc = dom.segAudioEl.src || '';
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
        dom.segAudioEl.pause();
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
        dom.segAudioEl.pause();
        stopSegAnimation();
        continuousPlay.set(false);
        playEndMs.set(0);
        return;
    }

    if (nextCurrentIdx !== prevIdx) {
        if (!get(continuousPlay) && prevIdx >= 0 && nextCurrentIdx >= 0) {
            dom.segAudioEl.pause();
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
            prefetchNextSegAudio(displayed, nextCurrentIdx, dom.segAudioEl.src || '', _segPrefetchCache);
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
    const curPlayEnd = get(playEndMs);
    if (!get(continuousPlay) && curPlayEnd > 0 && !dom.segAudioEl.paused
            && dom.segAudioEl.currentTime * 1000 >= curPlayEnd) {
        dom.segAudioEl.pause();
        // stopSegAnimation will set _segAnimId=null and update UI; return false
        // so the loop itself cancels cleanly.
        stopSegAnimation();
        playEndMs.set(0);
        return false;
    }
    return;
});

export function startSegAnimation(): void {
    dom.segPlayBtn.textContent = 'Pause';
    activeAudioSource.set('main');
    if (_prevHighlightedRow) {
        const btn = _prevHighlightedRow.querySelector('.seg-card-play-btn');
        if (btn) btn.textContent = '\u25A0';
    }
    _segAnimLoop.start();
    _segAnimId = 1;
}

export function stopSegAnimation(): void {
    const valAudio = getValCardAudioOrNull();
    if (!valAudio || valAudio.paused) {
        dom.segPlayBtn.textContent = 'Play';
    }
    if (get(activeAudioSource) === 'main') activeAudioSource.set(null);
    _segAnimLoop.stop();
    _segAnimId = null;
    if (_prevHighlightedRow) {
        const btn = _prevHighlightedRow.querySelector('.seg-card-play-btn');
        if (btn) btn.textContent = '\u25B6';
    }
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

/** Exposed for legacy callers; equivalent to startSegAnimation(). */
export function animateSeg(): void {
    startSegAnimation();
}

/** Check whether the segments animation loop is currently running. */
export function isSegAnimRunning(): boolean {
    return _segAnimId !== null;
}

export function updateSegHighlight(): void {
    const curIdx = get(segCurrentIdx);
    if (curIdx === _prevHighlightedIdx) return;
    if (_prevHighlightedRow) {
        _prevHighlightedRow.classList.remove('playing');
        const prevBtn = _prevHighlightedRow.querySelector('.seg-card-play-btn');
        if (prevBtn) prevBtn.textContent = '\u25B6';
    }
    _prevHighlightedRow = null;
    _prevHighlightedIdx = curIdx;
    if (curIdx >= 0) {
        const row = dom.segListEl.querySelector<HTMLElement>(`.seg-row[data-seg-index="${curIdx}"]`);
        if (row) {
            row.classList.add('playing');
            _prevHighlightedRow = row;
            if (!dom.segAudioEl.paused) {
                const btn = row.querySelector('.seg-card-play-btn');
                if (btn) btn.textContent = '\u25A0';
            }
        }
    }
}

export function drawActivePlayhead(): void {
    const _chStr = get(selectedChapter);
    const allData = get(segAllData);
    const curIdx = get(segCurrentIdx);
    if (!allData || !_chStr) return;
    if (get(editMode) && curIdx === get(editingSegIndex)) return;
    const chapter = parseInt(_chStr);
    const time = dom.segAudioEl.currentTime * 1000;

    const indexChanged = _prevPlayheadIdx !== curIdx;

    // On index change: clear playhead on the previous segment's canvas by
    // redrawing its waveform. _currentPlayheadRow at frame start still points
    // to last frame's current row -- which IS this frame's previous row.
    if (_prevPlayheadIdx >= 0 && indexChanged) {
        const prevRow = _currentPlayheadRow || dom.segListEl.querySelector<HTMLElement>(`.seg-row[data-seg-index="${_prevPlayheadIdx}"]`);
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
            ? dom.segListEl.querySelector<HTMLElement>(`.seg-row[data-seg-index="${curIdx}"]`)
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
    if (curIdx >= 0 && allData && _chStr) {
        const chapter = parseInt(_chStr);
        const seg = getSegByChapterIndex(chapter, curIdx);
        if (seg) {
            dom.segPlayStatus.textContent = `Segment #${seg.index} -- ${formatTimeMs(dom.segAudioEl.currentTime * 1000)}`;
        }
    } else {
        dom.segPlayStatus.textContent = '';
    }
}
