/**
 * _playRange — preview playback with animated playhead overlay.
 */

import { get, writable } from 'svelte/store';

import { audioSrcMatches, safePlay } from '../../../../lib/utils/audio';
import { PREVIEW_PLAYHEAD_COLOR } from '../../../../lib/utils/constants';
import { getSegByChapterIndex, selectedChapter } from '../../stores/chapter';
import { editCanvas, editingSegIndex } from '../../stores/edit';
import {
    playbackSpeed,
    segAudioElement,
} from '../../stores/playback';
import type { PreviewLoopMode, RafHandle } from '../../types/segments';
import { drawSplitWaveform } from '../waveform/split-draw';
import { drawTrimWaveform } from '../waveform/trim-draw';
import { vbrClipFor } from './range-spec';

// ---------------------------------------------------------------------------
// Module-local state
// ---------------------------------------------------------------------------

export const previewLooping = writable<PreviewLoopMode>(false);
let _previewJustSeeked = false;
let _playRangeRAF: RafHandle | null = null;
let _previewStopHandler: ((ev: Event) => void) | null = null;
let _previewCanplayHandler: (() => void) | null = null;

export function getPreviewLooping(): PreviewLoopMode { return get(previewLooping); }
export function setPreviewLooping(v: PreviewLoopMode): void { previewLooping.set(v); }

export function setPreviewJustSeeked(v: boolean): void { _previewJustSeeked = v; }

export function getPlayRangeRAF(): RafHandle | null { return _playRangeRAF; }
export function clearPlayRangeRAF(): void {
    if (_playRangeRAF) { cancelAnimationFrame(_playRangeRAF); _playRangeRAF = null; }
}

/** Detach any pending `canplay` listener from the audio element and clear the
 *  handler ref. Called from exitEditMode so that a canplay event that fires
 *  AFTER the user has cancelled the edit doesn't re-enter `doPlay` and kick
 *  off a phantom preview loop on a canvas whose _trimWindow is already gone. */
