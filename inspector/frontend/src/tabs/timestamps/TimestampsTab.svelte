<script lang="ts">
    /**
     * TimestampsTab — content surface for the redesigned Timestamps tab.
     *
     * Playback is owned by the SHARED shell player (dashPort + playerContext),
     * not this tab — the tab is published-by_surah-only and rides the same
     * continuous-chapter transport the Dashboard uses, so switching tabs keeps
     * audio / animation / waveform cursor in sync (the player never unmounts).
     *
     * This tab renders only: the waveform + the mega analysis display
     * (words / letters / phonemes / translations). The word-by-word animation
     * lives in the shared NowReciting bar; the footer controls (reciter picker,
     * shuffles, analysis toggles, loop, bookmark, shortcuts) live in the shared
     * BottomPlayer's slots (TimestampsFooterLeft / TimestampsFooterRight).
     *
     * `loadedVerse` is repurposed as the FOCUS verse — the verse under the
     * playhead (or clicked) that the analysis + waveform inspect. It follows the
     * shared playhead; it does not drive audio.
     */

    import { onDestroy, onMount } from 'svelte';
    import { get } from 'svelte/store';

    import { fetchSurahsForDelivery } from '../../lib/api/audio-surahs';
    import { setAdoptedSource } from '../../lib/playback/adopt-signal';
    import { adjacentAyahStartMs } from '../../lib/playback/ayah-seek';
    import { dashPort } from '../../lib/playback/dash-port';
    import { recycleAsShadow } from '../../lib/playback/shadow-audio';
    import {
        clearShuffle,
        consumeShuffle,
        type ConsumedShuffle,
        primeShuffle,
    } from '../../lib/playback/shuffle-prewarm';
    import {
        recitationConfigStore,
        recitationFocus,
    } from '../../lib/recitation-animation/recitation-settings';
    import { hasCapability } from '../../lib/stores/capabilities';
    import { currentUser } from '../../lib/stores/current-user';
    import { pendingTsNavigation } from '../../lib/stores/navigation';
    import { playerContext, setIsLoading, setIsPlaying } from '../../lib/stores/player-context';
    import type { TsConfigResponse } from '../../lib/types/api';
    import { getActiveTab, activeTab as activeTabStore } from '../../lib/utils/active-tab';
    import { analogousTriad } from '../../lib/utils/color-derive';
    import { LS_KEYS, TAB_NAMES } from '../../lib/utils/constants';
    import { shouldHandleKey } from '../../lib/utils/keyboard-guard';
    import { wordBoundaryScan } from '../../lib/utils/word-boundary';
    import { loadCatalog as loadPublicCatalog, catalogData } from '../dashboard/stores/catalog-data';
    import TimestampsWaveform from './components/TimestampsWaveform.svelte';
    import TsValidationPanel from './components/TsValidationPanel.svelte';
    import UnifiedDisplay from './components/UnifiedDisplay.svelte';
    import {
        assembleVerseFromShard,
        chapterVerseRefs,
        getRandomTarget,
        loadChapterShard,
        loadConfig,
        loadDk,
        loadManifest,
        loadQpc,
        loadTsValidation,
        loadVerseTranslations,
        reciterAudioFromManifest,
    } from './services/ts_client';
    import { findTsEntryBySlug, isTsCapable, resolveTsDeliveries } from './services/ts-published';
    import {
        showLetters,
        showPhonemes,
        showTranslations,
        translationLanguage,
        tsConfig,
        verseTranslations,
    } from './stores/display';
    import { tsLoading } from './stores/loading';
    import { exitLoop, loopTarget } from './stores/playback';
    import { manualShuffleRequest, shuffleAyah, shuffleMode } from './stores/shuffle';
    import { tsValidation } from './stores/validation';
    import {
        loadedVerse,
        selectedChapter,
        selectedReciter,
        selectedVerse,
        type TsLoadedVerse,
    } from './stores/verse';
    import { setupZoomLifecycle } from './utils/zoom';

    // ---- Local display constants ----
    const TS_EASING_NONE = 'none';
    const TS_EASING_DEFAULT = 'linear';
    const TS_UNIFIED_DISPLAY_MAX_HEIGHT_PX = 800;
    /** Fire the ayah-end shuffle this many ms before the exact verse end so the
     *  jump lands without a beat of the next ayah leaking in. */
    const SHUFFLE_END_GUARD_MS = 40;

    // ---- Component refs ----
    let unifiedEl: UnifiedDisplay;
    let waveformTabEl: TimestampsWaveform;

    // ---- Chapter focus data ----
    interface ChapVerse {
        ref: string;
        startMs: number;
        endMs: number;
        lv: TsLoadedVerse;
    }
    let chapterVerses: ChapVerse[] = [];
    /** Ascending list of ayah start ms — mirrors `chapterVerses` (which is
     *  sorted at assembly time, line ~297). Memoised so the keyboard handlers
     *  don't `chapterVerses.map(...)` per keydown. */
    let chapterStartMs: number[] = [];
    let loadedChapterKey = ''; // `${slug}:${chapter}` currently assembled
    let focusRef = '';
    let manifestSlugs = new Set<string>();
    /** Set when a context switch should seek to a specific verse once the new
     *  chapter's data + audio are ready (shuffle / validation jump / entry). */
    let pendingSeekRef: string | null = null;
    let shuffleFiredForRef = ''; // guard so ayah-end shuffle fires once per verse

    /** Loop is anchored to the verse that was in focus when the loop was
     *  engaged — NOT the live focus verse. Captured on the loopTarget null→set
     *  transition so a ~1-frame overshoot past the verse boundary can't drift
     *  the focus to the next ayah and (a) flip the analysis text + (b) blow up
     *  `endAbs` so the seek-back never fires again. Null while not looping. */
    let loopAnchor: ChapVerse | null = null;

    // ---------------------------------------------------------------------
    // Colors (shared accent → analysis triad)
    // ---------------------------------------------------------------------
    $: cfg = $tsConfig;
    $: triad = analogousTriad($recitationConfigStore.highlightColor);
    $: highlightColor = triad.word;
    $: wordDur =
        cfg && cfg.anim_transition_easing !== TS_EASING_NONE
            ? `${cfg.anim_word_transition_duration}s`
            : '0s';
    $: charDur =
        cfg && cfg.anim_transition_easing !== TS_EASING_NONE
            ? `${cfg.anim_char_transition_duration}s`
            : '0s';
    $: easing =
        cfg && cfg.anim_transition_easing !== TS_EASING_NONE
            ? cfg.anim_transition_easing
            : TS_EASING_DEFAULT;
    $: wordTransition = `opacity ${wordDur} ${easing}`;
    $: charTransition = `opacity ${charDur} ${easing}`;

    // ---------------------------------------------------------------------
    // Initial load
    // ---------------------------------------------------------------------
    async function init(): Promise<void> {
        loadConfig().then((c) => tsConfig.set(c as TsConfigResponse));
        void loadQpc().catch(() => {});
        void loadDk().catch(() => {});

        // Display prefs (letters/phonemes/translations) hydrate regardless of
        // the (now-removed) view mode.
        const sL = localStorage.getItem(LS_KEYS.TS_SHOW_LETTERS);
        const sP = localStorage.getItem(LS_KEYS.TS_SHOW_PHONEMES);
        const sT = localStorage.getItem(LS_KEYS.TS_SHOW_TRANSLATIONS);
        const sLang = localStorage.getItem(LS_KEYS.TS_TRANSLATION_LANG);
        if (sL !== null) showLetters.set(sL === 'true');
        if (sP !== null) showPhonemes.set(sP === 'true');
        if (sT !== null) showTranslations.set(sT === 'true');
        if (sLang) translationLanguage.set(sLang);

        try {
            const [, manifest] = await Promise.all([loadPublicCatalog(), loadManifest()]);
            manifestSlugs = new Set(Object.keys(manifest.reciters));
        } catch (e) {
            console.error('TS: catalog/manifest load failed', e);
        }

        // A bookmark deep-link owns the first load — let its consumer run.
        if (navHandled || get(pendingTsNavigation)) return;
        await resolveEntry(getActiveTab() === TAB_NAMES.TIMESTAMPS);
    }

    /** All published, by_surah, timestamped (reciter, delivery) pairs. */
    function tsEntries() {
        return resolveTsDeliveries(get(catalogData).reciters, manifestSlugs);
    }

    // ---------------------------------------------------------------------
    // Entry / continuity / cache resolution
    // ---------------------------------------------------------------------
    async function resolveEntry(autoplay: boolean): Promise<void> {
        const ctx = get(playerContext);
        // 1. Continuity: the shared player is already on a TS-capable reciter.
        if (isTsCapable(ctx.delivery, manifestSlugs) && ctx.surahNum) {
            cacheReciter(ctx.delivery!.slug);
            return; // the reactive chapter-load picks it up
        }
        // 2. Cache: last published TS-capable reciter the user had here. Resolve
        //    a valid (chapter, ayah) from the manifest — the reciter may not have
        //    chapter 1 timestamps, so never default to 1.
        const cached = localStorage.getItem(LS_KEYS.TS_RECITER) ?? '';
        const cachedEntry = findTsEntryBySlug(get(catalogData).reciters, manifestSlugs, cached);
        if (cachedEntry) {
            const t = await getRandomTarget({ reciter: cachedEntry.delivery.slug }).catch(() => null);
            if (t) {
                await startEntry(cachedEntry.reciter, cachedEntry.delivery, { chapter: t.chapter, verseRef: t.verseRef }, autoplay);
                return;
            }
            // Cached reciter has no usable shard (stale/broken) — drop it and
            // fall through to a random working reciter.
            localStorage.removeItem(LS_KEYS.TS_RECITER);
        }
        // 3. First entry / fallback: a random reciter that actually has a usable
        //    shard. Some manifest reciters are stale (listed but shards 404), so
        //    probe a few and take the first that yields a target.
        const entries = shuffleArr(tsEntries());
        for (const e of entries.slice(0, 8)) {
            const target = await getRandomTarget({ reciter: e.delivery.slug }).catch(() => null);
            if (target) {
                await startEntry(e.reciter, e.delivery, { chapter: target.chapter, verseRef: target.verseRef }, autoplay);
                return;
            }
        }
    }

    function shuffleArr<T>(arr: T[]): T[] {
        const a = [...arr];
        for (let i = a.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1));
            [a[i], a[j]] = [a[j]!, a[i]!];
        }
        return a;
    }

    function cacheReciter(slug: string): void {
        if (slug) localStorage.setItem(LS_KEYS.TS_RECITER, slug);
    }

    /** Point the shared player at a TS reciter+chapter and (optionally) queue a
     *  seek to a specific verse once its data lands. */
    async function startEntry(
        reciter: import('../../lib/types/public-state').PublicReciter,
        delivery: import('../../lib/types/public-state').PublicDelivery,
        target: { chapter: number; verseRef: string } | null,
        autoplay: boolean,
    ): Promise<void> {
        cacheReciter(delivery.slug);
        const chapter = target?.chapter ?? 1;
        pendingSeekRef = target?.verseRef ?? null;
        _autoplayPending = autoplay;
        playerContext.update((s) => ({
            ...s,
            reciter,
            delivery,
            surahNum: chapter,
            positionMs: 0,
            isPlaying: autoplay || s.isPlaying,
        }));
    }

    let _autoplayPending = false;

    // ---------------------------------------------------------------------
    // Chapter focus data — react to the shared player's reciter + surah
    // ---------------------------------------------------------------------
    $: void syncChapter($playerContext.delivery?.slug ?? '', $playerContext.surahNum ?? 0);

    async function syncChapter(slug: string, chapter: number): Promise<void> {
        if (!slug || !chapter) return;
        if (!manifestSlugs.has(slug)) return; // non-published reciter on dashboard
        const key = `${slug}:${chapter}`;
        if (key === loadedChapterKey) return;
        if (get(tsLoading)) return;
        // Guard: this reciter may not have timestamps for `chapter` (its
        // ts_chapters is a subset of all 114). Loading the shard would 404.
        // Correct the shared surah to a valid chapter — that also re-points the
        // audio and re-runs this reactive. Cheap: manifest is a warm singleton.
        const manifest = await loadManifest();
        const block = manifest.reciters[slug];
        if (!block) return;
        if (!block.ts_chapters.includes(chapter)) {
            const valid = block.ts_chapters[0];
            if (valid && valid !== chapter) {
                pendingSeekRef = null;
                playerContext.update((s) => ({ ...s, surahNum: valid, positionMs: 0 }));
            }
            return;
        }
        tsLoading.set(true);
        try {
            // Canonical per-chapter audio URL comes from /api/audio/surahs (the
            // audio-manifest sidecar) — same source playback uses, usually warm
            // from the player; fetched in parallel with the shard.
            const [shard, qpc, dk, surahs] = await Promise.all([
                loadChapterShard(slug, chapter),
                loadQpc(),
                loadDk(),
                fetchSurahsForDelivery(block.source ?? '', slug).catch(
                    (): Awaited<ReturnType<typeof fetchSurahsForDelivery>> => ({}),
                ),
            ]);
            const reciterAudio = reciterAudioFromManifest(manifest, slug);
            if (!reciterAudio) return;
            const chapterUrl = surahs[String(chapter)]?.url ?? '';
            const verses: ChapVerse[] = [];
            for (const ref of chapterVerseRefs(shard)) {
                const data = assembleVerseFromShard(slug, shard, ref, qpc, dk, reciterAudio, chapterUrl);
                if (!data) continue;
                verses.push({
                    ref,
                    startMs: data.time_start_ms,
                    endMs: data.time_end_ms,
                    lv: { data, tsSegOffset: data.time_start_ms / 1000, tsSegEnd: data.time_end_ms / 1000 },
                });
            }
            verses.sort((a, b) => a.startMs - b.startMs);
            chapterVerses = verses;
            // Memoised ascending startMs feeds `adjacentAyahStartMs` (which now
            // trusts sorted input) without allocating + sorting on every
            // keypress / drag. Reassigned alongside chapterVerses to keep both
            // reactive views in lockstep.
            chapterStartMs = verses.map((v) => v.startMs);
            loadedChapterKey = key;
            selectedReciter.set(slug);
            selectedChapter.set(String(chapter));

            // Owner/maintainer: load validation flags for this reciter.
            if (hasCapability(get(currentUser), 'timestamps.view_validation')) {
                void loadTsValidation(slug).then((doc) => {
                    if (get(selectedReciter) === slug) tsValidation.set(doc);
                });
            } else {
                tsValidation.set(null);
            }

            // Apply a queued seek (entry / shuffle / validation jump), else focus
            // the verse under the current playhead.
            if (pendingSeekRef) {
                const v = chapterVerses.find((x) => x.ref === pendingSeekRef);
                pendingSeekRef = null;
                if (v) {
                    setFocus(v);
                    dashPort.seek(v.startMs);
                    if (_autoplayPending) {
                        _autoplayPending = false;
                        try { dashPort.play(); } catch { /* autoplay policy */ }
                    }
                }
            } else {
                focusAt(dashPort.currentTimeMs());
            }
            // Warm the next shuffle target now that the chapter is loaded.
            void primeShuffleSlot();
        } catch (e) {
            console.error('TS: chapter sync failed', e);
        } finally {
            tsLoading.set(false);
        }
    }

    function setFocus(v: ChapVerse): void {
        focusRef = v.ref;
        loadedVerse.set(v.lv);
        selectedVerse.set(v.ref);
        // Publish to the shell-level focus store so NowReciting's filmstrip
        // bookmark button can mirror the focus without running its own rAF.
        // Verse refs are "surah:ayah" (chapterVerseRefs); parse defensively.
        const [s, a] = v.ref.split(':');
        const surah = Number(s);
        const ayah = Number(a);
        if (Number.isFinite(surah) && Number.isFinite(ayah) && surah > 0 && ayah > 0) {
            recitationFocus.set({ surah, ayah });
        }
    }

    /** Focus the verse containing `ms` (chapter-absolute), else the nearest
     *  preceding one. No-op if the focus is unchanged. */
    function focusAt(ms: number): void {
        if (chapterVerses.length === 0) return;
        let hit: ChapVerse | null = null;
        for (const v of chapterVerses) {
            if (ms >= v.startMs && ms < v.endMs) { hit = v; break; }
            if (v.startMs <= ms) hit = v; // nearest preceding
        }
        const v = hit ?? chapterVerses[0]!;
        if (v.ref !== focusRef) setFocus(v);
    }

    // ---------------------------------------------------------------------
    // Per-frame tick (focus + highlights + waveform cursor + loop + shuffle)
    // ---------------------------------------------------------------------
    let _raf: number | null = null;

    function startTick(): void {
        if (_raf !== null) return;
        const loop = (): void => {
            tick();
            _raf = requestAnimationFrame(loop);
        };
        _raf = requestAnimationFrame(loop);
    }
    function stopTick(): void {
        if (_raf !== null) { cancelAnimationFrame(_raf); _raf = null; }
    }

    function tick(): void {
        const ms = dashPort.currentTimeMs();

        // rAF seek-back loop (no kill-switch on the shared port; ≤1 frame
        // overshoot). The loop window is computed against the CAPTURED loop
        // anchor offset, never the live focus verse — a boundary-frame
        // overshoot must not drift the focus and so re-base endAbs onto the
        // next ayah (which would break the loop permanently). While looping,
        // focus stays PINNED to the loop verse (no focusAt advance).
        const loop = get(loopTarget);
        if (loop && loopAnchor) {
            const offsetSec = loopAnchor.startMs / 1000;
            const startAbs = (loop.startSec + offsetSec) * 1000;
            const endAbs = (loop.endSec + offsetSec) * 1000;
            if (ms >= endAbs) {
                dashPort.seek(startAbs);
            }
            // Keep focus on the loop's verse regardless of where the playhead
            // momentarily sits (the seek-back is async).
            if (focusRef !== loopAnchor.ref) setFocus(loopAnchor);
            refreshDisplays();
            return;
        }

        focusAt(ms);
        // rAF gives tight (~16 ms) boundary timing while the tab is active; the
        // onTimeUpdate/onEnded media-clock backstop (onMount) catches the boundary
        // when rAF is throttled (backgrounded tab / GC / heavy repaint), where it
        // would otherwise overshoot by 1-3 words. The once-per-verse guard dedupes
        // whichever fires first.
        maybeFireShuffle(ms);
        refreshDisplays();
    }

    // Ayah-end shuffle boundary: jump to a random target when the playhead reaches
    // the focus verse's end (once per verse). Called from both the rAF tick and the
    // onTimeUpdate/onEnded media-clock backstop; reads the focus verse fresh so the
    // boundary and the dedupe key never disagree. Gated to the active Timestamps tab
    // so the shared dashPort backstop can't hijack Dashboard playback (its own
    // gapless advance owns dashPort.onEnded when that tab is active).
    function maybeFireShuffle(ms: number): void {
        if (getActiveTab() !== TAB_NAMES.TIMESTAMPS) return;
        if (get(loopTarget) || !get(shuffleAyah)) return;
        const fv = get(loadedVerse);
        if (!fv) return;
        const endMs = fv.tsSegEnd * 1000;
        if (ms >= endMs - SHUFFLE_END_GUARD_MS && shuffleFiredForRef !== focusRef) {
            shuffleFiredForRef = focusRef;
            void shuffleJump();
        }
    }

    function refreshDisplays(): void {
        unifiedEl?.updateHighlights();
        waveformTabEl?.drawOverlays();
    }

    // ---------------------------------------------------------------------
    // Shuffle / navigation jumps
    // ---------------------------------------------------------------------
    async function shuffleJump(autoplay = true): Promise<void> {
        exitLoop();
        const cur = get(playerContext);
        const curSlug = cur.delivery?.slug ?? '';
        // The jump kind is the active mode at fire time: both → random reciter,
        // else (ayah) → random ayah of the same reciter.
        const randomReciter = get(shuffleMode) === 2;
        // Prefer the pre-rolled (warm) target so the jump can adopt gaplessly;
        // else roll a fresh one (gapped fallback).
        const consumed = consumeShuffle();
        const target = consumed?.target
            ?? await getRandomTarget(randomReciter ? {} : { reciter: curSlug }).catch(() => null);
        if (!target) {
            if (consumed) discardWarm(consumed.el);
            return;
        }

        const sameSource = target.reciter === curSlug && target.chapter === cur.surahNum;
        if (sameSource) {
            // In-chapter jump is already gapless (plain seek) — drop the warm el.
            if (consumed) discardWarm(consumed.el);
            const v = chapterVerses.find((x) => x.ref === target.verseRef);
            if (v) seekFocus(v, autoplay);
        } else if (consumed) {
            adoptGapless(consumed, autoplay);
        } else {
            // Cross-source look-ahead miss → gapped fallback.
            await jumpToTarget(target.reciter, target.chapter, target.verseRef, autoplay);
        }
        void primeShuffleSlot(); // re-arm the next jump
    }

    function discardWarm(el: HTMLAudioElement): void {
        try { el.pause(); el.removeAttribute('src'); el.load(); el.remove(); } catch { /* ignore */ }
    }

    /** Gapless cross-source jump: adopt the prewarmed element onto dashPort and
     *  start it WITHOUT a fresh load, then update playerContext (guarded by the
     *  adopt signal so BottomPlayer.reactToContext doesn't re-load + re-decode). */
    function adoptGapless(c: ConsumedShuffle, autoplay: boolean): void {
        const entry = findTsEntryBySlug(get(catalogData).reciters, manifestSlugs, c.target.reciter);
        if (!entry) { discardWarm(c.el); return; }
        const shouldPlay = autoplay || !dashPort.paused;
        const startMs = c.seekSec * 1000;

        // Match the triple BottomPlayer would build so its eventual setSource is
        // a guaranteed no-op (belt-and-braces alongside the adopt signal).
        dashPort.setSource({ audioUrl: c.rawUrl, cbrSrc: c.proxyUrl, reciter: c.target.reciter, vbr: false });
        setAdoptedSource({ deliverySlug: c.target.reciter, surahNum: c.target.chapter, srcUrl: c.proxyUrl });

        const oldEl = dashPort.element;
        dashPort.adoptElement(c.el, c.proxyUrl);
        if (oldEl && oldEl !== c.el) recycleAsShadow(oldEl, 'any');

        if (shouldPlay) dashPort.seekAndPlay(startMs); else dashPort.seek(startMs);
        setIsLoading(false);
        setIsPlaying(shouldPlay);

        pendingSeekRef = c.target.verseRef; // syncChapter focuses it once data lands
        _autoplayPending = false;           // already playing the adopted element
        playerContext.update((s) => ({
            ...s,
            reciter: entry.reciter,
            delivery: entry.delivery,
            surahNum: c.target.chapter,
            positionMs: startMs,
            isPlaying: shouldPlay,
        }));
    }

    /** Look-ahead: warm the single target the current shuffle mode will jump to,
     *  so the next jump can adopt it gaplessly. Off → nothing warm. Builds the
     *  SAME proxy URL the shared player would, so the warm element matches on
     *  consume. Range-windowed (the warm-seek triggers an HTTP Range request) —
     *  not a full-chapter download. Clears any stale (old-mode) target first so a
     *  verse-end racing the re-warm misses cleanly instead of jumping wrong. */
    async function primeShuffleSlot(): Promise<void> {
        clearShuffle();
        const mode = get(shuffleMode);
        if (mode === 0) return; // off → no look-ahead (no jump happens)
        const randomReciter = mode === 2;
        const curSlug = get(playerContext).delivery?.slug ?? '';
        const target = await getRandomTarget(randomReciter ? {} : { reciter: curSlug }).catch(() => null);
        if (!target) return;
        const entry = findTsEntryBySlug(get(catalogData).reciters, manifestSlugs, target.reciter);
        if (!entry) return;
        let urls: Awaited<ReturnType<typeof fetchSurahsForDelivery>>;
        try {
            urls = await fetchSurahsForDelivery(entry.delivery.source, target.reciter);
        } catch {
            return;
        }
        const u = urls[String(target.chapter)];
        if (!u) return;
        const rawUrl = u.url;
        const proxyUrl = rawUrl.startsWith('/api/')
            ? rawUrl
            : `/api/seg/audio-proxy/${target.reciter}?url=${encodeURIComponent(rawUrl)}`;
        // Verse start (chapter-absolute seconds) → warm-seek position.
        let seekSec = 0;
        try {
            const [shard, qpc, dk, manifest] = await Promise.all([
                loadChapterShard(target.reciter, target.chapter),
                loadQpc(), loadDk(), loadManifest(),
            ]);
            const ra = reciterAudioFromManifest(manifest, target.reciter);
            const data = ra
                ? assembleVerseFromShard(target.reciter, shard, target.verseRef, qpc, dk, ra, rawUrl)
                : null;
            if (data) seekSec = data.time_start_ms / 1000;
        } catch { /* seek 0 is an acceptable fallback */ }
        primeShuffle({ target, proxyUrl, rawUrl, seekSec });
    }

    /** Jump to (reciter, chapter, verseRef). Same chapter → seek in place.
     *  Different chapter/reciter → switch the shared context + queue the seek. */
    async function jumpToTarget(
        slug: string,
        chapter: number,
        verseRef: string,
        autoplay = true,
    ): Promise<void> {
        const curSlug = get(playerContext).delivery?.slug ?? '';
        const curChapter = get(playerContext).surahNum ?? 0;
        if (slug === curSlug && chapter === curChapter) {
            const v = chapterVerses.find((x) => x.ref === verseRef);
            if (v) seekFocus(v, autoplay);
            return;
        }
        const entry = findTsEntryBySlug(get(catalogData).reciters, manifestSlugs, slug);
        if (!entry) return;
        pendingSeekRef = verseRef;
        _autoplayPending = autoplay || !dashPort.paused; // keep or create playback across the jump
        playerContext.update((s) => ({
            ...s,
            reciter: entry.reciter,
            delivery: entry.delivery,
            surahNum: chapter,
            positionMs: 0,
            isPlaying: _autoplayPending,
        }));
    }

    function tryPlay(): void {
        try { dashPort.play(); } catch { /* autoplay policy */ }
    }

    function seekFocus(v: ChapVerse, autoplay = true): void {
        const wasPlaying = !dashPort.paused;
        setFocus(v);
        dashPort.seek(v.startMs);
        if (autoplay || wasPlaying) tryPlay();
        refreshDisplays();
    }

    function seekMsAndResume(targetMs: number): void {
        dashPort.seek(targetMs);
        tryPlay();
        focusAt(targetMs);
        refreshDisplays();
    }

    /** Step to the prev/next ayah in the current chapter (keyboard [ / ]). */
    function navigateVerse(delta: number): void {
        if (chapterVerses.length === 0) return;
        const idx = chapterVerses.findIndex((v) => v.ref === focusRef);
        const ni = idx + delta;
        if (ni < 0 || ni >= chapterVerses.length) return;
        exitLoop();
        const v = chapterVerses[ni]!;
        seekFocus(v);
    }

    /** Validation panel click — jump the focus (+ playhead) to a flagged verse,
     *  switching chapter if needed. */
    function jumpToFlaggedVerse(verseKey: string): void {
        const slug = get(playerContext).delivery?.slug ?? '';
        const surah = parseInt(verseKey.split(':')[0] ?? '0', 10);
        if (!slug || !surah) return;
        void jumpToTarget(slug, surah, verseKey);
    }

    // ---------------------------------------------------------------------
    // Bookmark deep-link (from BookmarksPanel) — load a specific verse with a
    // random TS-capable reciter and seek there.
    // ---------------------------------------------------------------------
    let navHandled = false;
    $: if ($pendingTsNavigation) consumePendingNav($pendingTsNavigation);

    function consumePendingNav(nav: { surah: number; ayah: number; autoplay: boolean }): void {
        navHandled = true;
        pendingTsNavigation.set(null);
        void loadBookmarkedVerse(nav.surah, nav.ayah, nav.autoplay);
    }

    async function loadBookmarkedVerse(surah: number, ayah: number, autoplay: boolean): Promise<void> {
        const verseRef = `${surah}:${ayah}`;
        for (const e of tsEntries()) {
            // Try the first reciter that has this verse in its shard.
            try {
                const shard = await loadChapterShard(e.delivery.slug, surah);
                if (!chapterVerseRefs(shard).includes(verseRef)) continue;
                pendingSeekRef = verseRef;
                _autoplayPending = autoplay;
                playerContext.update((s) => ({
                    ...s,
                    reciter: e.reciter,
                    delivery: e.delivery,
                    surahNum: surah,
                    positionMs: 0,
                    isPlaying: autoplay || s.isPlaying,
                }));
                return;
            } catch {
                continue;
            }
        }
    }

    // ---------------------------------------------------------------------
    // Translations (Analysis only) — lazily fetch glosses for the focus verse.
    // ---------------------------------------------------------------------
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
            .then((map) => { if (token === _trReq) verseTranslations.set(map); })
            .catch(() => { if (token === _trReq) verseTranslations.set({}); });
    }

    // (The once-per-verse shuffle guard resets implicitly: `shuffleFiredForRef`
    //  is compared against `focusRef`, so a focus change re-arms it.)

    // ---------------------------------------------------------------------
    // Keyboard (operates on the shared dashPort)
    // ---------------------------------------------------------------------
    function onKeydown(e: KeyboardEvent): void {
        if (!shouldHandleKey(e, 'timestamps')) return;
        if (getActiveTab() !== TAB_NAMES.TIMESTAMPS) return;
        const cur = dashPort.currentTimeMs() / 1000;
        const lv = get(loadedVerse);
        switch (e.code) {
            case 'Space':
                e.preventDefault();
                if (dashPort.paused) tryPlay(); else dashPort.pause();
                break;
            case 'ArrowLeft': {
                e.preventDefault();
                exitLoop();
                const t = adjacentAyahStartMs(chapterStartMs, cur * 1000, -1);
                if (t !== null) seekMsAndResume(t);
                break;
            }
            case 'ArrowRight': {
                e.preventDefault();
                exitLoop();
                const t = adjacentAyahStartMs(chapterStartMs, cur * 1000, 1);
                if (t !== null) seekMsAndResume(t);
                break;
            }
            case 'ArrowUp': {
                e.preventDefault();
                exitLoop();
                if (!lv) break;
                const t = cur - lv.tsSegOffset;
                const prev = wordBoundaryScan(lv.data.words, t, 'up');
                seekMsAndResume(((prev ?? 0) + lv.tsSegOffset) * 1000);
                break;
            }
            case 'ArrowDown': {
                e.preventDefault();
                exitLoop();
                if (!lv) break;
                const t = cur - lv.tsSegOffset;
                const next = wordBoundaryScan(lv.data.words, t, 'down');
                if (next !== null) seekMsAndResume((next + lv.tsSegOffset) * 1000);
                break;
            }
            case 'KeyR':
                void shuffleJump();
                break;
            case 'BracketLeft':
                navigateVerse(-1);
                break;
            case 'BracketRight':
                navigateVerse(+1);
                break;
            case 'KeyJ':
                e.preventDefault();
                unifiedEl?.scrollActiveIntoView();
                break;
            case 'KeyL':
                e.preventDefault();
                showLetters.update((v) => !v);
                break;
            case 'KeyP':
                e.preventDefault();
                showPhonemes.update((v) => !v);
                break;
        }
    }

    // ---------------------------------------------------------------------
    // Lifecycle — run the tick only while this tab is active.
    // ---------------------------------------------------------------------
    $: if ($activeTabStore === TAB_NAMES.TIMESTAMPS) startTick(); else stopTick();

    let _primedOnce = false;

    onMount(() => {
        setupZoomLifecycle();
        void init();
        // Re-resolve continuity when the tab regains focus (e.g. after the
        // dashboard switched to a non-published reciter).
        const unsubTab = activeTabStore.subscribe((t) => {
            if (t === TAB_NAMES.TIMESTAMPS && manifestSlugs.size > 0 && !navHandled) {
                void resolveEntry(false);
            }
        });
        // Re-warm the look-ahead when the shuffle MODE flips (the warm slot is
        // mode-specific). Subscribe to the derived `shuffleMode` (deduped by
        // integer) so one cycle step = one reprime — not the double-fire two
        // boolean subscriptions caused. Skip the initial fire — syncChapter
        // primes the first slot once data is loaded.
        const reprime = (): void => { if (_primedOnce) void primeShuffleSlot(); };
        const unsubShuf = shuffleMode.subscribe(reprime);
        let lastManualShuffle = get(manualShuffleRequest);
        const unsubManualShuffle = manualShuffleRequest.subscribe((n) => {
            if (n === lastManualShuffle) return;
            lastManualShuffle = n;
            if (!_primedOnce) return;
            void shuffleJump(true);
        });
        // Capture the loop's verse anchor on engage (null→set) and drop it on
        // exit. The loop setters (footer button, dbl-click, waveform click) all
        // run against the CURRENT focus verse, so the live `loadedVerse` at the
        // transition IS the loop verse. tick() reads `loopAnchor`, not the live
        // focus, so focus drift can't corrupt the loop window.
        const unsubLoop = loopTarget.subscribe((lt) => {
            if (lt && !loopAnchor) {
                loopAnchor = chapterVerses.find((v) => v.ref === focusRef) ?? null;
            } else if (!lt) {
                loopAnchor = null;
            }
        });
        // Media-clock backstop for the ayah-end shuffle: timeupdate/ended fire off
        // the audio clock (even when the tab is backgrounded and rAF is throttled),
        // so the boundary can't overshoot by seconds. Deduped against the rAF tick
        // by the once-per-verse guard.
        const offTimeUpdate = dashPort.onTimeUpdate((fileMs) => maybeFireShuffle(fileMs));
        const offEnded = dashPort.onEnded(() => maybeFireShuffle(Number.POSITIVE_INFINITY));
        _primedOnce = true;
        return () => {
            unsubTab(); unsubShuf(); unsubManualShuffle(); unsubLoop();
            offTimeUpdate(); offEnded();
        };
    });

    onDestroy(() => {
        stopTick();
        // Don't leak this tab's last focus to other surfaces (Dashboard's
        // NowReciting subscribes to it).
        recitationFocus.set(null);
    });
