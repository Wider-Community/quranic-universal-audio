/**
 * Core domain types shared across tabs.
 *
 * These mirror the shapes constructed by `inspector/services/**` and
 * returned via `inspector/routes/**`. Keep them in sync with the Python
 * side — every mismatch is an API-drift bug-log row.
 */

// ---------------------------------------------------------------------------
// Reference strings: "surah:ayah[:word]" or compound "S:A:W-S:A:W"
// ---------------------------------------------------------------------------

/** Word reference "surah:ayah:word" or word-range "S:A:W-S:A:W". */
export type Ref = string;

/** Verse reference "surah:ayah" (single) or "S:A-S:A2" (compound cross-verse). */
export type VerseRef = string;

// ---------------------------------------------------------------------------
// Segments
// ---------------------------------------------------------------------------

/** A single segment row as returned by /api/seg/data (chapter-scoped). */
export interface Segment {
    index: number;
    entry_idx: number;
    time_start: number; // milliseconds
    time_end: number; // milliseconds
    matched_ref: Ref;
    matched_text: string;
    display_text: string;
    confidence: number; // 0..1
    audio_url: string;
    ignored_categories?: string[];
    /** Back-compat legacy boolean from pre-categories ignore flag. Drift: absent from types/api.ts. */
    ignored?: boolean;
    wrap_word_ranges?: unknown; // opaque — used by repetition detection
    /** Server-side repetition flag persisted via save/undo. */
    has_repeated_words?: boolean;
    /** Space-separated ASR phoneme string used by tail-phoneme matching. */
    phonemes_asr?: string;
    /** Chapter number; present on /api/seg/all responses, derived client-side on /data. */
    chapter?: number;
    /** Stable UID assigned on first server load; present on /api/seg/all. */
    segment_uid?: string;
    entry_ref?: string;
    /**
     * Client-computed: (next.time_start - this.time_end) + 2*pad_ms for the
     * next segment in the same entry. `null` when there is no downstream
     * neighbour (end of chapter/entry); callers use `!= null` to gate.
     */
    silence_after_ms?: number | null;
    silence_after_raw_ms?: number | null;
    /** Client-only flag for filter "neighbour" highlighting. */
    _isNeighbour?: boolean;
}

/** Summary stats per-chapter, from /api/seg/data. */
export interface SegmentsChapterSummary {
    total_segments: number;
    matched_segments: number;
    failed_segments: number;
    conf_min: number;
    conf_median: number;
    conf_mean: number;
    conf_max: number;
    below_60: number;
    below_80: number;
    total_speech_ms: number;
    avg_segment_ms: number;
    total_silence_ms: number;
    avg_silence_ms: number;
    issue_indices: number[];
    missing_verses: VerseRef[];
}

/** Edit operation record (client builds via createOp; server echoes back in history). */
export interface EditOp {
    op_id: string;
    op_type: string;
    op_context_category: string | null;
    fix_kind: string | null;
    started_at_utc: string; // ISO8601
    applied_at_utc: string | null;
    ready_at_utc: string | null;
    targets_before: Array<Record<string, unknown>>;
    targets_after: Array<Record<string, unknown>>;
}

/** Validation summary snapshot — server records before/after each save. */
export interface ValidationSummarySnapshot {
    failed?: number;
    missing_verses?: number;
    missing_words?: number;
    structural_errors?: number;
    low_confidence?: number;
    cross_verse?: number;
    repetitions?: number;
    boundary_adj?: number;
    muqattaat?: number;
    qalqala?: number;
    [k: string]: unknown;
}

/** Edit history batch as returned by /api/seg/edit-history. */
export interface HistoryBatch {
    batch_id: string;
    batch_type: string | null;
    saved_at_utc: string | null;
    chapter: number | null;
    chapters?: number[];
    save_mode: string | null;
    is_revert: boolean;
    validation_summary_before: ValidationSummarySnapshot | null;
    validation_summary_after: ValidationSummarySnapshot | null;
    operations: EditOp[];
    reverted_op_ids?: string[];
}

export interface HistorySummary {
    total_operations: number;
    total_batches: number;
    chapters_edited: number;
    op_counts: Record<string, number>;
    fix_kind_counts: Record<string, number>;
}

// ---------------------------------------------------------------------------
// Peaks / Waveform
// ---------------------------------------------------------------------------

/** Pre-computed waveform peaks for an audio URL (full-file). */
export interface AudioPeaks {
    peaks: number[];
    duration_ms: number;
}

/** Peaks for a segment sub-range fetched via HTTP Range. */
export interface SegmentPeaks {
    peaks: number[];
    start_ms: number;
    end_ms: number;
    duration_ms: number;
}

// ---------------------------------------------------------------------------
// Reciters
// ---------------------------------------------------------------------------

export interface TsReciter {
    slug: string;
    name: string;
    audio_source?: string;
    audio_reciter?: string;
    has_data?: boolean;
}

export interface SegReciter {
    slug: string;
    name: string;
    audio_source: string;
}

// ---------------------------------------------------------------------------
// Timestamps
// ---------------------------------------------------------------------------

