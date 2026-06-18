/**
 * Timestamps-tab client types — FE-only.
 *
 * The verse model (`TsVerseData` + `PhonemeInterval`/`Letter`/`TsWord`) is
 * assembled client-side by the ts_client from a chapter shard — no wire
 * producer. The slim catalog projection (`TsCatalog*`), the positionally-typed
 * shard reads (`TsShardWord`/`SegmentEntry`/`TsShardResponse`), the surah-info
 * map, and the deprecated legacy `/api/ts/*` response shapes all live here too:
 * none has a generated equivalent (the catalog schema is not codegen'd to the
 * FE; the shard `words`/`segments` fields are opaque in the generated models).
 * The codegen'd `Ts*` wire types are imported from `./generated/schemas`.
 */

import type { ErrorEnvelope, TsShardMeta } from './generated/schemas';
import type { VerseRef } from './view-models';

// ---------------------------------------------------------------------------
// Client verse model (assembled by ts_client)
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
    /** True when the grapheme is silent (no audible phoneme at its own
     *  position) — the highlight skips it. From shard schema v4; absent on v3. */
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
}

/** Verse payload assembled by the frontend ts_client. Built client-side, no
 *  wire producer (mirrors the legacy `/api/ts/data` shape). */
export type TsDataResponse = TsVerseData;

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
// Shard reads (positionally-typed projections of the opaque generated shards)
// ---------------------------------------------------------------------------

/** Encoded word inside a segment. FE-typed positional projection of the
 *  codegen'd `TsShardWord` (which is the opaque `[unknown × 5]` json2ts emits
 *  for the `list`-typed Pydantic field). The wire really carries these precise
 *  element types — the shard decoder (`ts-source.ts`) reads them positionally. */
export type TsShardWord = [
    /** word_idx (1-based) */ number,
    /** start_ms */ number,
    /** end_ms */ number,
    /** letters: [char, start_ms|null, end_ms|null(, silent)][] (4th slot from schema v4) */
    Array<[string, number | null, number | null, boolean?]>,
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
 *  (segments required + richly-typed via `SegmentEntry`). The codegen'd
 *  `TsShardMeta` types the `_meta` block. */
export interface TsShardResponse {
    _meta: TsShardMeta;
    segments: SegmentEntry[];
}

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

// ---------------------------------------------------------------------------
// Deprecated legacy /api/ts/* response shapes
// ---------------------------------------------------------------------------

/** GET /api/ts/vbr/:reciter — fallback for older HF manifests. */
export interface TsVbrResponse {
    vbr_chapters: number[];
    error?: string;
}

/** @deprecated Reciter list now read from the manifest. */
export type TsRecitersResponse = TsReciter[];

/** @deprecated Chapter list now read from the manifest reciter block. */
export type TsChaptersResponse = number[] | ErrorEnvelope;

/** @deprecated Verse list now derived client-side from a chapter shard. */
export interface TsVersesResponse {
    verses: Array<{ ref: VerseRef; audio_url: string }>;
}
