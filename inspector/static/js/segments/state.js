/**
 * Segments tab -- shared mutable state, DOM references, constants,
 * dirty/op helpers, and the _findCoveringPeaks pure function.
 *
 * Every module in segments/ imports { state, dom } and reads/writes
 * properties directly: state.segData, dom.segListEl, etc.
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const EDIT_OP_LABELS = {
    trim_segment: 'Boundary adjustment', split_segment: 'Split',
    merge_segments: 'Merge', delete_segment: 'Deletion',
    edit_reference: 'Reference edit', confirm_reference: 'Reference confirmation',
    auto_fix_missing_word: 'Auto-fix missing word', ignore_issue: 'Ignored issue',
    waqf_sakt: 'Waqf sakt merge', remove_sadaqa: 'Remove Sadaqa',
};

export const ERROR_CAT_LABELS = {
    failed: 'Failed', low_confidence: 'Low confidence',
    boundary_adj: 'Boundary adj.',
    cross_verse: 'Cross-verse', missing_words: 'Missing words',
    audio_bleeding: 'Audio bleeding',
    repetitions: 'Repetitions',
    muqattaat: 'Muqattaat letters',
    qalqala: 'Qalqala',
};

export const SEG_FILTER_FIELDS = [
    { value: 'duration_s',        label: 'Duration (s)',       type: 'float' },
    { value: 'num_words',         label: 'Word count',         type: 'int'   },
    { value: 'num_verses',        label: 'Verses spanned',     type: 'int'   },
    { value: 'confidence_pct',    label: 'Confidence (%)',      type: 'float' },
    { value: 'silence_after_ms',  label: 'Silence after (ms)',  type: 'float', neighbour: true },
];

export const SEG_FILTER_OPS = ['>', '>=', '<', '<=', '='];

export const SEG_SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 5];

export const _SEG_NORMAL_IDS = ['seg-stats-panel', 'seg-validation-global', 'seg-validation',
    'seg-filter-bar', 'seg-list'];

export const _ARABIC_DIGITS = ['\u0660','\u0661','\u0662','\u0663','\u0664','\u0665','\u0666','\u0667','\u0668','\u0669'];

export const _MN_RE = /[\u0300-\u036F\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06DC\u06DF-\u06E4\u06E7-\u06E8\u06EA-\u06ED\u08D3-\u08FF\uFE20-\uFE2F]/;
export const _STRIP_CHARS = new Set(['\u0640', '\u06DE', '\u06E6', '\u06E9', '\u200F']);
export const _LETTER_RE = /\p{L}/u;

// ---------------------------------------------------------------------------
// Mutable state
// ---------------------------------------------------------------------------

export const state = {
    // Core data
    segData: null,          // { audio_url, summary, verse_word_counts, segments } -- chapter-specific
    segAllData: null,       // { segments, audio_by_chapter, verse_word_counts } -- reciter-level
    segActiveFilters: [],   // [{ field, op, value }, ...]
    segAnimId: null,        // animation frame ID for playback
    segCurrentIdx: -1,      // currently playing segment index
    segDisplayedSegments: null, // segments currently shown (may be filtered)
    segDirtyMap: new Map(),     // Map<chapter, {indices: Set, structural: boolean}>
    segEditMode: null,          // null | 'trim' | 'split'
    segEditIndex: -1,           // index of segment being edited

    // Prefetch & playback
    _segPrefetchCache: {},      // url -> Promise<void> for prefetched audio
    _segContinuousPlay: false,  // true while continuous playback is active
    _segAutoPlayEnabled: true,  // user preference: auto-advance
    _segPlayEndMs: 0,           // time_end (ms) of the currently playing segment

    // Validation & stats
    segValidation: null,        // cached validation data for current reciter
    segAllReciters: [],         // full list from /api/seg/reciters
    segStatsData: null,         // cached stats data for current reciter

    // Filter
    _segFilterDebounceTimer: null,

    // Audio source tracking
    _activeAudioSource: null,      // 'main' | 'error' | null
    _segIndexMap: null,            // Map<'chapter:index', segment> for O(1) lookups

    // Waveform observer
    _waveformObserver: null,

    // Filter view save/restore
    _segSavedFilterView: null,
    _segSavedPreviewState: null,

    // Peaks
    segPeaksByAudio: null,       // {url: {duration_ms, peaks}}
    _peaksPollTimer: null,

    // Rendering
    _cardRenderRafId: null,

    // Accordion edit context
    _accordionOpCtx: null,       // { wrapper, direction? }
    _splitChainWrapper: null,

    // Edit history
    segOpLog: new Map(),
    _pendingOp: null,
    _splitChainUid: null,
    _splitChainCategory: null,

    // Edit history viewer state
    segHistoryData: null,
    _segDataStale: false,

    // History filter & sort state
    _histFilterOpTypes: new Set(),
    _histFilterErrCats: new Set(),
    _histSortMode: 'time',
    _allHistoryItems: null,

    // Split chain state
    _splitChains: null,
    _chainedOpIds: null,
    _segSavedChains: null,

    // Server-provided canonical category list
    _validationCategories: null,

    // Classification data for per-segment category detection
    _muqattaatVerses: null,  // Set of "surah:ayah"
    _standaloneRefs: null,   // Set of "surah:ayah:word"
    _standaloneWords: null,  // Set of stripped Arabic words
    _qalqalaLetters: null,   // Set of Arabic letters
    _lcDefaultThreshold: 80,

    // SearchableSelect instance
    segChapterSS: null,

    // Highlight tracking (playback)
    _prevHighlightedRow: null,
    _prevHighlightedIdx: -1,
    _prevPlayheadIdx: -1,
    _prevPlayheadRow: null,
    _currentPlayheadRow: null,

    // Canvas scrub
    _segScrubActive: false,

    // Adjust/trim mode config (overridden by server config)
    TRIM_PAD_LEFT: 500,
    TRIM_PAD_RIGHT: 500,
    TRIM_DIM_ALPHA: 0.45,
    SHOW_BOUNDARY_PHONEMES: true,

    // Preview playback
    _previewStopHandler: null,
    _previewLooping: false,
    _previewJustSeeked: false,
    _playRangeRAF: null,

    // Error card audio
    valCardAudio: null,
    valCardPlayingBtn: null,
    valCardStopTime: null,
    valCardAnimId: null,
    valCardAnimSeg: null,

    // Audio cache
    _audioCachePollTimer: null,

    // Validation index fixup categories
    _VAL_SINGLE_INDEX_CATS: ['failed', 'low_confidence', 'boundary_adj', 'cross_verse', 'audio_bleeding', 'repetitions', 'muqattaat', 'qalqala'],
};

// ---------------------------------------------------------------------------
// DOM references -- set in index.js DOMContentLoaded
// ---------------------------------------------------------------------------

export const dom = {
    segReciterSelect: null,
    segChapterSelect: null,
    segVerseSelect: null,
    segListEl: null,
    segAudioEl: null,
    segPlayBtn: null,
    segAutoPlayBtn: null,
    segSpeedSelect: null,
    segSaveBtn: null,
    segPlayStatus: null,
    segValidationGlobalEl: null,
    segValidationEl: null,
    segStatsPanel: null,
    segStatsCharts: null,
    segFilterBarEl: null,
    segFilterRowsEl: null,
    segFilterAddBtn: null,
    segFilterClearBtn: null,
    segFilterCountEl: null,
    segFilterStatusEl: null,

    // History view
    segHistoryView: null,
    segHistoryBtn: null,
    segHistoryBackBtn: null,
    segHistoryStats: null,
    segHistoryBatches: null,
    segHistoryFilters: null,
    segHistoryFilterOps: null,
    segHistoryFilterCats: null,
    segHistoryFilterClear: null,
    segHistorySortTime: null,
    segHistorySortQuran: null,

    // Save preview
    segSavePreview: null,
    segSavePreviewCancel: null,
    segSavePreviewConfirm: null,
    segSavePreviewStats: null,
    segSavePreviewBatches: null,
};

// ---------------------------------------------------------------------------
// Classify function injection (breaks state <-> categories cycle)
// ---------------------------------------------------------------------------

let _classifyFn = () => [];

export function setClassifyFn(fn) {
    _classifyFn = fn;
}

// ---------------------------------------------------------------------------
// Operation helpers
// ---------------------------------------------------------------------------

export function createOp(opType, { contextCategory = null, fixKind = 'manual' } = {}) {
    return {
        op_id: crypto.randomUUID(),
        op_type: opType,
        op_context_category: contextCategory,
        fix_kind: fixKind,
        started_at_utc: new Date().toISOString(),
        applied_at_utc: null,
        ready_at_utc: null,
        targets_before: [],
        targets_after: [],
    };
}

export function snapshotSeg(seg) {
    const snap = {
        segment_uid: seg.segment_uid || null,
        index_at_save: seg.index,
        audio_url: seg.audio_url || null,
        time_start: seg.time_start,
        time_end: seg.time_end,
        matched_ref: seg.matched_ref || '',
        matched_text: seg.matched_text || '',
        display_text: seg.display_text || '',
        confidence: seg.confidence ?? 0,
    };
    if (seg.has_repeated_words) snap.has_repeated_words = true;
    if (seg.wrap_word_ranges) snap.wrap_word_ranges = seg.wrap_word_ranges;
    if (seg.phonemes_asr) snap.phonemes_asr = seg.phonemes_asr;
    if (seg.entry_ref) snap.entry_ref = seg.entry_ref;
    if (seg.chapter != null) snap.chapter = seg.chapter;
    if (seg.ignored_categories?.length) snap.ignored_categories = [...seg.ignored_categories];
    snap.categories = _classifyFn(seg);
    return snap;
}

export function finalizeOp(chapter, op) {
    op.ready_at_utc = new Date().toISOString();
    if (!state.segOpLog.has(chapter)) state.segOpLog.set(chapter, []);
    state.segOpLog.get(chapter).push(op);
    state._pendingOp = null;
}

// ---------------------------------------------------------------------------
// Dirty-state helpers
// ---------------------------------------------------------------------------

export function markDirty(chapter, index, structural = false) {
    if (!state.segDirtyMap.has(chapter)) {
        state.segDirtyMap.set(chapter, { indices: new Set(), structural: false });
    }
    const entry = state.segDirtyMap.get(chapter);
    if (index !== undefined) entry.indices.add(index);
    if (structural) entry.structural = true;
    dom.segSaveBtn.disabled = false;
}

export function unmarkDirty(chapter, index) {
    const entry = state.segDirtyMap.get(chapter);
    if (!entry) return;
    entry.indices.delete(index);
    if (entry.indices.size === 0 && !entry.structural) {
        state.segDirtyMap.delete(chapter);
    }
}

export function isDirty() {
    return state.segDirtyMap.size > 0;
}

export function isIndexDirty(chapter, index) {
    const entry = state.segDirtyMap.get(chapter);
    return entry ? entry.indices.has(index) : false;
}

// ---------------------------------------------------------------------------
// _findCoveringPeaks -- pure function reading state data
// (resolves waveform <-> waveform-draw circular dependency)
// ---------------------------------------------------------------------------

export function _findCoveringPeaks(audioUrl) {
    if (!state.segPeaksByAudio) return null;
    const pe = state.segPeaksByAudio[audioUrl];
    return pe?.peaks?.length > 0 ? pe : null;
}
