// @ts-nocheck — removed per-file as each module is typed in Phases 4+
/**
 * Timestamps tab — shared mutable state and DOM references.
 *
 * Every module in timestamps/ imports { state, dom } and reads/writes
 * properties directly: state.intervals, dom.audio.pause(), etc.
 */

/** All mutable state for the timestamps tab. */
export const state = {
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
    tsViewMode: 'analysis',    // 'analysis' | 'animation'
    tsGranularity: 'words',    // 'words' | 'characters'
    tsAutoMode: null,          // null | 'next' | 'random'
    tsAutoAdvancing: false,    // guard against re-entry from timeupdate
    tsShowLetters: true,
    tsShowPhonemes: false,

    // Cached DOM element refs (populated by buildUnifiedDisplay / buildPhonemeLabels)
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

    // All reciters (cached for optgroup rendering)
    tsAllReciters: [],

    // SearchableSelect instance for timestamps chapter dropdown
    tsChapterSS: null,

    // Validation data
    tsValidationData: null,
};

/**
 * DOM element references — initialized to null, set in index.js DOMContentLoaded.
 * Using an object (not top-level const assignments) so every module sees the
 * same reference after initialization.
 */
export const dom = {
    audio: null,
    canvas: null,
    ctx: null,
    tsReciterSelect: null,
    tsChapterSelect: null,
    tsSegmentSelect: null,
    phonemeLabels: null,
    unifiedDisplay: null,
    animDisplay: null,
    modeBtnA: null,
    modeBtnB: null,
    tsValidationEl: null,
    tsSpeedSelect: null,
    randomBtn: null,
    randomReciterBtn: null,
    tsPrevBtn: null,
    tsNextBtn: null,
    autoNextBtn: null,
    autoRandomBtn: null,
};
