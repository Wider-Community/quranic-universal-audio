/**
 * API response shapes — hand-mirrored from `inspector/routes/**`.
 *
 * One request/response pair per endpoint, grouped by blueprint.
 * Drift findings logged in `.refactor/stage1-bugs.md` §Section 3.
 */

import type {
    ApiErrorBody,
    AudioPeaks,
    EditOp,
    HistoryBatch,
    HistorySummary,
    Segment,
    SegmentsChapterSummary,
    SegmentPeaks,
    SegReciter,
    SurahInfoMap,
    TsBoundaryMismatch,
    TsMfaFailure,
    TsMissingWords,
    TsReciter,
    TsVerseData,
    ValidationSummarySnapshot,
    VerseRef,
} from './domain';

// ===========================================================================
// Cross-tab
// ===========================================================================

/** GET /api/surah-info */
export type SurahInfoResponse = SurahInfoMap;

// ===========================================================================
// /api/ts/* — Timestamps
// ===========================================================================

/** GET /api/ts/config */
export interface TsConfigResponse {
    unified_display_max_height: number;
    anim_highlight_color: string;
    anim_word_transition_duration: number;
    anim_char_transition_duration: number;
    anim_transition_easing: string;
    anim_word_spacing: number;
    anim_line_height: number;
    anim_font_size: number;
    analysis_word_font_size: number;
    analysis_letter_font_size: number;
}

/** GET /api/ts/reciters */
export type TsRecitersResponse = TsReciter[];

/** GET /api/ts/chapters/:reciter — 200 returns numbers, 404 returns error. */
export type TsChaptersResponse = number[] | ApiErrorBody;

/** GET /api/ts/verses/:reciter/:chapter */
export interface TsVersesResponse {
    verses: Array<{ ref: VerseRef; audio_url: string }>;
}

/** GET /api/ts/data/:reciter/:verse_ref (also used by /random and /random/:reciter). */
export type TsDataResponse = TsVerseData;

/** GET /api/ts/validate/:reciter */
export interface TsValidateResponse {
    mfa_failures: TsMfaFailure[];
    missing_words: TsMissingWords[];
    boundary_mismatches: TsBoundaryMismatch[];
    meta: {
        has_segments: boolean;
        tolerance_ms: number;
    };
}

// ===========================================================================
// /api/seg/* — Segments tab (data)
// ===========================================================================

/** GET /api/seg/config */
export interface SegConfigResponse {
    seg_font_size: number;
    seg_word_spacing: number;
    trim_pad_left: number;
    trim_pad_right: number;
    trim_dim_alpha: number;
    show_boundary_phonemes: boolean;
    low_conf_default_threshold: number;
    validation_categories: string[];
    muqattaat_verses: Array<[number, number]>;
    qalqala_letters: string[];
    standalone_refs: Array<[number, number, number]>;
    standalone_words: string[];
    accordion_context: Record<string, number>;
}

/** GET /api/seg/reciters */
export type SegRecitersResponse = SegReciter[];

/** GET /api/seg/chapters/:reciter */
export type SegChaptersResponse = number[] | ApiErrorBody;

/** GET /api/seg/data/:reciter/:chapter[?verse=:n] — 404 returns {error}. */
export interface SegDataResponse {
    audio_url: string;
    segments: Segment[];
    summary: SegmentsChapterSummary;
    verse_word_counts: Record<VerseRef, number>;
    /** Present when the route returns 404 (reciter/chapter not found). */
    error?: string;
}

/** GET /api/seg/all/:reciter */
export interface SegAllResponse {
    segments: Segment[];
    audio_by_chapter: Record<string, string>;
    verse_word_counts: Record<VerseRef, number>;
    pad_ms: number;
}

// ===========================================================================
// /api/seg/* — Segments tab (edit)
// ===========================================================================

/** GET /api/seg/resolve_ref?ref=<ref> */
export interface SegResolveRefResponse {
    text: string;
    display_text: string;
}

/** POST /api/seg/save/:reciter/:chapter — request body (subset — all that JS sends). */
export interface SegSaveRequest {
    segments: Array<Partial<Segment> & { chapter?: number }>;
    ops?: EditOp[];
    [k: string]: unknown;
}

