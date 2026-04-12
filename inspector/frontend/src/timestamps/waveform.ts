/**
 * Timestamps tab — waveform decoding, peak computation, and canvas drawing.
 */

import { state, dom } from './state';
import { AUDIO_BUFFER_CACHE_SIZE } from '../shared/constants';
import { getSegRelTime, getSegDuration } from './index';
import { updateDisplay } from './playback';
import { fetchArrayBuffer } from '../shared/api';

// NOTE: circular dependency with index.ts (getSegRelTime, getSegDuration) and
// playback.ts (updateDisplay for handleCanvasClick). Safe because these
// functions are only called at runtime via event handlers, long after all
// module-level code has executed.

export function setupCanvas(): void {
    const parent = dom.canvas.parentElement;
    if (!parent) return;
    const rect = parent.getBoundingClientRect();
    dom.canvas.width = rect.width;
    dom.canvas.height = 200;
}

// ---------------------------------------------------------------------------
// Waveform decoding (segment slice)
// ---------------------------------------------------------------------------

type AudioCtxCtor = typeof AudioContext;

export async function decodeWaveform(url: string): Promise<void> {
    if (!url) return;
    try {
        if (!state.audioContext) {
            const Ctor: AudioCtxCtor =
                window.AudioContext ||
                (window as unknown as { webkitAudioContext: AudioCtxCtor }).webkitAudioContext;
            state.audioContext = new Ctor();
        }

        let audioBuffer: AudioBuffer | undefined;
        if (state.audioBufferCache.has(url)) {
            audioBuffer = state.audioBufferCache.get(url);
        } else {
            const arrayBuffer = await fetchArrayBuffer(url);
            audioBuffer = await state.audioContext.decodeAudioData(arrayBuffer);
            // Evict oldest if cache exceeds 5 entries
            if (state.audioBufferCache.size >= AUDIO_BUFFER_CACHE_SIZE) {
                const oldest = state.audioBufferCache.keys().next().value;
                if (oldest !== undefined) state.audioBufferCache.delete(oldest);
            }
            state.audioBufferCache.set(url, audioBuffer);
        }
        if (!audioBuffer) return;
        state.fullAudioBuffer = audioBuffer;

        // Extract segment slice from the full audio
        const rawData = audioBuffer.getChannelData(0);
        const sampleRate = audioBuffer.sampleRate;
        const startSample = Math.floor(state.tsSegOffset * sampleRate);
        const endSample = Math.min(Math.floor(state.tsSegEnd * sampleRate), rawData.length);
        const sliceLength = endSample - startSample;

        if (sliceLength <= 0) {
            // Fallback: use entire buffer if no valid segment offset
            computePeaks(rawData);
            return;
        }

        const slice = rawData.subarray(startSample, endSample);
        computePeaks(slice);
    } catch (e) {
        console.error('Waveform decode failed:', e);
        state.waveformData = null;
    }
}

export function computePeaks(rawData: Float32Array): void {
    const buckets = dom.canvas.width || 1200;
    const blockSize = Math.max(1, Math.floor(rawData.length / buckets));
    const peaks = new Float32Array(buckets * 2); // [min0, max0, min1, max1, ...]

    for (let i = 0; i < buckets; i++) {
        let min = 1.0, max = -1.0;
        const start = i * blockSize;
        for (let j = 0; j < blockSize; j++) {
            const val = rawData[start + j] || 0;
            if (val < min) min = val;
            if (val > max) max = val;
        }
        peaks[i * 2] = min;
        peaks[i * 2 + 1] = max;
    }

    state.waveformData = peaks;
    cacheWaveformSnapshot();
}

// ---------------------------------------------------------------------------
// Canvas drawing
// ---------------------------------------------------------------------------

export function cacheWaveformSnapshot(): void {
    drawVisualization();
    if (!dom.canvas.width || !dom.canvas.height) return;
    if (!state.waveformSnapshot) {
        state.waveformSnapshot = document.createElement('canvas');
    }
    state.waveformSnapshot.width = dom.canvas.width;
    state.waveformSnapshot.height = dom.canvas.height;
    const snapCtx = state.waveformSnapshot.getContext('2d');
    if (snapCtx) snapCtx.drawImage(dom.canvas, 0, 0);
}