</script>

<svelte:window on:keydown={onKeydown} />

<div
    id="timestamps-panel"
    style:--unified-display-max-height="{cfg?.unified_display_max_height ?? TS_UNIFIED_DISPLAY_MAX_HEIGHT_PX}px"
    style:--anim-highlight-color={highlightColor}
    style:--ts-letter-color={triad.letter}
    style:--ts-phoneme-color={triad.phoneme}
    style:--anim-word-transition={wordTransition}
    style:--anim-char-transition={charTransition}
    style:--anim-word-spacing={cfg?.anim_word_spacing ?? ''}
    style:--anim-line-height={cfg?.anim_line_height ?? ''}
    style:--anim-font-size={cfg?.anim_font_size ?? ''}
    style:--analysis-word-font-size={cfg?.analysis_word_font_size ?? ''}
    style:--analysis-letter-font-size={cfg?.analysis_letter_font_size ?? ''}
>
    <main>
        {#if $tsValidation}
            <div class="ts-validation-row">
                <TsValidationPanel
                    doc={$tsValidation}
                    activeVerse={$selectedVerse}
                    onselect={jumpToFlaggedVerse}
                />
            </div>
        {/if}

        <div class="waveform-words-row" class:ts-region-loading={$tsLoading}>
            <TimestampsWaveform bind:this={waveformTabEl} />
            <UnifiedDisplay bind:this={unifiedEl} />
        </div>
    </main>
</div>

<style>
    #timestamps-panel {
        /* Reserve space for the shell-owned footer + now-reciting bar. */
        padding-bottom: calc(var(--player-h, 72px) + var(--now-reciting-h, 0px));
    }
    .waveform-words-row {
        transition: opacity 0.12s ease;
    }
    .waveform-words-row.ts-region-loading {
        opacity: 0.55;
        pointer-events: none;
    }
    .ts-validation-row {
        width: 100%;
        margin: 0 0 8px;
    }
</style>
