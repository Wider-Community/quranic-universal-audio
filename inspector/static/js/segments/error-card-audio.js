/**
 * Error card audio playback and animation.
 * Manages a dedicated <audio> element for playing segments from validation cards.
 */

import { state, dom } from './state.js';
import { drawWaveformFromPeaksForSeg, drawSegPlayhead, _drawSplitHighlight } from './waveform-draw.js';
import { safePlay } from '../shared/audio.js';

// ---------------------------------------------------------------------------
// getValCardAudio -- lazy-create a dedicated <audio> element for error cards
// ---------------------------------------------------------------------------

export function getValCardAudio() {
    if (!state.valCardAudio) {
        state.valCardAudio = document.createElement('audio');
        state.valCardAudio.addEventListener('timeupdate', () => {
            if (state.valCardStopTime !== null && state.valCardAudio.currentTime >= state.valCardStopTime) {
                stopErrorCardAudio();
            }
        });
        state.valCardAudio.addEventListener('ended', () => { stopErrorCardAudio(); });
        state.valCardAudio.addEventListener('play', () => {
            dom.segPlayBtn.textContent = 'Pause';
            state._activeAudioSource = 'error';
        });
        state.valCardAudio.addEventListener('pause', () => {
            if (dom.segAudioEl.paused) dom.segPlayBtn.textContent = 'Play';
            if (state._activeAudioSource === 'error') state._activeAudioSource = null;
        });
    }
    return state.valCardAudio;
}

// ---------------------------------------------------------------------------
// stopErrorCardAudio
// ---------------------------------------------------------------------------

export function stopErrorCardAudio() {
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

function _startValCardAnimation(btn, seg) {
    if (state.valCardAnimId) cancelAnimationFrame(state.valCardAnimId);
    state.valCardAnimSeg = seg;
    const row = btn.closest('.seg-row');
    const canvas = row ? row.querySelector('canvas') : null;
    if (!canvas) return;
    const chapter = seg.chapter;
    const segAudioUrl = seg.audio_url || state.segAllData?.audio_by_chapter?.[String(chapter)] || '';
    const splitHL = canvas._splitHL;
    const wfStart = splitHL ? splitHL.wfStart : seg.time_start;
    const wfEnd   = splitHL ? splitHL.wfEnd   : seg.time_end;

    function frame() {
        if (state.valCardPlayingBtn !== btn) {
            if (canvas && !canvas._splitData && !canvas._trimWindow) {
                const wfSeg = splitHL ? { ...seg, time_start: wfStart, time_end: wfEnd } : seg;
                drawWaveformFromPeaksForSeg(canvas, wfSeg, chapter);
                if (splitHL) _drawSplitHighlight(canvas, wfSeg);
            }
            state.valCardAnimId = null;
            state.valCardAnimSeg = null;
            return;
        }
        if (canvas && (canvas._splitData || canvas._trimWindow)) {
            state.valCardAnimId = null;
            state.valCardAnimSeg = null;
            return;
        }
        const timeMs = getValCardAudio().currentTime * 1000;
        if (state.valCardStopTime !== null && getValCardAudio().currentTime >= state.valCardStopTime) {
            stopErrorCardAudio();
            return;
        }
        if (!canvas._wfCache) {
            const cacheKey = `${wfStart}:${wfEnd}`;
            canvas._wfCache = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height);
            canvas._wfCacheKey = cacheKey;
        }
        drawSegPlayhead(canvas, wfStart, wfEnd, timeMs, segAudioUrl);
        state.valCardAnimId = requestAnimationFrame(frame);
    }
    state.valCardAnimId = requestAnimationFrame(frame);
}

// ---------------------------------------------------------------------------
// playErrorCardAudio -- play a segment from a validation error card
// ---------------------------------------------------------------------------

export function playErrorCardAudio(seg, btn, seekToMs) {
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
    const audioUrl = seg.audio_url || (state.segAllData && state.segAllData.audio_by_chapter && state.segAllData.audio_by_chapter[seg.chapter]) || '';
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
