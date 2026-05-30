<script lang="ts">
    /**
     * TimestampsTab — composition shell for the Timestamps tab.
     *
     * Owns:
     *   - Reciter/chapter/verse cascade (manifest fetch + shard slice + store writes).
     *   - Config fetch → CSS custom-property bindings on the root div.
     *   - Lookahead pre-rolls (`nextRandomSame` / `nextRandomAny`) for instant random.
     *   - Autoplay-on-active-tab on first load.
     *   - Delegating to subcomponents: TimestampsControls, TimestampsAudio,
     *     TimestampsKeyboard, TimestampsShortcutsGuide.
     *   - Passing display-update callbacks to UnifiedDisplay / AnimationDisplay /
     *     TimestampsWaveform (imperative 60fps highlight path).
     */

    import { onMount } from 'svelte';
    import { get } from 'svelte/store';

    import { consumeWarm, recycleAsShadow, shadowPrewarm } from '../../lib/playback/shadow-audio';
    import {
        addBookmark,
        bookmarks,
        isBookmarked,
        removeBookmark,
    } from '../../lib/stores/bookmarks';
    import { hasCapability } from '../../lib/stores/capabilities';
    import { currentUser } from '../../lib/stores/current-user';
    import { pendingTsNavigation } from '../../lib/stores/navigation';
    import type { TsConfigResponse, TsDataResponse } from '../../lib/types/api';
    import type { TsReciter } from '../../lib/types/domain';
    import { getActiveTab } from '../../lib/utils/active-tab';
    import { LS_KEYS } from '../../lib/utils/constants';
    import { ensureChapterPeaks } from '../../lib/utils/peaks-fetch';
    import { surahInfoReady } from '../../lib/utils/surah-info';
    import AnimationDisplay from './components/AnimationDisplay.svelte';
    import TimestampsAudio from './components/TimestampsAudio.svelte';
    import TimestampsControls from './components/TimestampsControls.svelte';
    import TimestampsKeyboard from './components/TimestampsKeyboard.svelte';
    import TimestampsShortcutsGuide from './components/TimestampsShortcutsGuide.svelte';
    import TimestampsViewControls from './components/TimestampsViewControls.svelte';
    import TimestampsWaveform from './components/TimestampsWaveform.svelte';
    import TsValidationPanel from './components/TsValidationPanel.svelte';
    import UnifiedDisplay from './components/UnifiedDisplay.svelte';
    import {
        assembleVerseFromShard,
        catalogReciterRows,
        chapterVerseRefs,
        getRandomTarget,
        loadCatalog,
        loadChapterShard,
        loadConfig,
        loadDk,
        loadManifest,
        loadQpc,
        loadTsValidation,
        loadVbrChapters,
        loadVerseTranslations,
        reciterAudioFromManifest,
        resolveAudioUrl,
        tsPlayUrl,
    } from './services/ts_client';
    import {
        granularity,
        showLetters,
        showPhonemes,
        showTranslations,
        translationLanguage,
        TS_GRANULARITIES,
        TS_VIEW_MODES,
        tsConfig,
        verseTranslations,
        viewMode,
    } from './stores/display';
    import { tsLoading } from './stores/loading';
    import {
        autoAdvancing,
        currentTime,
        loopTarget,
        tsAudioElement,
        tsPort,
        tsVbrChapters,
    } from './stores/playback';
    import { tsValidation } from './stores/validation';
    import {
        chapters,
        loadedVerse,
        reciters,
        selectedChapter,
        selectedReciter,
        selectedVerse,
        type TsVerseOption,
        verses,
    } from './stores/verse';
    import { setupZoomLifecycle } from './utils/zoom';

    // ---- Local display constants ----
    const TS_EASING_NONE = 'none';
    const TS_EASING_DEFAULT = 'linear';
    const TS_UNIFIED_DISPLAY_MAX_HEIGHT_PX = 800;

    // ---- Component refs ----
    let audioComp: TimestampsAudio;
    let controlsComp: TimestampsControls;
    let viewControlsComp: TimestampsViewControls;
    let unifiedEl: UnifiedDisplay;
    let animDisplayEl: AnimationDisplay;
    let waveformTabEl: TimestampsWaveform;

    // ---- Lookahead pre-rolls ----
    // Each pre-roll is the (reciter, chapter, verseRef) we'd jump to on the
    // matching random click. The shard is already in ts_client's LRU because
    // getRandomTarget loaded it during the pre-roll. Consuming a pre-roll is
    // therefore a dict-lookup-fast operation.
    let nextRandomSame: { reciter: string; chapter: number; verseRef: string } | null = null;
    let nextRandomAny: { reciter: string; chapter: number; verseRef: string } | null = null;

    // ---------------------------------------------------------------------
    // Initial load
    // ---------------------------------------------------------------------

    async function init(): Promise<void> {
        loadConfig().then((cfg) => tsConfig.set(cfg as TsConfigResponse));

        // Prefetch the ~3MB word-text dicts at mount, concurrent with the
        // manifest/catalog/surah-info loads. They're shared immutable reference
        // data (same for every reciter/verse) — loaded once in the background
        // here and browser-cached, so verse loads hit a warm cache rather than
        // the user paying the download on a click.
        void loadQpc().catch(() => {});
        void loadDk().catch(() => {});

        const savedView = localStorage.getItem(LS_KEYS.TS_VIEW_MODE);
        if (savedView === TS_VIEW_MODES.ANALYSIS || savedView === TS_VIEW_MODES.ANIMATION) {
            viewMode.set(savedView);
            if (savedView === TS_VIEW_MODES.ANALYSIS) {
                const sL = localStorage.getItem(LS_KEYS.TS_SHOW_LETTERS);
                const sP = localStorage.getItem(LS_KEYS.TS_SHOW_PHONEMES);
                if (sL !== null) showLetters.set(sL === 'true');
                if (sP !== null) showPhonemes.set(sP === 'true');
            } else {
                const sG = localStorage.getItem(LS_KEYS.TS_GRANULARITY);
                if (sG === TS_GRANULARITIES.WORDS || sG === TS_GRANULARITIES.CHARACTERS) {
                    granularity.set(sG);
                }
            }
        }

        // Translation prefs are independent of view mode (the toggle only
        // surfaces in Analysis, but the saved choice hydrates regardless).
        const sT = localStorage.getItem(LS_KEYS.TS_SHOW_TRANSLATIONS);
        if (sT !== null) showTranslations.set(sT === 'true');
        const sLang = localStorage.getItem(LS_KEYS.TS_TRANSLATION_LANG);
        if (sLang) translationLanguage.set(sLang);

        await surahInfoReady;
        await loadReciters();

        // A bookmark click (pendingTsNavigation) owns the first verse load —
        // skip the random auto-pick so we don't load a verse then immediately
        // replace it. The reactive consumer below handles the actual load.
        if (navHandled || get(pendingTsNavigation)) return;

        // Autoplay on first load only when this tab is the active one — a
        // browser deep-link or refresh while the Segments tab is up should
        // still start paused. The eventual audio.play() is wrapped so a
        // policy denial leaves the UI primed-paused without console noise.
        const autoplay = getActiveTab() === 'timestamps';

        // First-load auto-pick: if we have a persisted reciter, let the
        // reciter-change path auto-load a random verse from it. Otherwise
        // load a random verse from any reciter.
        const savedReciter = localStorage.getItem(LS_KEYS.TS_RECITER);
        const rs = get(reciters);
        const validSaved = savedReciter && rs.some((r) => r.slug === savedReciter)
            ? savedReciter
            : null;
        if (!validSaved && savedReciter) {
            // Drop the stale slug so we don't keep hammering 404 endpoints
            // every reload. The user picks a fresh reciter from the list.
            localStorage.removeItem(LS_KEYS.TS_RECITER);
        }
        if (validSaved) {
            selectedReciter.set(validSaved);
            await onReciterChange(validSaved, autoplay);
        } else {
            await loadRandomTimestamp(null, autoplay);
        }
    }

    async function loadReciters(): Promise<void> {
        // D20 Track B: the catalog endpoint enriches names; the manifest is
        // the source of truth for which reciters actually have published
        // timestamps in the bucket. Intersect against manifest reciter keys
        // so the dropdown only lists reciters the user can actually play.
        try {
            const cfg = await loadConfig();
            if (cfg.catalog_url) {
                const [catalog, manifest] = await Promise.all([
                    loadCatalog(),
                    loadManifest(),
                ]);
                const ready = new Set(Object.keys(manifest.reciters));
                const rs: TsReciter[] = catalogReciterRows(catalog)
                    .filter((row) => ready.has(row.slug))
                    .map((row) => ({
                        slug: row.slug,
                        name: row.name_en,
                        audio_source: row.source,
                    }));
                rs.sort((a, b) => a.name.localeCompare(b.name));
                reciters.set(rs);
                return;
            }
        } catch (e) {
            console.warn('Catalog load failed; falling back to manifest:', e);
        }

        try {
            const m = await loadManifest();
            const rs: TsReciter[] = Object.entries(m.reciters).map(([slug, b]) => ({
                slug,
                name: b.name_en,
                audio_source: b.source ?? '',
            }));
            // Sort by display name for deterministic dropdown order.
            rs.sort((a, b) => a.name.localeCompare(b.name));
            reciters.set(rs);
        } catch (e) {
            console.error('Error loading manifest:', e);
        }
    }

    // ---------------------------------------------------------------------
    // Reciter / chapter / verse cascade
    // ---------------------------------------------------------------------

    async function onReciterChange(reciter: string, autoplayOverride?: boolean): Promise<void> {
        if (reciter) localStorage.setItem(LS_KEYS.TS_RECITER, reciter);
        chapters.set([]);
        selectedChapter.set('');
        verses.set([]);
        selectedVerse.set('');
        clearDisplay();
        tsVbrChapters.set(new Set());
        tsValidation.set(null);
        if (!reciter) return;

        // Owner + maintainer only: load verse-level ts-validation flags.
        // Gated on the capability so public users never trigger the bucket
        // read on the single worker (the server 403s them anyway).
        if (hasCapability(get(currentUser), 'timestamps.view_validation')) {
            void loadTsValidation(reciter).then((doc) => {
                // Ignore a stale response if the reciter changed mid-flight.
                if (get(selectedReciter) === reciter) tsValidation.set(doc);
            });
        }

        try {
            const m = await loadManifest();
            const block = m.reciters[reciter];
            if (block) {
                chapters.set(block.ts_chapters);
            }
        } catch (e) {
            console.error('Error reading manifest for reciter:', e);
        }

        // Auto-load a random verse from this reciter so the tab always has
        // something on screen after a reciter change.
        await loadRandomTimestamp(reciter, autoplayOverride ?? false);
    }

    async function onChapterChange(chapter: string): Promise<void> {
        verses.set([]);
        selectedVerse.set('');
        clearDisplay();
        const reciter = get(selectedReciter);
        if (!reciter || !chapter) return;
        await populateVersesFor(reciter, parseInt(chapter, 10));
    }

    /** Populate the verses store from a chapter shard. Caches on ts_client's
     *  shard LRU so subsequent verse picks within the chapter are free.
     *
     *  ``audio_url`` is derived from the MANIFEST's reciter block, not the
     *  shard's `_meta.url_template` (stale on shards baked before the audio
     *  manifest landed); the shard's `_meta.audio_urls` rides as last-resort
     *  per-verse fallback when no template applies. */
    async function populateVersesFor(reciter: string, chapter: number): Promise<void> {
        try {
            const [shard, manifest] = await Promise.all([
                loadChapterShard(reciter, chapter),
                loadManifest(),
            ]);
            const reciterAudio = reciterAudioFromManifest(manifest, reciter);
            const meta = shard._meta;
            const refs = chapterVerseRefs(shard);
            const opts: TsVerseOption[] = refs.map((ref) => {
                const [s, a] = ref.split('-', 1)[0]!.split(':');
                const surahN = parseInt(s ?? '0', 10);
                const ayahN = parseInt(a ?? '0', 10);
                const audio_url = reciterAudio
                    ? resolveAudioUrl(reciterAudio.url_template, meta.audio_urls, surahN, ayahN)
                    : '';
                return { ref, audio_url };
            });
            verses.set(opts);
        } catch (e) {
            console.error('Error loading chapter shard:', e);
            verses.set([]);
        }
    }

    async function onVerseChange(verseRef: string): Promise<void> {
        const reciter = get(selectedReciter);
        const chapter = get(selectedChapter);
        if (!reciter || !chapter || verseRef === '') return;
        await loadTimestampVerse(reciter, parseInt(chapter, 10), verseRef);
    }

    /** Jump the cascade to a ts-validation-flagged verse (may switch chapter). */
    async function jumpToFlaggedVerse(verseKey: string): Promise<void> {
        const reciter = get(selectedReciter);
        const surah = parseInt(verseKey.split(':')[0] ?? '0', 10);
        if (!reciter || !surah) return;
        if (get(selectedChapter) !== String(surah)) {
            selectedChapter.set(String(surah));
            await populateVersesFor(reciter, surah);
        }
        selectedVerse.set(verseKey);
        await loadTimestampVerse(reciter, surah, verseKey);
    }

    async function loadTimestampVerse(
        reciter: string,
        chapter: number,
        verseRef: string,
    ): Promise<void> {
        // Single-flight: ignore re-entry while a load is in flight (the old
        // body-level `pointer-events:none` gave this for free; tsLoading now
        // does it locally). Guards keyboard/auto/click paths uniformly.
        if (get(tsLoading)) return;
        tsLoading.set(true);
        try {
            // qpc/dk are prewarmed at mount + browser-cached, so awaiting them
            // here is a warm-cache hit in the steady state; the shard is what
            // actually gates paint. vbr resolves concurrently too. The manifest
            // is also a warm cache here (loaded at mount + cached forever) —
            // we await it to get the authoritative reciter-audio block.
            const [shard, qpc, dk, vbr, manifest] = await Promise.all([
                loadChapterShard(reciter, chapter),
                loadQpc(),
                loadDk(),
                loadVbrChapters(reciter),
                loadManifest(),
            ]);
            const reciterAudio = reciterAudioFromManifest(manifest, reciter);
            if (!reciterAudio) {
                console.error('Manifest missing reciter block:', reciter);
                alert('Failed to load verse');
                return;
            }
            tsVbrChapters.set(new Set(vbr));
            const data = assembleVerseFromShard(reciter, shard, verseRef, qpc, dk, reciterAudio);
            if (!data) {
                alert('Error: verse not found in shard');
                return;
            }
            ingestVerseData(data);
        } catch (e) {
            console.error('Error loading timestamp verse:', e);
            alert('Failed to load verse');
        } finally {
            tsLoading.set(false);
        }
    }

    export async function loadRandomTimestamp(
        reciter: string | null = null,
        autoplay: boolean = true,
    ): Promise<void> {
        if (get(tsLoading)) return; // single-flight (storm guard)
        tsLoading.set(true);
        try {
            await loadRandomTimestampInner(reciter, autoplay);
        } catch (e) {
            console.error('Error loading random timestamp:', e);
        } finally {
            tsLoading.set(false);
            // Refresh both pre-rolls in parallel — fire-and-forget; the cache
            // they leave behind makes the next click instant.
            primePrerolls();
        }
    }

    /** Body of the random load WITHOUT the single-flight guard, so the
     *  bookmark-deep-link path (which already holds tsLoading) can fall back
     *  to it without self-deadlocking on the guard. */
    async function loadRandomTimestampInner(
        reciter: string | null,
        autoplay: boolean,
    ): Promise<void> {
        const target = reciter
            ? consumePreroll('same') ?? await getRandomTarget({ reciter })
            : consumePreroll('any') ?? await getRandomTarget();
        if (!target) {
            console.warn('No timestamp data available');
            return;
        }

        const [shard, qpc, dk, vbr, manifest] = await Promise.all([
            loadChapterShard(target.reciter, target.chapter),
            loadQpc(),
            loadDk(),
            loadVbrChapters(target.reciter),
            loadManifest(),
        ]);
        const reciterAudio = reciterAudioFromManifest(manifest, target.reciter);
        if (!reciterAudio) {
            console.error('Manifest missing reciter block:', target.reciter);
            return;
        }
        tsVbrChapters.set(new Set(vbr));
        const data = assembleVerseFromShard(
            target.reciter, shard, target.verseRef, qpc, dk, reciterAudio,
        );
        if (!data) {
            console.error('Random target verse missing from shard:', target);
            return;
        }

        const reciterChanged = get(selectedReciter) !== data.reciter;
        if (reciterChanged) {
            selectedReciter.set(data.reciter);
            localStorage.setItem(LS_KEYS.TS_RECITER, data.reciter);
            try {
                const m = await loadManifest();
                chapters.set(m.reciters[data.reciter]?.ts_chapters ?? []);
            } catch {
                chapters.set([]);
            }
        }
        if (reciterChanged || get(selectedChapter) !== String(data.chapter)) {
            selectedChapter.set(String(data.chapter));
            await populateVersesFor(data.reciter, data.chapter);
        }

        ingestVerseData(data, autoplay);
    }

    // ---------------------------------------------------------------------
    // Bookmark deep-link: load a SPECIFIC verse with a RANDOM published
    // reciter and autoplay. Mirrors loadRandomTimestamp's reciter/chapter
    // store-setting but pins the verseRef to the bookmarked verse.
    // ---------------------------------------------------------------------

    let navHandled = false;

    function shuffle<T>(arr: T[]): T[] {
        for (let i = arr.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [arr[i], arr[j]] = [arr[j]!, arr[i]!];
        }
        return arr;
    }

    export async function loadVerseRandomReciter(
        surah: number,
        ayah: number,
        autoplay: boolean = true,
    ): Promise<void> {
        if (get(tsLoading)) return; // single-flight
        tsLoading.set(true);
        const verseRef = `${surah}:${ayah}`;
        try {
            const m = await loadManifest();
            const candidates = shuffle(
                Object.keys(m.reciters).filter((slug) =>
                    m.reciters[slug]?.ts_chapters?.includes(surah),
                ),
            );
            const [qpc, dk] = await Promise.all([loadQpc(), loadDk()]);
            for (const reciter of candidates.slice(0, 6)) {
                try {
                    const shard = await loadChapterShard(reciter, surah);
                    if (!chapterVerseRefs(shard).includes(verseRef)) continue;
                    const reciterAudio = reciterAudioFromManifest(m, reciter);
                    if (!reciterAudio) continue;
                    tsVbrChapters.set(new Set(await loadVbrChapters(reciter)));
                    const data = assembleVerseFromShard(
                        reciter, shard, verseRef, qpc, dk, reciterAudio,
                    );
                    if (!data) continue;
                    selectedReciter.set(data.reciter);
                    localStorage.setItem(LS_KEYS.TS_RECITER, data.reciter);
                    chapters.set(m.reciters[data.reciter]?.ts_chapters ?? []);
                    selectedChapter.set(String(data.chapter));
                    await populateVersesFor(data.reciter, data.chapter);
                    ingestVerseData(data, autoplay);
                    return;
                } catch {
                    // Shard 404 / assemble miss — try the next reciter.
                    continue;
                }
            }
            // No published reciter has this exact verse — fall back to random
            // so the tab still shows something rather than an empty state.
            // Use the inner (un-guarded) form: we already hold tsLoading.
            console.warn(`No reciter found for ${verseRef}; falling back to random`);
            await loadRandomTimestampInner(null, autoplay);
        } catch (e) {
            console.error('Error loading bookmarked verse:', e);
        } finally {
            tsLoading.set(false);
            primePrerolls();
        }
    }

    function consumePendingNav(nav: { surah: number; ayah: number; autoplay: boolean }): void {
        navHandled = true;
        pendingTsNavigation.set(null);
        void loadVerseRandomReciter(nav.surah, nav.ayah, nav.autoplay);
    }

    /** Consume the matching pre-roll if it exists, otherwise return null. */
    function consumePreroll(
        kind: 'same' | 'any',
    ): { reciter: string; chapter: number; verseRef: string } | null {
        if (kind === 'same') {
            const r = get(selectedReciter);
            if (nextRandomSame && nextRandomSame.reciter === r) {
                const t = nextRandomSame;
                nextRandomSame = null;
                return t;
            }
            return null;
        }
        const t = nextRandomAny;
        nextRandomAny = null;
        return t;
    }

    /** Re-roll both pre-rolls. Their shards are pre-fetched into the LRU
     *  by `getRandomTarget` itself, so consuming the pre-roll is dict-fast.
     *  Each resolved target ALSO warms its chapter peaks (both kinds) AND
     *  its audio into a slot-specific shadow `<audio>` element, so the
     *  consume path can transplant the already-decoded element into the
     *  visible slot — no second decode pass on the play click. */
    function primePrerolls(): void {
        const reciter = get(selectedReciter) || null;
        if (reciter) {
            getRandomTarget({ reciter })
                .then((t) => { nextRandomSame = t; warmPreroll(t, 'same'); })
                .catch(() => { nextRandomSame = null; });
        } else {
            nextRandomSame = null;
        }
        getRandomTarget()
            .then((t) => { nextRandomAny = t; warmPreroll(t, 'any'); })
            .catch(() => { nextRandomAny = null; });
    }

    /** Fire-and-forget warmers for a pre-roll target. Warms the chapter peaks
     *  (deduped in `ensureChapterPeaks`) and an audio shadow element keyed by
     *  `slot` ('same' = random-current, 'any' = random-any). The shadow
     *  element seeks to the verse start so the decoder warms at the verse
     *  position (not byte 0), making `consumeWarm` on transplant return an
     *  element that's ready to play within a frame. */
    async function warmPreroll(
        t: { reciter: string; chapter: number; verseRef: string } | null,
        slot: 'same' | 'any',
    ): Promise<void> {
        if (!t) return;
        const cur = get(loadedVerse)?.data;
        if (cur && cur.reciter === t.reciter && cur.chapter === t.chapter
            && cur.verse_ref === t.verseRef) {
            return;
        }
        // Peaks: cheap GET-once-per-chapter, cached by reciter:chapter.
        ensureChapterPeaks(t.reciter, t.chapter).catch(() => {});
        try {
            // Shard for the per-verse audio_urls fallback only; url_template +
            // audio_category come from the manifest (warm cache singleton).
            const [shard, manifest] = await Promise.all([
                loadChapterShard(t.reciter, t.chapter),
                loadManifest(),
            ]);
            const reciterAudio = reciterAudioFromManifest(manifest, t.reciter);
            if (!reciterAudio) return;
            const head = t.verseRef.split('-')[0] ?? t.verseRef;
            const [s, a] = head.split(':');
            const surah = parseInt(s ?? '0', 10);
            const ayah = parseInt(a ?? '0', 10);
            const rawUrl = resolveAudioUrl(
                reciterAudio.url_template, shard._meta.audio_urls, surah, ayah,
            );
            if (!rawUrl) return;
            const cat = reciterAudio.audio_category === 'by_surah' ? 'by_surah_audio' : 'by_ayah_audio';
            const playUrl = tsPlayUrl(t.reciter, rawUrl, cat);

            // For by_surah_audio, the playback element starts the verse at the
            // verse's offset within the chapter file. Recompute that offset so
            // the shadow can seek there and warm the decoder at the actual
            // play position. For by_ayah the file IS the verse → seek 0.
            let seekSec = 0;
            if (cat === 'by_surah_audio') {
                const rawRow = shard[t.verseRef] as unknown;
                const isObjRow = !!rawRow && typeof rawRow === 'object' && !Array.isArray(rawRow);
                const objRow = isObjRow ? rawRow as Record<string, unknown> : null;
                const segStartMs = objRow && typeof objRow.verse_start_ms === 'number'
                    ? (objRow.verse_start_ms as number)
                    : null;
                const wordsRaw: unknown[] = Array.isArray(rawRow)
                    ? rawRow
                    : (objRow && Array.isArray(objRow.words) ? objRow.words : []);
                const firstWord = wordsRaw[0];
                const firstWordStart = Array.isArray(firstWord) && typeof firstWord[1] === 'number'
                    ? (firstWord[1] as number)
                    : null;
                const startMs = segStartMs !== null && firstWordStart !== null
                    ? Math.min(segStartMs, firstWordStart)
                    : (segStartMs ?? firstWordStart ?? 0);
                seekSec = startMs / 1000;
            }
            shadowPrewarm(playUrl, { slot, seekSec });
        } catch {
            /* prewarm is best-effort */
        }
    }

    function ingestVerseData(data: TsDataResponse, autoplay: boolean = true): void {
        const tsSegOffset = data.time_start_ms / 1000;
        const tsSegEnd = data.time_end_ms / 1000;

        loadedVerse.set({ data, tsSegOffset, tsSegEnd });
        selectedReciter.set(data.reciter);
        selectedChapter.set(String(data.chapter));
        selectedVerse.set(data.verse_ref);

        // Route per-surah audio through audio-proxy so the bucket-mounted
        // file (deployed NFS or local FUSE auto-mount) is served via
        // sendfile + Range/304. Falls through to a CDN stream-through inside
        // the proxy when the chapter isn't prefetched. Sending the browser
        // straight at the CDN URL wastes the prefetch and bills upstream.
        const playUrl = tsPlayUrl(data.reciter, data.audio_url, data.audio_category);
        const vbr = get(tsVbrChapters).has(data.chapter);
        tsPort.setSource({
            audioUrl: data.audio_url,
            cbrSrc: playUrl,
            reciter: data.reciter,
            vbr,
        });
        // Auto-next reaches here right after AudioRange.`_pauseAndFlush` ramped
        // the gain to 0. The eventual `setRange→_uncut` lifting it back to 1
        // runs in a microtask AFTER `audioComp.load` synchronously kicks off
        // `audio.play()`, so the new verse plays silent for ~5 ms — long
        // enough to look "stuck paused" if the browser also rejects the
        // play() (autoplay policy). Lift the cut on the same tick as the
        // load so the next play() sees gain=1 immediately.
        tsPort.uncut();

        // Element-reuse fast path: if a shadow slot was prewarmed for this
        // URL, transplant the already-decoded element into the visible slot
        // instead of re-loading + re-decoding on the current visible element.
        // VBR plays through the segment-clip endpoint which is per-verse, so
        // the chapter-URL shadow doesn't apply — fall through to the normal
        // load path in that case.
        const warm = !vbr ? consumeWarm(playUrl) : null;
        if (warm && audioComp) {
            adoptWarmElement(warm, playUrl, tsSegOffset, autoplay);
        } else {
            audioComp?.load(playUrl, tsSegOffset, autoplay);
        }
        autoAdvancing.set(false);
        // Verse change invalidates any active loop target.
        loopTarget.set(null);
    }

    /** Swap the visible `<audio>` with a prewarmed shadow element. The shadow
     *  already has `src` loaded and is seeked at (or near) the verse start;
     *  this is the gapless path that avoids the visible element's
     *  load → canplay → seek → decode round trip.
     *
     *  After the swap:
     *    - `tsPort` re-binds DOM listeners to the new element and synthesises
     *      its `_window` so future `loadCovering` short-circuits.
     *    - `tsAudioElement` store updates so reactive consumers (SpeedControl,
     *      waveform interactions) rebind.
     *    - The old visible element is recycled back into the 'any' shadow slot
     *      for the next rotation.
     *
     *  The Svelte `bind:this` references inside `AudioElement.svelte` /
     *  `AudioPlayer.svelte` go stale, but they're only read at mount time
     *  for the initial port attach + onError path. The runtime path goes
     *  through `tsPort` and `tsAudioElement`, both updated here. */
    function adoptWarmElement(
        warmEl: HTMLAudioElement,
        srcUrl: string,
        seekSec: number,
        autoplay: boolean,
    ): void {
        const oldEl = tsPort.element;
        if (!oldEl || !oldEl.parentNode) {
            // Fallback when the visible element isn't in the DOM yet (mount
            // races) — fall through to the normal load path.
            audioComp?.load(srcUrl, seekSec, autoplay);
            return;
        }
        // Mirror the visible element's user-facing attributes before the
        // physical DOM swap so the user sees no flash.
        warmEl.controls = oldEl.controls;
        warmEl.id = oldEl.id;
        // Preserve playback rate so the speed selector stays in sync.
        warmEl.playbackRate = oldEl.playbackRate;
        warmEl.hidden = false;
        warmEl.style.display = '';
        warmEl.removeAttribute('aria-hidden');

        oldEl.pause();
        oldEl.parentNode.replaceChild(warmEl, oldEl);

        // Re-wire the port + reactive consumers. `adoptElement` synthesises a
        // CBR `_window` so `seekAndPlay` doesn't trigger a fresh load.
        tsPort.adoptElement(warmEl, srcUrl);
        tsAudioElement.set(warmEl);

        // Recycle the previously-visible element back into the 'any' slot so
        // the next prewarm has a target. Its Web Audio kill-switch graph (if
        // wired) is preserved via the per-element WeakMap in audio-graph.ts.
        recycleAsShadow(oldEl, 'any');

        if (autoplay) {
            tsPort.seekAndPlay(seekSec * 1000);
        } else {
            tsPort.seek(seekSec * 1000);
        }
        currentTime.set(tsPort.currentTimeMs() / 1000);
    }

    function clearDisplay(): void {
        loadedVerse.set(null);
    }

    // ---------------------------------------------------------------------
    // Nav
    // ---------------------------------------------------------------------

    export function navigateVerse(delta: number): void {
        const vs = get(verses);
        const sel = get(selectedVerse);
        const idx = vs.findIndex((v) => v.ref === sel);
        const newIdx = idx + delta;
        if (newIdx < 0 || newIdx >= vs.length) {
            autoAdvancing.set(false);
            return;
        }
        const next = vs[newIdx];
        if (!next) return;
        selectedVerse.set(next.ref);
        onVerseChange(next.ref);
    }

    // ---------------------------------------------------------------------
    // Highlight tick — called by TimestampsAudio on each rAF frame
    // ---------------------------------------------------------------------

    function onTick(): void {
        if (get(viewMode) === TS_VIEW_MODES.ANIMATION) {
            if (animDisplayEl) animDisplayEl.updateHighlights();
        } else {
            if (unifiedEl) unifiedEl.updateHighlights();
        }
        if (waveformTabEl) waveformTabEl.drawOverlays();
    }

    // ---------------------------------------------------------------------
    // Reactive: CSS vars + nav button state
    // ---------------------------------------------------------------------

    $: cfg = $tsConfig;
    $: highlightColor = cfg?.anim_highlight_color ?? '#f0a500';
    $: wordDur =
        cfg && cfg.anim_transition_easing !== TS_EASING_NONE
            ? `${cfg.anim_word_transition_duration}s`
            : '0s';
    $: charDur =
        cfg && cfg.anim_transition_easing !== TS_EASING_NONE
            ? `${cfg.anim_char_transition_duration}s`
            : '0s';
    $: easing =
        cfg && cfg.anim_transition_easing !== TS_EASING_NONE ? cfg.anim_transition_easing : TS_EASING_DEFAULT;
    $: wordTransition = `opacity ${wordDur} ${easing}`;
    $: charTransition = `opacity ${charDur} ${easing}`;

    $: segmentSelectedIdx = $verses.findIndex((v) => v.ref === $selectedVerse);
    $: prevDisabled = segmentSelectedIdx <= 0;
    $: nextDisabled = segmentSelectedIdx < 0 || segmentSelectedIdx >= $verses.length - 1;

    // Bookmark deep-link consumer: fires on mount (if a click set it before the
    // tab mounted) and on every later bookmark click while the tab stays mounted.
    $: if ($pendingTsNavigation) consumePendingNav($pendingTsNavigation);

    // Current verse → bookmarkable surah:ayah (strip any compound-ref suffix).
    $: currentVerseKey = (() => {
        const ref = $selectedVerse;
        if (!ref) return '';
        const head = ref.split('-')[0] ?? ref;
        const [s, a] = head.split(':');
        const surah = parseInt(s ?? '', 10);
        const ayah = parseInt(a ?? '', 10);
        return surah && ayah ? `${surah}:${ayah}` : '';
    })();
    $: bookmarkedCurrent = currentVerseKey ? isBookmarked($bookmarks, currentVerseKey) : false;

    // Word-by-word translation overlay (Analysis only). Lazily fetch glosses
    // for the loaded verse whenever the toggle/language/verse changes. Async +
    // independent of the audio element — never seeks or pauses, so playback is
    // untouched (mirrors the passive letter/phoneme display). A monotonic token
    // guards against out-of-order responses when the user flips quickly.
    let _trReq = 0;
    $: refreshTranslations($loadedVerse, $showTranslations, $translationLanguage);
    function refreshTranslations(
        lv: typeof $loadedVerse,
        on: boolean,
        lang: string,
    ): void {
        if (!on || !lv || lv.data.words.length === 0) {
            verseTranslations.set({});
            return;
        }
        const token = ++_trReq;
        loadVerseTranslations(lv.data.words, lang)
            .then((map) => {
                if (token === _trReq) verseTranslations.set(map);
            })
            .catch(() => {
                if (token === _trReq) verseTranslations.set({});
            });
    }

    function toggleVerseBookmark(): void {
        if (!currentVerseKey) return;
        if (bookmarkedCurrent) {
            removeBookmark(currentVerseKey);
        } else {
            const [s, a] = currentVerseKey.split(':');
            addBookmark(parseInt(s ?? '', 10), parseInt(a ?? '', 10));
        }
    }

    // ---------------------------------------------------------------------
    // Mount
    // ---------------------------------------------------------------------

    onMount(() => {
        // Wire waveform-zoom reset triggers (loop exit, verse change). Idempotent
        // — internal `_wired` guard makes it safe to call on every mount even if
        // TimestampsTab.svelte ever gets remounted (e.g. tab swap teardown).
        setupZoomLifecycle();
        init();
    });
