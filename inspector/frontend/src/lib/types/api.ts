/**
 * API response shapes.
 *
 * Data-contract shapes here are RE-EXPORT SHIMS over the codegen'd wire types
 * in `./generated/schemas` (the source of truth — never hand-edit those).
 * Endpoints whose wire shape has no generated model yet (catalog projection,
 * the FE-assembled TS verse payload, deprecated legacy routes, stats/chart/
 * edit-history reads) keep real definitions and are flagged FE-only below.
 */

import type {
    AudioPeaks,
    GenerationBoundary,
    HistoryBatch,
    HistorySummary,
    SegmentPeaks,
    SurahInfoMap,
    TsReciter,
    TsVerseData,
    VerseRef,
} from './domain';

import type {
    AudioSurahEntry as GenAudioSurahEntry,
    AudioSurahsResponse as GenAudioSurahsResponse,
    ErrorEnvelope as GenErrorEnvelope,
    SegAllResponse as GenSegAllResponse,
    SegConfigResponse as GenSegConfigResponse,
    SegDataResponse as GenSegDataResponse,
    SegPeaksResponse as GenSegPeaksResponse,
    SegRecitersResponse as GenSegRecitersResponse,
    SegSaveRequest as GenSegSaveRequest,
    SegSaveResponse as GenSegSaveResponse,
    SegSegmentPeaksRequest as GenSegSegmentPeaksRequest,
    SegSegmentPeaksResponse as GenSegSegmentPeaksResponse,
    SegUndoBatchRequest as GenSegUndoBatchRequest,
    SegUndoOpsRequest as GenSegUndoOpsRequest,
    SegUndoResponse as GenSegUndoResponse,
    SegValAnyItem as GenSegValAnyItem,
    SegValAudioBleedingItem as GenSegValAudioBleedingItem,
    SegValAutoFix as GenSegValAutoFix,
    SegValBasmalaAminItem as GenSegValBasmalaAminItem,
    SegValBoundaryAdjItem as GenSegValBoundaryAdjItem,
    SegValCrossVerseItem as GenSegValCrossVerseItem,
    SegValFailedItem as GenSegValFailedItem,
    SegValidateResponse as GenSegValidateResponse,
    SegValLowConfidenceItem as GenSegValLowConfidenceItem,
    SegValLowConfidenceV2Item as GenSegValLowConfidenceV2Item,
    SegValMissingVerseItem as GenSegValMissingVerseItem,
    SegValMissingWordsItem as GenSegValMissingWordsItem,
    SegValMuqattaatItem as GenSegValMuqattaatItem,
    SegValQalqalaItem as GenSegValQalqalaItem,
    SegValRepetitionItem as GenSegValRepetitionItem,
    SegValStructuralErrorItem as GenSegValStructuralErrorItem,
    TsConfigResponse as GenTsConfigResponse,
    TsManifestReciter as GenTsManifestReciter,
    TsManifestResponse as GenTsManifestResponse,
    TsShardMeta as GenTsShardMeta,
} from './generated/schemas';

// ===========================================================================
// Cross-tab
// ===========================================================================

/** GET /api/surah-info — FE-only (route emits a bare map). */
export type SurahInfoResponse = SurahInfoMap;

// ===========================================================================
// /api/ts/* — Timestamps
// ===========================================================================

/** GET /api/ts/config — display constants + read-path URLs. Re-export shim
 *  (drops the phantom `mode`; `catalog_url` now required; anim/analysis
 *  font/spacing fields are CSS strings, not numbers). */
export type TsConfigResponse = GenTsConfigResponse;

/** Per-reciter block inside `manifest.json.gz`. Re-export shim (the
 *  build-internal `_build` block is no longer typed). */
export type TsManifestReciter = GenTsManifestReciter;

/** GET /api/static/catalog.json — slim catalog projection. FE-only: the route
 *  serves the full ReciterCatalog; only the Timestamps-tab fields are modelled.
 *  No generated equivalent (the catalog schema is not codegen'd to the FE). */
export interface TsCatalogReciter {
    reciter_id: string;
    name_en: string;
    name_ar?: string | null;
    country?: string | null;
    notes?: string | null;
}

