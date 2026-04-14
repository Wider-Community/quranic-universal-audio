/**
 * Client-side WebAudio peak-extraction helper.
 *
 * The Timestamps tab decodes the verse audio fully and computes a
 * peaks-per-bucket summary for the waveform canvas. (The Segments tab uses
 * server-side ffmpeg peaks instead — a different code path.)
 *
 * This helper is a pure function: no global state, no side effects. The
 * AudioBuffer LRU cache lives in module scope here (not a Svelte store —
 * it's non-reactive per S2-D12 precedent), keyed by audio URL.
 */

import type { PeakBucket } from '../../types/domain';
import { fetchArrayBuffer } from '../api';
import { AUDIO_BUFFER_CACHE_SIZE } from './constants';

// ---------------------------------------------------------------------------
// AudioContext + LRU buffer cache (module-scope, non-reactive)
// ---------------------------------------------------------------------------

type AudioCtxCtor = typeof AudioContext;

let _audioContext: AudioContext | null = null;
const _audioBufferCache: Map<string, AudioBuffer> = new Map();

function getAudioContext(): AudioContext {
    if (_audioContext) return _audioContext;
    const Ctor: AudioCtxCtor =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: AudioCtxCtor }).webkitAudioContext;
    _audioContext = new Ctor();
    return _audioContext;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Fetch + decode an audio URL into an AudioBuffer. Results are cached in a
 * small LRU keyed by URL (size `AUDIO_BUFFER_CACHE_SIZE`). Re-entrant safe:
 * simultaneous calls for the same URL will both trigger a decode; the
 * newer write wins. (Pre-existing behaviour from Stage 1 — acceptable.)
 */
export async function decodeAudioUrl(url: string): Promise<AudioBuffer> {
    const cached = _audioBufferCache.get(url);
    if (cached) return cached;

    const arrayBuffer = await fetchArrayBuffer(url);
    const buffer = await getAudioContext().decodeAudioData(arrayBuffer);

    // LRU: evict oldest if at capacity
    if (_audioBufferCache.size >= AUDIO_BUFFER_CACHE_SIZE) {
        const oldest = _audioBufferCache.keys().next().value;
        if (oldest !== undefined) _audioBufferCache.delete(oldest);
    }
    _audioBufferCache.set(url, buffer);
    return buffer;
}

/**
 * Compute peaks for the given audio buffer, restricted to the
 * [startSec, endSec) time slice. If the slice is invalid, falls back to the
 * full buffer.
 *
 * Returns `PeakBucket[]` — compatible with `lib/utils/waveform-draw.ts` and
 * `<WaveformCanvas>`. Each bucket is `[min, max]` amplitude in [-1, 1].
 */
export function computePeaksForSlice(
    buffer: AudioBuffer,
    startSec: number,
    endSec: number,
    bucketCount: number,
): PeakBucket[] {
    const rawData = buffer.getChannelData(0);
    const sampleRate = buffer.sampleRate;
    const startSample = Math.max(0, Math.floor(startSec * sampleRate));
    const endSample = Math.min(Math.floor(endSec * sampleRate), rawData.length);
    const sliceLength = endSample - startSample;

    const slice: Float32Array =
        sliceLength > 0 ? rawData.subarray(startSample, endSample) : rawData;

    const buckets = Math.max(1, bucketCount);
    const blockSize = Math.max(1, Math.floor(slice.length / buckets));
    const peaks: PeakBucket[] = new Array(buckets);

    for (let i = 0; i < buckets; i++) {
        let min = 1.0;
        let max = -1.0;
        const start = i * blockSize;
        for (let j = 0; j < blockSize; j++) {
            const val = slice[start + j] ?? 0;
            if (val < min) min = val;
            if (val > max) max = val;
        }
        peaks[i] = [min, max];
    }
    return peaks;
}

/** Clear the LRU cache (testing / reset hook). */
export function _clearAudioBufferCache(): void {
    _audioBufferCache.clear();
}