</script>

<TimestampsKeyboard
    {audioComp}
    on:navigateVerse={(e) => navigateVerse(e.detail)}
    on:randomAny={() => loadRandomTimestamp()}
    on:randomCurrent={() => loadRandomTimestamp(get(selectedReciter) || null)}
    on:setView={(e) => viewControlsComp?.setView(e.detail)}
    on:toggleModeA={() => viewControlsComp?.toggleModeA()}
    on:toggleModeB={() => viewControlsComp?.toggleModeB()}
    on:scrollActive={() => {
        if (get(viewMode) === TS_VIEW_MODES.ANIMATION) animDisplayEl?.scrollActiveIntoView();
        else unifiedEl?.scrollActiveIntoView();
    }}
    on:cycleSpeed={(e) => controlsComp?.cycleSpeed(e.detail)}
    on:tick={onTick}
/>

<div
    id="timestamps-panel"
    style:--unified-display-max-height="{cfg?.unified_display_max_height ?? TS_UNIFIED_DISPLAY_MAX_HEIGHT_PX}px"
    style:--anim-highlight-color={highlightColor}
    style:--anim-word-transition={wordTransition}
    style:--anim-char-transition={charTransition}
    style:--anim-word-spacing={cfg?.anim_word_spacing ?? ''}
    style:--anim-line-height={cfg?.anim_line_height ?? ''}
    style:--anim-font-size={cfg?.anim_font_size ?? ''}
    style:--analysis-word-font-size={cfg?.analysis_word_font_size ?? ''}
    style:--analysis-letter-font-size={cfg?.analysis_letter_font_size ?? ''}
