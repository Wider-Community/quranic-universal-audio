/**
 * Timestamps tab — client-side data layer for the shard-fetch model.
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
 * Verse assembly is a port of the deleted server-side
 * `services/ts_query.py::get_verse_data` — same output shape as the
 * legacy `/api/ts/data/<reciter>/<verse>` payload.
 */

import { ApiError, fetchArrayBuffer, fetchJson } from '../../../lib/api';
import type {
    TsCatalogResponse,
    TsConfigResponse,
    TsDataResponse,
    TsManifestResponse,
    TsShardResponse,
    TsShardWord,
    TsVbrResponse,
} from '../../../lib/types/api';
import type { Letter, PhonemeInterval, TsVerseData, TsWord } from '../../../lib/types/domain';

// ---------------------------------------------------------------------------
// Singleton caches
// ---------------------------------------------------------------------------

let _config: Promise<TsConfigResponse> | null = null;
let _catalog: Promise<TsCatalogResponse> | null = null;
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
 * Fetch the v2 reciter catalog once. Resolves with the parsed body — schema
 * matches {@link TsCatalogResponse}. Cached forever client-side; the backend
 * already serves a short ``Cache-Control: max-age=300`` so cross-tab catalog
 * edits propagate within a few minutes anyway.
 *
 * URL comes from ``tsConfig.catalog_url`` (set on every Inspector build that
 * has D20 Track B). The legacy ``loadManifest()`` path still feeds chapter
 * lists / VBR / validation / resources — this only displaces the reciter
 * dropdown source.
 */
export async function loadCatalog(): Promise<TsCatalogResponse> {
    if (!_catalog) {
        _catalog = (async () => {
            const cfg = await loadConfig();
            const url = cfg.catalog_url;
            if (!url) {
                throw new Error('TS config missing catalog_url — backend predates D20 Track B.');
            }
            return fetchJson<TsCatalogResponse>(url);
        })();
    }
    return _catalog;
}

/** Per-delivery dropdown entry derived from a catalog snapshot.
 *
 * Joins ``catalog.reciters[]`` (display name) against ``catalog.deliveries[]``
 * (slug, riwayah, style, audio_category) so every row carries the labels the
 * existing UI renders without forcing consumers to walk both arrays
 * themselves. One row per delivery — current Timestamps UX is a flat list,
 * not the Reciter→Mushaf→Source three-tier UX Track A introduces. */
export interface TsCatalogReciterRow {
    slug: string;
    reciter_id: string;
    name_en: string;
    name_ar: string | null;
    riwayah: string;
    style: string;
    source: string;
    audio_category: 'by_surah' | 'by_ayah';
}

