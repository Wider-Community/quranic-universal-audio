/**
 * Timestamps tab — load state.
 *
 * Replaces the old `document.body.classList.add('loading')` full-page 50% dim
 * (base.css `.loading`) with a tab-local flag. Consumers scope a skeleton/dim
 * to the waveform+display region only, so the rest of the page stays
 * interactive while a verse loads. Also doubles as a single-flight guard: the
 * verse/random loaders early-return when it's already true so a double-click /
 * keyboard-mash / auto-advance can't stack overlapping loads (the old global
 * `pointer-events: none` used to provide that for free).
 */
import { writable } from 'svelte/store';

export const tsLoading = writable<boolean>(false);
