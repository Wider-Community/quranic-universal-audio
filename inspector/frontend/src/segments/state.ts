/**
 * Segments tab -- shared mutable state, DOM references, constants,
 * dirty/op helpers, and the _findCoveringPeaks pure function.
 *
 * Every module in segments/ imports { state, dom } and reads/writes
 * properties directly: state.segData, dom.segListEl, etc.
 *
 * Typing conventions (Phase 4):
 *  - DOM refs: fields are typed as the narrow element interface (e.g.
 *    `HTMLSelectElement`) and initialised to `null as unknown as T`. The
 *    DOMContentLoaded handler in `segments/index.ts` assigns real elements
 *    before any call site reads them. Fields that MAY legitimately be null
 *    at call sites (e.g. optional widgets, post-cleanup state) are typed as
 *    `T | null` and the callers null-check.
 *  - `state` helpers (createOp/snapshotSeg/etc) have explicit return types
 *    so signatures are visible in the 28 consumer files (which still have
 *    per-file type checking suppressed until later phases).
 *  - The interfaces are exported so Phase 5+ can refine them (e.g. swap
 *    `unknown` for a narrow shape once the consumer is typed).
 */

import { getWaveformPeaks } from '../lib/utils/waveform-cache';
import type { SearchableSelect } from '../shared/searchable-select';
import type {
    SegAllResponse,
    SegDataResponse,
    SegEditHistoryResponse,
    SegStatsResponse,
    SegValidateResponse,
} from '../types/api';
import type {
    AudioPeaks,
    EditOp,
    HistoryBatch,
    PeakBucket,
    Segment,
    SegReciter,
} from '../types/domain';

// ---------------------------------------------------------------------------
// Supporting types (not exported from types/ because they are segments-local)
// ---------------------------------------------------------------------------

/** One active filter row — field + comparator + literal value. */
export interface SegActiveFilter {
    field: string;
    op: string;
    value: number | null;
}

/** Saved UI snapshot so navigation.ts can restore a filter + scroll view. */
export interface SegSavedFilterView {
    filters: SegActiveFilter[];
    chapter: string;
    verse: string;
    scrollTop: number;
}

/** One op + its enclosing batch, as held inside a SplitChain. */
export interface SplitChainOp {
    op: EditOp;
    batch: HistoryBatch;
}

/** Narrow view of a segment snapshot as referenced by history views. Loose
 *  by design — unknown fields preserved via index signature. */
export interface HistorySnapshot {
    index_at_save?: number;
    segment_uid?: string;
    audio_url?: string;
    time_start: number;
    time_end: number;
    matched_ref?: string;
    matched_text?: string;
    display_text?: string;
    confidence?: number;
    wrap_word_ranges?: unknown;
    has_repeated_words?: boolean;
    [k: string]: unknown;
}

/** Group of related split/trim/refine ops chained by segment lineage.
 *  Built by `_buildSplitChains` (history/index.ts) and consumed by
 *  history/rendering.ts + history/undo.ts. */
export interface SplitChain {
    /** The pre-split parent snapshot (first `targets_before` of root op). */
    rootSnap?: HistorySnapshot;
    /** The batch containing the root `split_segment` op. */
    rootBatch: HistoryBatch;
    /** All ops in the chain, in insertion order. */
    ops: SplitChainOp[];
    /** ISO timestamp of the latest absorbed op — used for sorting. */
    latestDate: string;
}

/** Flattened history display item produced by `_flattenBatchesToItems`
 *  (history/rendering.ts). This is the runtime shape of `_allHistoryItems`
 *  and the argument to `_renderHistoryDisplayItems`. */
export interface OpFlatItem {
    type: 'op-card' | 'strip-specials-card' | 'multi-chapter-card' | 'revert-card';
    group: EditOp[];
    chapter: number | null;
    chapters?: number[];
    batchId: string | null;
    date: string;
    isRevert: boolean;
    isPending: boolean;
    batchIdx: number;
    groupIdx: number;
}

