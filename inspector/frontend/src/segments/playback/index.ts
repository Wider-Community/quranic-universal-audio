/**
 * Audio playback, animation, highlight tracking, and play status.
 */

import { state, dom } from '../state';
import { getSegByChapterIndex } from '../data';
import { formatTimeMs } from '../references';
import { drawWaveformFromPeaksForSeg, drawSegPlayhead } from '../waveform/draw';
import { stopErrorCardAudio } from '../validation/error-card-audio';
import { safePlay } from '../../shared/audio';
import { createAnimationLoop } from '../../shared/animation';
import type { SegCanvas } from '../waveform/types';

/** Compare a segment's audio_url against segAudioEl.src. */
function _audioSrcMatch(segUrl: string | null | undefined, elSrc: string | null | undefined): boolean {
    if (!segUrl || !elSrc) return false;
    if (segUrl === elSrc) return true;
    return elSrc.endsWith(segUrl);
}

export function playFromSegment(
    segIndex: number,
    chapterOverride?: number | null,
    seekToMs?: number | null,
): void {
    if (!state.segAllData) return;
    stopErrorCardAudio();
    state._activeAudioSource = 'main';
    const chapter = chapterOverride ?? (dom.segChapterSelect.value ? parseInt(dom.segChapterSelect.value) : null);
    const seg = chapter != null
        ? getSegByChapterIndex(chapter, segIndex)
        : (state.segDisplayedSegments ? state.segDisplayedSegments.find(s => s.index === segIndex) : null);
    if (!seg) return;

    state._segContinuousPlay = state._segAutoPlayEnabled;
    state._segPlayEndMs = seg.time_end;

    const segAudioUrl = seg.audio_url || '';
    if (segAudioUrl && !dom.segAudioEl.src.endsWith(segAudioUrl)) {
        dom.segAudioEl.src = segAudioUrl;
    }

    dom.segAudioEl.playbackRate = parseFloat(dom.segSpeedSelect.value);
    dom.segAudioEl.currentTime = (seekToMs != null ? seekToMs : seg.time_start) / 1000;
    safePlay(dom.segAudioEl);
    state.segCurrentIdx = segIndex;
    updateSegPlayStatus();

    _prefetchNextSegAudio(segIndex);
}

function _nextDisplayedSeg(afterIndex: number) {
    if (!state.segDisplayedSegments) return null;
    const pos = state.segDisplayedSegments.findIndex(s => s.index === afterIndex);
    if (pos >= 0 && pos < state.segDisplayedSegments.length - 1) {
        return state.segDisplayedSegments[pos + 1] ?? null;
    }
    return null;
}

function _prefetchNextSegAudio(currentIndex: number): void {
    const next = _nextDisplayedSeg(currentIndex);
    if (!next) return;
    const currentUrl = dom.segAudioEl.src || '';
    if (!next.audio_url || _audioSrcMatch(next.audio_url, currentUrl)) return;
    if (next.audio_url in state._segPrefetchCache) return;
    state._segPrefetchCache[next.audio_url] = fetch(next.audio_url)
        .then(r => r.blob())
        .catch(() => {});
}

export function onSegPlayClick(): void {
    if (state.valCardAudio && !state.valCardAudio.paused) {
        stopErrorCardAudio();
        return;
    }
    if (dom.segAudioEl.paused) {
        if (state.segDisplayedSegments && state.segDisplayedSegments.length > 0 && state.segCurrentIdx < 0) {
            const first = state.segDisplayedSegments[0];
            if (first) playFromSegment(first.index, first.chapter);
        } else {
            state._segContinuousPlay = state._segAutoPlayEnabled;
            state._activeAudioSource = 'main';
            if (state.segCurrentIdx >= 0 && state.segDisplayedSegments) {
                const curSeg = state.segDisplayedSegments.find(s => s.index === state.segCurrentIdx);
                if (curSeg) state._segPlayEndMs = curSeg.time_end;
            }
            dom.segAudioEl.playbackRate = parseFloat(dom.segSpeedSelect.value);
            safePlay(dom.segAudioEl);
        }
    } else {
        state._segContinuousPlay = false;
        dom.segAudioEl.pause();
    }
}

