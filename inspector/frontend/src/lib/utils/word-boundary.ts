/**
 * Word-boundary navigation helper for audio playback.
 *
 * Extracted from TimestampsTab keyboard handler (ArrowUp/ArrowDown cases).
 * Scans a word-timestamp array to find the previous or next word boundary
 * relative to the current playback position.
 */

/** Minimum word shape required by this helper. */
export interface WordLike {
    start: number;
}

/**
 * Scan a word-timestamp array and return the start time of the
 * previous (direction = 'up') or next (direction = 'down') word boundary
 * relative to `currentTime`.
 *
 * - 'up'   → find the last word whose start < currentTime - epsilon.
 * - 'down' → find the first word whose start > currentTime + epsilon.
 *
 * Returns `null` when no qualifying word exists (caller should fall back to
 * segOffset or segEnd).
 *
 * @param words       - word objects with numeric `start` fields (seconds)
 * @param currentTime - current playback time relative to the segment start (seconds)
 * @param direction   - 'up' = seek backward; 'down' = seek forward
 */
export function wordBoundaryScan(
    words: WordLike[],
    currentTime: number,
    direction: 'up' | 'down',
): number | null {
    if (direction === 'up') {
        for (let i = words.length - 1; i >= 0; i--) {
            const w = words[i];
            if (w && w.start < currentTime - 0.01) {
                return w.start;
            }
        }
        return null;
    } else {
        for (let i = 0; i < words.length; i++) {
            const w = words[i];
            if (w && w.start > currentTime + 0.01) {
                return w.start;
            }
        }
        return null;
    }
}
