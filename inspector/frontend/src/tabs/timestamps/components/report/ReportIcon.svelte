<script lang="ts">
    /**
     * Line-icon set for the Report drop-up — one coherent stroke family
     * (24×24, currentColor, round joins) for the category rows, subtype rows,
     * and the footer Report flag. `name` selects the glyph.
     */
    let { name, size = 16 }: { name: string; size?: number } = $props();
</script>

<svg
    width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round"
    aria-hidden="true"
>
    {#if name === 'flag'}
        <path d="M5 21V4M5 4h11l-2 4 2 4H5" />
    {:else if name === 'audio'}
        <path d="M4 9v6h3.5L13 19V5L7.5 9H4z" />
        <path d="M16.5 8.5a5 5 0 010 7" />
    {:else if name === 'timing'}
        <circle cx="12" cy="12" r="8.5" />
        <path d="M12 7.5V12l3 2" />
    {:else if name === 'tajweed'}
        <path d="M4 13.5h16" />
        <path d="M6 17h5M14 17h4" />
        <path d="M8 8.5h8" />
    {:else if name === 'phonemes'}
        <path d="M5 10v4M9 7.5v9M13 6v12M17 9v6M21 11v2" />
    {:else if name === 'silence'}
        <path d="M9 6v12M15 6v12" />
    {:else if name === 'other'}
        <circle cx="6" cy="12" r="1.2" fill="currentColor" stroke="none" />
        <circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none" />
        <circle cx="18" cy="12" r="1.2" fill="currentColor" stroke="none" />
    {:else if name === 'wrong_rule'}
        <circle cx="12" cy="12" r="8.5" />
        <path d="M9.5 9.5l5 5M14.5 9.5l-5 5" />
    {:else if name === 'missing_rule'}
        <circle cx="12" cy="12" r="8.5" />
        <path d="M12 8.5v7M8.5 12h7" />
    {:else if name === 'chevron'}
        <path d="M9 6l6 6-6 6" />
    {:else if name === 'back'}
        <path d="M15 6l-6 6 6 6" />
    {:else if name === 'check'}
        <path d="M5 12.5l4.5 4.5L19 7" />
    {:else if name === 'trash'}
        <path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13" />
    {:else if name === 'edit'}
        <path d="M5 19l1-3.5 9.5-9.5 2.5 2.5L8.5 18 5 19z" />
    {/if}
</svg>
