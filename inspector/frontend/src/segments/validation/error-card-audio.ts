/**
 * Error card audio playback and animation.
 * Manages a dedicated <audio> element for playing segments from validation cards.
 */

import { state, dom } from '../state';
import { drawWaveformFromPeaksForSeg, drawSegPlayhead, _drawSplitHighlight } from '../waveform/draw';
import { safePlay } from '../../shared/audio';
import type { Segment } from '../../types/domain';

// ---------------------------------------------------------------------------
// Canvas metadata attached by other edit modes; error-card animation
// re-reads these to decide whether to keep drawing.
// ---------------------------------------------------------------------------

interface ValCanvas extends HTMLCanvasElement {
    _splitData?: unknown;
    _trimWindow?: unknown;
    _splitHL?: { wfStart: number; wfEnd: number };
    _wfCache?: ImageData;
    _wfCacheKey?: string;
}

// ---------------------------------------------------------------------------
// getValCardAudio -- lazy-create a dedicated <audio> element for error cards
// ---------------------------------------------------------------------------

export function getValCardAudio(): HTMLAudioElement {
    if (!state.valCardAudio) {
        const audio = document.createElement('audio');
        state.valCardAudio = audio;
        audio.addEventListener('timeupdate', () => {
            if (state.valCardStopTime !== null && audio.currentTime >= state.valCardStopTime) {
                stopErrorCardAudio();
            }
        });
        audio.addEventListener('ended', () => { stopErrorCardAudio(); });
        audio.addEventListener('play', () => {
            dom.segPlayBtn.textContent = 'Pause';
            state._activeAudioSource = 'error';
        });
        audio.addEventListener('pause', () => {
            if (dom.segAudioEl.paused) dom.segPlayBtn.textContent = 'Play';
            if (state._activeAudioSource === 'error') state._activeAudioSource = null;
        });
    }
    return state.valCardAudio;
}

// ---------------------------------------------------------------------------
// stopErrorCardAudio
// ---------------------------------------------------------------------------

export function stopErrorCardAudio(): void {
    if (!state.valCardAudio) return;
    state.valCardAudio.pause();
    state.valCardStopTime = null;
    if (state.valCardPlayingBtn) {
        state.valCardPlayingBtn.textContent = '\u25B6';
        state.valCardPlayingBtn = null;
    }
    if (state._activeAudioSource === 'error') state._activeAudioSource = null;
}

// ---------------------------------------------------------------------------
// _startValCardAnimation -- animate playhead on an error card canvas
// ---------------------------------------------------------------------------

function _startValCardAnimation(btn: HTMLElement, seg: Segment): void {
    if (state.valCardAnimId) cancelAnimationFrame(state.valCardAnimId);
    state.valCardAnimSeg = seg;
    const row = btn.closest('.seg-row');
    const canvas = row ? row.querySelector<ValCanvas>('canvas') : null;
    if (!canvas) return;
    const chapter = seg.chapter;
    const segAudioUrl = seg.audio_url || state.segAllData?.audio_by_chapter?.[String(chapter)] || '';
    const splitHL = canvas._splitHL;
    const wfStart = splitHL ? splitHL.wfStart : seg.time_start;
    const wfEnd   = splitHL ? splitHL.wfEnd   : seg.time_end;

    function frame(): void {
        if (!canvas) return;
        if (state.valCardPlayingBtn !== btn) {
            if (!canvas._splitData && !canvas._trimWindow) {
                const wfSeg: Segment = splitHL ? { ...seg, time_start: wfStart, time_end: wfEnd } : seg;
                drawWaveformFromPeaksForSeg(canvas, wfSeg, chapter);
                if (splitHL) _drawSplitHighlight(canvas, wfSeg);
            }
            state.valCardAnimId = null;
            state.valCardAnimSeg = null;
            return;
        }
        if (canvas._splitData || canvas._trimWindow) {
            state.valCardAnimId = null;
            state.valCardAnimSeg = null;
            return;
        }
        const audio = getValCardAudio();
        const timeMs = audio.currentTime * 1000;
        if (state.valCardStopTime !== null && audio.currentTime >= state.valCardStopTime) {
            stopErrorCardAudio();
            return;
        }
        if (!canvas._wfCache) {
            const cacheKey = `${wfStart}:${wfEnd}`;
            const ctx = canvas.getContext('2d');
            if (ctx) {
                canvas._wfCache = ctx.getImageData(0, 0, canvas.width, canvas.height);
                canvas._wfCacheKey = cacheKey;
            }
        }
        drawSegPlayhead(canvas, wfStart, wfEnd, timeMs, segAudioUrl);
        state.valCardAnimId = requestAnimationFrame(frame);
    }
    state.valCardAnimId = requestAnimationFrame(frame);
}

// ---------------------------------------------------------------------------
// playErrorCardAudio -- play a segment from a validation error card
// ---------------------------------------------------------------------------

export function playErrorCardAudio(seg: Segment, btn: HTMLElement, seekToMs?: number | null): void {
    const audio = getValCardAudio();
    if (state.valCardPlayingBtn === btn && !audio.paused && seekToMs == null) {
        stopErrorCardAudio();
        return;
    }
    if (!dom.segAudioEl.paused) {
        state._segContinuousPlay = false;
        dom.segAudioEl.pause();
    }
    state._activeAudioSource = 'error';
    if (state.valCardPlayingBtn) state.valCardPlayingBtn.textContent = '\u25B6';
    const chapterKey = seg.chapter != null ? String(seg.chapter) : '';
    const audioUrl = seg.audio_url
        || (state.segAllData && chapterKey && state.segAllData.audio_by_chapter?.[chapterKey])
        || '';
    if (!audioUrl) return;
    const seekSec = seekToMs != null ? seekToMs / 1000 : (seg.time_start || 0) / 1000;
    const endSec = (seg.time_end || 0) / 1000;
    if (audio.src !== audioUrl && audio.getAttribute('data-url') !== audioUrl) {
        audio.src = audioUrl;
        audio.setAttribute('data-url', audioUrl);
        audio.addEventListener('loadedmetadata', function onLoad() {
            audio.removeEventListener('loadedmetadata', onLoad);
            audio.currentTime = seekSec;
            state.valCardStopTime = endSec;
            audio.playbackRate = parseFloat(dom.segSpeedSelect.value);
            safePlay(audio);
        });
    } else {
        audio.currentTime = seekSec;
        state.valCardStopTime = endSec;
        audio.playbackRate = parseFloat(dom.segSpeedSelect.value);
        safePlay(audio);
    }
    btn.textContent = '\u23F9';
    state.valCardPlayingBtn = btn;
    _startValCardAnimation(btn, seg);
}
