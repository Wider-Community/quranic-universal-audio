<script lang="ts">
    /**
     * Inline SVG icon. Renders the raw markup from `./index.ts` via {@html}
     * so `currentColor` strokes/fills cascade from the parent. Size defaults
     * to 14px — set explicitly for surfaces that need a larger glyph
     * (e.g. <Icon name="autoscroll" size={17} /> in the segments footer).
     */
    import { type IconName,ICONS } from './index';

    export let name: IconName;
    export let size: number = 14;
    /** Optional aria-label for icon-only buttons. */
    export let label: string | undefined = undefined;
</script>

<span
    class="icon"
    style:width="{size}px"
    style:height="{size}px"
    role={label ? 'img' : undefined}
    aria-label={label}
    aria-hidden={label ? undefined : true}
>
    <!-- eslint-disable-next-line svelte/no-at-html-tags -->
    {@html ICONS[name]}
</span>

<style>
    .icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        flex-shrink: 0;
        line-height: 0;
    }
    .icon :global(svg) {
        width: 100%;
        height: 100%;
        display: block;
    }
</style>
