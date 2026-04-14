/**
 * Timestamps tab — verse/reciter/chapter selection + loaded verse data.
 *
 * Wraps the Stage-1 `state.currentData`, `state.intervals`, `state.words`,
 * reciter list, chapter list, verse list, and selection indices. UI
 * components subscribe to derived `recitersOptions`, `chaptersOptions`,
 * `versesOptions` for the three SearchableSelect / native selects.
 */

import { derived, writable } from 'svelte/store';

import type { TsValidateResponse } from '../../../types/api';
import type { PhonemeInterval, TsReciter, TsVerseData, TsWord } from '../../../types/domain';
import type { SelectOption } from '../../types/ui';
import { surahOptionText } from '../../utils/surah-info';

/** A verse option as served by /api/ts/verses. */
export interface TsVerseOption {
    ref: string;
    audio_url: string;
}

/** Loaded verse data + segment offsets (seconds). */
export interface TsLoadedVerse {
    data: TsVerseData;
    /** time_start_ms / 1000 — negative-timing offset for by_surah mode. */
    tsSegOffset: number;
    /** time_end_ms / 1000 — auto-advance clamp. */
    tsSegEnd: number;
}

// ---------------------------------------------------------------------------
// Selection state
// ---------------------------------------------------------------------------

/** All reciters (eager-loaded from /api/ts/reciters). */
export const reciters = writable<TsReciter[]>([]);
/** Currently selected reciter slug. */
export const selectedReciter = writable<string>('');
/** Chapter list for the selected reciter. */
export const chapters = writable<number[]>([]);
/** Currently selected chapter number (as string for <select> value symmetry). */
export const selectedChapter = writable<string>('');
/** Verse list for the selected chapter. */
export const verses = writable<TsVerseOption[]>([]);
/** Currently selected verse ref (e.g. "36:10"). */
export const selectedVerse = writable<string>('');

// ---------------------------------------------------------------------------
// Loaded verse + data
// ---------------------------------------------------------------------------

/** Currently-loaded verse data (null before first load). */
export const loadedVerse = writable<TsLoadedVerse | null>(null);

/** Phoneme intervals for the currently loaded verse (seconds-based). */
export const intervals = derived<typeof loadedVerse, PhonemeInterval[]>(
    loadedVerse,
    ($lv) => $lv?.data.intervals ?? [],
);

/** Word list for the currently loaded verse. */
export const words = derived<typeof loadedVerse, TsWord[]>(
    loadedVerse,
    ($lv) => $lv?.data.words ?? [],
);

// ---------------------------------------------------------------------------
// Validation data
// ---------------------------------------------------------------------------

/** Validation data for the current reciter. null = hidden panel. */
export const validationData = writable<TsValidateResponse | null>(null);

// ---------------------------------------------------------------------------
// Derived dropdown options
// ---------------------------------------------------------------------------

/**
 * Reciter select options grouped by audio_source.
 * The underlying HTML select in `TimestampsTab.svelte` renders <optgroup>s
 * manually from this list (grouped natively since the Wave-3 SearchableSelect
 * component doesn't wrap the reciter dropdown).
 */
export const recitersOptions = derived<typeof reciters, TsReciter[]>(reciters, ($rs) => $rs);

/** Chapter select options (passed to SearchableSelect). */
export const chaptersOptions = derived<typeof chapters, SelectOption[]>(chapters, ($cs) =>
    $cs.map((ch) => ({ value: String(ch), label: surahOptionText(ch) })),
);

/** Verse select options. */
export const versesOptions = derived<typeof verses, SelectOption[]>(verses, ($vs) =>
    $vs.map((v) => ({
        value: v.ref,
        label: v.ref.split(':')[1] ?? v.ref,
    })),
);
