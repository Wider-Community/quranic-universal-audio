/**
 * Timestamps-tab client types — FE-only.
 *
 * The timing view is assembled client-side from native v12 readings. Shard
 * metadata and timing sidecars reuse generated wire types; native phonemizer
 * documents reuse the renderer package types.
 */

import type { WirePayload } from '@quranic-phonemizer/cells';
import type { TsShardMeta } from './generated/schemas';
import type { VerseRef } from './view-models';

// ---------------------------------------------------------------------------
// Client verse model (assembled by ts_client)
// ---------------------------------------------------------------------------

/** One audio-relative sound interval used by animation and waveform surfaces. */
export interface PhonemeInterval {
    phone: string;
    start: number; // seconds
    end: number; // seconds
}

/** Single letter with optional per-letter timing. */
export interface Letter {
    char: string;
    start: number | null;
    end: number | null;
    /** True when the native source unit owns or presents no sound. */
    silent?: boolean;
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
    /** Native schema-v2 readings rendered by quran-cells, in audio order. */
    native: TsShardReading[];
}

// ---------------------------------------------------------------------------
// Reciters (Timestamps tab)
// ---------------------------------------------------------------------------

/** Timestamps-tab reciter row. Derived client-side from the manifest, no
 *  dedicated wire model. */
export interface TsReciter {
    slug: string;
    name: string;
    audio_source?: string;
    audio_reciter?: string;
    has_data?: boolean;
}

// ---------------------------------------------------------------------------
// Catalog projection (slim, Timestamps-tab fields only)
// ---------------------------------------------------------------------------

/** GET /api/static/catalog.json — slim catalog projection. The route serves the
 *  full ReciterCatalog; only the Timestamps-tab fields are modelled. No
 *  generated equivalent (the catalog schema is not codegen'd to the FE). */
export interface TsCatalogReciter {
    reciter_id: string;
    name_en: string;
    name_ar?: string | null;
    country?: string | null;
    notes?: string | null;
}

/** Delivery entry in the v2 catalog (see TsCatalogReciter). */
export interface TsCatalogDelivery {
    slug: string;
    reciter_id: string;
    riwayah: string;
    style: string;
    source: string;
    audio_category: 'by_surah' | 'by_ayah';
}

/** GET /api/static/catalog.json — slim projection (see above). */
export interface TsCatalogResponse {
    schema_version: number;
    reciters: TsCatalogReciter[];
    deliveries: TsCatalogDelivery[];
}

// ---------------------------------------------------------------------------
// Native shard v12
// ---------------------------------------------------------------------------

export interface TsShardPart {
    ref: string;
    t: [number, number];
    word_ids: number[];
}

export interface TsLetterUnit {
    source_unit_id: number;
    word_id: number;
    text: string;
    start_ms: number | null;
    end_ms: number | null;
    silent: boolean;
}

export interface TsWordTiming {
    word_id: number;
    start_ms: number;
    end_ms: number;
}

export interface TsSoundTiming {
    sound_id: number;
    start_ms: number;
    end_ms: number;
}

export interface TsBoundaryTiming {
    boundary_id: number;
    start_ms: number;
    end_ms: number;
}

export interface TsColumnTiming {
    column_id: string | number;
    start_ms: number | null;
    end_ms: number | null;
}

export interface TsShardReading {
    id: string;
    parts: TsShardPart[];
    wire: WirePayload;
    letters: TsLetterUnit[];
    timing: {
        words: TsWordTiming[];
        sounds: TsSoundTiming[];
        boundaries: TsBoundaryTiming[];
        columns: TsColumnTiming[];
    };
}

export interface TsShardResponse {
    _meta: TsShardMeta;
    readings: TsShardReading[];
}

export const nativePayload = (reading: TsShardReading): WirePayload => ({
    analysis: reading.wire.analysis,
    cells: reading.wire.cells,
});

// ---------------------------------------------------------------------------
// Surah info (cross-tab) — route emits a bare map, no wire model
// ---------------------------------------------------------------------------

export interface SurahInfo {
    name_en: string;
    name_ar: string;
    num_verses?: number;
}

export type SurahInfoMap = Record<string, SurahInfo>;

/** GET /api/surah-info — the route emits a bare map. */
export type SurahInfoResponse = SurahInfoMap;

/** GET /api/ts/vbr/:reciter — fallback for older HF manifests. */
export interface TsVbrResponse {
    vbr_chapters: number[];
    error?: string;
}
