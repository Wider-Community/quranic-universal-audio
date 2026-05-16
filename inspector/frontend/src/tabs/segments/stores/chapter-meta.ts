/**
 * Per-chapter audio metadata (bitrate_kbps) for the active reciter.
 *
 * Sourced from `SegDataResponse.chapter_bitrate_kbps` and refreshed on
 * every chapter load. Sparse — only CBR chapters with a positive kbps
 * appear. Absence is the no-op signal for the audio-warmup util (covers
 * VBR, missing kbps, and unknown-mode chapters in one rule).
 */

import { get, writable } from 'svelte/store';

/** Reciter-wide map: chapter number -> CBR bitrate in kbps. Empty when no
 *  CBR-with-kbps chapters known (e.g. fully VBR reciter, or sidecar
 *  missing). */
export const chapterCbrKbps = writable<Map<number, number>>(new Map());

/** Pure accessor — returns the chapter's CBR kbps or undefined if absent.
 *  Absence covers VBR, missing kbps, and unknown-mode in one rule. */
export function cbrKbpsForChapter(chapter: number | null | undefined): number | undefined {
    if (chapter == null) return undefined;
    return get(chapterCbrKbps).get(chapter);
}