/** Single phoneme interval as returned by /api/ts/data.intervals. */
export interface PhonemeInterval {
    phone: string;
    start: number; // seconds
    end: number; // seconds
    /** Set when the MFA aligner split a geminate into two tokens. */
    geminate_start?: boolean;
    /** Set on the second half of a split geminate; consumers use this to skip rendering. */
    geminate_end?: boolean;
}

/** Single letter with optional per-letter timing. */
export interface Letter {
    char: string;
    start: number | null;
    end: number | null;
}

/** Single word with text + timing + letters + phoneme indices into the flat intervals list. */
export interface TsWord {
    location: string; // "surah:ayah:word"
    text: string;
    display_text: string;
    start: number; // seconds (may be negative for by_surah mode after offset)
    end: number;
    phoneme_indices: number[];
    letters: Letter[];
}

/** Full verse data for the timestamps tab. */
export interface TsVerseData {
    reciter: string;
    chapter: number;
    verse_ref: VerseRef;
    audio_url: string;
    time_start_ms: number;
    time_end_ms: number;
    intervals: PhonemeInterval[];
    words: TsWord[];
}

// ---------------------------------------------------------------------------
// Validation error rows (ts tab)
// ---------------------------------------------------------------------------

export interface TsMfaFailure {
    verse_key: string;
    chapter: number;
    ref: string;
    seg: string;
    error: string;
    diff_ms: number;
    label: string;
}

export interface TsMissingWords {
    verse_key: string;
    chapter: number;
    missing: Array<string | Record<string, unknown>>;
    count: number;
    diff_ms: number;
    label: string;
}

export interface TsBoundaryMismatch {
    verse_key: string;
    chapter: number;
    side: string;
    diff_ms: number;
    label: string;
}

// ---------------------------------------------------------------------------
// Segments tab validation items (rows inside SegValidateResponse.*)
// ---------------------------------------------------------------------------

/**
 * Auto-fix descriptor attached to some `missing_words` entries.
 * `target_seg_index` is re-indexed client-side on split/merge/delete via
 * `_forEachValItem` / `_fixupValIndicesFor*`.
 */
export interface SegValAutoFix {
    target_seg_index: number;
    new_ref_start: string;
    new_ref_end: string;
}

/** Common fields present on every validation item row. */
export interface SegValItemBase {
    chapter: number;
    /** Server-emitted; client mutates during index-fixup after split/merge/delete. */
    seg_index?: number;
}

export interface SegValFailedItem extends SegValItemBase {
    seg_index: number;
    time: string;
}

export interface SegValMissingVerseItem extends SegValItemBase {
    verse_key: VerseRef;
    msg: string;
}

export interface SegValMissingWordsItem extends SegValItemBase {
    verse_key: VerseRef;
    msg?: string;
    /** Client mutates entries during index-fixup. */
    seg_indices?: number[];
    auto_fix?: SegValAutoFix;
}

export interface SegValStructuralErrorItem extends SegValItemBase {
    verse_key: VerseRef;
    msg: string;
}

export interface SegValLowConfidenceItem extends SegValItemBase {
    seg_index: number;
    ref: Ref;
    confidence: number; // 0..1
}

export interface SegValBoundaryAdjItem extends SegValItemBase {
    seg_index: number;
    ref: Ref;
    verse_key: VerseRef;
    gt_tail?: string;
    asr_tail?: string;
}

export interface SegValCrossVerseItem extends SegValItemBase {
    seg_index: number;
    ref: Ref;
}

export interface SegValAudioBleedingItem extends SegValItemBase {
    seg_index: number;
    entry_ref: string;
    matched_verse: string;
    ref: Ref;
    confidence: number;
    time: string;
    msg: string;
}

export interface SegValRepetitionItem extends SegValItemBase {
    seg_index: number;
    ref: Ref;
    display_ref?: Ref;
    confidence: number;
    time: string;
    text: string;
}

export interface SegValMuqattaatItem extends SegValItemBase {
    seg_index: number;
    ref: Ref;
}

export interface SegValQalqalaItem extends SegValItemBase {
    seg_index: number;
    ref: Ref;
    qalqala_letter: string;
}

/** Union of every validation item variant the panel renders. */
export type SegValAnyItem =
    | SegValFailedItem
    | SegValMissingVerseItem
    | SegValMissingWordsItem
    | SegValStructuralErrorItem
    | SegValLowConfidenceItem
    | SegValBoundaryAdjItem
    | SegValCrossVerseItem
    | SegValAudioBleedingItem
    | SegValRepetitionItem
    | SegValMuqattaatItem
    | SegValQalqalaItem;

// ---------------------------------------------------------------------------
// Surah info (cross-tab)
// ---------------------------------------------------------------------------

export interface SurahInfo {
    name_en: string;
    name_ar: string;
    num_verses?: number;
    [k: string]: unknown;
}

export type SurahInfoMap = Record<string, SurahInfo>;

// ---------------------------------------------------------------------------
// Generic error envelope (most 4xx/5xx responses)
// ---------------------------------------------------------------------------

export interface ApiErrorBody {
    error: string;
}
