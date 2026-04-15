<script lang="ts">
    /**
     * AudioTab — Svelte component for the Audio tab (S2-D06).
     *
     * Replaces the Stage-1 imperative audio/index.ts. Owns:
     *   - Category toggle (By Surah / By Ayah).
     *   - Reciter, surah, and ayah dropdowns (via SearchableSelect).
     *   - Audio player with prev/next navigation.
     *   - Source loading from /api/audio/sources + /api/audio/surahs/*.
     *   - localStorage restore of last selected reciter.
     *
     * No store needed — all state is component-local (no cross-tab sharing).
     * Pattern notes #1-#8 from Wave 4 apply.
     */

    import { onMount } from 'svelte';

    import SearchableSelect from '../../lib/components/SearchableSelect.svelte';
    import { fetchJson } from '../../lib/api';
    import { LS_KEYS } from '../../lib/utils/constants';
    import { surahInfoReady, surahOptionText } from '../../lib/utils/surah-info';
    import type { SelectOption } from '../../lib/types/ui';
    import type { AudioSourcesResponse, AudioSurahsResponse } from '../../types/api';

    // ---- Types ----
    interface AudioReciter {
        slug: string;
        name: string;
    }
    type AudioCategorySources = Record<string, AudioReciter[]>;

    // ---- State ----
    let selectedCategory: 'by_surah' | 'by_ayah' = 'by_surah';
    let currentCategory: string | null = null;
    let audioSources: AudioSourcesResponse = {};

    // Cache: "category/source/slug" -> {key: url}
    const urlCache: Record<string, Record<string, string>> = {};

    // For by_ayah: parsed structure { surahNum -> [ayahNum, ...] } and flat sorted keys
    let ayahBySurah: Record<number, number[]> = {};
    let allSurahNums: number[] = [];

    // Dropdown options (reactive arrays drive SearchableSelect)
    let reciterOptions: SelectOption[] = [];
    let surahOptions: SelectOption[] = [];
    let ayahOptions: SelectOption[] = [];

    // Selected values
    let selectedReciter = '';
    let selectedSurah = '';
    let selectedAyah = '';

    // Player ref
    let playerEl: HTMLAudioElement;

    // Nav button states
    let prevDisabled = true;
    let nextDisabled = true;

    // ---- Lifecycle ----
    onMount(() => {
        void loadSources();
    });

    // ---- Source loading ----
    async function loadSources(): Promise<void> {
        try {
            await surahInfoReady;
            audioSources = await fetchJson<AudioSourcesResponse>('/api/audio/sources');

            // Restore category from saved reciter before populating
            const savedAudReciter = localStorage.getItem(LS_KEYS.AUD_RECITER);
            if (savedAudReciter) {
                const savedCat = savedAudReciter.split('/')[0];
                if ((savedCat === 'by_surah' || savedCat === 'by_ayah') && savedCat !== selectedCategory) {
                    selectedCategory = savedCat;
                }
            }

            populateReciters();
        } catch (_e) {
            reciterOptions = [{ value: '', label: 'Error loading sources' }];
        }
    }

    // ---- Populate dropdowns ----
    function populateReciters(): void {
        reciterOptions = [];
        surahOptions = [];
        ayahOptions = [];
        selectedReciter = '';
        selectedSurah = '';
        selectedAyah = '';
        currentCategory = null;
        updateNavButtons();

        const catData = audioSources[selectedCategory] as AudioCategorySources | undefined;
        if (catData) {
            const opts: SelectOption[] = [];
            for (const source of Object.keys(catData).sort()) {
                const reciters = catData[source];
                if (!reciters || reciters.length === 0) continue;
                for (const r of reciters) {
                    opts.push({
                        value: `${selectedCategory}/${source}/${r.slug}`,
                        label: r.name,
                        group: source,
                    });
                }
            }
            reciterOptions = opts;
        }

        // Restore saved reciter (only when it matches the current category)
        const savedAudReciter = localStorage.getItem(LS_KEYS.AUD_RECITER);
        if (savedAudReciter && savedAudReciter.startsWith(selectedCategory + '/')) {
            selectedReciter = savedAudReciter;
            void onReciterChange(savedAudReciter);
        }
    }

    async function onReciterChange(val: string): Promise<void> {
        selectedReciter = val;
        surahOptions = [];
        ayahOptions = [];
        selectedSurah = '';
        selectedAyah = '';
        clearPlayer();

        if (!val) {
            currentCategory = null;
            return;
        }

        if (val) localStorage.setItem(LS_KEYS.AUD_RECITER, val);

        // val is "category/source/slug"
        const parts = val.split('/');
        currentCategory = parts[0] ?? null;
        const sourceSlug = parts.slice(1).join('/'); // "source/slug"

        try {
            let urls = urlCache[val];
            if (!urls) {
                const data = await fetchJson<AudioSurahsResponse>(
                    `/api/audio/surahs/${currentCategory}/${sourceSlug}`,
                );
                urls = data.surahs || {};
                urlCache[val] = urls;
            }

            if (currentCategory === 'by_ayah') {
                buildAyahStructure(urls);
                populateSurahOptions(allSurahNums);
            } else {
                const nums = Object.keys(urls).map(Number).sort((a, b) => a - b);
                populateSurahOptions(nums);
            }
        } catch (_e) {
            surahOptions = [{ value: '', label: 'Error loading' }];
        }
    }

    function onSurahChange(val: string): void {
        selectedSurah = val;
        selectedAyah = '';
        if (currentCategory === 'by_ayah') {
            populateAyahOptions();
            clearPlayer();
        } else {
            playCurrentSelection();
        }
        updateNavButtons();
    }

    function onAyahChange(val: string): void {
        selectedAyah = val;
        playCurrentSelection();
        updateNavButtons();
    }

    // ---- Category toggle ----
    function setCategory(cat: 'by_surah' | 'by_ayah'): void {
        if (cat === selectedCategory) return;
        selectedCategory = cat;
        populateReciters();
    }

    // ---- Build data structures ----
    function buildAyahStructure(urls: Record<string, string>): void {
        ayahBySurah = {};
        for (const key of Object.keys(urls)) {
            const parts = key.split(':');
            const s = Number(parts[0]);
            const a = Number(parts[1]);
            if (!ayahBySurah[s]) ayahBySurah[s] = [];
            ayahBySurah[s]!.push(a);
        }
        for (const s of Object.keys(ayahBySurah)) {
            ayahBySurah[Number(s)]!.sort((a, b) => a - b);
        }
        allSurahNums = Object.keys(ayahBySurah).map(Number).sort((a, b) => a - b);
    }

    function populateSurahOptions(nums: number[]): void {
        surahOptions = nums.map(n => ({ value: String(n), label: surahOptionText(n) }));
    }

    function populateAyahOptions(): void {
        ayahOptions = [];
        selectedAyah = '';
        const s = Number(selectedSurah);
        if (!s || !ayahBySurah[s]) return;
        ayahOptions = (ayahBySurah[s] ?? []).map(a => ({ value: String(a), label: String(a) }));
    }

    // ---- Playback ----
    function playCurrentSelection(): void {
        if (!selectedReciter) { clearPlayer(); return; }
        const urls = urlCache[selectedReciter];
        if (!urls) { clearPlayer(); return; }

        let key: string;
        if (currentCategory === 'by_ayah') {
            if (!selectedSurah || !selectedAyah) { clearPlayer(); return; }
            key = `${selectedSurah}:${selectedAyah}`;
        } else {
            key = selectedSurah;
            if (!key) { clearPlayer(); return; }
        }

        const url = urls[key];
        if (url) {
            playerEl.src = url;
            playerEl.load();
        } else {
            clearPlayer();
        }
    }

    function clearPlayer(): void {
        if (playerEl) {
            playerEl.removeAttribute('src');
            playerEl.load();
        }
        updateNavButtons();
    }

    // ---- Navigation ----
    function navigate(delta: number): void {
        if (currentCategory === 'by_ayah') {
            navigateAyah(delta);
        } else {
            const idx = surahOptions.findIndex(o => o.value === selectedSurah);
            const newIdx = idx + delta;
            if (newIdx < 0 || newIdx >= surahOptions.length) return;
            const opt = surahOptions[newIdx];
            if (!opt) return;
            selectedSurah = opt.value;
            playCurrentSelection();
            updateNavButtons();
        }
    }

    function navigateAyah(delta: number): void {
        const s = Number(selectedSurah);
        const a = Number(selectedAyah);
        if (!s || !a) return;

        const ayahs = ayahBySurah[s];
        if (!ayahs) return;
        const idx = ayahs.indexOf(a);
        const newIdx = idx + delta;

        if (newIdx >= 0 && newIdx < ayahs.length) {
            // Move within same surah
            selectedAyah = String(ayahs[newIdx]);
        } else if (delta > 0) {
            // Move to first ayah of next surah
            const sIdx = allSurahNums.indexOf(s);
            if (sIdx >= allSurahNums.length - 1) return;
            const nextS = allSurahNums[sIdx + 1];
            if (nextS === undefined) return;
            selectedSurah = String(nextS);
            populateAyahOptions();
            selectedAyah = String(ayahBySurah[nextS]?.[0] ?? '');
        } else {
            // Move to last ayah of previous surah
            const sIdx = allSurahNums.indexOf(s);
            if (sIdx <= 0) return;
            const prevS = allSurahNums[sIdx - 1];
            if (prevS === undefined) return;
            selectedSurah = String(prevS);
            populateAyahOptions();
            const prevAyahs = ayahBySurah[prevS] ?? [];
            selectedAyah = String(prevAyahs[prevAyahs.length - 1] ?? '');
        }
        playCurrentSelection();
        updateNavButtons();
    }

    function updateNavButtons(): void {
        if (currentCategory === 'by_ayah') {
            const s = Number(selectedSurah);
            const a = Number(selectedAyah);
            if (!s || !a) {
                prevDisabled = true;
                nextDisabled = true;
                return;
            }
            const ayahs = ayahBySurah[s];
            if (!ayahs) { prevDisabled = true; nextDisabled = true; return; }
            const aIdx = ayahs.indexOf(a);
            const sIdx = allSurahNums.indexOf(s);
            prevDisabled = (sIdx === 0 && aIdx === 0);
            nextDisabled = (sIdx === allSurahNums.length - 1 && aIdx === ayahs.length - 1);
        } else {
            const idx = surahOptions.findIndex(o => o.value === selectedSurah);
            prevDisabled = (idx <= 0);
            nextDisabled = (idx < 0 || idx >= surahOptions.length - 1);
        }
    }
