import type { SegAllResponse, SegDataResponse } from '../../types/api';
import type { EditOp, HistoryBatch, PeakBucket, Segment } from '../../types/domain';

// ---------------------------------------------------------------------------
// Split chain + history types
// ---------------------------------------------------------------------------

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

/** Group of related split/trim/refine ops chained by segment lineage. */
export interface SplitChain {
    rootSnap?: HistorySnapshot;
    rootBatch: HistoryBatch;
    ops: SplitChainOp[];
    latestDate: string;
}

/** Flattened history display item produced by `flattenBatchesToItems`. */
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

// ---------------------------------------------------------------------------
// Filter types
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

// ---------------------------------------------------------------------------
// Data state types
// ---------------------------------------------------------------------------

/** Augmented `SegAllResponse` — client adds lazy chapter indices. */
export interface SegAllDataState extends SegAllResponse {
    _byChapter?: Record<string, Segment[]> | null;
    _byChapterIndex?: Map<string, Segment> | null;
}

/** Augmented `SegDataResponse` — client may overwrite audio_url with a proxy URL. */
export type SegDataState = SegDataResponse;

// ---------------------------------------------------------------------------
// Dirty state
// ---------------------------------------------------------------------------

/** Dirty-map entry — edited indices plus structural-change flag. */
export interface DirtyEntry {
    indices: Set<number>;
    structural: boolean;
}

// ---------------------------------------------------------------------------
// Accordion / edit context
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Peaks (covering-range + observer queue)
// ---------------------------------------------------------------------------

/** Segment-level peaks entry keyed by URL (covering-range cache). */
export interface SegPeaksRangeEntry {
    startMs: number;
    endMs: number;
    peaks: PeakBucket[];
    durationMs: number;
}

/** Queue item for the observer-driven segment-peaks batch fetcher. Field
 *  names match the wire format (`POST /api/seg/segment-peaks/`) so the
 *  queue can be sent straight through as `segments:[]`. */
export interface ObserverPeaksQueueItem {
    url: string;
    start_ms: number;
    end_ms: number;
}

// ---------------------------------------------------------------------------
// Timer handles
// ---------------------------------------------------------------------------

export type TimerHandle = ReturnType<typeof setTimeout>;
export type RafHandle = number;

// ---------------------------------------------------------------------------
// Preview loop mode
// ---------------------------------------------------------------------------

/** `_previewLooping` is a trivalued flag: false, or one of the three loop keys. */
export type PreviewLoopMode = false | 'trim' | 'split-left' | 'split-right';

// ---------------------------------------------------------------------------
// Classification / ops
// ---------------------------------------------------------------------------

export interface CreateOpOptions {
    contextCategory?: string | null;
    fixKind?: string;
}

/** Snapshot of a segment captured at op-start / op-end. */
export type SegSnapshot = Record<string, unknown>;
