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
    Ref,
    Segment,
    SegmentPeaks,
    SegmentsChapterSummary,
    SegReciter,
    SurahInfoMap,
    TsBoundaryMismatch,
    TsLargeGap,
    TsMfaFailure,
    TsMissingVerse,
    TsMissingWords,
    TsReciter,
    TsVerseData,
    TsVerseOverlap,
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

/** GET /api/ts/config — display constants + read-path URLs. */
export interface TsConfigResponse {
    /** "local"  — Flask serves shards from on-disk timestamps tree.
     *  "bucket" — Flask serves shards from <bucket>/published/<slug>/timestamps/. */
    mode: 'local' | 'bucket';
    /** Full URL the frontend fetches once to populate the in-memory manifest. */
    manifest_url: string;
    /** URL template with `{reciter}` + `{chapter}` placeholders. */
    shard_url_template: string;
    /** D20 Track B: optional URL of the v2 catalog JSON. When present, the
     *  frontend prefers this over `manifest.reciters[]` for the dropdown. */
    catalog_url?: string;
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

/** Per-reciter block inside `manifest.json.gz`. */
export interface TsManifestReciter {
    name_en: string;
    name_ar?: string | null;
    riwayah: string;
    style: string;
    source?: string;
    /** "by_surah" or "by_ayah" — shard-internal short form, not "*_audio". */
    audio_category: 'by_surah' | 'by_ayah';
    /** Templated URL (`{surah:03d}` / `{ayah:03d}`). Empty string when audio
     *  manifests don't fit a templatable pattern; clients then fall back to
     *  per-verse URLs in the shard's `_meta.audio_urls`. */
    url_template: string;
    /** Sorted list of chapter numbers the reciter has shards for. */
    ts_chapters: number[];
    /** Sorted list of chapters whose audio is known VBR. Optional for older HF manifests. */
    vbr_chapters?: number[];
    validation: { boundary_mismatches: TsBoundaryMismatch[] };
    /** Build-internal payload — not relied on by the read path. */
    _build?: { shard_hashes?: Record<string, string> };
}

/** Reciter entry in the v2 catalog (`<bucket>/catalog/reciter_catalog.json`).
 *  Mirrors `scripts.lib.schemas.ReciterEntry` — fields the Timestamps tab
 *  dropdown uses; full schema carries optional `country`, `notes`. */
export interface TsCatalogReciter {
    reciter_id: string;
    name_en: string;
    name_ar?: string | null;
    country?: string | null;
    notes?: string | null;
}

/** Delivery entry in the v2 catalog. Slug uniquely identifies a delivery
 *  (= what the legacy manifest called a "reciter slug"). Mirrors
 *  `scripts.lib.schemas.Delivery` — only the fields the Timestamps tab
 *  needs are typed here; pass-through fields ignored. */
export interface TsCatalogDelivery {
    slug: string;
    reciter_id: string;
    riwayah: string;
    style: string;
    source: string;
    audio_category: 'by_surah' | 'by_ayah';
}

/** GET /api/static/catalog.json — slim projection of `ReciterCatalog` carrying
 *  the fields the Timestamps tab uses. The route serves the full catalog; we
 *  only model what's read here. */
export interface TsCatalogResponse {
    schema_version: number;
    reciters: TsCatalogReciter[];
    deliveries: TsCatalogDelivery[];
}

/** Body of `manifest.json.gz` (decompressed). */
export interface TsManifestResponse {
    schema_version: number;
    generated_at: string;
    commit?: string;
    /** "" in local mode (resources are absolute Flask paths); full URL in HF mode. */
    dataset_base_url: string;
    shard_url_template: string;
    /** Filenames keyed by purpose; resolved against `dataset_base_url` in HF
     *  mode and used as absolute paths in local mode (where `dataset_base_url=""`). */
    resources: Record<'qpc_hafs' | 'digital_khatt' | string, string>;
    reciters: Record<string, TsManifestReciter>;
}

/** Per-shard `_meta` block. Aligner-side fields (padding, beam, …) pass through. */
export interface TsShardMeta {
    schema_version: number;
    reciter: string;
    chapter: number;
    audio_category: 'by_surah' | 'by_ayah';
    url_template: string;
    /** Per-verse audio URL fallback when `url_template` is empty. */
    audio_urls?: Record<string, string>;
    /** Per-chapter slice of `mfa_failures` for the validation panel. */
    mfa_failures?: Array<Record<string, unknown>>;
    [k: string]: unknown;
}

/** Encoded verse row inside a shard. Flat tuples to keep gzipped payload small. */
export type TsShardWord = [
    /** word_idx (1-based) */ number,
    /** start_ms */ number,
    /** end_ms */ number,
    /** letters: [char, start_ms|null, end_ms|null][] */ Array<[string, number | null, number | null]>,
    /** phones: [phone, start_ms, end_ms, ...optional flags][] */ Array<(string | number | boolean)[]>,
];

/** Verse value inside a shard — either ``{words: [...]}`` or a bare list. */
export type TsShardVerse = { words: TsShardWord[]; [k: string]: unknown } | TsShardWord[];

/** Body of one chapter shard (decompressed). Verse keys may be compound (e.g. "37:151:3-37:152:2"). */
export interface TsShardResponse {
    _meta: TsShardMeta;
    [verseRef: string]: TsShardMeta | TsShardVerse;
}

/** Verse payload assembled by the frontend ts_client — same shape as the legacy
 *  ``/api/ts/data`` response so consumer components stay unchanged. */
export type TsDataResponse = TsVerseData;

/** GET /api/ts/vbr/:reciter — fallback for older HF manifests. */
export interface TsVbrResponse {
    vbr_chapters: number[];
    error?: string;
}

/** @deprecated Reciter list now read from {@link TsManifestResponse.reciters}. */
export type TsRecitersResponse = TsReciter[];

/** @deprecated Chapter list now read from {@link TsManifestReciter.ts_chapters}. */
export type TsChaptersResponse = number[] | ApiErrorBody;

/** @deprecated Verse list now derived client-side from a chapter shard. */
export interface TsVersesResponse {
    verses: Array<{ ref: VerseRef; audio_url: string }>;
}

/** GET /api/ts/validate/:reciter */
export interface TsValidateResponse {
    mfa_failures: TsMfaFailure[];
    missing_verses: TsMissingVerse[];
    missing_words: TsMissingWords[];
    verse_overlaps: TsVerseOverlap[];
    boundary_mismatches: TsBoundaryMismatch[];
    large_gaps: TsLargeGap[];
    meta: {
        has_segments: boolean;
        tolerance_ms: number;
    };
    /** Present when the endpoint returns an error (e.g. reciter not found). */
    error?: string;
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
    accordion_context: Record<string, string>;
}

/** GET /api/seg/reciters */
export type SegRecitersResponse = SegReciter[];

/** GET /api/seg/chapters/:reciter */
export type SegChaptersResponse = number[] | ApiErrorBody;

/** GET /api/seg/data/:reciter/:chapter[?verse=:n] — 404 returns {error}. */
export interface SegDataResponse {
    audio_url: string;
    /** True when the chapter audio is VBR (per data/.audio_meta.json).
     *  Frontend routes playback through the segment-clip endpoint instead of
     *  HTML5 `<audio>.currentTime` (which mis-seeks Xing-less VBR files).
     *  Defaults to false for unknown / unprobed chapters. */
    vbr: boolean;
    /** All chapters of this reciter known VBR. Populated from the same
     *  `data/.audio_meta.json` source as `vbr`, but covers the full reciter
     *  rather than just the active chapter — needed for cross-chapter
     *  accordion prefetch to pick the clip endpoint vs chapter URL based on
     *  the next sibling's chapter. */
    reciter_vbr_chapters: number[];
    segments: Segment[];
    summary: SegmentsChapterSummary;
    verse_word_counts: Record<VerseRef, number>;
    /** Flat ``"surah:ayah:word" -> Digital Khatt text`` slice for this chapter.
     *  Consumed by `dkTextForRef` to render row body text from `matched_ref`. */
    dk_words: Record<string, string>;
    /** Present when the route returns 404 (reciter/chapter not found). */
    error?: string;
}

/** GET /api/seg/all/:reciter */
export interface SegAllResponse {
    segments: Segment[];
    audio_by_chapter: Record<string, string>;
    /** All chapters of this reciter known VBR. Reciter-level mirror of
     *  SegDataResponse.reciter_vbr_chapters so global accordions can route
     *  cross-chapter playback before/independent of a chapter-data refresh. */
    reciter_vbr_chapters?: number[];
    verse_word_counts: Record<VerseRef, number>;
    /** Flat ``"surah:ayah:word" -> Digital Khatt text`` map (full corpus).
     *  Consumed by `dkTextForRef` to render row body text from `matched_ref`. */
    dk_words: Record<string, string>;
    /** Legacy symmetric shim: ``(pad_left_ms + pad_right_ms) / 2``. Prefer the L/R fields. */
    pad_ms: number;
    pad_left_ms: number;
    pad_right_ms: number;
    min_silence_floor_ms: number;
}

// ===========================================================================
// /api/seg/* — Segments tab (edit)
// ===========================================================================

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

// ---------------------------------------------------------------------------
// /api/seg/validate — per-category item shapes
// ---------------------------------------------------------------------------

/**
 * Auto-fix descriptor attached to some `missing_words` entries.
 * `target_seg_index` is the chapter-local index of the segment to adjust.
 */
export interface SegValAutoFix {
    target_seg_index: number;
    new_ref_start: string;
    new_ref_end: string;
}

/** Common fields present on every validation item row. */
export interface SegValItemBase {
    chapter: number;
    /** Server-emitted positional index; legacy fallback when segment_uid is absent. */
    seg_index?: number;
    /** Stable segment identity (IS-10). Present on per-segment items; null on chapter-level items. */
    segment_uid?: string | null;
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
    auto_fix_up?: SegValAutoFix;
    auto_fix_down?: SegValAutoFix;
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

/** Item for the *Low Confidence v2* category — segments flagged by the
 *  extraction-time MFA tight-beam probe. No confidence score; the signal is
 *  binary (probe pass/fail). */
export interface SegValLowConfidenceV2Item extends SegValItemBase {
    seg_index: number;
    ref: Ref;
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
    end_of_verse: boolean;
}

/** Union of every validation item variant the panel renders. */
export type SegValAnyItem =
    | SegValFailedItem
    | SegValMissingVerseItem
    | SegValMissingWordsItem
    | SegValStructuralErrorItem
    | SegValLowConfidenceItem
    | SegValLowConfidenceV2Item
    | SegValBoundaryAdjItem
    | SegValCrossVerseItem
    | SegValAudioBleedingItem
    | SegValRepetitionItem
    | SegValMuqattaatItem
    | SegValQalqalaItem;

/** GET /api/seg/validate/:reciter */
export interface SegValidateResponse {
    /** Structural validation issues — the server actually emits this key. */
    errors?: SegValStructuralErrorItem[];
    failed?: SegValFailedItem[];
    missing_verses?: SegValMissingVerseItem[];
    missing_words?: SegValMissingWordsItem[];
    /** Live alias of {@link errors} — both keys are emitted by the server (additive, MUST-1 compliant). */
    structural_errors?: SegValStructuralErrorItem[];
    low_confidence?: SegValLowConfidenceItem[];
    low_confidence_v2?: SegValLowConfidenceV2Item[];
    boundary_adj?: SegValBoundaryAdjItem[];
    cross_verse?: SegValCrossVerseItem[];
    audio_bleeding?: SegValAudioBleedingItem[];
    repetitions?: SegValRepetitionItem[];
    muqattaat?: SegValMuqattaatItem[];
    qalqala?: SegValQalqalaItem[];
    [k: string]: unknown;
}

/** GET /api/seg/stats/:reciter — distributions + percentiles. Shape varies. */
export interface SegStatsResponse {
    distributions?: Record<string, { bins: number[]; counts: number[]; percentiles?: Record<string, number> }>;
    vad_params?: {
        min_silence_ms: number;
        min_speech_ms?: number;
        pad_left_ms?: number;
        pad_right_ms?: number;
        min_silence_floor_ms?: number;
        [k: string]: unknown;
    };
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
    segments: Array<{ url: string; start_ms: number; end_ms: number; chapter?: number }>;
    cached_only?: boolean;
}

export interface SegSegmentPeaksResponse {
    /** Keyed by `${url}:${start_ms}:${end_ms}` — colon-delimited string. */
    peaks: Record<string, SegmentPeaks>;
}

// ===========================================================================
// /api/seg/* — Audio proxy & cache
// ===========================================================================

/** GET /api/seg/audio-cache-status/:reciter.
 *  Server emits: {cached_count, total, cached_bytes, downloading, download_progress}.
 *  See `services/audio_proxy.py:50`. B20.
 */
export interface SegAudioCacheStatusResponse {
    total: number;
    cached_count: number;
    cached_bytes: number;
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
