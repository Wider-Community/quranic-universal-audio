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
    import { buildGroupedReciters, reciterGroupsToOptions } from '../../../lib/utils/grouped-reciters';
    import { LS_KEYS, PLACEHOLDER_SELECT } from '../../../lib/utils/constants';
    import type { TsReciter } from '../../../lib/types/domain';

    const dispatch = createEventDispatcher<{
        reciterChange: string;
        chapterChange: string;
        verseChange: string;
    }>();

    // ---- Grouped reciter options ----
    $: groupedReciters = buildGroupedReciters($reciters as TsReciter[]);
    $: reciterOptions = reciterGroupsToOptions(groupedReciters);
</script>

<div class="info-bar">
    <!-- svelte-ignore a11y-label-has-associated-control (control is inside SearchableSelect) -->
    <label>Reciter:
        <SearchableSelect
            options={reciterOptions}
            bind:value={$selectedReciter}
            placeholder={$reciters.length ? PLACEHOLDER_SELECT : 'Loading...'}
            on:change={(e) => dispatch('reciterChange', e.detail)}
        />
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
    <!-- svelte-ignore a11y-label-has-associated-control (control is inside SearchableSelect) -->
    <label>Ayah:
        <SearchableSelect
            options={$versesOptions}
            bind:value={$selectedVerse}
            placeholder="--"
            on:change={(e) => dispatch('verseChange', e.detail)}
        />
    </label>
    <SpeedControl bind:this={_speedCtrl} audioElement={$tsAudioElement} lsKey={LS_KEYS.TS_SPEED} />
</div>
