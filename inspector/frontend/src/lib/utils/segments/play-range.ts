/**
 * _playRange — preview playback with animated playhead overlay.
 *
 * Still reads `dom` for audio element access. Preview-looping / seeked /
 * rAF / stop-handler flags are module-local (were on `state`).
 */

import { get } from 'svelte/store';

import { dom } from '../../segments-state';
import { getSegByChapterIndex } from '../../stores/segments/chapter';
import { editingSegIndex } from '../../stores/segments/edit';
import type { PreviewLoopMode, RafHandle } from '../../types/segments';
import type { SegCanvas } from '../../types/segments-waveform';
import { safePlay } from '../audio';
import { _getEditCanvas } from './get-edit-canvas';

// ---------------------------------------------------------------------------
// Module-local state (was state._previewLooping / _previewJustSeeked /
// _playRangeRAF / _previewStopHandler)
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
// Draw function registration (breaks circular imports)
// ---------------------------------------------------------------------------

type DrawWaveformFn = (canvas: SegCanvas) => void;

let _drawSplitWaveformFn: DrawWaveformFn | null = null;
let _drawTrimWaveformFn: DrawWaveformFn | null = null;

export function registerPlayRangeDrawFns(trimDraw: DrawWaveformFn, splitDraw: DrawWaveformFn): void {
    _drawTrimWaveformFn = trimDraw;
    _drawSplitWaveformFn = splitDraw;
}

// ---------------------------------------------------------------------------
// _playRange
// ---------------------------------------------------------------------------

export function _playRange(startMs: number, endMs: number): void {
    if (_previewStopHandler) {
        dom.segAudioEl.removeEventListener('timeupdate', _previewStopHandler);
        _previewStopHandler = null;
    }
    if (_playRangeRAF) { cancelAnimationFrame(_playRangeRAF); _playRangeRAF = null; }
    const start = startMs / 1000;
    const canvas = _getEditCanvas() as SegCanvas | null;

    let wfStart: number, wfEnd: number;
    if (canvas?._trimWindow) { wfStart = canvas._trimWindow.windowStart; wfEnd = canvas._trimWindow.windowEnd; }
    else if (canvas?._splitData) { wfStart = canvas._splitData.seg.time_start; wfEnd = canvas._splitData.seg.time_end; }
    else { wfStart = startMs; wfEnd = endMs; }

    const cleanup = (): void => {
        if (_playRangeRAF) { cancelAnimationFrame(_playRangeRAF); _playRangeRAF = null; }
        if (canvas?._splitData) _drawSplitWaveformFn?.(canvas);
        else if (canvas?._trimWindow) _drawTrimWaveformFn?.(canvas);
    };

    const inEditMode = canvas && (canvas._splitData || canvas._trimWindow);
    let _playRangeSnapshot: ImageData | null = null;
    if (canvas && !inEditMode) {
        const ctx = canvas.getContext('2d');
        if (ctx) _playRangeSnapshot = ctx.getImageData(0, 0, canvas.width, canvas.height);
    }

    function animatePlayhead(): void {
        if (!canvas || dom.segAudioEl.paused) return;
        const curMs = dom.segAudioEl.currentTime * 1000;
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
                dom.segAudioEl.currentTime = loopStart / 1000;
                _previewJustSeeked = true;
                _playRangeRAF = requestAnimationFrame(animatePlayhead);
                return;
            }
            dom.segAudioEl.pause();
            cleanup();
            return;
        }
        if (canvas._splitData) _drawSplitWaveformFn?.(canvas);
        else if (canvas._trimWindow) _drawTrimWaveformFn?.(canvas);
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
        dom.segAudioEl.currentTime = start;
        dom.segAudioEl.playbackRate = parseFloat(dom.segSpeedSelect.value);
        safePlay(dom.segAudioEl);
        _playRangeRAF = requestAnimationFrame(animatePlayhead);
    };

    const targetUrl = canvas?._splitData?.audioUrl
        || canvas?._trimWindow?.audioUrl
        || (() => { const ch = dom.segChapterSelect.value ? parseInt(dom.segChapterSelect.value) : null;
                     const editIdx = get(editingSegIndex);
                     const s = ch != null ? getSegByChapterIndex(ch, editIdx) : null;
                     return s && s.audio_url; })();
    if (targetUrl && !dom.segAudioEl.src.endsWith(targetUrl)) {
        dom.segAudioEl.src = targetUrl;
        dom.segAudioEl.addEventListener('canplay', doPlay, { once: true });
        dom.segAudioEl.load();
    } else if (dom.segAudioEl.src && dom.segAudioEl.readyState >= 1) {
        doPlay();
    } else if (targetUrl) {
        dom.segAudioEl.src = targetUrl;
        dom.segAudioEl.addEventListener('canplay', doPlay, { once: true });
        dom.segAudioEl.load();
    }
}