/** Segment-level peaks entry keyed by URL inside `_segPeaksByUrl`. */
export interface SegPeaksRangeEntry {
    startMs: number;
    endMs: number;
    peaks: PeakBucket[];
    durationMs: number;
}

/** Queue item for the observer-driven segment-peaks batch fetcher.
 *  Field names match the wire format (`POST /api/seg/segment-peaks/`) so the
 *  queue can be sent straight through as `segments:[]`. See B18. */
export interface ObserverPeaksQueueItem {
    url: string;
    start_ms: number;
    end_ms: number;
}

/** Dirty-map entry — edited indices plus structural-change flag. */
export interface DirtyEntry {
    indices: Set<number>;
    structural: boolean;
}

/** The accordion op context captured at the row / prev / next button click site. */
export interface AccordionOpCtx {
    wrapper: HTMLElement;
    direction?: 'prev' | 'next';
}

/** Snapshot of the split-chain state captured while showing the save preview. */
export interface SavedChainsSnapshot {
    splitChains: Map<string, SplitChain> | null;
    chainedOpIds: Set<string> | null;
}

/** Saved scroll position snapshot around showSavePreview. */
export interface SegSavedPreviewState {
    scrollTop: number;
}

/** Augmented `SegAllResponse` — client adds lazy chapter indices. */
export interface SegAllDataState extends SegAllResponse {
    _byChapter?: Record<string, Segment[]> | null;
    _byChapterIndex?: Map<string, Segment> | null;
}

/** Augmented `SegDataResponse` — client may overwrite audio_url with a proxy URL. */
export type SegDataState = SegDataResponse;

// setTimeout / setInterval / requestAnimationFrame return values are branded
// in both DOM and Node envs. Use ReturnType so both environments compile.
export type TimerHandle = ReturnType<typeof setTimeout>;
export type RafHandle = number;

/** `_previewLooping` is a trivalued flag: false, or one of the three loop keys. */
export type PreviewLoopMode = false | 'trim' | 'split-left' | 'split-right';

// ---------------------------------------------------------------------------
// Mutable state — THE hub
// ---------------------------------------------------------------------------

/** Public shape of the segments tab mutable state singleton. */
export interface SegmentsState {
    // Core data
    segData: SegDataState | null;
    segAllData: SegAllDataState | null;
    segActiveFilters: SegActiveFilter[];
    segAnimId: RafHandle | null;
    segCurrentIdx: number;
    segDisplayedSegments: Segment[] | null;
    segDirtyMap: Map<number, DirtyEntry>;
    segEditMode: 'trim' | 'split' | null;
    segEditIndex: number;

    // Prefetch & playback
    _segPrefetchCache: Record<string, Promise<unknown>>;
    _segContinuousPlay: boolean;
    _segAutoPlayEnabled: boolean;
    _segPlayEndMs: number;

    // Validation & stats
    segValidation: SegValidateResponse | null;
    segAllReciters: SegReciter[];
    segStatsData: SegStatsResponse | null;

    // Filter
    _segFilterDebounceTimer: TimerHandle | null;

    // Audio source tracking
    _activeAudioSource: 'main' | 'error' | null;
    _segIndexMap: Map<string, Segment> | null;

    // Waveform observer
    _waveformObserver: IntersectionObserver | null;

    // Filter view save/restore
    _segSavedFilterView: SegSavedFilterView | null;
    _segSavedPreviewState: SegSavedPreviewState | null;

    // Peaks (Wave 7: chapter-wide peaks moved to lib/utils/waveform-cache;
    // _segPeaksByUrl still holds covering-range entries built from segment-peaks API).
    _peaksPollTimer: TimerHandle | null;
    _segPeaksByUrl: Record<string, SegPeaksRangeEntry[]> | null;
    _observerPeaksQueue: ObserverPeaksQueueItem[];
    _observerPeaksTimer: TimerHandle | null;
    _observerPeaksRequested: Set<string>;

    // Rendering
    _cardRenderRafId: RafHandle | null;

    // Accordion edit context
    _accordionOpCtx: AccordionOpCtx | null;
    _splitChainWrapper: HTMLElement | null;

