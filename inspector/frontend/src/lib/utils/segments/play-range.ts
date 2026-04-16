/**
 * _playRange — preview playback with animated playhead overlay.
 *
 * Extracted from segments/edit/common.ts (Ph4a). Still reads `state` and
 * `dom` for preview-looping flags and audio element access. A future
 * refactor (Ph4b+) can parameterize these away; for now the extraction
 * centralizes the logic in lib/ while preserving behavior.
 */

import { dom, state } from '../../../segments/state';
import { getSegByChapterIndex } from '../../stores/segments/chapter';
import type { SegCanvas } from '../../types/segments-waveform';
import { safePlay } from '../audio';
import { _getEditCanvas } from './get-edit-canvas';

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
    if (state._previewStopHandler) {
        dom.segAudioEl.removeEventListener('timeupdate', state._previewStopHandler);
        state._previewStopHandler = null;
    }
    if (state._playRangeRAF) { cancelAnimationFrame(state._playRangeRAF); state._playRangeRAF = null; }
    const start = startMs / 1000;
    const canvas = _getEditCanvas() as SegCanvas | null;

    let wfStart: number, wfEnd: number;
    if (canvas?._trimWindow) { wfStart = canvas._trimWindow.windowStart; wfEnd = canvas._trimWindow.windowEnd; }
    else if (canvas?._splitData) { wfStart = canvas._splitData.seg.time_start; wfEnd = canvas._splitData.seg.time_end; }
    else { wfStart = startMs; wfEnd = endMs; }

    const cleanup = (): void => {
        if (state._playRangeRAF) { cancelAnimationFrame(state._playRangeRAF); state._playRangeRAF = null; }
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
        if (state._previewLooping === 'trim' && canvas?._trimWindow) {
            effectiveEnd = canvas._trimWindow.currentEnd;
            loopStart = canvas._trimWindow.currentStart;
        } else if (state._previewLooping === 'split-left' && canvas?._splitData) {
            effectiveEnd = canvas._splitData.currentSplit;
            loopStart = canvas._splitData.seg.time_start;
        } else if (state._previewLooping === 'split-right' && canvas?._splitData) {
            effectiveEnd = canvas._splitData.seg.time_end;
            loopStart = canvas._splitData.currentSplit;
        } else if (canvas?._splitData && endMs !== canvas._splitData.seg.time_end) {
            effectiveEnd = canvas._splitData.currentSplit;
        }
        if (state._previewJustSeeked && curMs < effectiveEnd) {
            state._previewJustSeeked = false;
        }
        if (curMs >= effectiveEnd && !state._previewJustSeeked) {
            if (state._previewLooping && loopStart !== null) {
                dom.segAudioEl.currentTime = loopStart / 1000;
                state._previewJustSeeked = true;
                state._playRangeRAF = requestAnimationFrame(animatePlayhead);
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
            if (!ctx) { state._playRangeRAF = requestAnimationFrame(animatePlayhead); return; }
            const w = canvas.width, h = canvas.height;
            const x = ((curMs - wfStart) / (wfEnd - wfStart)) * w;
            ctx.strokeStyle = '#f72585'; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
            ctx.fillStyle = '#f72585';
            ctx.beginPath(); ctx.moveTo(x - 4, 0); ctx.lineTo(x + 4, 0); ctx.lineTo(x, 6); ctx.closePath(); ctx.fill();
        }
        state._playRangeRAF = requestAnimationFrame(animatePlayhead);
    }

    const doPlay = (): void => {
        dom.segAudioEl.currentTime = start;
        dom.segAudioEl.playbackRate = parseFloat(dom.segSpeedSelect.value);
        safePlay(dom.segAudioEl);
        state._playRangeRAF = requestAnimationFrame(animatePlayhead);
    };

    const targetUrl = canvas?._splitData?.audioUrl
        || canvas?._trimWindow?.audioUrl
        || (() => { const ch = dom.segChapterSelect.value ? parseInt(dom.segChapterSelect.value) : null;
                     const s = ch != null ? getSegByChapterIndex(ch, state.segEditIndex) : null;
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
