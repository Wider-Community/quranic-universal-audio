/**
 * Shared progress-bar pointer signals, in chapter-absolute ms (or null), that
 * decouple the footer bar (`PlayerProgress`) from the dashboard now-reciting
 * filmstrip (`AyahFilmstrip` via `NowReciting`) — the two siblings don't need
 * to know about each other.
 *
 * Hover and drag are mutually exclusive:
 *   - `progressHoverMs`: pointer hovering the bar (no button). The filmstrip
 *     preview-highlights the ayah cell under that time. No scroll.
 *   - `progressScrubMs`: pointer actively dragging the bar. The filmstrip
 *     scroll-follows it (both motion modes); the hover preview is suppressed
 *     while it is non-null. Cleared on release, where the seek fires and the
 *     strip settles on the dragged verse.
 */
import { writable } from 'svelte/store';

export const progressHoverMs = writable<number | null>(null);
export const progressScrubMs = writable<number | null>(null);
