<script lang="ts">
    /**
     * TranslationLangSelect — language picker for the word-by-word overlay.
     *
     * A compact custom listbox (native <select> can't render a badge). Complete
     * languages are listed first; languages with meaningful English-fallback
     * gaps (full-Quran measured) sit under a "Partial" divider and carry a
     * "partial" pill, so the user isn't surprised by English mixed into a
     * non-English gloss. Keyboard: Enter/Space/↓ open, ↑/↓ move, Enter select,
     * Esc close; closes on outside click.
     */
    import { i18n } from '../../../lib/i18n/locale.svelte';
    import * as m from '../../../lib/paraglide/messages';
    import type { WbwLanguage } from '../services/ts_client';

    let {
        languages = [],
        value = 'en',
        onChange,
    }: {
        languages?: WbwLanguage[];
        value?: string;
        onChange: (_code: string) => void;
    } = $props();

    let open = $state(false);
    let highlight = $state(-1);
    let rootEl: HTMLDivElement | undefined = $state();

    // Complete languages first, then partial ones (each flagged with a pill).
    const ordered = $derived([
        ...languages.filter((l) => l.complete),
        ...languages.filter((l) => !l.complete),
    ]);
    const current = $derived(languages.find((l) => l.code === value));
    const firstPartialIdx = $derived(ordered.findIndex((l) => !l.complete));

    // Reading i18n.locale here re-renders the localized chrome on a locale switch.
    const partialGroupLabel = $derived((i18n.locale, m.ts_translation_group_partial()));

    function openMenu(): void {
        open = true;
        highlight = Math.max(0, ordered.findIndex((l) => l.code === value));
    }
    function close(): void {
        open = false;
        highlight = -1;
    }
    function pick(code: string): void {
        onChange(code);
        close();
    }
    function onKey(e: KeyboardEvent): void {
        if (!open) {
            if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                openMenu();
            }
            return;
        }
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            highlight = Math.min(highlight + 1, ordered.length - 1);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            highlight = Math.max(highlight - 1, 0);
        } else if (e.key === 'Enter') {
            e.preventDefault();
            const o = ordered[highlight];
            if (o) pick(o.code);
        } else if (e.key === 'Escape') {
            e.preventDefault();
            close();
        }
    }

    $effect(() => {
        if (!open) return;
        const onDoc = (e: MouseEvent): void => {
            if (rootEl && !rootEl.contains(e.target as Node)) close();
        };
        document.addEventListener('click', onDoc);
        return () => document.removeEventListener('click', onDoc);
    });
</script>

<div class="tls" bind:this={rootEl}>
    <button
        type="button"
        class="tls-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        onclick={(e) => { e.stopPropagation(); open ? close() : openMenu(); }}
        onkeydown={onKey}
    >
        <span class="tls-current">{current?.label ?? '--'}</span>
        <span class="tls-caret" aria-hidden="true">▾</span>
    </button>
    {#if open}
        <ul class="tls-menu" role="listbox" tabindex="-1">
            {#each ordered as lang, i (lang.code)}
                {#if i === firstPartialIdx && firstPartialIdx > 0}
                    <li class="tls-group" role="presentation">{partialGroupLabel}</li>
                {/if}
                <li role="option" aria-selected={lang.code === value}>
                    <button
                        type="button"
                        class="tls-opt"
                        class:sel={lang.code === value}
                        class:hl={i === highlight}
                        onclick={(e) => { e.stopPropagation(); pick(lang.code); }}
                        onmouseenter={() => (highlight = i)}
                    >
                        <span class="tls-label">{lang.label}</span>
                        {#if !lang.complete}<span class="tls-pill">{m.ts_translation_pill_partial()}</span>{/if}
                    </button>
                </li>
            {/each}
        </ul>
    {/if}
</div>

<style>
    .tls {
        position: relative;
        flex: 0 0 auto;
    }
    .tls-trigger {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        max-width: 11rem;
        padding: 3px 8px;
        background: oklch(0.22 0.018 274);
        color: oklch(0.88 0.01 255);
        border: 1px solid oklch(0.32 0.02 274);
        border-radius: 4px;
        font-size: 0.8rem;
        cursor: pointer;
    }
    .tls-trigger:hover { border-color: oklch(0.42 0.03 274); }
    .tls-trigger:focus-visible {
        outline: 2px solid var(--anim-highlight-color);
        outline-offset: 1px;
    }
    .tls-current { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .tls-caret { font-size: 0.6rem; opacity: 0.6; }

    .tls-menu {
        position: absolute;
        top: calc(100% + 3px);
        left: 0;
        z-index: 200;
        min-width: 100%;
        max-height: 300px;
        overflow-y: auto;
        margin: 0;
        padding: 4px;
        list-style: none;
        background: oklch(0.2 0.018 274);
        border: 1px solid oklch(0.32 0.02 274);
        border-radius: 6px;
        box-shadow: 0 8px 24px oklch(0.05 0.02 274 / 0.6);
    }
    .tls-group {
        padding: 6px 8px 3px;
        font-size: 0.66rem;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: oklch(0.6 0.015 255);
        border-top: 1px solid oklch(0.3 0.015 274);
        margin-top: 4px;
    }
    .tls-opt {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        width: 100%;
        padding: 5px 8px;
        background: transparent;
        border: none;
        border-radius: 4px;
        color: oklch(0.86 0.012 255);
        font-size: 0.82rem;
        text-align: left;
        cursor: pointer;
    }
    .tls-opt.hl { background: oklch(0.3 0.025 274); }
    .tls-opt.sel { color: var(--anim-highlight-color); font-weight: 600; }
    .tls-pill {
        flex: 0 0 auto;
        padding: 1px 6px;
        border-radius: 999px;
        background: oklch(0.32 0.04 70);
        color: oklch(0.85 0.06 80);
        font-size: 0.62rem;
        letter-spacing: 0.02em;
    }
</style>
