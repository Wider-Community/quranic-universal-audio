/**
 * Error card audio playback and animation.
 * Manages a dedicated <audio> element for playing segments from validation cards.
 */

import { get } from 'svelte/store';

import {
    segAllData,
    selectedChapter,
    selectedReciter,
} from '../../stores/segments/chapter';
import {
    activeAudioSource,
    continuousPlay,
    playbackSpeed,
    playButtonLabel,
    segAudioElement,
} from '../../stores/segments/playback';
import type { Segment } from '../../types/domain';
import type { RafHandle } from '../../types/segments';
import type { SegCanvas } from '../../types/segments-waveform';
import { safePlay } from '../audio';
import { _drawSplitHighlight, drawSegPlayhead, drawWaveformFromPeaksForSeg } from './waveform-draw-seg';
import { _fetchChapterPeaksIfNeeded, _fetchPeaksForClick } from './waveform-utils';

// Canvas metadata attached by other edit modes; error-card animation
// re-reads these to decide whether to keep drawing.
type ValCanvas = SegCanvas;

// ---------------------------------------------------------------------------
// Module-local state
// ---------------------------------------------------------------------------

let valCardAudio: HTMLAudioElement | null = null;
let valCardPlayingBtn: HTMLElement | null = null;
let valCardStopTime: number | null = null;
let valCardAnimId: RafHandle | null = null;
let valCardAnimSeg: Segment | null = null;

/** Read-only accessor for callers that need to check playback state (e.g.
 *  onSegPlayClick checking whether the error-card audio is playing). */
export function getValCardAudioOrNull(): HTMLAudioElement | null {
    return valCardAudio;
}

/** Read-only accessor for the currently-playing error-card button (used by
 *  canvas-scrub to seek the error-card audio when scrubbing its canvas). */
export function getValCardPlayingBtn(): HTMLElement | null {
    return valCardPlayingBtn;
}

// ---------------------------------------------------------------------------
// getValCardAudio — lazy-create a dedicated <audio> element for error cards
// ---------------------------------------------------------------------------

export function getValCardAudio(): HTMLAudioElement {
    if (!valCardAudio) {
        const audio = document.createElement('audio');
        valCardAudio = audio;
        audio.addEventListener('timeupdate', () => {
            if (valCardStopTime !== null && audio.currentTime >= valCardStopTime) {
                stopErrorCardAudio();
            }
        });
        audio.addEventListener('ended', () => { stopErrorCardAudio(); });
        audio.addEventListener('play', () => {
            playButtonLabel.set('Pause');
            activeAudioSource.set('error');
        });
        audio.addEventListener('pause', () => {
            const main = get(segAudioElement);
            if (!main || main.paused) playButtonLabel.set('Play');
            if (get(activeAudioSource) === 'error') activeAudioSource.set(null);
        });
    }
    return valCardAudio;
}

// ---------------------------------------------------------------------------
// stopErrorCardAudio
// ---------------------------------------------------------------------------

