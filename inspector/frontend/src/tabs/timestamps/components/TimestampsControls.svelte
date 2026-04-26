<script lang="ts">
    import { createEventDispatcher } from 'svelte';

    import SearchableSelect from '../../../lib/components/SearchableSelect.svelte';
    import SpeedControl from '../../../lib/components/SpeedControl.svelte';

    // Speed control ref — exposed to the parent via cycleSpeed so keyboard
    // shortcuts (, and .) can drive the same widget that lives in the info-bar.
    let _speedCtrl: SpeedControl;
    export function cycleSpeed(direction: 'up' | 'down'): void {
        _speedCtrl?.cycle(direction);
    }
    import {
        chaptersOptions,
        reciters,
        selectedChapter,
        selectedReciter,
        selectedVerse,
        versesOptions,
    } from '../stores/verse';
    import { tsAudioElement } from '../stores/playback';
    import { buildGroupedReciters } from '../../../lib/utils/grouped-reciters';
    import { LS_KEYS, PLACEHOLDER_SELECT } from '../../../lib/utils/constants';
    import type { TsReciter } from '../../../lib/types/domain';

    const dispatch = createEventDispatcher<{
        reciterChange: string;
        chapterChange: string;
        verseChange: string;
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
</script>

<div class="info-bar">
    <label>Reciter:
        <select
            id="ts-reciter-select"
            bind:value={$selectedReciter}
            on:change={onReciterSelectChange}
        >
            <option value="">{$reciters.length ? PLACEHOLDER_SELECT : 'Loading...'}</option>
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
    <label>Surah:
        <SearchableSelect
            options={$chaptersOptions}
            bind:value={$selectedChapter}
            placeholder="--"
            on:change={(e) => dispatch('chapterChange', e.detail)}
        />
    </label>
    <label>Ayah:
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
    <SpeedControl bind:this={_speedCtrl} audioElement={$tsAudioElement} lsKey={LS_KEYS.TS_SPEED} />
</div>
