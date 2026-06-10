/**
 * Core domain types shared across tabs.
 *
 * Data-contract shapes here are RE-EXPORT SHIMS over the codegen'd wire types
 * in `./generated/schemas` (the source of truth — never hand-edit those).
 * Each `export ... as` aliases an old hand-mirror name to its generated
 * equivalent so existing `from './domain'` imports keep resolving. Genuinely
 * FE-only types (UI/view-model, the peaks Int8Array transport branch, the
 * client-side timestamps verse model, ref-string aliases) stay real
 * definitions below.
 */

import type {
    Actor as GenActor,
    ErrorEnvelope as GenErrorEnvelope,
    FlagAuthor as GenFlagAuthor,
    FlagComment as GenFlagComment,
    SegmentFlagView as GenSegmentFlagView,
    SegmentsChapterSummary as GenSegmentsChapterSummary,
    SegReciter as GenSegReciter,
} from './generated/schemas';

// ---------------------------------------------------------------------------
// Reference strings: "surah:ayah[:word]" or compound "S:A:W-S:A:W"
// FE-only aliases — the wire carries these as bare `string`.
// ---------------------------------------------------------------------------

/** Word reference "surah:ayah:word" or word-range "S:A:W-S:A:W". */
export type Ref = string;

/** Verse reference "surah:ayah" (single) or "S:A-S:A2" (compound cross-verse). */
export type VerseRef = string;

// ---------------------------------------------------------------------------
// Segments — re-export shims over generated wire types
// ---------------------------------------------------------------------------

/** Author of a flag comment, as served by /api/seg/all. */
export type FlagAuthor = GenFlagAuthor;

/** One comment in a flag thread (root or follow-up), FE-facing shape. */
export type FlagComment = GenFlagComment;

/** A segment's flag thread: a root comment plus append-only follow-up replies. */
export type SegmentFlagView = GenSegmentFlagView;

/**
 * The Segments-tab working segment — a FE-only view-model, not a wire row.
 *
 * The wire has TWO distinct shapes (`SegDataSegment` from `/data`, with a flat
 * `audio_url`; `SegAllSegment` from `/all`, with `chapter`/`segment_uid`/
 * `entry_ref`). The editor merges them into ONE mutable object and injects
 * client-only working fields (`matched_text`, `silence_after_ms`, `_derived`,
 * …) at load time, then mutates it in place through the edit pipeline. That
 * merged object is genuinely FE-only — no single generated row models it — so
 * it stays a real definition here, built as the superset of both wire rows
 * plus the client-only fields. The strict generated rows remain the element
 * types of `SegAllResponse.segments` / `SegDataResponse.segments`.
 */
export interface Segment {
    // Wire fields common to both rows
    index: number;
    entry_idx: number;
    time_start: number; // milliseconds
    time_end: number; // milliseconds
    matched_ref: Ref;
    confidence: number; // 0..1
    ignored_categories?: string[] | null;
    is_wasl?: boolean | null;
    /** Opaque — used by repetition detection. */
    wrap_word_ranges?: unknown;
    // From SegDataSegment (`/data`) — injected onto `/all` rows by the editor
    audio_url?: string;
    // From SegAllSegment (`/all`)
    chapter?: number;
    segment_uid?: string;
    entry_ref?: string;
    /** Manual "needs a second look" flag thread. Present (on /api/seg/all)
     *  only when the segment is flagged. */
    flag?: GenSegmentFlagView | null;
    // ---- Client-only working fields (no wire producer) ----
    /** Reference text, populated client-side for display/edit. */
    matched_text?: string;
    /** Back-compat legacy boolean from pre-categories ignore flag. */
    ignored?: boolean;
    /** Client-computed silence gap to the next same-entry neighbour (ms);
     *  `null` when there is no downstream neighbour. */
    silence_after_ms?: number | null;
    silence_after_raw_ms?: number | null;
    /** Client-only flag for filter "neighbour" highlighting. */
    _isNeighbour?: boolean;
    /** Client-only cached derived reference info; cleared on ref edit. */
    _derived?: unknown;
}

/** Summary stats per-chapter, from /api/seg/data. */
export type SegmentsChapterSummary = GenSegmentsChapterSummary;

/** Forward-change patch envelope produced by `applyCommand` and consumed by
 *  inverse-patch logic. FE working shape — `applyCommand` always builds every
 *  field, so all are required here (the persisted `EditOpPatch` schema tolerates
 *  partials). Structural mirror of the Python `SegmentPatch` dataclass. */
export interface EditOpPatch {
    before: Array<Record<string, unknown>>;
    after: Array<Record<string, unknown>>;
    removedIds: string[];
    insertedIds: string[];
    affectedChapterIds: number[];
}

/** Edit operation record — the FE working/derived op shape. Built client-side
 *  by `applyCommand` and echoed back in the `/api/seg/edit-history` derived
 *  presentation read (which has no Pydantic producer). The persisted on-disk op
 *  is modelled separately by `EditOperation` in `qua_shared`; this is the FE's
 *  view-model and carries the client-only `merge_direction` tag (set on merge
 *  ops, stripped before persisting) plus a finalize-time forward `patch`. */
