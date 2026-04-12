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
