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

import type { CellRole, CellStatus, ErrorEnvelope, TsShardMeta } from './generated/schemas';
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

/** One per-character cell — the ordered source for the analysis letter row
 *  (schema v5). Cells include `base` consonant/carrier cells (which anchor a
 *  group + carry its full-letter glyph via `sourceLetterIndex`) alongside the
 *  haraka / tanween / long-vowel-carrier / implicit cells from the phonemizer's
 *  `character_phoneme_mappings()`. All script/visual specifics (mini-meem glyph,
 *  open/closed/iqlab form, above/below placement) are derived in the FE from
 *  `tag` + `chars`. */
export interface TsCell {
    /** canonical source char(s); '' for a fully implicit cell */
    chars: string;
    role: CellRole;
    status: CellStatus;
    /** indices into the verse-flat `intervals[]` — the cell's timing anchor ([] = silent) */
    phonemeIndices: number[];
    /** the letter (index into this word's `letters`) the cell sits on/after; -1 if implicit */
    sourceLetterIndex: number;
    /** canonical rule/case key the renderer switches on (e.g. 'iqlab_tanween', 'madd_iwad') */
    tag: string | null;
    /** cells sharing one id highlight together (long vowel; cross-word idgham) */
    shareGroup: number | null;
    /** per-phoneme rule tags parallel to `phonemeIndices` (same length), each a
     *  rule key or null — set only on muqattaat cells whose phonemes carry
     *  distinct tajweed (schema v8, 8th shard slot). Absent → null, and the FE
     *  falls back to the single-`tag` colouring. */
    phonemeRuleTags?: (string | null)[] | null;
    /** extra rules co-occurring on this grapheme that lost the single-`tag` pick
     *  (in practice `['tafkheem']` on a heavy madd/qalqala cell) — the renderer
     *  stacks them as additional badges on `tag` (schema v9, 9th shard slot).
     *  Absent → null. */
    secondaryTags?: string[] | null;
}

/** A raw positional shard cell row (the 6th word slot) —
 *  `[chars, role, status, phoneme_indices, source_letter_index, tag?, share_group?,
 *   phoneme_rule_tags?, secondary_tags?]`. `phoneme_indices` are word-local
 *  indexable-phone indices; the optional 8th slot `phoneme_rule_tags` (schema v8)
 *  is parallel to them; the optional 9th slot `secondary_tags` (schema v9) is the
 *  heaviness-stack list (slot 8 padded null when only it is present). */
export type TsShardCellRow = [
    string,
    string,
    string,
    number[],
    number,
    (string | null)?,
    (number | null)?,
    ((string | null)[] | null)?,
    (string[] | null)?,
];

/** Read a positional shard cell row by name — the FE mirror of
 *  `qua_shared/ts_shard_cells.parse_cell`, so no consumer unpacks `row[0..7]`
 *  inline. `phonemeIndices` stay WORD-LOCAL here; the caller maps them to the
 *  verse-flat `intervals[]`. The optional 8th slot `phoneme_rule_tags` (v8) is
 *  read here too — v5-v7 rows lack it and parse to null. The 9th slot
 *  `secondary_tags` (v9) is read likewise; older rows parse to null. */
export function parseShardCell(row: TsShardCellRow): TsCell {
    return {
        chars: row[0],
        role: row[1] as CellRole,
        status: row[2] as CellStatus,
        phonemeIndices: row[3] ?? [],
        sourceLetterIndex: row[4],
        tag: (row[5] ?? null) as string | null,
        shareGroup: (row[6] ?? null) as number | null,
        phonemeRuleTags: (row[7] ?? null) as (string | null)[] | null,
        secondaryTags: (row[8] ?? null) as string[] | null,
    };
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
    /** Ordered per-character cells (schema v5) — includes `base` cells; the
     *  single source for the analysis letter row. Always present on real shard
     *  data; optional only so lightweight unit-test fixtures may omit it (the
     *  renderer synthesizes base cells from `letters` when absent). */
    cells?: TsCell[];
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
    /** cells (schema v5, optional): the positional `TsShardCellRow` rows.
     *  phoneme_indices are word-local indices over the word's INDEXABLE phones
     *  (qalqala `Q` excluded); the optional 8th slot phoneme_rule_tags (v8) is
     *  parallel to them, the optional 9th slot secondary_tags (v9) is the
     *  heaviness stack. */
    TsShardCellRow[]?,
];

/** One recited segment in a chapter's temporal `segments[]` array. FE-typed
 *  projection of the codegen'd `TsShardSegment` (`t` is `[unknown, unknown]`
 *  and `words` is opaque there). `ref` is always a single verse `"surah:ayah"`;
 *  `t` is the `[start_ms, end_ms]` span; a verse may recur across entries. */
export interface SegmentEntry {
    ref: string;
    t: [number, number];
    words: TsShardWord[];
    /** Schema v10: present (and `true`) ONLY when this take continues into the
     *  next segment without a stop (cross-verse waṣl). Absent on v9- shards, so
     *  every waṣl consumer treats `undefined` as "no bridge" and no-ops. */
    wasl?: boolean;
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