/** Delivery entry in the v2 catalog. FE-only (see TsCatalogReciter). */
export interface TsCatalogDelivery {
    slug: string;
    reciter_id: string;
    riwayah: string;
    style: string;
    source: string;
    audio_category: 'by_surah' | 'by_ayah';
}

/** GET /api/static/catalog.json — slim projection. FE-only (see above). */
export interface TsCatalogResponse {
    schema_version: number;
    reciters: TsCatalogReciter[];
    deliveries: TsCatalogDelivery[];
}

/** Body of `manifest.json.gz` (decompressed). Re-export shim. */
export type TsManifestResponse = GenTsManifestResponse;

/** Slim per-shard `_meta` block. Re-export shim. */
export type TsShardMeta = GenTsShardMeta;

/** Encoded word inside a segment. FE-typed positional projection of the
 *  codegen'd `TsShardWord` (which is the opaque `[unknown × 5]` json2ts emits
 *  for the `list`-typed Pydantic field). The wire really carries these precise
 *  element types — the shard decoder (`ts-source.ts`) reads them positionally. */
export type TsShardWord = [
    /** word_idx (1-based) */ number,
    /** start_ms */ number,
    /** end_ms */ number,
    /** letters: [char, start_ms|null, end_ms|null][] */ Array<[string, number | null, number | null]>,
    /** phones: [phone, start_ms, end_ms, ...optional flags][] */ Array<(string | number | boolean)[]>,
];

/** One recited segment in a chapter's temporal `segments[]` array. FE-typed
 *  projection of the codegen'd `TsShardSegment` (`t` is `[unknown, unknown]`
 *  and `words` is opaque there). `ref` is always a single verse `"surah:ayah"`;
 *  `t` is the `[start_ms, end_ms]` span; a verse may recur across entries. */
export interface SegmentEntry {
    ref: string;
    t: [number, number];
    words: TsShardWord[];
}

/** Body of one chapter shard (decompressed): slim `_meta` + a flat
 *  recitation-ordered `segments[]` array. FE-typed projection of `TsShardDoc`
 *  (segments required + richly-typed via `SegmentEntry`). */
export interface TsShardResponse {
    _meta: TsShardMeta;
    segments: SegmentEntry[];
}

/** Verse payload assembled by the frontend ts_client. FE-only — built
 *  client-side, no wire producer (mirrors the legacy `/api/ts/data` shape). */
export type TsDataResponse = TsVerseData;

/** GET /api/ts/vbr/:reciter — fallback for older HF manifests. FE-only. */
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

// ===========================================================================
// /api/seg/* — Segments tab (data)
// ===========================================================================

/** GET /api/seg/config. Re-export shim (font/spacing are STRINGS; adds
 *  `seg_scroll_anim_mode`). */
export type SegConfigResponse = GenSegConfigResponse;

/** GET /api/seg/reciters. Re-export shim. */
export type SegRecitersResponse = GenSegRecitersResponse;

/** GET /api/seg/chapters/:reciter — 404 returns {error}. FE-only union. */
export type SegChaptersResponse = number[] | ApiErrorBody;

/** GET /api/seg/data/:reciter/:chapter[?verse=:n]. Re-export shim (segments are
 *  `SegDataSegment[]`; `reciter_vbr_chapters` is required). */
export type SegDataResponse = GenSegDataResponse;

/** GET /api/seg/all/:reciter. Re-export shim (segments are `SegAllSegment[]`). */
export type SegAllResponse = GenSegAllResponse;

// ===========================================================================
// /api/seg/* — Segments tab (edit)
// ===========================================================================

/** POST /api/seg/save/:reciter/:chapter — request body. Re-export shim (the
 *  route reads `operations`, NOT `ops`; segments are loose dicts). */
export type SegSaveRequest = GenSegSaveRequest;

/** POST /api/seg/save — success body. Re-export shim ({ ok: true } only —
 *  the invented batch_id/saved_at_utc/edit_history keys are gone). */
export type SegSaveResponse = GenSegSaveResponse;

/** POST /api/seg/undo-batch/:reciter — request body. Re-export shim. */
export type SegUndoBatchRequest = GenSegUndoBatchRequest;

/** POST /api/seg/undo-batch — success body. Re-export shim over the shared
 *  undo response ({ ok, operations_reversed }). */
export type SegUndoBatchResponse = GenSegUndoResponse;

