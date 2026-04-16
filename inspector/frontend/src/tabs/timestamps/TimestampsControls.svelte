<script lang="ts">
    import { createEventDispatcher } from 'svelte';

    import SearchableSelect from '../../lib/components/SearchableSelect.svelte';
    import {
        autoMode,
    } from '../../lib/stores/timestamps/playback';
    import {
        granularity,
        showLetters,
        showPhonemes,
        viewMode,
    } from '../../lib/stores/timestamps/display';
    import {
        chaptersOptions,
        reciters,
        selectedChapter,
        selectedReciter,
        selectedVerse,
        versesOptions,
    } from '../../lib/stores/timestamps/verse';
    import { buildGroupedReciters } from '../../lib/utils/grouped-reciters';
    import { LS_KEYS } from '../../lib/utils/constants';
    import type { TsReciter } from '../../types/domain';

    const dispatch = createEventDispatcher<{
        reciterChange: string;
        chapterChange: string;
        verseChange: string;
        randomAny: void;
        randomCurrent: void;
    }>();

    // ---- Grouped reciter options ----
    $: groupedReciters = buildGroupedReciters($reciters as TsReciter[]);

    // ---- Event handlers ----
    function onReciterSelectChange(e: Event): void {
        const v = (e.currentTarget as HTMLSelectElement).value;
        dispatch('reciterChange', v);
    }

    function onVerseSelectChange(e: Event): void {
        const v = (e.currentTarget as HTMLSelectElement).value;
        dispatch('verseChange', v);
    }

    // ---- View/mode/auto toggles ----
    export function setView(mode: 'analysis' | 'animation'): void {
        viewMode.set(mode);
        localStorage.setItem(LS_KEYS.TS_VIEW_MODE, mode);
        if (mode === 'analysis') {
            showLetters.set(true);
            showPhonemes.set(false);
        } else {
            granularity.set('words');
        }
    }

    export function toggleModeA(): void {
        if ($viewMode === 'analysis') {
            const nv = !$showLetters;
            showLetters.set(nv);
            localStorage.setItem(LS_KEYS.TS_SHOW_LETTERS, String(nv));
        } else {
            granularity.set('words');
            localStorage.setItem(LS_KEYS.TS_GRANULARITY, 'words');
        }
    }

    export function toggleModeB(): void {
        if ($viewMode === 'analysis') {
            const nv = !$showPhonemes;
            showPhonemes.set(nv);
            localStorage.setItem(LS_KEYS.TS_SHOW_PHONEMES, String(nv));
        } else {
            granularity.set('characters');
            localStorage.setItem(LS_KEYS.TS_GRANULARITY, 'characters');
        }
    }

    export function toggleAuto(mode: 'next' | 'random'): void {
        autoMode.update((cur) => (cur === mode ? null : mode));
    }
</script>

<div class="info-bar">
    <label>Reciter:
        <select
            id="ts-reciter-select"
            bind:value={$selectedReciter}
            on:change={onReciterSelectChange}
        >
            <option value="">{$reciters.length ? '-- select --' : 'Loading...'}</option>
            {#each groupedReciters as g}
                <optgroup label={g.group}>
                    {#each g.items as r}
                        <option value={r.slug}>{r.name}</option>
                    {/each}
                </optgroup>
            {/each}
        </select>
    </label>
    <!-- svelte-ignore a11y-label-has-associated-control (control is inside SearchableSelect) -->
    <label>Chapter:
        <SearchableSelect
            options={$chaptersOptions}
            bind:value={$selectedChapter}
            placeholder="--"
            on:change={(e) => dispatch('chapterChange', e.detail)}
        />
    </label>
    <label>Verse:
        <select
            id="ts-segment-select"
            bind:value={$selectedVerse}
            on:change={onVerseSelectChange}
        >
            <option value="">--</option>
            {#each $versesOptions as v}
                <option value={v.value}>{v.label}</option>
            {/each}
        </select>
    </label>
    <div class="ts-random-group">
        <button class="btn" title="Random verse from any reciter"
            on:click={() => dispatch('randomAny')}>🎲 Any Reciter</button>
        <button class="btn" title="Random verse from current reciter"
            on:click={() => dispatch('randomCurrent')}>🎲 Current Reciter</button>
    </div>
</div>

<div class="ts-view-controls">
    <div class="ts-view-toggle">
        <button class="ts-view-btn" class:active={$viewMode === 'analysis'}
            on:click={() => setView('analysis')}>Analysis</button>
        <button class="ts-view-btn" class:active={$viewMode === 'animation'}
            on:click={() => setView('animation')}>Animation</button>
    </div>
    <div class="ts-mode-toggle">
        <button class="ts-mode-btn"
            class:active={$viewMode === 'analysis' ? $showLetters : $granularity === 'words'}
            on:click={toggleModeA}>
            {$viewMode === 'analysis' ? 'Letters' : 'Words'}
        </button>
        <button class="ts-mode-btn"
            class:active={$viewMode === 'analysis' ? $showPhonemes : $granularity === 'characters'}
            on:click={toggleModeB}>
            {$viewMode === 'analysis' ? 'Phonemes' : 'Letters'}
        </button>
    </div>
    <div class="ts-auto-toggles">
        <button class="ts-auto-btn" class:active={$autoMode === 'next'}
            title="Auto-advance to next verse" on:click={() => toggleAuto('next')}>Auto Next</button>
        <button class="ts-auto-btn" class:active={$autoMode === 'random'}
            title="Auto-load random verse (any reciter)" on:click={() => toggleAuto('random')}>Auto Random</button>
    </div>
</div>