>
    <TimestampsShortcutsGuide />

    <TimestampsControls
        bind:this={controlsComp}
        on:reciterChange={(e) => onReciterChange(e.detail)}
        on:chapterChange={(e) => onChapterChange(e.detail)}
        on:verseChange={(e) => onVerseChange(e.detail)}
    />

    {#if $tsValidation}
        <div class="ts-validation-row">
            <TsValidationPanel
                doc={$tsValidation}
                activeVerse={$selectedVerse}
                onselect={jumpToFlaggedVerse}
            />
        </div>
    {/if}

    {#if currentVerseKey}
        <div class="ts-bookmark-row">
            <button
                type="button"
                class="ts-bookmark-btn"
                class:active={bookmarkedCurrent}
                title={bookmarkedCurrent ? 'Remove bookmark' : 'Bookmark this verse'}
                on:click={toggleVerseBookmark}
            >
                {bookmarkedCurrent ? '★ Bookmarked' : '☆ Bookmark verse'}
            </button>
        </div>
    {/if}

    <main>
        <TimestampsAudio
            bind:this={audioComp}
            {prevDisabled}
            {nextDisabled}
            on:prev={() => navigateVerse(-1)}
            on:next={() => navigateVerse(+1)}
            on:tick={onTick}
            on:autoNext={() => navigateVerse(+1)}
            on:autoRandomAny={() => loadRandomTimestamp()}
            on:autoRandomCurrent={() => loadRandomTimestamp(get(selectedReciter) || null)}
        />

        <TimestampsViewControls
            bind:this={viewControlsComp}
            on:randomAny={() => loadRandomTimestamp()}
            on:randomCurrent={() => loadRandomTimestamp(get(selectedReciter) || null)}
        />

        <div class="waveform-words-row" class:ts-region-loading={$tsLoading}>
            <TimestampsWaveform bind:this={waveformTabEl} />
            <div hidden={$viewMode === TS_VIEW_MODES.ANIMATION}>
                <UnifiedDisplay bind:this={unifiedEl} />
            </div>
            <div hidden={$viewMode === TS_VIEW_MODES.ANALYSIS}>
                <AnimationDisplay bind:this={animDisplayEl} />
            </div>
        </div>
    </main>
</div>

<style>
    /* Localized load dim: only the waveform+display region fades while a verse
       loads, instead of the old document.body 50% full-page grey-out. Keeps the
       previous verse visible (least jarring) and leaves controls interactive. */
    .waveform-words-row {
        transition: opacity 0.12s ease;
    }
    .waveform-words-row.ts-region-loading {
        opacity: 0.55;
        pointer-events: none;
    }
    .ts-validation-row {
        max-width: 720px;
        margin: 8px auto 2px;
    }
    .ts-bookmark-row {
        display: flex;
        justify-content: center;
        margin: 6px 0 2px;
    }
    .ts-bookmark-btn {
        background: #16213e;
        color: #d8def0;
        border: 1px solid #2a3a6a;
        border-radius: 6px;
        padding: 5px 12px;
        font-size: 0.85rem;
        cursor: pointer;
        transition: background 0.2s, color 0.2s, border-color 0.2s;
    }
    .ts-bookmark-btn:hover { background: #1c294b; border-color: #4cc9f0; }
    .ts-bookmark-btn.active { color: #f0a500; border-color: #f0a500; }
</style>
