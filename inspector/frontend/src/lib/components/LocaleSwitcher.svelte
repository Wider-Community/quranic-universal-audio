<!--
    Locale switcher (Svelte 5 runes). Toggles the SPA between English and
    Arabic in-place (no reload) via the shared `i18n` rune. Reading
    `i18n.locale` keeps the active-state highlight reactive; switching updates
    every `m.*()` read app-wide plus <html dir/lang>.
-->
<script lang="ts">
    import * as m from '$lib/paraglide/messages';
    import { i18n, type Locale } from '$lib/i18n/locale.svelte';

    const LABELS: Record<Locale, string> = { en: 'EN', ar: 'ع' };
    // Reading i18n.locale makes this $derived re-run on switch.
    const groupAriaLabel = $derived((i18n.locale, m.common_locale_switcher_aria_label()));
</script>

<div class="locale-switcher" role="group" aria-label={groupAriaLabel}>
    {#each i18n.locales as loc (loc)}
        <button
            type="button"
            class="locale-btn"
            class:active={i18n.locale === loc}
            aria-pressed={i18n.locale === loc}
            lang={loc}
            onclick={() => i18n.set(loc)}
        >
            {LABELS[loc] ?? loc}
        </button>
    {/each}
</div>

<style>
    .locale-switcher {
        display: inline-flex;
        gap: 2px;
        align-items: center;
    }
    .locale-btn {
        border: 1px solid #333;
        background: #16213e;
        color: #ccc;
        padding: 4px 9px;
        border-radius: 6px;
        cursor: pointer;
        font-size: 0.85rem;
        line-height: 1;
        transition:
            background 0.2s,
            border-color 0.2s,
            color 0.2s;
    }
    .locale-btn:hover {
        border-color: #4cc9f0;
        color: #4cc9f0;
    }
    .locale-btn.active {
        background: #1a2a4e;
        border-color: #4cc9f0;
        color: #4cc9f0;
        font-weight: 600;
    }
</style>