</script>

<div class="info-bar">
    <div class="ts-view-toggle">
        <button
            class="ts-view-btn"
            class:active={selectedCategory === 'by_surah'}
            on:click={() => setCategory('by_surah')}
        >By Surah</button>
        <button
            class="ts-view-btn"
            class:active={selectedCategory === 'by_ayah'}
            on:click={() => setCategory('by_ayah')}
        >By Ayah</button>
    </div>
    <!-- svelte-ignore a11y-label-has-associated-control (control is inside SearchableSelect) -->
    <label>Reciter:
        <SearchableSelect
            options={reciterOptions}
            bind:value={selectedReciter}
            placeholder="-- Select reciter --"
            on:change={(e) => { void onReciterChange(e.detail); }}
        />
    </label>
    <!-- svelte-ignore a11y-label-has-associated-control (control is inside SearchableSelect) -->
    <label>Surah:
        <SearchableSelect
            options={surahOptions}
            bind:value={selectedSurah}
            placeholder="--"
            on:change={(e) => onSurahChange(e.detail)}
        />
    </label>
    {#if selectedCategory === 'by_ayah'}
        <!-- svelte-ignore a11y-label-has-associated-control (control is inside SearchableSelect) -->
        <label>Ayah:
            <SearchableSelect
                options={ayahOptions}
                bind:value={selectedAyah}
                placeholder="--"
                on:change={(e) => onAyahChange(e.detail)}
            />
        </label>
    {/if}
</div>
<div class="audio-controls">
    <button
        class="btn btn-nav"
        disabled={prevDisabled}
        title="Previous"
        on:click={() => navigate(-1)}
    >&#9664; Prev</button>
    <!-- id="aud-player" preserved: App.svelte switchTab() queries it to pause -->
    <audio id="aud-player" bind:this={playerEl} controls preload="none"></audio>
    <button
        class="btn btn-nav"
        disabled={nextDisabled}
        title="Next"
        on:click={() => navigate(+1)}
    >Next &#9654;</button>
</div>

<style>
    /* Audio player sizing — scoped from styles/audio-tab.css */
    #aud-player {
        width: 500px;
        flex-shrink: 1;
        min-width: 200px;
    }
</style>
