/**
 * Timestamps tab — display / view-mode state.
 *
 * Owns view mode, granularity, show-letters, and show-phonemes flags.
 * These persist to localStorage via a `<svelte:window>` effect in
 * `TimestampsTab.svelte`.
 */

import { writable } from 'svelte/store';

import type { TsConfigResponse } from '../../../lib/types/api';

/** "analysis" = mega-blocks; "animation" = reveal-mode per-word fade-in. */
export type TsViewMode = 'analysis' | 'animation';

/** In animation mode, per-word or per-character highlighting. */
export type TsGranularity = 'words' | 'characters';

/** Current view mode. */
export const viewMode = writable<TsViewMode>('analysis');

/** Animation-mode granularity. */
export const granularity = writable<TsGranularity>('words');

/** Analysis mode: toggle letter row visibility. */
export const showLetters = writable<boolean>(true);

/** Analysis mode: toggle phoneme row + cross-word bridge visibility. */
export const showPhonemes = writable<boolean>(false);

/** Timestamps /api/ts/config — load once, drive CSS variables. null = not loaded yet. */
export const tsConfig = writable<TsConfigResponse | null>(null);