export function onSegTimeUpdate(): void {
    const timeMs = dom.segAudioEl.currentTime * 1000;
    const currentSrc = dom.segAudioEl.src || '';

    let lastSegOnAudio = null;
    if (state.segDisplayedSegments && state.segDisplayedSegments.length > 0) {
        for (let i = state.segDisplayedSegments.length - 1; i >= 0; i--) {
            const s = state.segDisplayedSegments[i];
            if (s && _audioSrcMatch(s.audio_url, currentSrc)) {
                lastSegOnAudio = s;
                break;
            }
        }
        if (!lastSegOnAudio) lastSegOnAudio = state.segDisplayedSegments[state.segDisplayedSegments.length - 1] ?? null;
    }

    if (lastSegOnAudio && timeMs >= lastSegOnAudio.time_end) {
        const nextSeg = _nextDisplayedSeg(lastSegOnAudio.index);
        const isConsecutive = nextSeg && nextSeg.index === lastSegOnAudio.index + 1;
        if (state._segContinuousPlay && isConsecutive && nextSeg && !_audioSrcMatch(nextSeg.audio_url, currentSrc)) {
            playFromSegment(nextSeg.index, nextSeg.chapter);
            return;
        }
        dom.segAudioEl.pause();
        stopSegAnimation();
        state._segContinuousPlay = false;
        state._segPlayEndMs = 0;
        return;
    }

    const prevIdx = state.segCurrentIdx;
    state.segCurrentIdx = -1;
    if (state.segDisplayedSegments) {
        for (const seg of state.segDisplayedSegments) {
            if (timeMs >= seg.time_start && timeMs < seg.time_end) {
                if (currentSrc && !_audioSrcMatch(seg.audio_url, currentSrc)) continue;
                state.segCurrentIdx = seg.index;
                break;
            }
        }
    }

    if (state.segCurrentIdx === -1 && state._segPlayEndMs > 0 && timeMs >= state._segPlayEndMs) {
        if (state._segContinuousPlay && state.segDisplayedSegments) {
            const justEnded = state.segDisplayedSegments.find(s => s.time_end === state._segPlayEndMs
                && _audioSrcMatch(s.audio_url, currentSrc));
            if (justEnded) {
                const nextSeg2 = _nextDisplayedSeg(justEnded.index);
                if (nextSeg2 && _audioSrcMatch(nextSeg2.audio_url, currentSrc)) {
                    return;
                }
            }
        }
        dom.segAudioEl.pause();
        stopSegAnimation();
        state._segContinuousPlay = false;
        state._segPlayEndMs = 0;
        return;
    }

    if (state.segCurrentIdx !== prevIdx) {
        if (!state._segContinuousPlay && prevIdx >= 0 && state.segCurrentIdx >= 0) {
            dom.segAudioEl.pause();
            stopSegAnimation();
            state._segPlayEndMs = 0;
            return;
        }
        if (state.segCurrentIdx >= 0 && state.segDisplayedSegments) {
            const curSeg = state.segDisplayedSegments.find(s => s.index === state.segCurrentIdx);
            if (curSeg) state._segPlayEndMs = curSeg.time_end;
        }
        updateSegHighlight();
        updateSegPlayStatus();
        if (state.segCurrentIdx >= 0) _prefetchNextSegAudio(state.segCurrentIdx);
    }
}

// ---------------------------------------------------------------------------
// Animation loop (wraps shared/animation.ts createAnimationLoop)
// ---------------------------------------------------------------------------
// Behavior preserved verbatim from the old rAF loop: each frame calls
// updateSegHighlight + drawActivePlayhead, and returns `false` to self-stop
// when continuous-play has ended. `state.segAnimId` is synced so external
// checks (truthy means "running") behave identically.
const _segAnimLoop = createAnimationLoop(() => {
    updateSegHighlight();
    drawActivePlayhead();
    if (!state._segContinuousPlay && state._segPlayEndMs > 0 && !dom.segAudioEl.paused
            && dom.segAudioEl.currentTime * 1000 >= state._segPlayEndMs) {
        dom.segAudioEl.pause();
        // stopSegAnimation will set segAnimId=null and update UI; return false
        // so the loop itself cancels cleanly.
        stopSegAnimation();
        state._segPlayEndMs = 0;
        return false;
    }
    return;
});

export function startSegAnimation(): void {
    dom.segPlayBtn.textContent = 'Pause';
    state._activeAudioSource = 'main';
    if (state._prevHighlightedRow) {
        const btn = state._prevHighlightedRow.querySelector('.seg-card-play-btn');
        if (btn) btn.textContent = '\u25A0';
    }
    _segAnimLoop.start();
    state.segAnimId = 1;
}

