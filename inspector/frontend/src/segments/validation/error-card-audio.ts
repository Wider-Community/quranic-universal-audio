/**
 * Error card audio playback and animation.
 * Manages a dedicated <audio> element for playing segments from validation cards.
 */

import type { SegCanvas } from '../../lib/types/segments-waveform';
import { safePlay } from '../../lib/utils/audio';
import { _drawSplitHighlight,drawSegPlayhead, drawWaveformFromPeaksForSeg } from '../../lib/utils/segments/waveform-draw-seg';
import { _fetchChapterPeaksIfNeeded,_fetchPeaksForClick } from '../../lib/utils/segments/waveform-utils';
import type { Segment } from '../../types/domain';
import { dom,state } from '../state';

// Canvas metadata attached by other edit modes; error-card animation
// re-reads these to decide whether to keep drawing. Use SegCanvas
// canonical surface from waveform/types.ts.
type ValCanvas = SegCanvas;

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
    // Redraw the active canvas so the playhead doesn't linger after stop. The
    // running animation's cleanup frame won't run once we cancel it below, so
    // we do the same redraw it would have done.
    if (state.valCardPlayingBtn && state.valCardAnimSeg) {
        const row = state.valCardPlayingBtn.closest('.seg-row');
        const canvas = row ? row.querySelector<ValCanvas>('canvas') : null;
        if (canvas && !canvas._splitData && !canvas._trimWindow) {
            const seg = state.valCardAnimSeg;
            const chapter = seg.chapter ?? 0;
            const splitHL = canvas._splitHL;
            const wfSeg: Segment = splitHL
                ? { ...seg, time_start: splitHL.wfStart, time_end: splitHL.wfEnd }
                : seg;
            canvas._wfCache = null;
            const didDraw = drawWaveformFromPeaksForSeg(canvas, wfSeg, chapter);
            if (!didDraw) {
                const ctx = canvas.getContext('2d');
                if (ctx) {
                    ctx.fillStyle = '#0f0f23';
                    ctx.fillRect(0, 0, canvas.width, canvas.height);
                }
            }
            if (splitHL) _drawSplitHighlight(canvas, wfSeg);
        }
    }
    if (state.valCardAnimId) {
        cancelAnimationFrame(state.valCardAnimId);
        state.valCardAnimId = null;
    }
    state.valCardAnimSeg = null;
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
    const chapter = seg.chapter ?? 0;
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
    // Switching to a different error card: stop prior playback so the old
    // canvas's playhead is cleared before the new animation takes over.
    if (state.valCardPlayingBtn && state.valCardPlayingBtn !== btn) {
        stopErrorCardAudio();
    }
    if (!dom.segAudioEl.paused) {
        state._segContinuousPlay = false;
        dom.segAudioEl.pause();
    }
    state._activeAudioSource = 'error';
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

    // Trigger on-demand ffmpeg peaks fetch so the waveform renders in error
    // cards. Chapter view runs _fetchChapterPeaksIfNeeded on chapter load, so
    // by_chapter (local) peaks are already cached when playFromSegment fires.
    // Accordion-only playback has no such prefetch, and /api/seg/segment-peaks
    // can't serve local URLs (HTTP Range via urllib fails), so call both:
    // chapter peaks covers by_chapter local files, segment peaks covers
    // by_surah CDN audio.
    const chapterForPeaks = seg.chapter ?? (dom.segChapterSelect.value ? parseInt(dom.segChapterSelect.value) : 0);
    if (chapterForPeaks) {
        _fetchChapterPeaksIfNeeded(dom.segReciterSelect.value, chapterForPeaks);
        void _fetchPeaksForClick(seg, chapterForPeaks);
    }
}
