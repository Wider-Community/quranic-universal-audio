<script lang="ts">
    /**
     * Surah picker popover — wraps SearchableSelect with the same
     * Arabic-normalizing fuzzy search the timestamps + segments tabs
     * use. The label uses surahOptionText() so users see the same
     * format ("3 Ali Imran الْعِمْرَانَ") they're used to elsewhere.
     */
    import { createEventDispatcher, onMount } from 'svelte';

    import SearchableSelect from '../SearchableSelect.svelte';
    import type { SelectOption } from '../../types/ui';
    import { getSurahInfo, surahInfoReady, surahOptionText } from '../../utils/surah-info';

    export let surahNums: number[] = [];
    export let value: number | null = null;

    let ready = false;
    let options: SelectOption[] = [];

    onMount(async () => {
        await surahInfoReady;
        ready = true;
    });

    $: if (ready && surahNums.length > 0) {
        const _info = getSurahInfo();
        void _info; // ensure deps tracked
        options = surahNums.map((n) => ({
            value: String(n),
            label: surahOptionText(n),
        }));
    }

    const dispatch = createEventDispatcher<{ change: number }>();

    function onChange(ev: CustomEvent<string>): void {
        const n = parseInt(ev.detail, 10);
        if (!Number.isNaN(n)) dispatch('change', n);
    }
</script>

<div class="wrap">
    <SearchableSelect
        options={options}
        value={value === null ? '' : String(value)}
        placeholder="Pick a surah"
        on:change={onChange}
    />
</div>

<style>
    .wrap {
        width: 340px;
    }
    .wrap :global(.ss-input) {
        background: var(--panel);
        border-color: var(--border-quiet);
        color: var(--text-primary);
    }
    .wrap :global(.ss-input:focus) {
        border-color: var(--accent);
    }
</style>
