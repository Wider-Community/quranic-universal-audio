/**
 * Timestamps tab — shared mutable state and DOM references.
 *
 * Every module in timestamps/ imports { state, dom } and reads/writes
 * properties directly: state.intervals, dom.audio.pause(), etc.
 *
 * Typing conventions mirror segments/state.ts — DOM refs are narrow
 * element types seeded with `null as unknown as T` and populated by
 * DOMContentLoaded; animation caches remain opaque arrays because they
 * are only ever produced and consumed by animation.ts internals.
 */

import type { SearchableSelect } from '../shared/searchable-select';
import type { TsValidateResponse } from '../types/api';
import type { PhonemeInterval, TsReciter, TsVerseData, TsWord } from '../types/domain';

/** Animation-display cache item (granularity-aware word/character). */
export interface TsAnimCacheItem {
    el: HTMLElement;
    start: number;
    end: number;
    groupId: string | null;
    cacheIdx: number;
}

/**
 * Array of cache items augmented with an internal group index. `initAnimCache`
 * in animation.ts attaches `_groupIndex` after construction; consumers read it
 * when applying reveal/active classes.
 */
export interface TsAnimCache extends Array<TsAnimCacheItem> {
    _groupIndex?: Record<string, number[]>;
}

/** All mutable state for the timestamps tab. */
export interface TimestampsState {
    currentData: TsVerseData | null;
    intervals: PhonemeInterval[];
    words: TsWord[];
    audioContext: AudioContext | null;
    waveformData: Float32Array | null;
    fullAudioBuffer: AudioBuffer | null;
    audioBufferCache: Map<string, AudioBuffer>;
    waveformSnapshot: HTMLCanvasElement | null;

    // Segment offset state (seconds)
    tsSegOffset: number;
    tsSegEnd: number;

    // View / display mode
    tsViewMode: 'analysis' | 'animation';
    tsGranularity: 'words' | 'characters';
    tsAutoMode: 'next' | 'random' | null;
    /** Guard against re-entry from timeupdate auto-advance. */
    tsAutoAdvancing: boolean;
    tsShowLetters: boolean;
    tsShowPhonemes: boolean;

    // Cached DOM element refs (populated by buildUnifiedDisplay / buildPhonemeLabels)
    cachedBlocks: HTMLElement[];
    cachedPhonemes: HTMLElement[];
    cachedLetterEls: HTMLElement[];
    cachedLabels: HTMLElement[];
    prevActiveWordIdx: number;
    prevActivePhonemeIdx: number;

    // Animation caches
    animWordCache: TsAnimCache | null;
    animCharCache: TsAnimCache | null;
    lastAnimIdx: number;
    animationId: number | null;

    // loadedmetadata handler cleanup tracking
    _currentOnMeta: ((ev: Event) => void) | null;

    // All reciters (cached for optgroup rendering)
    tsAllReciters: TsReciter[];

    // SearchableSelect instance for timestamps chapter dropdown
    tsChapterSS: SearchableSelect | null;

    // Validation data
    tsValidationData: TsValidateResponse | null;
}

export const state: TimestampsState = {
    currentData: null,
    intervals: [],
    words: [],
    audioContext: null,
    waveformData: null,
    fullAudioBuffer: null,
    audioBufferCache: new Map(),
    waveformSnapshot: null,

    // Segment offset state
    tsSegOffset: 0,
    tsSegEnd: 0,

    // View / display mode
    tsViewMode: 'analysis',
    tsGranularity: 'words',
    tsAutoMode: null,
    tsAutoAdvancing: false,
    tsShowLetters: true,
    tsShowPhonemes: false,

    // Cached DOM element refs
    cachedBlocks: [],
    cachedPhonemes: [],
    cachedLetterEls: [],
    cachedLabels: [],
    prevActiveWordIdx: -1,
    prevActivePhonemeIdx: -1,

    // Animation caches
    animWordCache: null,
    animCharCache: null,
    lastAnimIdx: -1,
    animationId: null,

    // loadedmetadata handler cleanup tracking
    _currentOnMeta: null,

    // All reciters
    tsAllReciters: [],

    // SearchableSelect instance
    tsChapterSS: null,

    // Validation data
    tsValidationData: null,
};

/**
 * DOM element references — initialized to null, set in index.ts DOMContentLoaded.
 * Using an object (not top-level const assignments) so every module sees the
 * same reference after initialization. Fields are non-nullable via a
 * `null as unknown as T` seed to avoid null-checks at every call site —
 * callers assume init has run (guaranteed by DOMContentLoaded ordering).
 */
export interface TimestampsDomRefs {
    audio: HTMLAudioElement;
    canvas: HTMLCanvasElement;
    /** Populated via `canvas.getContext('2d')` in DOMContentLoaded; may be null
     *  if the browser refuses a 2D context. Callers must null-check (or the
     *  file's @ts-nocheck must be removed so strictNullChecks enforces it). */
    ctx: CanvasRenderingContext2D | null;
    tsReciterSelect: HTMLSelectElement;
    tsChapterSelect: HTMLSelectElement;
    tsSegmentSelect: HTMLSelectElement;
    phonemeLabels: HTMLDivElement;
    unifiedDisplay: HTMLDivElement;
    animDisplay: HTMLDivElement;
    modeBtnA: HTMLButtonElement;
    modeBtnB: HTMLButtonElement;
    tsValidationEl: HTMLDivElement;
    tsSpeedSelect: HTMLSelectElement;
    randomBtn: HTMLButtonElement;
    randomReciterBtn: HTMLButtonElement;
    tsPrevBtn: HTMLButtonElement;
    tsNextBtn: HTMLButtonElement;
    autoNextBtn: HTMLButtonElement;
    autoRandomBtn: HTMLButtonElement;
}

const _UNSET = null as unknown as never;

export const dom: TimestampsDomRefs = {
    audio: _UNSET,
    canvas: _UNSET,
    ctx: _UNSET,
    tsReciterSelect: _UNSET,
    tsChapterSelect: _UNSET,
    tsSegmentSelect: _UNSET,
    phonemeLabels: _UNSET,
    unifiedDisplay: _UNSET,
    animDisplay: _UNSET,
    modeBtnA: _UNSET,
    modeBtnB: _UNSET,
    tsValidationEl: _UNSET,
    tsSpeedSelect: _UNSET,
    randomBtn: _UNSET,
    randomReciterBtn: _UNSET,
    tsPrevBtn: _UNSET,
    tsNextBtn: _UNSET,
    autoNextBtn: _UNSET,
    autoRandomBtn: _UNSET,
};
