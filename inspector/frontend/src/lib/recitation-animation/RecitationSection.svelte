<script lang="ts">
    /**
     * Collapsible "now reciting" section — the line animation plus a thin
     * header (collapse toggle + eyebrow + optional context). Designed to sit
     * directly above the dashboard audio footer; appears only while a
     * published reciter is playing (the parent gates mounting).
     */
    import { untrack } from 'svelte';

    import { type RecitationAnimConfig } from './config';
    import LineAnimation from './LineAnimation.svelte';
    import type { AnimUnit } from './types';

    interface Props {
        units: AnimUnit[];
        config: RecitationAnimConfig;
        getTimeMs: () => number;
        playing: boolean;
        /** Short context line, e.g. "Surah 36 · Al-Fatihah". */
        context?: string;
        onSeekToWord?: (ms: number) => void;
    }

    let { units, config, getTimeMs, playing, context, onSeekToWord }: Props = $props();

    // Initial-only read of the prop — `untrack` makes "snapshot, don't subscribe" explicit.
    let open = $state(untrack(() => !config.collapsedByDefault));
    let line = $state<{ refresh: () => void } | undefined>(undefined);
    let autoExpandedOnce = false;

    // Auto-expand the first time playback starts (if configured). Doesn't
    // fight a later manual collapse — only fires once per mount.
    $effect(() => {
        if (playing && config.autoExpandOnPlay && !autoExpandedOnce) {
            autoExpandedOnce = true;
            open = true;
        }
    });

    export function refresh(): void {
        line?.refresh();
    }
</script>

<section class="ra-section" class:open>
    <button
        type="button"
        class="ra-header"
        aria-expanded={open}
        onclick={() => (open = !open)}
    >
        <span class="caret" class:open aria-hidden="true">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="m6 9 6 6 6-6" />
            </svg>
        </span>
        <span class="eyebrow">Now reciting</span>
        {#if context}<span class="context">{context}</span>{/if}
    </button>

    {#if open}
        <div class="ra-body">
            <LineAnimation
                bind:this={line}
                {units}
                {config}
                {getTimeMs}
                {playing}
                {onSeekToWord}
            />
        </div>
    {/if}
</section>

<style>
    .ra-section {
        border-bottom: 1px solid var(--border-quiet);
    }
    .ra-header {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        width: 100%;
        padding: 4px var(--s-1);
        color: var(--text-muted);
        transition: color var(--t-fast);
    }
    .ra-header:hover {
        color: var(--text-secondary);
    }
    .caret {
        display: inline-flex;
        transition: transform var(--t-fast) var(--ease-out-quart);
        transform: rotate(-90deg);
    }
    .caret.open {
        transform: rotate(0deg);
    }
    .eyebrow {
        font-size: var(--fs-meta);
        letter-spacing: 0.04em;
        text-transform: uppercase;
    }
    .context {
        font-size: var(--fs-meta);
        color: var(--text-faint);
    }
    .ra-body {
        padding: var(--s-1) var(--s-2) var(--s-3);
    }
</style>