export function drawVisualization(): void {
    if (!dom.canvas.width || !dom.canvas.height) return;
    const ctx = dom.ctx;
    if (!ctx) return;

    const width = dom.canvas.width;
    const height = dom.canvas.height;
    const duration = getSegDuration();
    const waveH = height - 30;
    const centerY = waveH / 2;

    // Clear canvas
    ctx.fillStyle = '#0f0f23';
    ctx.fillRect(0, 0, width, height);

    // Draw phoneme boundaries (gray, thin)
    ctx.strokeStyle = '#333';
    ctx.lineWidth = 1;

    state.intervals.forEach(interval => {
        const x = (interval.start / duration) * width;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, waveH);
        ctx.stroke();
    });

    // Draw word boundaries (gold, thicker)
    ctx.strokeStyle = '#f0a500';
    ctx.lineWidth = 2;

    state.words.forEach(word => {
        const x = (word.start / duration) * width;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, waveH);
        ctx.stroke();
    });

    // Draw waveform
    if (state.waveformData) {
        const buckets = state.waveformData.length / 2;
        const scale = waveH / 2 * 0.95;

        // Filled waveform shape
        ctx.beginPath();
        for (let i = 0; i < buckets; i++) {
            const x = (i / buckets) * width;
            const maxVal = state.waveformData[i * 2 + 1] ?? 0;
            const y = centerY - maxVal * scale;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        for (let i = buckets - 1; i >= 0; i--) {
            const x = (i / buckets) * width;
            const minVal = state.waveformData[i * 2] ?? 0;
            const y = centerY - minVal * scale;
            ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.fillStyle = 'rgba(67, 97, 238, 0.3)';
        ctx.fill();

        // Waveform outline
        ctx.strokeStyle = '#4361ee';
        ctx.lineWidth = 1;
        ctx.beginPath();
        for (let i = 0; i < buckets; i++) {
            const x = (i / buckets) * width;
            const maxVal = state.waveformData[i * 2 + 1] ?? 0;
            const y = centerY - maxVal * scale;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.stroke();
        ctx.beginPath();
        for (let i = 0; i < buckets; i++) {
            const x = (i / buckets) * width;
            const minVal = state.waveformData[i * 2] ?? 0;
            const y = centerY - minVal * scale;
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.stroke();
    }
}

export function drawVisualizationWithPlayhead(progress: number): void {
    const ctx = dom.ctx;
    if (!ctx) return;
    if (state.waveformSnapshot && state.waveformSnapshot.width) {
        ctx.drawImage(state.waveformSnapshot, 0, 0);
    } else {
        drawVisualization();
    }

    const width = dom.canvas.width;
    const height = dom.canvas.height - 30;
    const time = getSegRelTime();
    const duration = getSegDuration();

    // Draw current word highlight (subtle gold)
    for (let i = 0; i < state.words.length; i++) {
        const w = state.words[i];
        if (!w) continue;
        if (time >= w.start && time < w.end) {
            const startX = (w.start / duration) * width;
            const endX = (w.end / duration) * width;

            ctx.fillStyle = 'rgba(240, 165, 0, 0.1)';
            ctx.fillRect(startX, 0, endX - startX, height);
            break;
        }
    }

    // Draw current phoneme highlight (blue)
    for (let i = 0; i < state.intervals.length; i++) {
        const iv = state.intervals[i];
        if (!iv) continue;
        if (time >= iv.start && time < iv.end) {
            const startX = (iv.start / duration) * width;
            const endX = (iv.end / duration) * width;

            ctx.fillStyle = 'rgba(76, 201, 240, 0.2)';
            ctx.fillRect(startX, 0, endX - startX, height);
            break;
        }
    }

    // Draw playhead
    const x = progress * width;
    ctx.strokeStyle = '#f72585';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();

    // Draw playhead triangle
    ctx.fillStyle = '#f72585';
    ctx.beginPath();
    ctx.moveTo(x - 6, 0);
    ctx.lineTo(x + 6, 0);
    ctx.lineTo(x, 10);
    ctx.closePath();
    ctx.fill();
}

export function handleCanvasClick(e: MouseEvent): void {
    if (!dom.audio.duration) return;

    const rect = dom.canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const progress = x / dom.canvas.width;

    // Map canvas position to absolute audio time within segment bounds
    const segDuration = getSegDuration();
    const targetRelTime = progress * segDuration;
    dom.audio.currentTime = targetRelTime + state.tsSegOffset;
    updateDisplay();
}
