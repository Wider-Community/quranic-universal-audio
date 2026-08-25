/**
 * Timestamps tab — display / view-mode state.
 *
 * Owns view mode, granularity, show-letters, and show-phonemes flags.
 * These persist to localStorage via a `<svelte:window>` effect in
 * `TimestampsTab.svelte`.
 */

import { writable } from 'svelte/store';

import type { TsConfigResponse } from '../../../lib/types/generated/schemas';

/** "analysis" = mega-blocks; "animation" = reveal-mode per-word fade-in. */
export const TS_VIEW_MODES = { ANALYSIS: 'analysis', ANIMATION: 'animation' } as const;
export type TsViewMode = typeof TS_VIEW_MODES[keyof typeof TS_VIEW_MODES];
export const TS_VIEW_MODE_DEFAULT: TsViewMode = TS_VIEW_MODES.ANALYSIS;

/** In animation mode, per-word or per-character highlighting. */
export const TS_GRANULARITIES = { WORDS: 'words', CHARACTERS: 'characters' } as const;
export type TsGranularity = typeof TS_GRANULARITIES[keyof typeof TS_GRANULARITIES];
export const TS_GRANULARITY_DEFAULT: TsGranularity = TS_GRANULARITIES.WORDS;

/** Current view mode. */
export const viewMode = writable<TsViewMode>(TS_VIEW_MODE_DEFAULT);

/** Animation-mode granularity. */
export const granularity = writable<TsGranularity>(TS_GRANULARITY_DEFAULT);

/** Analysis mode: toggle letter row visibility. */
export const showLetters = writable<boolean>(true);

/** Analysis mode: toggle phoneme row + cross-word bridge visibility. */
export const showPhonemes = writable<boolean>(true);

/** Analysis mode: toggle the word-by-word translation row (above each word). */
export const showTranslations = writable<boolean>(false);

/** Analysis-mode highlight style. false = discrete fill (a cell crisply lights
 *  and fades), true = continuous karaoke wipe (the fill tracks the voice across
 *  each cell). Self-persisted here (the boolean toggles above are persisted from
 *  `TimestampsTab`; this one is loaded/saved inline to stay self-contained). */
const LS_HIGHLIGHT_WIPE = 'ts:highlightWipe';
function _wipeInitial(): boolean {
    try {
        return localStorage.getItem(LS_HIGHLIGHT_WIPE) === 'true';
    } catch {
        return false;
    }
}
export const highlightWipe = writable<boolean>(_wipeInitial());
highlightWipe.subscribe((v) => {
    try {
        localStorage.setItem(LS_HIGHLIGHT_WIPE, String(v));
    } catch {
        /* private mode / storage disabled — in-memory only */
    }
});

/** ISO code of the chosen word-by-word translation language (default English). */
export const translationLanguage = writable<string>('en');

/** location ("surah:ayah:word") → gloss for the loaded verse's ayah(s).
 *  `{}` when translations are off or none loaded. Populated lazily by
 *  TimestampsTab; rendered statically by TimedAnalysisRow (never per-frame, so
 *  it stays out of the playback-highlight hot path). */
export const verseTranslations = writable<Record<string, string>>({});

/** Timestamps /api/ts/config — load once, drive CSS variables. null = not loaded yet. */
export const tsConfig = writable<TsConfigResponse | null>(null);

// ---------------------------------------------------------------------------
// Cross-component hover (blocks panel ↔ waveform)
// ---------------------------------------------------------------------------

/** The element currently hovered in TimedAnalysisRow (Analysis view). The waveform
 *  subscribes to paint a matching-color band at the [startSec, endSec] range. */
export interface TsHoveredElement {
    kind: 'word' | 'letter' | 'phoneme';
    startSec: number;
    endSec: number;
}

/** null when nothing is hovered. */
export const tsHoveredElement = writable<TsHoveredElement | null>(null);

/** Slice-relative seconds when the pointer is on the waveform. null when off.
 *  Published by TimestampsWaveform; consumed by TimedAnalysisRow to drive entity
 *  highlights while audio is paused (so hover-scrubbing previews the position). */
export const tsWaveformHoverTime = writable<number | null>(null);
