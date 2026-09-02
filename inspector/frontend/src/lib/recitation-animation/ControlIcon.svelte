<script lang="ts">
    /**
     * Tiny inline SVG icon set for the now-reciting footer controls. Single
     * source for the chosen glyphs (granularity bar/dots, eye states, droplet,
     * filmstrip motion, size −/+) so the section header and the filmstrip edge
     * render identical icons. All inherit `currentColor`.
     *
     * `tajweed` is the one exception: rather than an SVG glyph it renders a real
     * analysis cell (the same 3px-rounded shape) reading `TJW`, with three of the
     * cell's own stacked underline bars — each bar cycling three `--tj-*` palette
     * hues — so the icon literally is the stacked-underline feature it opens. It
     * uses the live palette vars, not `currentColor`.
     */
    interface Props {
        name:
            | 'gran-word' | 'gran-letter'
            | 'eye-full' | 'eye-dim' | 'eye-hidden'
            | 'droplet'
            | 'motion-hybrid' | 'motion-snap'
            | 'size-down' | 'size-up'
            | 'silent-cohighlight' | 'silent-omit'
            | 'letters' | 'phonemes' | 'globe' | 'tajweed' | 'wipe'
            | 'bookmark' | 'bookmark-filled' | 'bookmarks-panel' | 'help';
        size?: number;
    }
    let { name, size = 17 }: Props = $props();

    // Real Arabic letters (the Arabic "abc/A"): word = أبت (a few letters),
    // letter = أ (single, with hamza), size = أ small vs large. Rendered as SVG
    // text so they inherit currentColor; an Arabic-capable system font shapes
    // the glyphs.
    const AR = 'font-family="Tahoma,\'Segoe UI\',\'Noto Naskh Arabic\',sans-serif" font-weight="600" fill="currentColor" text-anchor="middle" direction="rtl"';
    const P: Partial<Record<Props['name'], string>> = {
        'gran-word':
            `<text x="12" y="16.5" font-size="12.5" ${AR}>أبت</text>`,
        'gran-letter':
            `<text x="12" y="17" font-size="16" ${AR}>ب</text>`,
        'eye-full':
            '<path d="M2 12C5 4.5 19 4.5 22 12 19 19.5 5 19.5 2 12Z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/>'
            + '<circle cx="12" cy="12" r="3.3" fill="currentColor"/>',
        'eye-dim':
            '<path d="M2.5 13.5C5.5 7.5 18.5 7.5 21.5 13.5" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>'
            + '<circle cx="12" cy="13.7" r="2.6" fill="currentColor"/>',
        'eye-hidden':
            '<path d="M2 12C5 4.5 19 4.5 22 12 19 19.5 5 19.5 2 12Z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round" opacity=".5"/>'
            + '<line x1="3.5" y1="20.5" x2="20.5" y2="3.5" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>',
        // Silent-letter paint policy. A small sounding mark sits above its
        // written host: solid host = co-highlight; dashed host = keep visible
        // but omit from the highlight. State is carried by shape, not colour.
        'silent-cohighlight':
            '<circle cx="15.2" cy="5.8" r="2.2" fill="currentColor"/>'
            + '<path d="M4.2 13.1c1.8 5.4 11.7 6.5 15.6 0v2.8c-4.9 5.1-14 4-15.6-2.8Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
        'silent-omit':
            '<circle cx="15.2" cy="5.8" r="2.2" fill="currentColor"/>'
            + '<path d="M4.2 13.1c.8 2.5 2.8 4 5.2 4.6M14.3 17.7c2.3-.7 4.4-2.2 5.5-4.6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
        'droplet':
            '<path d="M12 3s-7 8-7 12a7 7 0 0 0 14 0c0-4-7-12-7-12Z" fill="currentColor"/>',
        // Continuous glide: a knob on a track with directional chevrons (slides
        // freely so the playhead stays centered).
        'motion-hybrid':
            '<line x1="5" y1="12" x2="19" y2="12" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>'
            + '<path d="M4 9.8 2.3 12 4 14.2M20 9.8 21.7 12 20 14.2" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/>'
            + '<circle cx="12" cy="12" r="3.1" fill="currentColor"/>',
        // Snap to ayah: a magnet.
        'motion-snap':
            '<path d="M7 5v6a5 5 0 0 0 10 0V5" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>'
            + '<rect x="5.3" y="3" width="3.4" height="2.9" rx="0.6" fill="currentColor"/>'
            + '<rect x="15.3" y="3" width="3.4" height="2.9" rx="0.6" fill="currentColor"/>',
        // Zoom out / zoom in (magnifier with − / +) → smaller / larger text.
        'size-down':
            '<circle cx="10" cy="10" r="6.3" fill="none" stroke="currentColor" stroke-width="1.9"/>'
            + '<line x1="14.9" y1="14.9" x2="20.5" y2="20.5" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"/>'
            + '<line x1="7.2" y1="10" x2="12.8" y2="10" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>',
        'size-up':
            '<circle cx="10" cy="10" r="6.3" fill="none" stroke="currentColor" stroke-width="1.9"/>'
            + '<line x1="14.9" y1="14.9" x2="20.5" y2="20.5" stroke="currentColor" stroke-width="2.1" stroke-linecap="round"/>'
            + '<line x1="7.2" y1="10" x2="12.8" y2="10" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>'
            + '<line x1="10" y1="7.2" x2="10" y2="12.8" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"/>',
        // Letters tier: a single Arabic letter.
        'letters':
            `<text x="12" y="17" font-size="15" ${AR}>ب</text>`,
        // Phonemes tier: spoken sound — a soundwave (varying-height bars).
        'phonemes':
            '<g stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none">'
            + '<line x1="4" y1="11" x2="4" y2="13"/>'
            + '<line x1="7.2" y1="8.5" x2="7.2" y2="15.5"/>'
            + '<line x1="10.4" y1="5.5" x2="10.4" y2="18.5"/>'
            + '<line x1="13.6" y1="8" x2="13.6" y2="16"/>'
            + '<line x1="16.8" y1="10" x2="16.8" y2="14"/>'
            + '<line x1="20" y1="7" x2="20" y2="17"/>'
            + '</g>',
        // Continuous-highlight (karaoke wipe): a cell filling like liquid — a
        // wave level inside the rounded cell, signalling the fill that tracks the
        // voice across each cell (vs the discrete fill when off).
        'wipe':
            '<rect x="3.5" y="4.5" width="17" height="15" rx="3" fill="none" stroke="currentColor" stroke-width="1.8"/>'
            + '<path d="M4.5 12.8q3.75-2.6 7.5 0t7.5 0L19.5 17.2a2.3 2.3 0 0 1-2.3 2.3L6.8 19.5a2.3 2.3 0 0 1-2.3-2.3Z" fill="currentColor"/>',
        // Translations: a globe (languages).
        'globe':
            '<circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="1.8"/>'
            + '<path d="M3.5 12h17" stroke="currentColor" stroke-width="1.4"/>'
            + '<path d="M12 3.5c2.6 2.3 2.6 14.7 0 17M12 3.5c-2.6 2.3-2.6 14.7 0 17" fill="none" stroke="currentColor" stroke-width="1.4"/>'
            + '<path d="M5.2 7.2c2.1 1.3 11.5 1.3 13.6 0M5.2 16.8c2.1-1.3 11.5-1.3 13.6 0" fill="none" stroke="currentColor" stroke-width="1.4"/>',
        // Bookmark (outline + filled).
        'bookmark':
            '<path d="M6 4h12v16l-6-4-6 4Z" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/>',
        'bookmark-filled':
            '<path d="M6 4h12v16l-6-4-6 4Z" fill="currentColor" stroke="currentColor" stroke-width="1.9" stroke-linejoin="round"/>',
        // Bookmarks panel: a side panel (left rail) with a bookmark tab inside.
        'bookmarks-panel':
            '<rect x="3.5" y="4" width="17" height="16" rx="2.2" fill="none" stroke="currentColor" stroke-width="1.8"/>'
            + '<line x1="9" y1="4" x2="9" y2="20" stroke="currentColor" stroke-width="1.6"/>'
            + '<path d="M12.5 7.5h5v6l-2.5-1.7-2.5 1.7Z" fill="currentColor"/>',
        // Help / shortcuts guide: question mark in a rounded square.
        'help':
            '<rect x="3.5" y="3.5" width="17" height="17" rx="4" fill="none" stroke="currentColor" stroke-width="1.8"/>'
            + '<path d="M9.3 9.2a2.7 2.7 0 0 1 5.2 1c0 1.8-2.5 2-2.5 3.6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>'
            + '<circle cx="12" cy="17" r="1.05" fill="currentColor"/>',
    };
