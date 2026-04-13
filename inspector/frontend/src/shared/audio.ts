/**
 * Shared audio playback utilities.
 */

/**
 * Call audio.play() and swallow AbortError — fired when src changes or
 * pause() interrupts a pending play() promise. Non-abort errors still throw.
 */
export function safePlay(audioEl: HTMLAudioElement): Promise<void> | undefined {
    const p = audioEl.play();
    if (p && typeof p.catch === 'function') {
        p.catch((e: unknown) => {
            if (e && (e as { name?: string }).name !== 'AbortError') throw e;
        });
    }
    return p;
}

/** True if `src` equals `target` or ends with `target` (handles relative vs absolute URL). */
export function audioSrcMatches(src: string | null | undefined, target: string | null | undefined): boolean {
    if (!src || !target) return false;
    if (src === target) return true;
    return target.endsWith(src);
}
