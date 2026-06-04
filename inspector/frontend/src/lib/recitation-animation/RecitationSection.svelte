<script lang="ts">
    /**
     * Collapsible "now reciting" section — the line animation plus a thin
     * header (collapse toggle + eyebrow + optional context + optional actions).
     * Designed to sit directly above the dashboard audio footer; appears only
     * while a published reciter is playing (the parent gates mounting).
     *
     * `open` is bindable so the consumer can persist + control the collapse
     * state (the dashboard caches it and defaults expanded on a published
     * selection). `headerActions` is an optional right-aligned snippet for
     * surface-specific controls (e.g. the dashboard customize gear) — kept as a
     * snippet so the shared lib never imports a dashboard component.
     */
    import { type Snippet, untrack } from 'svelte';

    import { type RecitationAnimConfig } from './config';
    import LineAnimation from './LineAnimation.svelte';
    import type { AnimUnit } from './types';

    interface Props {
        units: AnimUnit[];
        config: RecitationAnimConfig;
        getTimeMs: () => number;
        playing: boolean;
        /** Short context line, e.g. "Surah 36 · Al-Fatihah". Omit to hide. */
        context?: string;
        /** Header eyebrow label; '' hides it (slim chrome — just the caret). */
        eyebrow?: string;
        onSeekToWord?: (_ms: number) => void;
        /** Two-way collapse state. Defaults from `config.collapsedByDefault`. */
        open?: boolean;
        /** Render the header row (caret + eyebrow + actions). When false the
         *  section is just the centered line body (collapse is driven
         *  externally, e.g. from the footer controls). */
        showHeader?: boolean;
        /** Right-aligned header controls (e.g. a customize gear). */
        headerActions?: Snippet;
    }

    let {
        units,
        config,
        getTimeMs,
        playing,
        context,
        eyebrow = 'Now reciting',
        onSeekToWord,
        open = $bindable(untrack(() => !config.collapsedByDefault)),
        showHeader = true,
        headerActions,
    }: Props = $props();

    let line = $state<{ refresh: () => void } | undefined>(undefined);

    export function refresh(): void {
        line?.refresh();
    }
</script>

<section class="ra-section" class:open>
    {#if showHeader}
    <div class="ra-header">
        <button
            type="button"
            class="ra-toggle"
            aria-expanded={open}
            onclick={() => (open = !open)}
        >
            <span class="caret" class:open aria-hidden="true">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="m6 9 6 6 6-6" />
                </svg>
            </span>
            {#if eyebrow}<span class="eyebrow">{eyebrow}</span>{/if}
            {#if context}<span class="context">{context}</span>{/if}
        </button>
        {#if headerActions}
            <span class="ra-actions">{@render headerActions()}</span>
        {/if}
    </div>
    {/if}

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
    }
    .ra-toggle {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        flex: 1 1 auto;
        min-width: 0;
        padding: 4px var(--s-1);
        color: var(--text-muted);
        background: transparent;
        border: 0;
        cursor: pointer;
        transition: color var(--t-fast);
    }
    .ra-toggle:hover {
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
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .ra-actions {
        display: inline-flex;
        align-items: center;
        flex: 0 0 auto;
        margin-left: auto;
        padding-right: var(--s-1);
    }
    /* Symmetric vertical padding so the single line reads vertically centered
     *  (the controls moved to the footer, so there's no header offsetting it). */
    .ra-body {
        padding: var(--s-2) var(--s-2);
    }
</style>