/** POST /api/seg/save — response (success variant). */
export interface SegSaveResponse {
    ok?: boolean;
    batch_id?: string;
    saved_at_utc?: string;
    edit_history?: HistoryBatch[];
    [k: string]: unknown;
}

/** POST /api/seg/undo-batch/:reciter */
export interface SegUndoBatchRequest {
    batch_id: string;
}

export interface SegUndoBatchResponse {
    ok?: boolean;
    [k: string]: unknown;
}

/** POST /api/seg/undo-ops/:reciter */
export interface SegUndoOpsRequest {
    batch_id: string;
    op_ids: string[];
}

export type SegUndoOpsResponse = SegUndoBatchResponse;

// ===========================================================================
// /api/seg/* — Segments tab (validation, stats, history)
// ===========================================================================

/** POST /api/seg/trigger-validation/:reciter */
export interface SegTriggerValidationResponse {
    ok: true;
}

/** GET /api/seg/validate/:reciter — shape varies by category; keep loose. */
export interface SegValidateResponse {
    errors?: unknown[];
    failed?: unknown[];
    missing_verses?: unknown[];
    missing_words?: unknown[];
    structural_errors?: unknown[];
    low_confidence?: unknown[];
    boundary_adj?: unknown[];
    cross_verse?: unknown[];
    audio_bleeding?: unknown[];
    repetitions?: unknown[];
    muqattaat?: unknown[];
    qalqala?: unknown[];
    [k: string]: unknown;
}

/** GET /api/seg/stats/:reciter — distributions + percentiles. Shape varies. */
export interface SegStatsResponse {
    distributions?: Record<string, { bins: number[]; counts: number[]; percentiles?: Record<string, number> }>;
    vad_params?: { min_silence_ms: number; [k: string]: unknown };
    [k: string]: unknown;
}

/** POST /api/seg/stats/:reciter/save-chart (multipart). */
export interface SegSaveChartResponse {
    ok?: boolean;
    path?: string;
    error?: string;
}

/** GET /api/seg/edit-history/:reciter */
export interface SegEditHistoryResponse {
    batches: HistoryBatch[];
    summary: HistorySummary | null;
}

// ===========================================================================
// /api/seg/* — Segments tab (peaks)
// ===========================================================================

/** GET /api/seg/peaks/:reciter?chapters=1,2,3&cached_only=true */
export interface SegPeaksResponse {
    peaks: Record<string, AudioPeaks>;
    complete: boolean;
}

/** POST /api/seg/segment-peaks/:reciter */
export interface SegSegmentPeaksRequest {
    segments: Array<{ url: string; start_ms: number; end_ms: number }>;
    cached_only?: boolean;
}

export interface SegSegmentPeaksResponse {
    /** Keyed by `${url}:${start_ms}:${end_ms}` — colon-delimited string. */
    peaks: Record<string, SegmentPeaks>;
}

// ===========================================================================
// /api/seg/* — Audio proxy & cache
// ===========================================================================

/** GET /api/seg/audio-cache-status/:reciter */
export interface SegAudioCacheStatusResponse {
    total: number;
    cached: number;
    downloading: boolean;
    download_progress: { total: number; downloaded: number; complete: boolean } | null;
    [k: string]: unknown;
}

/** POST /api/seg/prepare-audio/:reciter */
export interface SegPrepareAudioResponse {
    status: 'started' | 'already_running';
    total: number;
    to_download?: number;
    downloaded?: number;
    complete?: boolean;
    [k: string]: unknown;
}

/** DELETE /api/seg/delete-audio-cache/:reciter */
export interface SegDeleteAudioCacheResponse {
    ok?: boolean;
    [k: string]: unknown;
}

// ===========================================================================
// /api/audio/* — Audio tab
// ===========================================================================

/** GET /api/audio/sources — hierarchical {by_surah, by_ayah}. Loose shape. */
export interface AudioSourcesResponse {
    by_surah?: Record<string, unknown>;
    by_ayah?: Record<string, unknown>;
    [k: string]: unknown;
}

/** GET /api/audio/surahs/:category/:source/:slug */
export interface AudioSurahsResponse {
    surahs: Record<string, string>;
}