    // Edit history
    segOpLog: Map<number, EditOp[]>;
    _pendingOp: EditOp | null;
    _splitChainUid: string | null;
    _splitChainCategory: string | null;

    // Edit history viewer state
    segHistoryData: SegEditHistoryResponse | null;
    _segDataStale: boolean;

    // History filter & sort state
    _histFilterOpTypes: Set<string>;
    _histFilterErrCats: Set<string>;
    _histSortMode: 'time' | 'quran';
    /** Flat list of display items built from batches.
     *  `group` is an `EditOp[]` grouped by display; extra fields come from the
     *  enclosing batch. Produced/consumed by history/rendering + history/filters. */
    _allHistoryItems: OpFlatItem[] | null;

    // Split chain state (Map of chain id -> chain descriptor)
    _splitChains: Map<string, SplitChain> | null;
    _chainedOpIds: Set<string> | null;
    _segSavedChains: SavedChainsSnapshot | null;

    // Server-provided canonical category list (from /api/seg/config)
    _validationCategories: string[] | null;

    // Classification data for per-segment category detection
    _muqattaatVerses: Set<string> | null;
    _standaloneRefs: Set<string> | null;
    _standaloneWords: Set<string> | null;
    _qalqalaLetters: Set<string> | null;
    _lcDefaultThreshold: number;
    _accordionContext: Record<string, string> | null;

    // SearchableSelect instance
    segChapterSS: SearchableSelect | null;

    // Highlight tracking (playback)
    _prevHighlightedRow: Element | null;
    _prevHighlightedIdx: number;
    _prevPlayheadIdx: number;
    _currentPlayheadRow: Element | null;

    // Canvas scrub
    _segScrubActive: boolean;

    // Adjust/trim mode config (overridden by server config)
    TRIM_PAD_LEFT: number;
    TRIM_PAD_RIGHT: number;
    TRIM_DIM_ALPHA: number;
    SHOW_BOUNDARY_PHONEMES: boolean;

    // Preview playback
    _previewStopHandler: ((ev: Event) => void) | null;
    _previewLooping: PreviewLoopMode;
    _previewJustSeeked: boolean;
    _playRangeRAF: RafHandle | null;

    // Error card audio
    valCardAudio: HTMLAudioElement | null;
    valCardPlayingBtn: HTMLElement | null;
    valCardStopTime: number | null;
    valCardAnimId: RafHandle | null;
    valCardAnimSeg: Segment | null;

    // Audio cache
    _audioCachePollTimer: TimerHandle | null;

    // Validation index fixup categories
    _VAL_SINGLE_INDEX_CATS: readonly string[];
}

