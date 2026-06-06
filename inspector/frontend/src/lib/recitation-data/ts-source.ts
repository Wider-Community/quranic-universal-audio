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
 * raw, in recitation order). `assembleVerseFromShard` reduces a verse to its
 * canonical (completing) occasion via `occasion-dedup`; `verseOccasionsFromShard`
 * exposes all occasions for the (deferred) loopback filmstrip.
 */

import { ApiError, fetchArrayBuffer, fetchJson } from '../api';
import type {
    TsConfigResponse,
    TsManifestResponse,
    TsShardResponse,
    TsVbrResponse,
} from '../types/api';
import type { Letter, PhonemeInterval, TsVerseData, TsWord } from '../types/domain';
import type { TsValidationDoc } from '../types/generated/schemas';

import {
    type VerseOccasions,
    canonicalClip,
    groupVerseOccasions,
    maxWordIndex,
} from './occasion-dedup';

// ---------------------------------------------------------------------------
// Singleton caches
// ---------------------------------------------------------------------------

let _config: Promise<TsConfigResponse> | null = null;
let _manifest: Promise<TsManifestResponse> | null = null;
let _qpc: Promise<Record<string, { text?: string }>> | null = null;
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
    /** Templated audio URL with `{surah:03d}` / `{ayah:03d}` placeholders. Empty
     *  string when the audio manifest can't be expressed as a single template. */
    url_template: string;
    /** Short form (`'by_surah'` / `'by_ayah'`) — the contract the FE drives
     *  audio routing + offset logic from. */
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
    return {
        url_template: block.url_template ?? '',
        audio_category: block.audio_category,
    };
}

/**
 * Resolve the audio URL for `(surah, ayah)` from the manifest's `url_template`.
 *
 * `url_template` carries `{surah:03d}` / `{ayah:03d}` placeholders for by_ayah
 * reciters and just `{surah:03d}` for by_surah; protocol-less templates get an
 * `https://` prefix. Returns the empty string when the template is empty — caller
 * must NOT push that into an `<audio>` element (browser resolves "" to the page
 * URL and errors).
 */
