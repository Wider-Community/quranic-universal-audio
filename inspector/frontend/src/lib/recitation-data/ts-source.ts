/**
 * Shared shard-fetch data layer (was `tabs/timestamps/services/ts_client.ts`).
 *
 * Relocated under `lib/` so non-timestamps surfaces (the dashboard now-reciting
 * section) can consume it without a cross-tab import — the shared lib must not
 * import from `tabs/*`. The timestamps tab keeps its old import path via a thin
 * re-export barrel at `tabs/timestamps/services/ts_client.ts`. One module =
 * one set of module-level caches, so every surface shares the same fetch.
 *
 * Replaces the per-verse `/api/ts/{reciters,chapters,verses,data,random}`
 * round-trips with one manifest fetch + per-chapter shards. Local-mode
 * Flask and the HF dataset CDN both speak the same shape so the only
 * branch in this module is URL templating against `tsConfig`.
 *
 * Caching:
 *   - Config / manifest / qpc / dk: module-level singletons (load once).
 *   - Shards: small LRU keyed `${reciter}:${chapter}` so back-and-forth
 *     between two reciters keeps both currents resident.
 *
 * Each chapter shard is a temporal `segments[]` array (every recited segment
 * raw, in recitation order). `shardOccasions` splits it into occasions (a verse
 * may recur — loopbacks, re-dos) and `assembleOccasion` builds one occasion's
 * `TsVerseData` with every recited word kept (no dedup). See `occasions.ts`.
 */

import { ApiError, fetchArrayBuffer, fetchJson } from '../api';
import type { TsConfigResponse, TsManifestResponse, TsValidationDoc } from '../types/generated/schemas';
import type {
    Letter,
    PhonemeInterval,
    SegmentEntry,
    TsCell,
    TsShardResponse,
    TsVbrResponse,
    TsVerseData,
    TsWord,
} from '../types/ts-client';
import { parseShardCell } from '../types/ts-client';

// Render-only phone markers — NOT letter-derived, so excluded from the indexable
// phone sequence the cell `phoneme_indices` count against. Mirrors the
// phonemizer's `is_render_only` (the qalqala echo `Q`); the phonemizer test pins
// the value, keep the two in lockstep.
const RENDER_ONLY_PHONES = new Set(['Q']);

import { type ChapterOccasion, chapterOccasions } from './occasions';

// ---------------------------------------------------------------------------
// Singleton caches
// ---------------------------------------------------------------------------

let _config: Promise<TsConfigResponse> | null = null;
let _manifest: Promise<TsManifestResponse> | null = null;
let _qpc: Promise<Record<string, { text?: string }>> | null = null;
let _qpcVerseIndex: Promise<Map<number, Map<number, number>>> | null = null;
let _dk: Promise<Record<string, { text?: string }>> | null = null;

/** Bounded LRU for chapter shards — covers current + adjacent + two pre-rolls. */
const SHARD_CACHE_SIZE = 4;
const _shards: Map<string, Promise<TsShardResponse>> = new Map();
const _vbrChapters: Map<string, Promise<number[]>> = new Map();

function _shardKey(reciter: string, chapter: number): string {
    return `${reciter}:${chapter}`;
}

function _lruTouch(key: string, value: Promise<TsShardResponse>): void {
    // Map iteration order is insertion order; re-set bumps to "most recent".
    _shards.delete(key);
    _shards.set(key, value);
    while (_shards.size > SHARD_CACHE_SIZE) {
        const oldest = _shards.keys().next().value;
        if (oldest === undefined) break;
        _shards.delete(oldest);
    }
}

// ---------------------------------------------------------------------------
// Gzip + JSON fetch
// ---------------------------------------------------------------------------

/**
 * Fetch a gzipped JSON body (manifest, shard, resource) and decode it.
 *
 * Bodies are pre-gzipped at rest with no `Content-Encoding: gzip` header
 * (matches HF's static file serving), so we decompress explicitly via
 * `DecompressionStream('gzip')`. Falls back to a clear error message if
 * the browser is too old (Safari < 16.4 lacks DecompressionStream).
 */
