<!--
  LocaleSwitcher — a single button cycling Auto → English → عربي → Auto, the
  sibling of ThemeToggle in the header.

  It shows ONE language at a time (its endonym), never a segmented pair. 'Auto'
  (the default) follows the browser's language and is marked by the leading globe;
  an explicit choice pins the locale (Paraglide's `insp_locale` key) and drops the
  globe, leaving just the word. Fully token-driven so it re-skins for light AND dark.
-->
<script lang="ts">
    import * as m from '$lib/paraglide/messages';
    import { i18n, type Locale } from '$lib/i18n/locale.svelte';

    // Each language in its own name — data, not translated by the active UI locale.
    const ENDONYMS: Record<Locale, string> = { en: 'English', ar: 'عربي' };

    const mode = $derived(i18n.mode);
    const isAuto = $derived(mode === 'auto');
    // In auto mode show the resolved locale; when pinned, the pinned one.
    // (`mode === 'auto'` narrows the else branch to Locale; `isAuto` would not.)
    const shown = $derived<Locale>(mode === 'auto' ? i18n.locale : mode);

    // Reading i18n.locale keeps the tooltip reactive across switches.
    const label = $derived(
        (i18n.locale,
        isAuto
            ? m.common_locale_toggle_auto_label()
            : mode === 'ar'
              ? m.common_locale_toggle_ar_label()
              : m.common_locale_toggle_en_label()),
    );
</script>

<button
    type="button"
    class="locale-toggle"
    class:auto={isAuto}
    title={label}
    aria-label={label}
    onclick={() => i18n.cycle()}
>
    {#if isAuto}
        <!-- globe = following the browser (auto); dropped once a locale is pinned -->
        <svg class="glyph" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="9" />
            <path d="M3 12h18" />
            <path d="M12 3c2.6 2.7 3.9 5.9 3.9 9s-1.3 6.3-3.9 9c-2.6-2.7-3.9-5.9-3.9-9s1.3-6.3 3.9-9z" />
        </svg>
    {/if}
    <span class="name" lang={shown}>{ENDONYMS[shown] ?? shown}</span>
</button>

<style>
    .locale-toggle {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        height: 32px;
        padding: 0 9px;
        border: 1px solid var(--border-default);
        background: var(--panel);
        color: var(--text-secondary);
        border-radius: var(--r-2);
        font: inherit;
        font-size: 0.8125rem;
        line-height: 1;
        cursor: pointer;
        transition:
            background var(--t-fast),
            color var(--t-fast),
            border-color var(--t-fast);
    }
    .locale-toggle:hover {
        background: var(--panel-2);
        border-color: var(--accent);
        color: var(--accent);
    }
    .locale-toggle:focus-visible {
        outline: 2px solid var(--accent);
        outline-offset: 2px;
    }
    .glyph {
        flex: none;
        opacity: 0.85;
    }
    .name {
        font-weight: 500;
    }
    /* The Arabic endonym reads better a touch larger against the Latin metrics. */
    .name:lang(ar) {
        font-size: 0.9375rem;
    }
</style>