export function resolveAudioUrl(
    urlTemplate: string,
    surah: number,
    ayah: number,
): string {
    if (!urlTemplate) return '';
    const httpsTmpl = /^https?:\/\//i.test(urlTemplate) ? urlTemplate : `https://${urlTemplate}`;
    return httpsTmpl
        .replace(/\{surah:03d\}/g, String(surah).padStart(3, '0'))
        .replace(/\{ayah:03d\}/g, String(ayah).padStart(3, '0'))
        .replace(/\{surah\}/g, String(surah))
        .replace(/\{ayah\}/g, String(ayah));
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

/** Per-shard memo of `groupVerseOccasions` keyed by verse ref. The grouping
 *  cost is O(segments) per chapter; callers iterate every verse of a chapter,
 *  so memoizing on the (LRU-stable) shard object turns O(verses²) into O(1)
 *  lookups after the first build. */
const _occasionsByShard = new WeakMap<TsShardResponse, Map<string, VerseOccasions>>();

function shardOccasions(shard: TsShardResponse): Map<string, VerseOccasions> {
    let index = _occasionsByShard.get(shard);
    if (!index) {
        index = new Map();
        for (const g of groupVerseOccasions(shard.segments ?? [])) index.set(g.ref, g);
        _occasionsByShard.set(shard, index);
    }
    return index;
}

/**
 * Build the `TsVerseData` payload for one verse from a chapter's segment array.
 *
 * The shard stores every recited segment raw, in recitation order; a verse may
 * recur across several entries (loopbacks, re-dos). This selects the canonical
 * (completing) occasion via {@link groupVerseOccasions} / {@link canonicalClip}
 * — mirroring the backend `project_segment_shard` rule — then assembles its
 * words with QPC / DK text and the `by_surah_audio` offset adjustment that
 * subtracts the verse's start so the audio element starts at zero.
 *
 * Identity flows top-down: the caller knows which slug it fetched `shard` for
 * (it's in the URL), so `reciter` is a param and rides back on the result.
 *
 * Audio routing (`audio_url` + `audio_category`) is sourced from `reciterAudio`
 * — the manifest's reciter block, the live source — never from the shard.
 */
export function assembleVerseFromShard(
    reciter: string,
    shard: TsShardResponse,
    verseRef: string,
    qpc: Record<string, { text?: string }>,
    dk: Record<string, { text?: string }>,
    reciterAudio: TsReciterAudio,
): TsVerseData | null {
    if (verseRef === '_meta') return null;

    const verseSegs = (shard.segments ?? []).filter((s) => s.ref === verseRef);
    if (verseSegs.length === 0) return null;

    const chapter = parseInt(verseRef.split(':')[0] ?? '0', 10);

    // Pick the canonical occasion's words + clip span (completion-based dedup).
    // Grouping runs against the FULL chapter (memoized per shard) so interleaving
    // from other verses correctly splits a re-recited verse into occasions.
    const nWords = maxWordIndex(verseSegs);
    const grouped = shardOccasions(shard).get(verseRef);
    const occasion = grouped?.canonical ?? verseSegs;
    const clip = canonicalClip(occasion, nWords);
    const wordsRaw = clip.words;

    const intervals: PhonemeInterval[] = [];
    const wordsOut: TsWord[] = [];

    for (const w of wordsRaw) {
        const wordIdx = w[0];
        const wStart = w[1] / 1000;
        const wEnd = w[2] / 1000;
        const lettersRaw = (w[3] ?? []) as Array<[string, number | null, number | null]>;
        const phonesRaw = (w[4] ?? []) as Array<(string | number | boolean)[]>;

        const location = `${verseRef}:${wordIdx}`;
        const text = qpc[location]?.text ?? '';
        const displayText = dk[location]?.text ?? text;

        const letters: Letter[] = lettersRaw.map((lt) => ({
            char: lt[0],
            start: lt[1] === null ? null : lt[1] / 1000,
            end: lt[2] === null ? null : lt[2] / 1000,
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

        wordsOut.push({
            location, text, display_text: displayText,
            start: wStart, end: wEnd, phoneme_indices: phonemeIndices, letters,
        });
    }

    // Audio URL — template comes from the manifest's reciter block (live).
    const surahNum = chapter;
    const ayahNum = parseInt(verseRef.split(':')[1] ?? '0', 10);
    const audioUrl = resolveAudioUrl(reciterAudio.url_template, surahNum, ayahNum);

    // The TsVerseData type expects the long form ("by_*_audio") — the manifest
    // carries the short form. Map here.
    const audioCategory: 'by_ayah_audio' | 'by_surah_audio' =
        reciterAudio.audio_category === 'by_surah' ? 'by_surah_audio' : 'by_ayah_audio';

    let timeStartMs = 0;
    let timeEndMs = 0;

    // Clip bounds come from the canonical occasion's segment span — the
    // contiguous `[start, end]` the dataset publishes (segmenter's natural
    // lead-in / trailing silence included). Audio plays through the silence with
    // no word/letter highlighted — that's expected.
    if (audioCategory === 'by_surah_audio') {
        if (wordsRaw.length > 0) {
            const wordStart = wordsRaw[0]![1];
            const wordEnd = wordsRaw.reduce(
                (m, w) => (w[2] > m ? w[2] : m), wordsRaw[0]![2]);
            timeStartMs = Math.min(clip.startMs, wordStart);
            timeEndMs = Math.max(clip.endMs, wordEnd);
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
        }
    } else {
        // by_ayah: per-verse file, words already 0-anchored. Clip end is the
        // segment span end (which can include trailing silence past the last word).
        timeEndMs = clip.endMs > 0
            ? clip.endMs
            : (intervals.length > 0
                ? Math.round(intervals[intervals.length - 1]!.end * 1000)
                : (wordsRaw.length > 0
                    ? wordsRaw.reduce((m, w) => (w[2] > m ? w[2] : m), wordsRaw[0]![2])
                    : 0));
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
 *  even when it recurs across multiple segments). */
export function chapterVerseRefs(shard: TsShardResponse): string[] {
    return [...shardOccasions(shard).keys()];
}

/** Recitation-ordered occasions per verse for the chapter — every take a verse
 *  was recited (loopbacks / re-dos), in playback order. Feeds the (deferred)
 *  loopback filmstrip; the default per-verse clip uses `g.canonical`. */
export function verseOccasionsFromShard(shard: TsShardResponse): VerseOccasions[] {
    return [...shardOccasions(shard).values()];
}

/** A single recited span of one word, chapter-absolute, in seconds. */
export interface OccasionInterval {
    /** "surah:ayah:word". */
    location: string;
    start: number;
    end: number;
}

/**
 * Every word's recited span across ALL occasions of every verse, chapter-
 * absolute (seconds). The canonical occasion is included alongside the
 * loopbacks / re-dos, so the full-chapter player can cover the entire audio
 * timeline — the recited highlight travels back into a re-recited verse instead
 * of freezing on the canonical-only span.
 *
 * Geometry / text still come from the canonical occasion (via
 * `assembleVerseFromShard`); this only supplies the extra `intervals` the
 * recitation locator (`findActiveAt`) matches against. Words are keyed by
 * location so the chapter builder folds them onto the matching deduped unit.
 */
export function chapterOccasionIntervals(shard: TsShardResponse): OccasionInterval[] {
    const out: OccasionInterval[] = [];
    for (const g of shardOccasions(shard).values()) {
        for (const occasion of g.occasions) {
            for (const seg of occasion) {
                for (const w of seg.words) {
                    out.push({
                        location: `${g.ref}:${w[0]}`,
                        start: w[1] / 1000,
                        end: w[2] / 1000,
                    });
                }
            }
        }
    }
    return out;
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
    const slugs = Object.keys(m.reciters);
    if (slugs.length === 0) return null;

    const reciter = opts.reciter ?? slugs[Math.floor(Math.random() * slugs.length)]!;
    const block = m.reciters[reciter];
    if (!block || block.ts_chapters.length === 0) return null;

    // Retry on shard 404 / empty-shard so a single stale manifest entry (e.g.
    // a chapter listed in `ts_chapters` whose shard file vanished from the
    // bucket between manifest build and this fetch) doesn't break the random
    // button. Each retry picks a different unseen chapter.
    const tried = new Set<number>();
    for (let i = 0; i < RANDOM_TARGET_MAX_TRIES; i++) {
        const remaining = block.ts_chapters.filter((c) => !tried.has(c));
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
    _dk = null;
    _shards.clear();
    _vbrChapters.clear();
}