/** POST /api/seg/undo-ops/:reciter — request body. Re-export shim. */
export type SegUndoOpsRequest = GenSegUndoOpsRequest;

/** POST /api/seg/undo-ops — success body. Re-export shim (shared). */
export type SegUndoOpsResponse = GenSegUndoResponse;

// ===========================================================================
// /api/seg/* — Segments tab (validation, stats, history)
// ===========================================================================

/** Auto-fix descriptor attached to some `missing_words` entries. Re-export shim. */
export type SegValAutoFix = GenSegValAutoFix;

// Per-category validation item rows — re-export shims. The generated items are
// flat (no shared `SegValItemBase`) and each carries `classified_issues`.
export type SegValFailedItem = GenSegValFailedItem;
export type SegValMissingVerseItem = GenSegValMissingVerseItem;
export type SegValMissingWordsItem = GenSegValMissingWordsItem;
export type SegValStructuralErrorItem = GenSegValStructuralErrorItem;
export type SegValLowConfidenceItem = GenSegValLowConfidenceItem;
export type SegValLowConfidenceV2Item = GenSegValLowConfidenceV2Item;
export type SegValBoundaryAdjItem = GenSegValBoundaryAdjItem;
export type SegValCrossVerseItem = GenSegValCrossVerseItem;
export type SegValAudioBleedingItem = GenSegValAudioBleedingItem;
export type SegValRepetitionItem = GenSegValRepetitionItem;
export type SegValMuqattaatItem = GenSegValMuqattaatItem;
export type SegValQalqalaItem = GenSegValQalqalaItem;
export type SegValBasmalaAminItem = GenSegValBasmalaAminItem;

/** Union of every validation item variant. Re-export shim. */
export type SegValAnyItem = GenSegValAnyItem;

/** GET /api/seg/validate/:reciter. Re-export shim (items carry
 *  `classified_issues`; adds `category_counts`/`stats`/`low_confidence_v2_meta`). */
export type SegValidateResponse = GenSegValidateResponse;

/** GET /api/seg/stats/:reciter — distributions + percentiles. FE-only (shape
 *  varies; no generated model). */
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

/** POST /api/seg/stats/:reciter/save-chart (multipart). FE-only. */
export interface SegSaveChartResponse {
    ok?: boolean;
    path?: string;
    error?: string;
}

/** GET /api/seg/edit-history/:reciter. FE-only — the FE-shaped history read
 *  (HistoryBatch/HistorySummary/GenerationBoundary are FE rollups). */
export interface SegEditHistoryResponse {
    batches: HistoryBatch[];
    summary: HistorySummary | null;
    /** Ascending TS-generation boundaries — drives the history tier filter.
     *  Absent/empty when the reciter has never had timestamps generated. */
    generations?: GenerationBoundary[];
}

// ===========================================================================
// /api/seg/* — Segments tab (peaks)
// ===========================================================================

/** GET /api/seg/peaks/:reciter?chapters=1,2,3. Re-export shim (slim int8
 *  envelope per URL — `SegSlimPeaks`, NOT the nested-float `AudioPeaks`). */
export type SegPeaksResponse = GenSegPeaksResponse;

/** POST /api/seg/segment-peaks/:reciter — request body. Re-export shim. */
export type SegSegmentPeaksRequest = GenSegSegmentPeaksRequest;

/** POST /api/seg/segment-peaks/:reciter — response. Re-export shim. */
export type SegSegmentPeaksResponse = GenSegSegmentPeaksResponse;

// ===========================================================================
// /api/audio/* — Audio tab
// ===========================================================================

/** GET /api/audio/surahs/:category/:source/:slug — one entry. Re-export shim
 *  (generated entry is an open `{ [k]: unknown }` map). */
export type AudioSurahEntry = GenAudioSurahEntry;

/** GET /api/audio/surahs/:category/:source/:slug. Re-export shim. */
export type AudioSurahsResponse = GenAudioSurahsResponse;

// ===========================================================================
// Error envelope re-export (kept here for the legacy `from './api'` imports)
// ===========================================================================

/** Re-export shim over the generated `ErrorEnvelope`. */
export type ApiErrorBody = GenErrorEnvelope;

// Re-export domain types referenced by callers that import them from `./api`.
export type { AudioPeaks, SegmentPeaks };
