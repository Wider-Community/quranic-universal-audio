/**
 * _playRange — preview playback with animated playhead overlay.
 */

import { get } from 'svelte/store';

import { getSegByChapterIndex, selectedChapter } from '../../stores/segments/chapter';
import { editCanvas, editingSegIndex } from '../../stores/segments/edit';
import {
    playbackSpeed,
    segAudioElement,
} from '../../stores/segments/playback';
import type { PreviewLoopMode, RafHandle } from '../../types/segments';
import { safePlay } from '../audio';
import { drawSplitWaveform } from './split-draw';
import { drawTrimWaveform } from './trim-draw';

// ---------------------------------------------------------------------------
// Module-local state
// ---------------------------------------------------------------------------

let _previewLooping: PreviewLoopMode = false;
let _previewJustSeeked = false;
let _playRangeRAF: RafHandle | null = null;
let _previewStopHandler: ((ev: Event) => void) | null = null;

export function getPreviewLooping(): PreviewLoopMode { return _previewLooping; }
export function setPreviewLooping(v: PreviewLoopMode): void { _previewLooping = v; }

export function setPreviewJustSeeked(v: boolean): void { _previewJustSeeked = v; }

export function getPlayRangeRAF(): RafHandle | null { return _playRangeRAF; }
export function clearPlayRangeRAF(): void {
    if (_playRangeRAF) { cancelAnimationFrame(_playRangeRAF); _playRangeRAF = null; }
}

export function getPreviewStopHandler(): ((ev: Event) => void) | null { return _previewStopHandler; }
export function setPreviewStopHandler(h: ((ev: Event) => void) | null): void { _previewStopHandler = h; }

// ---------------------------------------------------------------------------
// _playRange
// ---------------------------------------------------------------------------

export function _playRange(startMs: number, endMs: number): void {
    const audioEl = get(segAudioElement);
    if (!audioEl) return;
    if (_previewStopHandler) {
        audioEl.removeEventListener('timeupdate', _previewStopHandler);
        _previewStopHandler = null;
    }
    if (_playRangeRAF) { cancelAnimationFrame(_playRangeRAF); _playRangeRAF = null; }
    const start = startMs / 1000;
    const canvas = get(editCanvas);

    let wfStart: number, wfEnd: number;
    if (canvas?._trimWindow) { wfStart = canvas._trimWindow.windowStart; wfEnd = canvas._trimWindow.windowEnd; }
    else if (canvas?._splitData) { wfStart = canvas._splitData.seg.time_start; wfEnd = canvas._splitData.seg.time_end; }
    else { wfStart = startMs; wfEnd = endMs; }

    const cleanup = (): void => {
        if (_playRangeRAF) { cancelAnimationFrame(_playRangeRAF); _playRangeRAF = null; }
        if (canvas?._splitData) drawSplitWaveform(canvas);
        else if (canvas?._trimWindow) drawTrimWaveform(canvas);
    };

    const inEditMode = canvas && (canvas._splitData || canvas._trimWindow);
    let _playRangeSnapshot: ImageData | null = null;
    if (canvas && !inEditMode) {
        const ctx = canvas.getContext('2d');
        if (ctx) _playRangeSnapshot = ctx.getImageData(0, 0, canvas.width, canvas.height);
    }

    function animatePlayhead(): void {
        if (!canvas || audioEl!.paused) return;
        const curMs = audioEl!.currentTime * 1000;
        let effectiveEnd = endMs;
        let loopStart: number | null = null;
        if (_previewLooping === 'trim' && canvas?._trimWindow) {
            effectiveEnd = canvas._trimWindow.currentEnd;
            loopStart = canvas._trimWindow.currentStart;
        } else if (_previewLooping === 'split-left' && canvas?._splitData) {
            effectiveEnd = canvas._splitData.currentSplit;
            loopStart = canvas._splitData.seg.time_start;
        } else if (_previewLooping === 'split-right' && canvas?._splitData) {
            effectiveEnd = canvas._splitData.seg.time_end;
            loopStart = canvas._splitData.currentSplit;
        } else if (canvas?._splitData && endMs !== canvas._splitData.seg.time_end) {
            effectiveEnd = canvas._splitData.currentSplit;
        }
        if (_previewJustSeeked && curMs < effectiveEnd) {
            _previewJustSeeked = false;
        }
        if (curMs >= effectiveEnd && !_previewJustSeeked) {
            if (_previewLooping && loopStart !== null) {
                audioEl!.currentTime = loopStart / 1000;
                _previewJustSeeked = true;
                _playRangeRAF = requestAnimationFrame(animatePlayhead);
                return;
            }
            audioEl!.pause();
            cleanup();
            return;
        }
        if (canvas._splitData) drawSplitWaveform(canvas);
        else if (canvas._trimWindow) drawTrimWaveform(canvas);
        else if (_playRangeSnapshot) {
            const ctx2 = canvas.getContext('2d');
            if (ctx2) ctx2.putImageData(_playRangeSnapshot, 0, 0);
        }
        if (curMs >= wfStart && curMs <= wfEnd) {
            const ctx = canvas.getContext('2d');
            if (!ctx) { _playRangeRAF = requestAnimationFrame(animatePlayhead); return; }
            const w = canvas.width, h = canvas.height;
            const x = ((curMs - wfStart) / (wfEnd - wfStart)) * w;
            ctx.strokeStyle = '#f72585'; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
            ctx.fillStyle = '#f72585';
            ctx.beginPath(); ctx.moveTo(x - 4, 0); ctx.lineTo(x + 4, 0); ctx.lineTo(x, 6); ctx.closePath(); ctx.fill();
        }
        _playRangeRAF = requestAnimationFrame(animatePlayhead);
    }

    const doPlay = (): void => {
        audioEl.currentTime = start;
        audioEl.playbackRate = get(playbackSpeed);
        safePlay(audioEl);
        _playRangeRAF = requestAnimationFrame(animatePlayhead);
    };

    const chStr = get(selectedChapter);
    const targetUrl = canvas?._splitData?.audioUrl
        || canvas?._trimWindow?.audioUrl
        || (() => { const ch = chStr ? parseInt(chStr) : null;
                     const editIdx = get(editingSegIndex);
                     const s = ch != null ? getSegByChapterIndex(ch, editIdx) : null;
                     return s && s.audio_url; })();
    if (targetUrl && !audioEl.src.endsWith(targetUrl)) {
        audioEl.src = targetUrl;
        audioEl.addEventListener('canplay', doPlay, { once: true });
        audioEl.load();
    } else if (audioEl.src && audioEl.readyState >= 1) {
        doPlay();
    } else if (targetUrl) {
        audioEl.src = targetUrl;
        audioEl.addEventListener('canplay', doPlay, { once: true });
        audioEl.load();
    }
}
