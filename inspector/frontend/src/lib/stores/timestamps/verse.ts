/**
 * Timestamps tab — verse/reciter/chapter selection + loaded verse data.
 *
 * Owns reciter list, chapter list, verse list, selection state, and the
 * loaded verse payload. UI components subscribe to `chaptersOptions` and
 * `versesOptions` for the two SearchableSelect / native selects.
 */

import { derived, writable } from 'svelte/store';

import type { TsValidateResponse } from '../../types/api';
import type { TsReciter, TsVerseData } from '../../types/domain';
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

// `intervals` and `words` derived stores were removed: components compute
// these inline via `$loadedVerse` + `$:` reactive statements as needed
// (UnifiedDisplay / AnimationDisplay). Re-introducing them without any
// `$store` consumer would be a tautological pass-through.

// ---------------------------------------------------------------------------
// Validation data
// ---------------------------------------------------------------------------

/** Validation data for the current reciter. null = hidden panel. */
export const validationData = writable<TsValidateResponse | null>(null);

// ---------------------------------------------------------------------------
// Derived dropdown options
// ---------------------------------------------------------------------------

// `recitersOptions` was removed — TimestampsTab reads `$reciters` directly
// to build its grouped-<optgroup> structure; an identity-wrap derived store
// has zero value.

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
