/**
 * Shared types for the recitation-animation feature.
 *
 * Surface-agnostic: the engine + components consume these, never a tab store.
 * `AnimUnit` carries chapter-absolute timing (seconds) so the same units feed
 * the dashboard full-chapter player and, later, the timestamps tab.
 */

/** One per-letter timing inside a word (seconds, chapter-absolute). */
export interface AnimLetter {
    char: string;
    start: number | null;
    end: number | null;
}

/** One animatable word with chapter-absolute timing (seconds). */
export interface AnimUnit {
    /** "surah:ayah:word". */
    location: string;
    /** "surah:ayah" — paging clears when this changes. */
    ayahKey: string;
    surah: number;
    ayah: number;
    /** Word index within its ayah (from the shard row). */
    word: number;
    /** Display text (Arabic), already DK/QPC-resolved. */
    text: string;
    /** Chapter-absolute start (seconds). */
    start: number;
    /** Chapter-absolute end (seconds). */
    end: number;
    letters: AnimLetter[];
}

/** Per-ayah boundary for the picker + timeline markers. */
export interface AyahBoundary {
    ayahKey: string;
    surah: number;
    ayah: number;
    /** Chapter-absolute ms of the ayah's first word start. */
    startMs: number;
    /** Chapter-absolute ms of the ayah's last word end. */
    endMs: number;
}

/** Assembled chapter recitation — the input to every animation surface. */
export interface ChapterRecitation {
    reciter: string;
    chapter: number;
    units: AnimUnit[];
    ayahs: AyahBoundary[];
    /** Chapter-absolute ms of the last word end. Fallback duration when the
     *  audio element hasn't reported its real length yet. */
    contentEndMs: number;
}

/** The slice of playback the animation reads. An AudioPort satisfies this. */
export interface RecitationPlayback {
    /** Chapter-absolute current time in ms. */
    currentTimeMs(): number;
    /** Seek to a chapter-absolute ms position. */
    seek(ms: number): void;
}