export function clearPreviewCanplayHandler(): void {
    const audioEl = get(segAudioElement);
    if (audioEl && _previewCanplayHandler) {
        audioEl.removeEventListener('canplay', _previewCanplayHandler);
    }
    _previewCanplayHandler = null;
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
    const canvas = get(editCanvas);

    // VBR routing: when the chapter's audio is VBR-without-Xing, byte-position
    // seeks on the chapter MP3 mis-decode (drift up to ~10 s on long files).
    // For the edit-mode preview we extract a clip of [startMs, endMs] from
    // the source via /api/seg/segment-clip and play it from byte 0 — no seek,
    // no drift. The playhead-drawing branch below recovers file-absolute time
    // by adding `clipFileOffsetMs` to the clip-relative `audioEl.currentTime`.
    const sourceUrl = canvas?._splitData?.audioUrl
        || canvas?._trimWindow?.audioUrl
        || (() => { const ch = get(selectedChapter) ? parseInt(get(selectedChapter)) : null;
                     const editIdx = get(editingSegIndex);
                     const s = ch != null ? getSegByChapterIndex(ch, editIdx) : null;
                     return s && s.audio_url; })()
        || '';
    const vbrClip = sourceUrl ? vbrClipFor(sourceUrl, startMs, endMs) : null;
    const start = vbrClip ? 0 : startMs / 1000;
    const clipFileOffsetMs = vbrClip ? vbrClip.fileOffsetMs : 0;

    let wfStart: number, wfEnd: number;
    // Trim + Split modes: playhead x is mapped against the VISIBLE window
    // (not the full clamp / segment range) — so a zoomed-in view shows the
    // playhead aligned with the rendered peaks. Playback itself is unaffected
    // (still plays the full preview range); when curMs falls outside the
    // visible window the `if (curMs >= wfStart && curMs <= wfEnd)` gate
    // below simply skips drawing for that frame. The animatePlayhead loop
    // re-reads view bounds each frame so wheel-zoom mid-playback updates
    // the mapping live.
    if (canvas?._trimWindow) { wfStart = canvas._trimWindow.viewStart; wfEnd = canvas._trimWindow.viewEnd; }
    else if (canvas?._splitData) { wfStart = canvas._splitData.viewStart; wfEnd = canvas._splitData.viewEnd; }
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
        if (!canvas) return;
        // Keep the rAF chain alive across transient paused states (post-seek
        // before play() resolves, between loop-seek-back and resume, etc).
        // Bailing on paused here used to kill the chain on the first frame
        // after `doPlay` → the playhead never drew, loop-back never ran,
        // drag-updates-loop-live stopped working. Explicit cleanup uses
        // `clearPlayRangeRAF` to cancel the rAF.
        if (audioEl!.paused) {
            _playRangeRAF = requestAnimationFrame(animatePlayhead);
            return;
        }
        // In VBR clip mode `currentTime` is clip-relative; add the file
        // offset so all the file-absolute comparisons below (effectiveEnd,
        // loopStart, viewStart/End) keep working unchanged.
        const curMs = audioEl!.currentTime * 1000 + clipFileOffsetMs;
        const loopMode = get(previewLooping);
        let effectiveEnd = endMs;
        let loopStart: number | null = null;
        if (loopMode === 'trim' && canvas?._trimWindow) {
            effectiveEnd = canvas._trimWindow.currentEnd;
            loopStart = canvas._trimWindow.currentStart;
        } else if (loopMode === 'split-left' && canvas?._splitData) {
            effectiveEnd = canvas._splitData.currentSplit;
            loopStart = canvas._splitData.seg.time_start;
        } else if (loopMode === 'split-right' && canvas?._splitData) {
            effectiveEnd = canvas._splitData.seg.time_end;
            loopStart = canvas._splitData.currentSplit;
        } else if (canvas?._splitData && endMs !== canvas._splitData.seg.time_end) {
            effectiveEnd = canvas._splitData.currentSplit;
        }
        if (_previewJustSeeked && curMs < effectiveEnd) {
            _previewJustSeeked = false;
        }
        if (curMs >= effectiveEnd && !_previewJustSeeked) {
            if (loopMode && loopStart !== null) {
                // loopStart is file-absolute; map it back to clip-relative
                // for the seek when we're playing the segment-clip src.
                audioEl!.currentTime = (loopStart - clipFileOffsetMs) / 1000;
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
        // Re-read view bounds each frame so wheel-zoom mid-playback updates
        // the playhead mapping immediately (closure-captured values would
        // go stale otherwise). Both trim AND split support live re-scaling;
        // non-edit mode keeps its closure-captured bounds.
        const liveStart = canvas._trimWindow ? canvas._trimWindow.viewStart
            : canvas._splitData ? canvas._splitData.viewStart
            : wfStart;
        const liveEnd   = canvas._trimWindow ? canvas._trimWindow.viewEnd
            : canvas._splitData ? canvas._splitData.viewEnd
            : wfEnd;
        if (curMs >= liveStart && curMs <= liveEnd) {
            const ctx = canvas.getContext('2d');
            if (!ctx) { _playRangeRAF = requestAnimationFrame(animatePlayhead); return; }
            const w = canvas.width, h = canvas.height;
            const x = ((curMs - liveStart) / (liveEnd - liveStart)) * w;
            ctx.strokeStyle = PREVIEW_PLAYHEAD_COLOR; ctx.lineWidth = 2;
            ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
            ctx.fillStyle = PREVIEW_PLAYHEAD_COLOR;
            ctx.beginPath(); ctx.moveTo(x - 4, 0); ctx.lineTo(x + 4, 0); ctx.lineTo(x, 6); ctx.closePath(); ctx.fill();
        }
        _playRangeRAF = requestAnimationFrame(animatePlayhead);
    }

    const doPlay = (): void => {
        _previewCanplayHandler = null;
        audioEl.currentTime = start;
        audioEl.playbackRate = get(playbackSpeed);
        safePlay(audioEl);
        // Start the rAF immediately. `animatePlayhead` is now resilient to
        // paused state (see the early-continue above), so whether `safePlay`
        // has resolved yet doesn't matter — the chain keeps ticking and
        // starts drawing the playhead as soon as `audioEl.paused` flips false.
        _playRangeRAF = requestAnimationFrame(animatePlayhead);
    };

    // VBR: load the clip URL instead of the chapter audio. The audio plays
    // from byte 0; `start` is 0 (clip-relative), so `doPlay` seeks to 0 and
    // play() is drift-free.
    const targetUrl = vbrClip ? vbrClip.clipUrl : (canvas?._splitData?.audioUrl
        || canvas?._trimWindow?.audioUrl
        || (() => { const ch = get(selectedChapter) ? parseInt(get(selectedChapter)) : null;
                     const editIdx = get(editingSegIndex);
                     const s = ch != null ? getSegByChapterIndex(ch, editIdx) : null;
                     return s && s.audio_url; })());
    if (targetUrl && !audioSrcMatches(audioEl.src, targetUrl)) {
        if (_previewCanplayHandler) {
            audioEl.removeEventListener('canplay', _previewCanplayHandler);
            _previewCanplayHandler = null;
        }
        _previewCanplayHandler = doPlay;
        audioEl.src = targetUrl;
        audioEl.addEventListener('canplay', doPlay, { once: true });
        audioEl.load();
    } else if (audioEl.src && audioEl.readyState >= 1) {
        doPlay();
    } else if (targetUrl) {
        if (_previewCanplayHandler) {
            audioEl.removeEventListener('canplay', _previewCanplayHandler);
            _previewCanplayHandler = null;
        }
        _previewCanplayHandler = doPlay;
        audioEl.src = targetUrl;
        audioEl.addEventListener('canplay', doPlay, { once: true });
        audioEl.load();
    }
}
