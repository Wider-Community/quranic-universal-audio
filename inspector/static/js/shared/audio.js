/**
 * Shared audio playback utilities.
 */

/**
 * Call audio.play() and swallow AbortError — fired when src changes or
 * pause() interrupts a pending play() promise. Non-abort errors still throw.
 */
export function safePlay(audioEl) {
    const p = audioEl.play();
    if (p && typeof p.catch === 'function') {
        p.catch(e => { if (e && e.name !== 'AbortError') throw e; });
    }
    return p;
}