export function stopErrorCardAudio(): void {
    if (!valCardAudio) return;
    valCardAudio.pause();
    valCardStopTime = null;
    // Redraw the active canvas so the playhead doesn't linger after stop. The
    // running animation's cleanup frame won't run once we cancel it below, so
    // we do the same redraw it would have done.
    if (valCardPlayingBtn && valCardAnimSeg) {
        const row = valCardPlayingBtn.closest('.seg-row');
        const canvas = row ? row.querySelector<ValCanvas>('canvas') : null;
        if (canvas && !canvas._splitData && !canvas._trimWindow) {
            const seg = valCardAnimSeg;
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
    if (valCardAnimId) {
        cancelAnimationFrame(valCardAnimId);
        valCardAnimId = null;
    }
    valCardAnimSeg = null;
    if (valCardPlayingBtn) {
        valCardPlayingBtn.textContent = '\u25B6';
        valCardPlayingBtn = null;
    }
    if (get(activeAudioSource) === 'error') activeAudioSource.set(null);
}

// ---------------------------------------------------------------------------
// _startValCardAnimation — animate playhead on an error card canvas
// ---------------------------------------------------------------------------

function _startValCardAnimation(btn: HTMLElement, seg: Segment): void {
    if (valCardAnimId) cancelAnimationFrame(valCardAnimId);
    valCardAnimSeg = seg;
    const row = btn.closest('.seg-row');
    const canvas = row ? row.querySelector<ValCanvas>('canvas') : null;
    if (!canvas) return;
    const chapter = seg.chapter ?? 0;
    const allData = get(segAllData);
    const segAudioUrl = seg.audio_url || allData?.audio_by_chapter?.[String(chapter)] || '';
    const splitHL = canvas._splitHL;
    const wfStart = splitHL ? splitHL.wfStart : seg.time_start;
    const wfEnd   = splitHL ? splitHL.wfEnd   : seg.time_end;

    function frame(): void {
        if (!canvas) return;
        if (valCardPlayingBtn !== btn) {
            if (!canvas._splitData && !canvas._trimWindow) {
                const wfSeg: Segment = splitHL ? { ...seg, time_start: wfStart, time_end: wfEnd } : seg;
                drawWaveformFromPeaksForSeg(canvas, wfSeg, chapter);
                if (splitHL) _drawSplitHighlight(canvas, wfSeg);
            }
            valCardAnimId = null;
            valCardAnimSeg = null;
            return;
        }
        if (canvas._splitData || canvas._trimWindow) {
            valCardAnimId = null;
            valCardAnimSeg = null;
            return;
        }
        const audio = getValCardAudio();
        const timeMs = audio.currentTime * 1000;
        if (valCardStopTime !== null && audio.currentTime >= valCardStopTime) {
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
        valCardAnimId = requestAnimationFrame(frame);
    }
    valCardAnimId = requestAnimationFrame(frame);
}

// ---------------------------------------------------------------------------
// playErrorCardAudio — play a segment from a validation error card
// ---------------------------------------------------------------------------

export function playErrorCardAudio(seg: Segment, btn: HTMLElement, seekToMs?: number | null): void {
    const audio = getValCardAudio();
    if (valCardPlayingBtn === btn && !audio.paused && seekToMs == null) {
        stopErrorCardAudio();
        return;
    }
    // Switching to a different error card: stop prior playback so the old
    // canvas's playhead is cleared before the new animation takes over.
    if (valCardPlayingBtn && valCardPlayingBtn !== btn) {
        stopErrorCardAudio();
    }
    const mainAudio = get(segAudioElement);
    if (mainAudio && !mainAudio.paused) {
        continuousPlay.set(false);
        mainAudio.pause();
    }
    activeAudioSource.set('error');
    const chapterKey = seg.chapter != null ? String(seg.chapter) : '';
    const allData = get(segAllData);
    const audioUrl = seg.audio_url
        || (allData && chapterKey && allData.audio_by_chapter?.[chapterKey])
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
            valCardStopTime = endSec;
            audio.playbackRate = get(playbackSpeed);
            safePlay(audio);
        });
    } else {
        audio.currentTime = seekSec;
        valCardStopTime = endSec;
        audio.playbackRate = get(playbackSpeed);
        safePlay(audio);
    }
    btn.textContent = '\u23F9';
    valCardPlayingBtn = btn;
    _startValCardAnimation(btn, seg);

    // Trigger on-demand ffmpeg peaks fetch so the waveform renders in error
    // cards. Chapter view runs _fetchChapterPeaksIfNeeded on chapter load, so
    // by_chapter (local) peaks are already cached when playFromSegment fires.
    // Accordion-only playback has no such prefetch, and /api/seg/segment-peaks
    // can't serve local URLs (HTTP Range via urllib fails), so call both:
    // chapter peaks covers by_chapter local files, segment peaks covers
    // by_surah CDN audio.
    const chStr = get(selectedChapter);
    const chapterForPeaks = seg.chapter ?? (chStr ? parseInt(chStr) : 0);
    if (chapterForPeaks) {
        _fetchChapterPeaksIfNeeded(get(selectedReciter), chapterForPeaks);
        void _fetchPeaksForClick(seg, chapterForPeaks);
    }
}
