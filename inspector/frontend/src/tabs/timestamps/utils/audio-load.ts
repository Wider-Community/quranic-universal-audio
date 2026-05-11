/**
 * Timestamps-tab AudioPort loader.
 *
 * Keeps the component thin and makes CBR/VBR transport behavior unit-testable:
 * callers set the port's logical source first, then this helper loads the
 * requested file-absolute window and seeks/plays in file-absolute time.
 */

import type { AudioPort } from '../../../lib/playback/audio-port';
import type { TsLoadedVerse } from '../stores/verse';

function isAbortError(e: unknown): boolean {
    return !!e && typeof e === 'object' && (e as { name?: string }).name === 'AbortError';
}

export async function loadTimestampsAudio(
    port: AudioPort,
    loadedVerse: TsLoadedVerse | null,
    atTimeSec: number = 0,
    autoplay: boolean = true,
): Promise<void> {
    if (!port.element || !port.source) return;

    const startMs = Math.max(0, Math.round(atTimeSec * 1000));
    let endMs = loadedVerse && loadedVerse.tsSegEnd > 0
        ? Math.round(loadedVerse.tsSegEnd * 1000)
        : startMs + 1;
    if (endMs <= startMs) endMs = startMs + 1;

    const load = port.loadCovering(startMs, endMs);
    try {
        await load.ready;
    } catch (e) {
        if (isAbortError(e)) return;
        throw e;
    }

    if (autoplay) port.seekAndPlay(startMs);
    else port.seek(startMs);
}