export interface EditOp {
    op_id: string;
    op_type: string;
    op_context_category: string | null;
    fix_kind: string | null;
    targets_before: Array<Record<string, unknown>>;
    targets_after: Array<Record<string, unknown>>;
    /** Set on merge ops — `'prev'` or `'next'`. Client-only. */
    merge_direction?: 'prev' | 'next';
    /** Forward-change patch attached at finalize time; reversed on undo/discard. */
    patch?: EditOpPatch;
}

/** Edit history batch as returned by /api/seg/edit-history. FE-only read shape:
 *  the route derives a presentation form (`save_mode`/`is_revert`/
 *  `reverted_op_ids`, nullable `batch_id` for pending) that no Pydantic schema
 *  models — the persisted batch is `EditHistoryBatch` in `qua_shared`. */
export interface HistoryBatch {
    batch_id: string | null;
    batch_type: string | null;
    saved_at_utc: string | null;
    chapter: number | null;
    chapters?: number[];
    save_mode: string | null;
    is_revert: boolean;
    operations: EditOp[];
    reverted_op_ids?: string[];
}

/** Actor identity stamped on flags / edit batches. */
export type Actor = GenActor;

// ---------------------------------------------------------------------------
// Edit-history rollups — FE-only (no generated producer modelled)
// ---------------------------------------------------------------------------

/** One TS-generation boundary in the edit-history timeline (ascending). The
 *  FE partitions edit batches into tiers split by these `produced_at` times.
 *  `published` marks a generation that an HF publish landed on. */
export interface GenerationBoundary {
    version: string | null;
    produced_at: string | null;
    published: boolean;
    published_at: string | null;
}

export interface HistorySummary {
    total_operations: number;
    total_batches: number;
    chapters_edited: number;
    op_counts: Record<string, number>;
    fix_kind_counts: Record<string, number>;
    /** Count of unique verse refs touched across all operations; optional for forward compat. */
    verses_edited?: number;
}

// ---------------------------------------------------------------------------
// Peaks / Waveform — FE-only transport (Int8Array branch has no wire model)
// ---------------------------------------------------------------------------

/** A single peak bucket: [min, max] pair. Server rounds to 4 decimal places. */
export type PeakBucket = [number, number];

/** Pre-computed waveform peaks for an audio URL (full-file).
 *  Server emits `peaks: [[min, max], ...]` — see `services/peaks.py`. B19.
 *
 *  Under the flag-gated drawer-int8 path (``localStorage.peaksInt8Drawer === '1'``)
 *  ``peaks`` is an ``Int8Array(n * 2)`` instead — interleaved min/max bytes
 *  in [-127, 127]. The hot-path drawer reads it via ``peaks-view.ts``
 *  (one branch at view construction, then shape-free per-pixel reads).
 *  Per-segment peaks (ffmpeg fallback) and history-peaks JSONL stay nested
 *  list — see ``docs/proposals/peaks-int8-drawer.md``. */
export interface AudioPeaks {
    peaks: PeakBucket[] | Int8Array;
    duration_ms: number;
    /** Start offset of this chunk within the audio file (ms). Present on per-segment peaks;
     *  absent/0 for full-file peaks. Drawing must subtract this from seg.time_start/time_end
     *  before slicing into the peaks array. */
    start_ms?: number;
}

/** Peaks for a segment sub-range fetched via HTTP Range. */
export interface SegmentPeaks {
    peaks: PeakBucket[];
    start_ms: number;
    end_ms: number;
    duration_ms: number;
}

// ---------------------------------------------------------------------------
// Reciters
// ---------------------------------------------------------------------------

/** Timestamps-tab reciter row. FE-only — derived client-side from the
 *  manifest, no dedicated wire model. */
export interface TsReciter {
    slug: string;
    name: string;
    audio_source?: string;
    audio_reciter?: string;
    has_data?: boolean;
}

/** GET /api/seg/reciters row. Re-export shim over the generated wire type
 *  (now carries `state` + `visibility` that the hand-mirror omitted). */
export type SegReciter = GenSegReciter;

// ---------------------------------------------------------------------------
// Timestamps — FE-only client verse model (assembled by ts_client)
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
    /** Cross-word tajweed bridge rule (idgham) when this phone is a merger that
     *  fuses with the previous word; the Timestamps tab renders it as a tile
     *  between word blocks. Baked into the shard at generation (schema v3). */
    bridge?: string;
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
    /** "by_ayah_audio" (default) or "by_surah_audio" — drives URL-rewrite + offset handling. */
    audio_category: 'by_ayah_audio' | 'by_surah_audio';
    time_start_ms: number;
    time_end_ms: number;
    intervals: PhonemeInterval[];
    words: TsWord[];
}

// ---------------------------------------------------------------------------
// Surah info (cross-tab) — FE-only (route emits a bare map, no wire model)
// ---------------------------------------------------------------------------

export interface SurahInfo {
    name_en: string;
    name_ar: string;
    num_verses?: number;
}

export type SurahInfoMap = Record<string, SurahInfo>;

// ---------------------------------------------------------------------------
// Generic error envelope (most 4xx/5xx responses)
// ---------------------------------------------------------------------------

/** Re-export shim over the generated `ErrorEnvelope` (adds optional
 *  `code`/`detail` the hand-mirror lacked; `error` stays required). */
export type ApiErrorBody = GenErrorEnvelope;