/** Build the flat reciter-dropdown list from a catalog snapshot. */
export function catalogReciterRows(catalog: TsCatalogResponse): TsCatalogReciterRow[] {
    const byId = new Map(catalog.reciters.map((r) => [r.reciter_id, r]));
    const rows: TsCatalogReciterRow[] = [];
    for (const d of catalog.deliveries) {
        const r = byId.get(d.reciter_id);
        if (!r) continue; // FK invariant guaranteed by the pydantic model; skip defensively.
        rows.push({
            slug: d.slug,
            reciter_id: d.reciter_id,
            name_en: r.name_en,
            name_ar: r.name_ar ?? null,
            riwayah: d.riwayah,
            style: d.style,
            source: d.source,
            audio_category: d.audio_category,
        });
    }
    return rows;
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
 * locations (handles cross-verse compound segments — usually 1 ayah, sometimes
 * 2). Per-ayah results are merged and cached. A failed ayah fetch is skipped
 * (its words simply render no gloss) rather than failing the whole verse.
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
 * Templated audio URL for `(surah, ayah)` against a shard's `_meta`.
 *
 * `url_template` carries `{surah:03d}` / `{ayah:03d}` placeholders for
 * by_ayah reciters and just `{surah:03d}` for by_surah. Empty template
 * falls back to per-verse `audio_urls` keyed `"<surah>:<ayah>"` (by_ayah)
 * or `"<surah>"` (by_surah).
 */
export function audioUrlFor(
    meta: TsShardResponse['_meta'],
    surah: number,
    ayah: number,
): string {
    const tmpl = meta.url_template;
    if (tmpl) {
        const httpsTmpl = /^https?:\/\//i.test(tmpl) ? tmpl : `https://${tmpl}`;
        return httpsTmpl
            .replace(/\{surah:03d\}/g, String(surah).padStart(3, '0'))
            .replace(/\{ayah:03d\}/g, String(ayah).padStart(3, '0'))
            .replace(/\{surah\}/g, String(surah))
            .replace(/\{ayah\}/g, String(ayah));
    }
    const fallback = meta.audio_urls;
    if (!fallback) return '';
    return (
        fallback[`${surah}:${ayah}`]
        ?? fallback[String(surah)]
        ?? ''
    );
}

/**
 * Pure port of `inspector/services/ts_query.py:get_verse_data`.
 *
 * Builds the full `TsVerseData` payload from a shard verse row plus
 * QPC / DK lookups. Handles compound refs (`"37:151:3-37:152:2"`) and
 * the `by_surah_audio` offset adjustment that subtracts the verse's
 * start time so the audio element starts at zero.
 */
/**
 * Identity flows top-down. The caller already knows which slug it fetched
 * `shard` for (it's in the URL), so we take `reciter` as a param and return
 * it on the result. The shard's `_meta.reciter` is ignored for identity —
 * it can drift from the bucket folder slug (pre-cutover legacy slugs are
 * still embedded in some `timestamps_full.json` sources) and trusting it
 * silently breaks every manifest-lookup downstream.
 */
export function assembleVerseFromShard(
    reciter: string,
    shard: TsShardResponse,
    verseRef: string,
    qpc: Record<string, { text?: string }>,
    dk: Record<string, { text?: string }>,
): TsVerseData | null {
    const verse = shard[verseRef];
    if (!verse || verseRef === '_meta') return null;

    const meta = shard._meta as TsShardResponse['_meta'];
    const wordsRaw: TsShardWord[] = Array.isArray(verse)
        ? verse as TsShardWord[]
        : ((verse as { words: TsShardWord[] }).words ?? []);
    const chapter = parseInt(verseRef.split(':')[0] ?? '0', 10);

    const isCompound = verseRef.includes('-');
    let compoundSurah = 0;
    let compoundStartAyah = 0;
    let compoundEndAyah = 0;
    if (isCompound) {
        const [startPart, endPart] = verseRef.split('-', 2);
        const sp = (startPart ?? '').split(':');
        const ep = (endPart ?? '').split(':');
        compoundSurah = parseInt(sp[0] ?? '0', 10);
        compoundStartAyah = parseInt(sp[1] ?? '0', 10);
        compoundEndAyah = parseInt(ep[1] ?? '0', 10);
    }

    const intervals: PhonemeInterval[] = [];
    const wordsOut: TsWord[] = [];
    let curAyah = isCompound ? compoundStartAyah : 0;
    let prevWordIdx = -1;

    for (const w of wordsRaw) {
        const wordIdx = w[0];
        const wStart = w[1] / 1000;
        const wEnd = w[2] / 1000;
        const lettersRaw = (w[3] ?? []) as Array<[string, number | null, number | null]>;
        const phonesRaw = (w[4] ?? []) as Array<(string | number | boolean)[]>;

        let location: string;
        if (isCompound) {
            if (prevWordIdx >= 0 && wordIdx <= prevWordIdx && curAyah < compoundEndAyah) {
                curAyah += 1;
            }
            location = `${compoundSurah}:${curAyah}:${wordIdx}`;
            prevWordIdx = wordIdx;
        } else {
            location = `${verseRef}:${wordIdx}`;
        }
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

    // Audio URL — derived from shard `_meta` (template or fallback map).
    const surahNum = isCompound ? compoundSurah : chapter;
    const ayahNum = isCompound
        ? compoundStartAyah
        : parseInt(verseRef.split(':')[1] ?? '0', 10);
    const audioUrl = audioUrlFor(meta, surahNum, ayahNum);

    // The TsVerseData type expects the long form ("by_*_audio"); the shard
    // stores the short form. Map here.
    const audioCategory: 'by_ayah_audio' | 'by_surah_audio' =
        meta.audio_category === 'by_surah' ? 'by_surah_audio' : 'by_ayah_audio';

    let timeStartMs = 0;
    let timeEndMs = 0;

    // Prefer seg-based `verse_start_ms` / `verse_end_ms` from the shard so
    // the inspector's clip matches what the dataset publishes (segmenter's
    // natural lead-in / trailing silence included). Audio plays through the
    // silence with no word/letter highlighted — that's expected. When the
    // shard predates seg bounds, fall back to MFA word bounds.
    const shardVerse = (verse && typeof verse === 'object' && !Array.isArray(verse))
        ? (verse as Record<string, unknown>)
        : null;
    const seg_start_ms = typeof shardVerse?.verse_start_ms === 'number'
        ? shardVerse.verse_start_ms : null;
    const seg_end_ms = typeof shardVerse?.verse_end_ms === 'number'
        ? shardVerse.verse_end_ms : null;

    if (audioCategory === 'by_surah_audio') {
        if (wordsRaw.length > 0) {
            const wordStart = wordsRaw[0]![1];
            const wordEnd = wordsRaw.reduce(
                (m, w) => (w[2] > m ? w[2] : m), wordsRaw[0]![2]);
            timeStartMs = seg_start_ms !== null
                ? Math.min(seg_start_ms, wordStart)
                : wordStart;
            timeEndMs = seg_end_ms !== null
                ? Math.max(seg_end_ms, wordEnd)
                : wordEnd;
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
    } else if (seg_end_ms !== null) {
        timeEndMs = seg_end_ms;
    } else if (intervals.length > 0) {
        timeEndMs = Math.round(intervals[intervals.length - 1]!.end * 1000);
    } else if (wordsRaw.length > 0) {
        timeEndMs = wordsRaw.reduce(
            (m, w) => (w[2] > m ? w[2] : m), wordsRaw[0]![2]);
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

/** List the verse refs belonging to a chapter, in canonical sort order. */
export function chapterVerseRefs(shard: TsShardResponse): string[] {
    return Object.keys(shard).filter((k) => k !== '_meta');
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
    _catalog = null;
    _manifest = null;
    _qpc = null;
    _dk = null;
    _shards.clear();
    _vbrChapters.clear();
}