</script>

<span
    class="ci"
    class:ci-fill={name === 'tajweed'}
    style:width={name === 'tajweed' ? null : `${size}px`}
    style:height={name === 'tajweed' ? null : `${size}px`}
    aria-hidden="true"
>
    {#if name === 'tajweed'}
        <span class="tjw" style:font-size="{size}px">
            <span class="tjw-txt">TJW</span>
            <span class="tjw-ul">
                <span class="tjw-bar">
                    <i style:background="var(--tj-qalqala)"></i>
                    <i style:background="var(--tj-izhar-halqi)"></i>
                    <i style:background="var(--tj-madd-arid)"></i>
                </span>
            </span>
        </span>
    {:else}
        <!-- Static internal SVG table (no user input) — safe to inline. -->
        <!-- eslint-disable-next-line svelte/no-at-html-tags -->
        {@html `<svg viewBox="0 0 24 24" width="100%" height="100%">${P[name] ?? ''}</svg>`}
    {/if}
</span>

<style>
    .ci { display: inline-flex; line-height: 0; }
    .ci :global(svg) { display: block; }
    /* The tajweed icon fills its footer button so its underline spans the whole
       (blue, on hover/active) cell. */
    .ci-fill { width: 100%; height: 100%; }

    /* The tajweed icon IS the footer button cell: borderless + transparent so the
       button's own (blue, on hover/active) fill reads as the cell, with a big
       top-pinned TJW over one underline bar cycling three palette hues spanning the
       full width. overflow-hidden + the button-matched radius clip the bar to the
       rounded bottom; the bar ends round so it bleeds to the edge like a live cell. */
    .tjw {
        position: relative;
        width: 100%;
        height: 100%;
        display: flex;
        align-items: center;
        justify-content: center;
        /* Reserve the underline strip so TJW centres in the space ABOVE it — equal
           gap from the top edge and from the colours. */
        padding-bottom: 0.14em;
        background: transparent;
        border-radius: var(--r-2, 5px);
        overflow: hidden;
    }
    .tjw-txt {
        font-size: 0.62em;
        font-weight: 700;
        letter-spacing: -0.07em;
        line-height: 1;
        /* Inherit the footer button's icon colour (muted → primary on hover →
           accent on active) so TJW matches its sibling icons in every state. */
        color: inherit;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }
    .tjw-ul {
        position: absolute;
        left: 0;
        right: 0;
        bottom: 0;
        display: flex;
        flex-direction: column;
    }
    .tjw-bar { display: flex; height: 0.14em; }
    .tjw-bar i { flex: 1; display: block; }
    .tjw-bar i:first-child {
        border-top-left-radius: 1.5px;
        border-bottom-left-radius: 1.5px;
    }
    .tjw-bar i:last-child {
        border-top-right-radius: 1.5px;
        border-bottom-right-radius: 1.5px;
    }
</style>