async function _fetchGzipJson<T>(url: string): Promise<T> {
    if (typeof DecompressionStream === 'undefined') {
        throw new Error(
            'This browser is too old for the Timestamps tab — please update to '
            + 'a recent Chrome, Firefox, Edge, or Safari (16.4+).',
        );
    }
    const buf = await fetchArrayBuffer(url);
    const decompressed = new Response(
        new Blob([buf]).stream().pipeThrough(new DecompressionStream('gzip')),
    );
    return (await decompressed.json()) as T;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/** Fetch `/api/ts/config` once. Resolves on first call, returns the cache afterwards. */
export function loadConfig(): Promise<TsConfigResponse> {
    if (!_config) {
        _config = fetchJson<TsConfigResponse>('/api/ts/config');
    }
    return _config;
}

/**
 * Fetch the gzipped manifest once. Resolves with the parsed body — schema
 * matches `TsManifestResponse`. Cached forever client-side.
 */
export async function loadManifest(): Promise<TsManifestResponse> {
    if (!_manifest) {
        _manifest = (async () => {
            const cfg = await loadConfig();
            return _fetchGzipJson<TsManifestResponse>(cfg.manifest_url);
        })();
    }
    return _manifest;
}

/**
 * Fetch a per-chapter shard. The shard URL is templated against
 * `tsConfig.shard_url_template` (full URL in HF mode; `/api/ts/shard/...`
 * locally). Concurrent calls dedupe via the in-flight Promise.
 */
export async function loadChapterShard(
    reciter: string,
    chapter: number,
): Promise<TsShardResponse> {
    const key = _shardKey(reciter, chapter);
    const existing = _shards.get(key);
    if (existing) {
        // Touch so it stays resident across LRU evictions.
        _lruTouch(key, existing);
        return existing;
    }
    const promise = (async () => {
        const cfg = await loadConfig();
        const url = cfg.shard_url_template
            .replace('{reciter}', encodeURIComponent(reciter))
            .replace('{chapter}', String(chapter));
        return _fetchGzipJson<TsShardResponse>(url);
    })();
    _lruTouch(key, promise);
    // If the fetch fails, drop the entry so the next call retries.
    promise.catch(() => _shards.delete(key));
    return promise;
}

/**
 * Fetch & cache `qpc_hafs` (Uthmani text) keyed by `surah:ayah:word`.
 * URL comes from the manifest's `resources.qpc_hafs`, joined with
 * `dataset_base_url`.
 */
export async function loadQpc(): Promise<Record<string, { text?: string }>> {
    if (!_qpc) {
        _qpc = (async () => {
            const m = await loadManifest();
            const url = _resourceUrl(m, 'qpc_hafs');
            return _fetchGzipJson<Record<string, { text?: string }>>(url);
        })();
    }
    return _qpc;
}

/**
 * Reference word counts per verse, derived once from the full `qpc_hafs`
 * singleton: `chapter → (ayah → wordCount)`. The mushaf reference for "does
 * this verse have every word" — the chapter's verse count is the max ayah key.
 * Memoized (one O(qpc) scan), so the filmstrip's coverage diff is free after the
 * qpc the animation already loads. Word count = max word index seen (robust to a
 * gap in qpc keys).
 */
export async function loadQpcVerseIndex(): Promise<Map<number, Map<number, number>>> {
    if (!_qpcVerseIndex) {
        _qpcVerseIndex = (async () => {
            const qpc = await loadQpc();
            const index = new Map<number, Map<number, number>>();
            for (const loc of Object.keys(qpc)) {
                const parts = loc.split(':');
                if (parts.length !== 3) continue;
                const ch = parseInt(parts[0]!, 10);
                const ayah = parseInt(parts[1]!, 10);
                const word = parseInt(parts[2]!, 10);
                if (!ch || !ayah || !word) continue;
                let byAyah = index.get(ch);
                if (!byAyah) {
                    byAyah = new Map();
                    index.set(ch, byAyah);
                }
                const prev = byAyah.get(ayah) ?? 0;
                if (word > prev) byAyah.set(ayah, word);
            }
            return index;
        })();
    }
    return _qpcVerseIndex;
}

/**
 * Fetch & cache `digital_khatt_v2` (display text) keyed by `surah:ayah:word`.
 * Same resolution path as `loadQpc`.
 */
export async function loadDk(): Promise<Record<string, { text?: string }>> {
    if (!_dk) {
        _dk = (async () => {
            const m = await loadManifest();
            const url = _resourceUrl(m, 'digital_khatt');
            return _fetchGzipJson<Record<string, { text?: string }>>(url);
        })();
    }
    return _dk;
}

// ---------------------------------------------------------------------------
// Word-by-word translations (Quran.Foundation Content API, via Flask proxy)
// ---------------------------------------------------------------------------

export interface WbwLanguage {
    code: string;
    label: string;
    /** False when the language has meaningful English-fallback gaps (full-Quran
     *  measured); the picker flags these as "partial". */
    complete: boolean;
}

let _wbwLangs: Promise<WbwLanguage[]> | null = null;

/** Available WBW translation languages (load once).
 *  `cache: 'no-cache'` revalidates with the server instead of trusting a
 *  possibly-stale cached copy — the response shape gained a `complete` field,
 *  and a long-lived cached body from before that change would otherwise drop
 *  it (making every language look "partial"). Revalidation is a cheap 304 once
 *  the body is current. */
export async function loadWbwLanguages(): Promise<WbwLanguage[]> {
    if (!_wbwLangs) {
        _wbwLangs = fetchJson<WbwLanguage[]>('/api/qf/content/wbw/languages', {
            cache: 'no-cache',
        }).catch((e) => {
            _wbwLangs = null; // allow retry
            throw e;
        });
    }
    return _wbwLangs;
}

interface WbwResponse {
    verse_key: string;
    language: string;
    words: Record<string, string>;
}

/** Per-(ayahKey|language) cache so re-toggling / re-visiting a verse is free. */
const _wbwByAyah = new Map<string, Promise<Record<string, string>>>();

async function _fetchAyahTranslation(
    ayahKey: string,
    language: string,
): Promise<Record<string, string>> {
    const cacheKey = `${ayahKey}|${language}`;
    const hit = _wbwByAyah.get(cacheKey);
    if (hit) return hit;
    const [surah, ayah] = ayahKey.split(':');
    const url = `/api/qf/content/wbw/${surah}/${ayah}?language=${encodeURIComponent(language)}`;
    const promise = fetchJson<WbwResponse>(url)
        .then((r) => r.words ?? {})
        .catch((e) => {
            _wbwByAyah.delete(cacheKey); // allow retry on transient failure
            throw e;
        });
    _wbwByAyah.set(cacheKey, promise);
    return promise;
}

/**
 * Resolve word-by-word glosses for a loaded verse's words, keyed by
 * `location` ("surah:ayah:word"). Distinct ayahs are derived from the words'
 * locations (single verse). Per-ayah results are merged and cached. A failed
 * ayah fetch is skipped (its words simply render no gloss) rather than failing
 * the whole verse.
 */
export async function loadVerseTranslations(
    words: TsWord[],
    language: string,
): Promise<Record<string, string>> {
    const ayahs = new Set<string>();
    for (const w of words) {
        const parts = w.location.split(':');
        if (parts.length >= 2) ayahs.add(`${parts[0]}:${parts[1]}`);
    }
    const merged: Record<string, string> = {};
    await Promise.all(
        [...ayahs].map((ayahKey) =>
            _fetchAyahTranslation(ayahKey, language)
                .then((map) => Object.assign(merged, map))
                .catch(() => {
                    /* skip this ayah on failure */
                }),
        ),
    );
    return merged;
}

function _resourceUrl(manifest: TsManifestResponse, key: string): string {
    const filename = manifest.resources?.[key];
    if (!filename) {
        throw new Error(`Manifest missing required resource: ${key}`);
    }
    const base = (manifest.dataset_base_url || '').replace(/\/$/, '');
    if (!base) return filename; // local mode — filename is already an absolute path.
    return `${base}/${filename.replace(/^\//, '')}`;
}

/** Read VBR chapter metadata from a manifest, or null when the manifest predates it. */
export function vbrChaptersFromManifest(
    manifest: TsManifestResponse,
    reciter: string,
): number[] | null {
    const raw = manifest.reciters?.[reciter]?.vbr_chapters;
    return Array.isArray(raw)
        ? raw.filter((n): n is number => Number.isInteger(n)).sort((a, b) => a - b)
        : null;
}

/** Resolve VBR chapters, preferring manifest metadata and falling back to Flask. */
export async function resolveVbrChaptersForReciter(
    reciter: string,
    manifest: TsManifestResponse,
): Promise<number[]> {
    const fromManifest = vbrChaptersFromManifest(manifest, reciter);
    if (fromManifest !== null) return fromManifest;
    const data = await fetchJson<TsVbrResponse>(`/api/ts/vbr/${encodeURIComponent(reciter)}`);
    return Array.isArray(data.vbr_chapters)
        ? data.vbr_chapters.filter((n): n is number => Number.isInteger(n)).sort((a, b) => a - b)
        : [];
}

/** Fetch/cache the per-reciter VBR chapter map for timestamp playback + peaks. */
export async function loadVbrChapters(reciter: string): Promise<number[]> {
    if (!reciter) return [];
    const existing = _vbrChapters.get(reciter);
    if (existing) return existing;
    const promise = (async () => {
        try {
            const manifest = await loadManifest();
            return await resolveVbrChaptersForReciter(reciter, manifest);
        } catch (e) {
            console.warn('Failed to load TS VBR metadata:', reciter, e);
            return [];
        }
    })();
    _vbrChapters.set(reciter, promise);
    return promise;
}

/**
 * Authoritative per-reciter audio metadata, sourced from the manifest's reciter
 * block — the live source the backend rebuilds against the current audio-manifest
 * sidecar. The shard's slim `_meta` carries no audio routing fields.
 */
export interface TsReciterAudio {
    /** Short form (`'by_surah'` / `'by_ayah'`) — the contract the FE drives
     *  audio routing + offset logic from. Per-chapter audio URLs are NOT in the
     *  manifest; resolve them from the canonical `/api/audio/surahs` endpoint. */
    audio_category: 'by_surah' | 'by_ayah';
}

/** Look up a reciter's authoritative audio metadata from a loaded manifest.
 *  Returns null when the manifest doesn't advertise the reciter (caller should
 *  treat as "audio unavailable"). */
export function reciterAudioFromManifest(
    manifest: TsManifestResponse,
    reciter: string,
): TsReciterAudio | null {
    const block = manifest.reciters?.[reciter];
    if (!block) return null;
    return { audio_category: block.audio_category };
}

/**
 * Resolve the URL the `<audio>` element should actually load for a TS verse.
 *
 * by_surah audio is routed through the audio-proxy so the bucket-mounted file
 * (or CDN stream-through) is served via sendfile + Range/304; by_ayah / already
 * proxied URLs pass through. ONE source of truth so the prewarm path and the
 * real-play path produce byte-identical URLs (otherwise the shadow-audio prewarm
 * fills a different cache key than playback reads → silent miss).
 */
export function tsPlayUrl(reciter: string, audioUrl: string, audioCategory: string): string {
    return (audioCategory === 'by_surah_audio' && audioUrl && !audioUrl.startsWith('/api/'))
        ? `/api/seg/audio-proxy/${reciter}?url=${encodeURIComponent(audioUrl)}`
        : audioUrl;
}

/**
 * Verse-level ts-validation flags for the Timestamps-tab accordion.
 *
 * Backed by ``reciters/<slug>/ts_validation.json`` (multi-beam generate-job
 * output). 403 → caller lacks ``timestamps.view_validation``; 404 → caller
 * holds it but the reciter isn't viewable (unreleased and the caller doesn't
 * hold ``timestamps.view_unreleased``). Both return ``null`` so the panel
 * stays hidden. A viewable reciter with no flags returns an empty ``verses``
 * map. Only call this when the user holds the view-validation capability
 * (avoids a wasted bucket read per reciter-load for public users on the
 * single worker).
 */
export async function loadTsValidation(reciter: string): Promise<TsValidationDoc | null> {
    if (!reciter) return null;
    try {
        const resp = await fetch(`/api/ts/validation/${encodeURIComponent(reciter)}`);
        if (!resp.ok) return null; // 404 (not viewable) or transient — hide panel
        return (await resp.json()) as TsValidationDoc;
    } catch {
        return null;
    }
}

// ---------------------------------------------------------------------------
// Segment-array assembly
// ---------------------------------------------------------------------------

/** Per-shard memo of `chapterOccasions`. The split is O(segments) per chapter;
 *  callers iterate every occasion of a chapter, so it's cached on the
 *  (LRU-stable) shard object. */
const _occasionsByShard = new WeakMap<TsShardResponse, ChapterOccasion[]>();

export function shardOccasions(shard: TsShardResponse): ChapterOccasion[] {
    let list = _occasionsByShard.get(shard);
    if (!list) {
        list = chapterOccasions(shard.segments ?? []);
        _occasionsByShard.set(shard, list);
    }
    return list;
}

/**
 * Build the `TsVerseData` for one OCCASION — a contiguous recitation of a verse
 * (`occasions.ts`). Thin wrapper over {@link assembleMembers} with a single
 * member. Every recited word across the occasion's segments is kept, in audio
 * order: no dedup, so leading/trailing repeats and mid-verse lookbacks all render
 * and stay seekable. Words carry QPC / DK text; `by_surah_audio` words are
 * 0-anchored by subtracting the occasion's start so the audio element starts at
 * zero. The clip span (`[time_start_ms, time_end_ms]`) covers every segment /
 * word / letter time — the segmenter's natural lead-in + trailing silence
 * included (audio plays through it with nothing highlighted).
 *
 * Identity flows top-down: the caller knows which slug it fetched `shard` for, so
 * `reciter` is a param and rides back on the result. `audio_category` (offset
 * logic) comes from `reciterAudio` — the manifest's reciter block. `chapterAudioUrl`
 * is the canonical per-chapter link the caller resolved from `/api/audio/surahs`
 * (never recomputed from a template, so non-templatable sources like per-chapter
 * YouTube IDs resolve). For by_surah every occasion in the chapter shares it.
 */
export function assembleOccasion(
    reciter: string,
    occasion: ChapterOccasion,
    qpc: Record<string, { text?: string }>,
    dk: Record<string, { text?: string }>,
    reciterAudio: TsReciterAudio,
    chapterAudioUrl: string,
): TsVerseData {
    return assembleMembers(reciter, [occasion], occasion.ref, qpc, dk, reciterAudio, chapterAudioUrl);
}

/**
 * Build one `TsVerseData` for a cross-verse waṣl GROUP — a chain of occasions
 * recited into each other without a stop (`wasl.ts::waslGroupOf`). Display-only
 * context merge: every member verse's words/cells are concatenated in recitation
 * order so the analysis view shows the whole continuous span and junction tajweed
 * renders across each boundary; each word keeps its true `surah:ayah:word`
 * location so consumers can still scope editing/loop/validation to the focus
 * verse. `verseRef` labels the result (the focused verse). by_surah only — the
 * group span lives in one chapter file (the caller gates by_ayah out).
 */
export function assembleWaslGroup(
    reciter: string,
    members: ChapterOccasion[],
    verseRef: string,
    qpc: Record<string, { text?: string }>,
    dk: Record<string, { text?: string }>,
    reciterAudio: TsReciterAudio,
    chapterAudioUrl: string,
): TsVerseData {
    return assembleMembers(reciter, members, verseRef, qpc, dk, reciterAudio, chapterAudioUrl);
}

/**
 * Reconstruct the per-letter `Letter[]` from a word's cell row when the shard
 * omits the raw `letters` slot. Re-stamped shards consolidate per-letter facts
 * into cells + phonemes (the analysis letter row renders straight from those),
 * leaving the legacy `letters` slot empty — but the teleprompter / filmstrip
 * still drive their reveal off `Letter[]`. Groups cells by `sourceLetterIndex`
 * (one orthographic letter per group), takes the group's base glyph, and spans
 * its phoneme intervals; a group with no audible phoneme is `silent` with null
 * timing (the char-time stamper inherits a neighbour). `phonemeIndices` are
 * already verse-flat, so they index `intervals` directly.
 *
 * A long vowel's phoneme is referenced by BOTH the consonant's `haraka` cell and
 * the following `madd` carrier cell (one `shareGroup`) — e.g. `قَا`'s `aˤ:` rides
 * the fatha on `ق` and the alef on `ا`. Letting both claim it stretches the
 * consonant's span across the whole vowel, so it co-highlights with the carrier
 * (and any later same-time letter). Each phoneme is therefore assigned to exactly
 * ONE letter — the carrier (`madd`) wins over the consonant's `haraka` — so spans
 * stay disjoint and ordered, matching the original slot-3 timings.
 */
function lettersFromCells(cells: TsCell[], intervals: PhonemeInterval[]): Letter[] {
    // One letter per sourceLetterIndex, in cell (reading) order; remember each
    // letter's ordinal so phoneme ownership can pick a single winner.
    const out: Letter[] = [];
    const ordOf = new Map<number, number>();
    let curLi = -1;
    let cur: Letter | null = null;
    for (const c of cells) {
        const li = c.sourceLetterIndex;
        if (li < 0) continue; // implicit cell — carries no orthographic letter
        if (li !== curLi || !cur) {
            cur = { char: c.chars, start: null, end: null, silent: true };
            ordOf.set(li, out.length);
            out.push(cur);
            curLi = li;
        } else if (!cur.char && c.chars) {
            cur.char = c.chars;
        }
    }

    // Assign each phoneme to a single owning letter. A `madd` carrier owns the
    // long vowel it shares with the preceding consonant's `haraka`; otherwise the
    // first claimant wins (no real contention).
    const ownerOrd = new Map<number, number>();
    const ownerIsMadd = new Map<number, boolean>();
    for (const c of cells) {
        const li = c.sourceLetterIndex;
        if (li < 0) continue;
        const ord = ordOf.get(li);
        if (ord === undefined) continue;
        const isMadd = c.role === 'madd';
        for (const pi of c.phonemeIndices) {
            if (!ownerOrd.has(pi) || (isMadd && !ownerIsMadd.get(pi))) {
                ownerOrd.set(pi, ord);
                ownerIsMadd.set(pi, isMadd);
            }
        }
    }

    for (const [pi, ord] of ownerOrd) {
        const iv = intervals[pi];
        const lt = out[ord];
        if (!iv || !lt) continue;
        lt.silent = false;
        if (lt.start === null || iv.start < lt.start) lt.start = iv.start;
        if (lt.end === null || iv.end > lt.end) lt.end = iv.end;
    }
    return out;
}

/**
 * Core assembler shared by {@link assembleOccasion} (one member) and
 * {@link assembleWaslGroup} (a chain). Flattens every word across all member
 * occasions' segments in audio order; each word's `location` uses ITS OWN
 * member's ref, and the `share_group` base runs across the WHOLE list so co-light
 * ids stay unique across segments and verses. `verseRef` labels the result
 * (`verse_ref` + chapter); the by_surah 0-anchor + clip span cover all members,
 * so the merged times are relative to the group start (consumers in group mode
 * key off the group offset, not the focus verse's).
 */
function assembleMembers(
    reciter: string,
    members: ChapterOccasion[],
    verseRef: string,
    qpc: Record<string, { text?: string }>,
    dk: Record<string, { text?: string }>,
    reciterAudio: TsReciterAudio,
    chapterAudioUrl: string,
): TsVerseData {
    const chapter = parseInt(verseRef.split(':')[0] ?? '0', 10);

    // Every recited word across all members' segments, in audio order (no dedup
    // — repeats/lookbacks stay seekable). `cells[].share_group` ids are numbered
    // per source SEGMENT (each restarts at 0), so offset each segment's ids by a
    // running base to keep them unique across every segment AND member verse —
    // else a consumer keying co-light by id would merge unrelated groups.
    // `wordRefs[i]` is the owning verse ref of word `wordsRaw[i]` (its location).
    const wordsRaw: SegmentEntry['words'] = [];
    const wordRefs: string[] = [];
    const sgOffsets: number[] = [];
    let sgBase = 0;
    for (const member of members) {
        for (const seg of member.segments) {
            let maxSg = -1;
            for (const w of seg.words) {
                wordsRaw.push(w);
                wordRefs.push(member.ref);
                sgOffsets.push(sgBase);
                for (const c of w[5] ?? []) {
                    const sg = c[6];
                    if (sg != null && sg > maxSg) maxSg = sg;
                }
            }
            sgBase += maxSg + 1;
        }
    }

    const intervals: PhonemeInterval[] = [];
    const wordsOut: TsWord[] = [];

    for (let wi = 0; wi < wordsRaw.length; wi++) {
        const w = wordsRaw[wi]!;
        // Per-segment base so cross-segment share_group ids don't collide.
        const sgOffset = sgOffsets[wi] ?? 0;
        const memberRef = wordRefs[wi] ?? verseRef;
        const wordIdx = w[0];
        const wStart = w[1] / 1000;
        const wEnd = w[2] / 1000;
        const lettersRaw = (w[3] ?? []) as Array<[string, number | null, number | null, boolean?]>;
        const phonesRaw = (w[4] ?? []) as Array<(string | number | boolean)[]>;

        const location = `${memberRef}:${wordIdx}`;
        const text = qpc[location]?.text ?? '';
        const displayText = dk[location]?.text ?? text;

        const rawLetters: Letter[] = lettersRaw.map((lt) => ({
            char: lt[0],
            start: lt[1] === null ? null : lt[1] / 1000,
            end: lt[2] === null ? null : lt[2] / 1000,
            silent: lt[3] === true,
        }));

        const phoneStartIdx = intervals.length;
        for (const ph of phonesRaw) {
            const interval: PhonemeInterval = {
                phone: ph[0] as string,
                start: (ph[1] as number) / 1000,
                end: (ph[2] as number) / 1000,
            };
            if (ph[3] === true) interval.geminate_start = true;
            if (ph[4] === true) interval.geminate_end = true;
            if (ph[5]) interval.bridge = ph[5] as string;
            intervals.push(interval);
        }
        const phonemeIndices = Array.from(
            { length: intervals.length - phoneStartIdx },
            (_, i) => phoneStartIdx + i,
        );

        // Verse-flat indices of this word's INDEXABLE phones (render-only markers
        // excluded) — maps a cell's word-local indexable index to the flat list.
        const indexableFlat: number[] = [];
        for (let i = 0; i < phonesRaw.length; i++) {
            const p = phonesRaw[i]?.[0] as string | undefined;
            if (p && !RENDER_ONLY_PHONES.has(p)) indexableFlat.push(phoneStartIdx + i);
        }
        // All cells flow through unchanged — including `base` cells (the ordered
        // anchors the letter row groups on). Read each row by name (parseShardCell)
        // then map its word-local indexable indices to the verse-flat list; the
        // share_group carries the per-segment offset so cross-segment ids don't collide.
        const cells: TsCell[] = (w[5] ?? []).map((row) => {
            const c = parseShardCell(row);
            const mapped: number[] = [];
            for (const k of c.phonemeIndices) {
                const flat = indexableFlat[k];
                if (flat !== undefined) mapped.push(flat);
            }
            return {
                ...c,
                phonemeIndices: mapped,
                shareGroup: c.shareGroup == null ? null : c.shareGroup + sgOffset,
            };
        });

        // Prefer the shard's raw `letters`; fall back to cell-derived timing when
        // a re-stamped shard left the slot empty (cells own the per-letter facts).
        const letters = rawLetters.length > 0 || cells.length === 0
            ? rawLetters
            : lettersFromCells(cells, intervals);

        wordsOut.push({
            location, text, display_text: displayText,
            start: wStart, end: wEnd, phoneme_indices: phonemeIndices, letters, cells,
        });
    }

    // Audio URL — canonical per-chapter link resolved by the caller from
    // `/api/audio/surahs` (the audio-manifest sidecar), never a template.
    const audioUrl = chapterAudioUrl;

    // The TsVerseData type expects the long form ("by_*_audio") — the manifest
    // carries the short form. Map here.
    const audioCategory: 'by_ayah_audio' | 'by_surah_audio' =
        reciterAudio.audio_category === 'by_surah' ? 'by_surah_audio' : 'by_ayah_audio';

    // Span: the contiguous `[start, end]` covering every member's segments,
    // words and letters (a word/letter can bleed a few ms past its segment `t`).
    const firstSeg = members[0]?.segments[0];
    let spanStart = firstSeg?.t[0] ?? 0;
    let spanEnd = firstSeg?.t[1] ?? 0;
    for (const member of members) {
        for (const seg of member.segments) {
            if (seg.t[0] < spanStart) spanStart = seg.t[0];
            if (seg.t[1] > spanEnd) spanEnd = seg.t[1];
            for (const w of seg.words) {
                if (w[1] < spanStart) spanStart = w[1];
                if (w[2] > spanEnd) spanEnd = w[2];
                for (const lt of w[3] ?? []) {
                    if (lt[1] != null && lt[1] < spanStart) spanStart = lt[1];
                    if (lt[2] != null && lt[2] > spanEnd) spanEnd = lt[2];
                }
            }
        }
    }

    let timeStartMs = 0;
    let timeEndMs = 0;

    if (audioCategory === 'by_surah_audio') {
        timeStartMs = spanStart;
        timeEndMs = spanEnd;
        const offsetSec = timeStartMs / 1000;
        for (const wo of wordsOut) {
            wo.start -= offsetSec;
            wo.end -= offsetSec;
            for (const lt of wo.letters) {
                if (lt.start !== null) lt.start -= offsetSec;
                if (lt.end !== null) lt.end -= offsetSec;
            }
        }
        for (const iv of intervals) {
            iv.start -= offsetSec;
            iv.end -= offsetSec;
        }
    } else {
        // by_ayah: per-verse file, words already 0-anchored; the clip end is the
        // occasion span end (may include trailing silence past the last word).
        timeEndMs = spanEnd;
    }

    return {
        reciter,
        chapter,
        verse_ref: verseRef,
        audio_url: audioUrl,
        audio_category: audioCategory,
        time_start_ms: timeStartMs,
        time_end_ms: timeEndMs,
        intervals,
        words: wordsOut,
    };
}

/** Distinct verse refs in a chapter, in recitation order (a verse appears once
 *  even when it recurs across multiple occasions). */
export function chapterVerseRefs(shard: TsShardResponse): string[] {
    const seen = new Set<string>();
    const refs: string[] = [];
    for (const o of shardOccasions(shard)) {
        if (!seen.has(o.ref)) {
            seen.add(o.ref);
            refs.push(o.ref);
        }
    }
    return refs;
}

// ---------------------------------------------------------------------------
// Random target picking
// ---------------------------------------------------------------------------

export interface TsRandomTarget {
    reciter: string;
    chapter: number;
    verseRef: string;
}

/**
 * Pick a random `(reciter, chapter, verseRef)` from the manifest plus a
 * peek at one shard. The "any-reciter" form picks a reciter at random;
 * the "same-reciter" form pins to `reciter`.
 *
 * Returns null when the manifest has no eligible reciters (e.g. empty
 * local data tree). Caller is responsible for displaying a user-facing
 * empty state.
 *
 * Note: pre-rolling for lookahead requires fetching the resulting
 * shard so the verseRef list is known. The random target therefore
 * resolves only after the chosen shard is loaded.
 */
const RANDOM_TARGET_MAX_TRIES = 5;

export async function getRandomTarget(opts: { reciter?: string } = {}): Promise<TsRandomTarget | null> {
    const m = await loadManifest();
    const reciters = m.reciters ?? {};
    const slugs = Object.keys(reciters);
    if (slugs.length === 0) return null;

    const reciter = opts.reciter ?? slugs[Math.floor(Math.random() * slugs.length)]!;
    const block = reciters[reciter];
    const blockChapters = block?.ts_chapters ?? [];
    if (!block || blockChapters.length === 0) return null;

    // Retry on shard 404 / empty-shard so a single stale manifest entry (e.g.
    // a chapter listed in `ts_chapters` whose shard file vanished from the
    // bucket between manifest build and this fetch) doesn't break the random
    // button. Each retry picks a different unseen chapter.
    const tried = new Set<number>();
    for (let i = 0; i < RANDOM_TARGET_MAX_TRIES; i++) {
        const remaining = blockChapters.filter((c) => !tried.has(c));
        if (remaining.length === 0) return null;
        const chapter = remaining[Math.floor(Math.random() * remaining.length)]!;
        tried.add(chapter);
        try {
            const shard = await loadChapterShard(reciter, chapter);
            const refs = chapterVerseRefs(shard);
            if (refs.length === 0) continue;
            const verseRef = refs[Math.floor(Math.random() * refs.length)]!;
            return { reciter, chapter, verseRef };
        } catch (e) {
            if (e instanceof ApiError && e.status === 404) continue;
            throw e;
        }
    }
    return null;
}

// ---------------------------------------------------------------------------
// Test seam — clears all module-level caches so unit tests stay isolated.
// ---------------------------------------------------------------------------

export function _resetForTests(): void {
    _config = null;
    _manifest = null;
    _qpc = null;
    _qpcVerseIndex = null;
    _dk = null;
    _shards.clear();
    _vbrChapters.clear();
}