export function stopSegAnimation(): void {
    if (!state.valCardAudio || state.valCardAudio.paused) {
        dom.segPlayBtn.textContent = 'Play';
    }
    if (state._activeAudioSource === 'main') state._activeAudioSource = null;
    _segAnimLoop.stop();
    state.segAnimId = null;
    if (state._prevHighlightedRow) {
        const btn = state._prevHighlightedRow.querySelector('.seg-card-play-btn');
        if (btn) btn.textContent = '\u25B6';
    }
}

export function onSegAudioEnded(): void {
    if (state._segContinuousPlay && state.segCurrentIdx >= 0) {
        const next = _nextDisplayedSeg(state.segCurrentIdx);
        if (next && next.audio_url) {
            playFromSegment(next.index, next.chapter);
            return;
        }
    }
    state._segContinuousPlay = false;
    stopSegAnimation();
}

/** Exposed for legacy callers; equivalent to startSegAnimation(). */
export function animateSeg(): void {
    startSegAnimation();
}

export function updateSegHighlight(): void {
    if (state.segCurrentIdx === state._prevHighlightedIdx) return;
    if (state._prevHighlightedRow) {
        state._prevHighlightedRow.classList.remove('playing');
        const prevBtn = state._prevHighlightedRow.querySelector('.seg-card-play-btn');
        if (prevBtn) prevBtn.textContent = '\u25B6';
    }
    state._prevHighlightedRow = null;
    state._prevHighlightedIdx = state.segCurrentIdx;
    if (state.segCurrentIdx >= 0) {
        const row = dom.segListEl.querySelector<HTMLElement>(`.seg-row[data-seg-index="${state.segCurrentIdx}"]`);
        if (row) {
            row.classList.add('playing');
            state._prevHighlightedRow = row;
            if (!dom.segAudioEl.paused) {
                const btn = row.querySelector('.seg-card-play-btn');
                if (btn) btn.textContent = '\u25A0';
            }
        }
    }
}

export function drawActivePlayhead(): void {
    if (!state.segAllData || !dom.segChapterSelect.value) return;
    if (state.segEditMode && state.segCurrentIdx === state.segEditIndex) return;
    const chapter = parseInt(dom.segChapterSelect.value);
    const time = dom.segAudioEl.currentTime * 1000;

    const indexChanged = state._prevPlayheadIdx !== state.segCurrentIdx;

    if (state._prevPlayheadIdx >= 0 && indexChanged) {
        const prevRow = state._prevPlayheadRow || dom.segListEl.querySelector<HTMLElement>(`.seg-row[data-seg-index="${state._prevPlayheadIdx}"]`);
        if (prevRow) {
            const canvas = prevRow.querySelector<SegCanvas>('canvas');
            const seg = getSegByChapterIndex(chapter, state._prevPlayheadIdx);
            if (canvas && seg) {
                drawWaveformFromPeaksForSeg(canvas, seg, chapter);
            }
        }
    }

    if (indexChanged) {
        state._prevPlayheadRow = state._currentPlayheadRow;
        state._currentPlayheadRow = state.segCurrentIdx >= 0
            ? dom.segListEl.querySelector<HTMLElement>(`.seg-row[data-seg-index="${state.segCurrentIdx}"]`)
            : null;
    }
    state._prevPlayheadIdx = state.segCurrentIdx;

    if (state.segCurrentIdx >= 0) {
        const row = state._currentPlayheadRow;
        if (row) {
            const canvas = row.querySelector<SegCanvas>('canvas');
            const seg = getSegByChapterIndex(chapter, state.segCurrentIdx);
            if (canvas && seg) {
                const audioUrl = seg.audio_url || state.segAllData?.audio_by_chapter?.[String(chapter)] || '';
                drawSegPlayhead(canvas, seg.time_start, seg.time_end, time, audioUrl);
            }
        }
    }
}

export function updateSegPlayStatus(): void {
    if (state.segCurrentIdx >= 0 && state.segAllData && dom.segChapterSelect.value) {
        const chapter = parseInt(dom.segChapterSelect.value);
        const seg = getSegByChapterIndex(chapter, state.segCurrentIdx);
        if (seg) {
            dom.segPlayStatus.textContent = `Segment #${seg.index} -- ${formatTimeMs(dom.segAudioEl.currentTime * 1000)}`;
        }
    } else {
        dom.segPlayStatus.textContent = '';
    }
}