export const state: SegmentsState = {
    // Core data
    segData: null,
    segAllData: null,
    segActiveFilters: [],
    segAnimId: null,
    segCurrentIdx: -1,
    segDisplayedSegments: null,
    segDirtyMap: new Map(),
    segEditMode: null,
    segEditIndex: -1,

    // Prefetch & playback
    _segPrefetchCache: {},
    _segContinuousPlay: false,
    _segAutoPlayEnabled: true,
    _segPlayEndMs: 0,

    // Validation & stats
    segValidation: null,
    segAllReciters: [],
    segStatsData: null,

    // Filter
    _segFilterDebounceTimer: null,

    // Audio source tracking
    _activeAudioSource: null,
    _segIndexMap: null,

    // Waveform observer
    _waveformObserver: null,

    // Filter view save/restore
    _segSavedFilterView: null,
    _segSavedPreviewState: null,

    // Peaks
    _peaksPollTimer: null,
    _segPeaksByUrl: null,
    _observerPeaksQueue: [],
    _observerPeaksTimer: null,
    _observerPeaksRequested: new Set(),

    // Rendering
    _cardRenderRafId: null,

    // Accordion edit context
    _accordionOpCtx: null,
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
    _muqattaatVerses: null,
    _standaloneRefs: null,
    _standaloneWords: null,
    _qalqalaLetters: null,
    _lcDefaultThreshold: 80,
    _accordionContext: null,

    // SearchableSelect instance
    segChapterSS: null,

    // Highlight tracking (playback)
    _prevHighlightedRow: null,
    _prevHighlightedIdx: -1,
    _prevPlayheadIdx: -1,
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
// DOM references -- set in index.ts DOMContentLoaded
// ---------------------------------------------------------------------------

/**
 * Public shape of the segments tab DOM references.
 *
 * All fields are non-nullable and narrowed to their actual element type.
 * They are initialised to `null as unknown as T` below; the DOMContentLoaded
 * handler in `segments/index.ts` populates them before any feature code runs.
 * The alternative would be to type each as `T | null` and null-check at every
 * call site — that would add noise to 28 modules for a guarantee already
 * established by the ordering of import-time registration vs DOMContentLoaded.
 */
export interface DomRefs {
    segReciterSelect: HTMLSelectElement;
    segChapterSelect: HTMLSelectElement;
    segVerseSelect: HTMLSelectElement;
    segListEl: HTMLDivElement;
    segAudioEl: HTMLAudioElement;
    segPlayBtn: HTMLButtonElement;
    segAutoPlayBtn: HTMLButtonElement;
    segSpeedSelect: HTMLSelectElement;
    segSaveBtn: HTMLButtonElement;
    segPlayStatus: HTMLElement;
    segValidationGlobalEl: HTMLDivElement;
    segValidationEl: HTMLDivElement;
    segFilterBarEl: HTMLDivElement;
    segFilterRowsEl: HTMLDivElement;
    segFilterAddBtn: HTMLButtonElement;
    segFilterClearBtn: HTMLButtonElement;
    segFilterCountEl: HTMLElement;
    segFilterStatusEl: HTMLElement;

    // History view
    segHistoryView: HTMLDivElement;
    segHistoryBtn: HTMLButtonElement;
    segHistoryBackBtn: HTMLButtonElement;
    segHistoryStats: HTMLDivElement;
    segHistoryBatches: HTMLDivElement;
    segHistoryFilters: HTMLDivElement;
    segHistoryFilterOps: HTMLDivElement;
    segHistoryFilterCats: HTMLDivElement;
    segHistoryFilterClear: HTMLButtonElement;
    segHistorySortTime: HTMLButtonElement;
    segHistorySortQuran: HTMLButtonElement;

    // Save preview
    segSavePreview: HTMLDivElement;
    segSavePreviewCancel: HTMLButtonElement;
    segSavePreviewConfirm: HTMLButtonElement;
    segSavePreviewStats: HTMLDivElement;
    segSavePreviewBatches: HTMLDivElement;
}

// Sentinel for DOM ref seeding. `never` is assignable to every field type,
// so this satisfies `DomRefs` without writing `null as unknown as HTMLXxx` at
// every slot. Populated by `document.getElementById(...)` inside the
// DOMContentLoaded handler in `segments/index.ts` before any consumer runs.
// Trade-off: a forgotten id (returning null from getElementById) would NPE
// at first use with no TSC warning. If that becomes a real footgun, flip the
// fields to `T | null` and accept the call-site ripple.
const _UNSET = null as unknown as never;

export const dom: DomRefs = {
    segReciterSelect: _UNSET,
    segChapterSelect: _UNSET,
    segVerseSelect: _UNSET,
    segListEl: _UNSET,
    segAudioEl: _UNSET,
    segPlayBtn: _UNSET,
    segAutoPlayBtn: _UNSET,
    segSpeedSelect: _UNSET,
    segSaveBtn: _UNSET,
    segPlayStatus: _UNSET,
    segValidationGlobalEl: _UNSET,
    segValidationEl: _UNSET,
    segFilterBarEl: _UNSET,
    segFilterRowsEl: _UNSET,
    segFilterAddBtn: _UNSET,
    segFilterClearBtn: _UNSET,
    segFilterCountEl: _UNSET,
    segFilterStatusEl: _UNSET,

    // History view
    segHistoryView: _UNSET,
    segHistoryBtn: _UNSET,
    segHistoryBackBtn: _UNSET,
    segHistoryStats: _UNSET,
    segHistoryBatches: _UNSET,
    segHistoryFilters: _UNSET,
    segHistoryFilterOps: _UNSET,
    segHistoryFilterCats: _UNSET,
    segHistoryFilterClear: _UNSET,
    segHistorySortTime: _UNSET,
    segHistorySortQuran: _UNSET,

    // Save preview
    segSavePreview: _UNSET,
    segSavePreviewCancel: _UNSET,
    segSavePreviewConfirm: _UNSET,
    segSavePreviewStats: _UNSET,
    segSavePreviewBatches: _UNSET,
};

// ---------------------------------------------------------------------------
// Classify function injection (breaks state <-> categories cycle)
// ---------------------------------------------------------------------------

/** Shape of the classifier injected by `setClassifyFn` at module-top in index.ts. */
export type ClassifyFn = (seg: Segment) => string[];

let _classifyFn: ClassifyFn = () => [];

export function setClassifyFn(fn: ClassifyFn): void {
    _classifyFn = fn;
}

// ---------------------------------------------------------------------------
// Operation helpers
// ---------------------------------------------------------------------------

export interface CreateOpOptions {
    contextCategory?: string | null;
    fixKind?: string;
}

export function createOp(opType: string, { contextCategory = null, fixKind = 'manual' }: CreateOpOptions = {}): EditOp {
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

/** Snapshot of a segment captured at op-start / op-end. Shape mirrors `Segment`
 *  with a few client-added flags (`index_at_save`, `categories`). Loose-typed
 *  so downstream history rendering doesn't have to cast every read. */
export type SegSnapshot = Record<string, unknown>;

export function snapshotSeg(seg: Segment): SegSnapshot {
    const snap: SegSnapshot = {
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

export function finalizeOp(chapter: number, op: EditOp): void {
    op.ready_at_utc = new Date().toISOString();
    if (!state.segOpLog.has(chapter)) state.segOpLog.set(chapter, []);
    state.segOpLog.get(chapter)!.push(op);
    state._pendingOp = null;
}

// ---------------------------------------------------------------------------
// Dirty-state helpers
// ---------------------------------------------------------------------------

export function markDirty(chapter: number, index?: number, structural = false): void {
    if (!state.segDirtyMap.has(chapter)) {
        state.segDirtyMap.set(chapter, { indices: new Set(), structural: false });
    }
    const entry = state.segDirtyMap.get(chapter)!;
    if (index !== undefined) entry.indices.add(index);
    if (structural) entry.structural = true;
    dom.segSaveBtn.disabled = false;
}

export function unmarkDirty(chapter: number, index: number): void {
    const entry = state.segDirtyMap.get(chapter);
    if (!entry) return;
    entry.indices.delete(index);
    if (entry.indices.size === 0 && !entry.structural) {
        state.segDirtyMap.delete(chapter);
    }
}

export function isDirty(): boolean {
    return state.segDirtyMap.size > 0;
}

export function isIndexDirty(chapter: number, index: number): boolean {
    const entry = state.segDirtyMap.get(chapter);
    return entry ? entry.indices.has(index) : false;
}

// ---------------------------------------------------------------------------
// _findCoveringPeaks -- pure function reading state data
// (resolves waveform <-> waveform-draw circular dependency)
// ---------------------------------------------------------------------------

export function _findCoveringPeaks(
    audioUrl: string,
    startMs?: number | null,
    endMs?: number | null,
): AudioPeaks | null {
    // Wave 7 CF: read via waveform-cache util (normalized URL key per S2-B04).
    const pe = getWaveformPeaks(audioUrl);
    if (pe && pe.peaks && pe.peaks.length > 0) return pe;
    // Then try segment-level peaks covering the requested range
    if (startMs != null && endMs != null && state._segPeaksByUrl) {
        const entries = state._segPeaksByUrl[audioUrl];
        if (entries) {
            for (const entry of entries) {
                if (entry.startMs <= startMs && entry.endMs >= endMs) {
                    return { peaks: entry.peaks, duration_ms: entry.durationMs, start_ms: entry.startMs };
                }
            }
        }
    }
    return null;
}
