/**
 * Timestamps tab — waveform decoding, peak computation, and canvas drawing.
 */

import { state, dom } from './state.js';
import { getSegRelTime, getSegDuration } from './index.js';
import { updateDisplay } from './playback.js';

// NOTE: circular dependency with index.js (getSegRelTime, getSegDuration) and
// playback.js (updateDisplay for handleCanvasClick). Safe because these
// functions are only called at runtime via event handlers, long after all
// module-level code has executed.

export function setupCanvas() {
    const rect = dom.canvas.parentElement.getBoundingClientRect();
    dom.canvas.width = rect.width;
    dom.canvas.height = 200;
}

// ---------------------------------------------------------------------------
// Waveform decoding (segment slice)
// ---------------------------------------------------------------------------

export async function decodeWaveform(url) {
    if (!url) return;
    try {
        if (!state.audioContext) {
            state.audioContext = new (window.AudioContext || window.webkitAudioContext)();
        }

        let audioBuffer;
        if (state.audioBufferCache.has(url)) {
            audioBuffer = state.audioBufferCache.get(url);
        } else {
            const response = await fetch(url);
            const arrayBuffer = await response.arrayBuffer();
            audioBuffer = await state.audioContext.decodeAudioData(arrayBuffer);
            // Evict oldest if cache exceeds 5 entries
            if (state.audioBufferCache.size >= 5) {
                const oldest = state.audioBufferCache.keys().next().value;
                state.audioBufferCache.delete(oldest);
            }
            state.audioBufferCache.set(url, audioBuffer);
        }
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

export function computePeaks(rawData) {
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

export function cacheWaveformSnapshot() {
    drawVisualization();
    if (!dom.canvas.width || !dom.canvas.height) return;
    if (!state.waveformSnapshot) {
        state.waveformSnapshot = document.createElement('canvas');
    }
    state.waveformSnapshot.width = dom.canvas.width;
    state.waveformSnapshot.height = dom.canvas.height;
    state.waveformSnapshot.getContext('2d').drawImage(dom.canvas, 0, 0);
}

export function drawVisualization() {
    if (!dom.canvas.width || !dom.canvas.height) return;

    const width = dom.canvas.width;
    const height = dom.canvas.height;
    const duration = getSegDuration();
    const waveH = height - 30;
    const centerY = waveH / 2;

    // Clear canvas
    dom.ctx.fillStyle = '#0f0f23';
    dom.ctx.fillRect(0, 0, width, height);

    // Draw phoneme boundaries (gray, thin)
    dom.ctx.strokeStyle = '#333';
    dom.ctx.lineWidth = 1;

    state.intervals.forEach(interval => {
        const x = (interval.start / duration) * width;
        dom.ctx.beginPath();
        dom.ctx.moveTo(x, 0);
        dom.ctx.lineTo(x, waveH);
        dom.ctx.stroke();
    });

    // Draw word boundaries (gold, thicker)
    dom.ctx.strokeStyle = '#f0a500';
    dom.ctx.lineWidth = 2;

    state.words.forEach(word => {
        const x = (word.start / duration) * width;
        dom.ctx.beginPath();
        dom.ctx.moveTo(x, 0);
        dom.ctx.lineTo(x, waveH);
        dom.ctx.stroke();
    });

    // Draw waveform
    if (state.waveformData) {
        const buckets = state.waveformData.length / 2;
        const scale = waveH / 2 * 0.95;

        // Filled waveform shape
        dom.ctx.beginPath();
        for (let i = 0; i < buckets; i++) {
            const x = (i / buckets) * width;
            const maxVal = state.waveformData[i * 2 + 1];
            const y = centerY - maxVal * scale;
            if (i === 0) dom.ctx.moveTo(x, y);
            else dom.ctx.lineTo(x, y);
        }
        for (let i = buckets - 1; i >= 0; i--) {
            const x = (i / buckets) * width;
            const minVal = state.waveformData[i * 2];
            const y = centerY - minVal * scale;
            dom.ctx.lineTo(x, y);
        }
        dom.ctx.closePath();
        dom.ctx.fillStyle = 'rgba(67, 97, 238, 0.3)';
        dom.ctx.fill();

        // Waveform outline
        dom.ctx.strokeStyle = '#4361ee';
        dom.ctx.lineWidth = 1;
        dom.ctx.beginPath();
        for (let i = 0; i < buckets; i++) {
            const x = (i / buckets) * width;
            const maxVal = state.waveformData[i * 2 + 1];
            const y = centerY - maxVal * scale;
            if (i === 0) dom.ctx.moveTo(x, y);
            else dom.ctx.lineTo(x, y);
        }
        dom.ctx.stroke();
        dom.ctx.beginPath();
        for (let i = 0; i < buckets; i++) {
            const x = (i / buckets) * width;
            const minVal = state.waveformData[i * 2];
            const y = centerY - minVal * scale;
            if (i === 0) dom.ctx.moveTo(x, y);
            else dom.ctx.lineTo(x, y);
        }
        dom.ctx.stroke();
    }
}

export function drawVisualizationWithPlayhead(progress) {
    if (state.waveformSnapshot && state.waveformSnapshot.width) {
        dom.ctx.drawImage(state.waveformSnapshot, 0, 0);
    } else {
        drawVisualization();
    }

    const width = dom.canvas.width;
    const height = dom.canvas.height - 30;
    const time = getSegRelTime();
    const duration = getSegDuration();

    // Draw current word highlight (subtle gold)
    for (let i = 0; i < state.words.length; i++) {
        if (time >= state.words[i].start && time < state.words[i].end) {
            const startX = (state.words[i].start / duration) * width;
            const endX = (state.words[i].end / duration) * width;

            dom.ctx.fillStyle = 'rgba(240, 165, 0, 0.1)';
            dom.ctx.fillRect(startX, 0, endX - startX, height);
            break;
        }
    }

    // Draw current phoneme highlight (blue)
    for (let i = 0; i < state.intervals.length; i++) {
        if (time >= state.intervals[i].start && time < state.intervals[i].end) {
            const startX = (state.intervals[i].start / duration) * width;
            const endX = (state.intervals[i].end / duration) * width;

            dom.ctx.fillStyle = 'rgba(76, 201, 240, 0.2)';
            dom.ctx.fillRect(startX, 0, endX - startX, height);
            break;
        }
    }

    // Draw playhead
    const x = progress * width;
    dom.ctx.strokeStyle = '#f72585';
    dom.ctx.lineWidth = 2;
    dom.ctx.beginPath();
    dom.ctx.moveTo(x, 0);
    dom.ctx.lineTo(x, height);
    dom.ctx.stroke();

    // Draw playhead triangle
    dom.ctx.fillStyle = '#f72585';
    dom.ctx.beginPath();
    dom.ctx.moveTo(x - 6, 0);
    dom.ctx.lineTo(x + 6, 0);
    dom.ctx.lineTo(x, 10);
    dom.ctx.closePath();
    dom.ctx.fill();
}

export function handleCanvasClick(e) {
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
