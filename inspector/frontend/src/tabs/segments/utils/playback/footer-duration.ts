/**
 * Resolve the chapter duration (ms) the Segments footer uses to size its
 * chapter-wide progress bar.
 *
 * The footer's progress is `currentMs / chapterDurationMs`. `currentMs` is
 * file-absolute, so the denominator must be the full chapter's duration.
 *
 * Two cases break the naive `<audio>.duration` read:
 *   - **Non-finite `el.duration`** — headerless MP3 streamed from the CDN (no
 *     bucket file → no up-front duration) reports `Infinity`/`NaN`. Fall back
 *     to the manifest's chapter duration.
 *   - **VBR clip mode** — the element plays a short per-segment clip, so
 *     `el.duration` is the CLIP length, not the chapter; using it would make
 *     the file-absolute `currentMs` overflow the bar. Use the manifest
 *     chapter duration instead.
 *
 * Returns 0 when no duration is resolvable (caller hides the progress row).
 */
export function resolveChapterDurationMs(opts: {
    /** `el.duration * 1000` when finite, else 0. */
    elDurationMs: number;
    /** The port is playing a per-segment VBR clip (`window.isClip`). */
    inClip: boolean;
    /** Chapter duration from the audio manifest (`chapter_duration_ms_by_chapter`), or 0. */
    manifestDurMs: number;
}): number {
    const { elDurationMs, inClip, manifestDurMs } = opts;
    if (!inClip && elDurationMs > 0) return elDurationMs;
    return manifestDurMs > 0 ? manifestDurMs : 0;
}
