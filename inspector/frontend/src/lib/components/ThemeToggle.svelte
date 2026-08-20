<!--
  ThemeToggle — a single icon button cycling System → Light → Dark → System.

  The icon always shows the RESOLVED appearance (sun = light, moon = dark). In
  System mode (the default, following the device's prefers-color-scheme live) a
  small monitor badge is pinned to the corner to mark it as device-driven —
  so the button reads as "this is what you're seeing, and it's automatic",
  rather than hiding the current look behind a monitor glyph. Token-driven so it
  re-skins itself.
-->
<script lang="ts">
    import * as m from '$lib/paraglide/messages';
    import { i18n } from '$lib/i18n/locale.svelte';
    import { themeStore } from '../stores/theme.svelte';
    import AutoBadge from './AutoBadge.svelte';

    const mode = $derived(themeStore.mode);
    const isSystem = $derived(mode === 'system');
    // The icon reflects the resolved theme (what's on screen), in every mode.
    const resolved = $derived(themeStore.current);
    const label = $derived(
        (i18n.locale,
        mode === 'system'
            ? m.common_theme_toggle_system_label()
            : mode === 'light'
              ? m.common_theme_toggle_light_label()
              : m.common_theme_toggle_dark_label()),
    );
</script>

<button
    type="button"
    class="theme-toggle"
    class:auto={isSystem}
    title={label}
    aria-label={label}
    onclick={() => themeStore.cycle()}
>
    {#if resolved === 'light'}
        <!-- sun -->
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
        </svg>
    {:else}
        <!-- moon -->
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
    {/if}
    {#if isSystem}
        <AutoBadge />
    {/if}
</button>

<style>
    .theme-toggle {
        position: relative;
        display: grid;
        place-items: center;
        width: 32px;
        height: 32px;
        border: 1px solid var(--border-default);
        background: var(--panel);
        color: var(--text-secondary);
        border-radius: var(--r-2);
        cursor: pointer;
        transition: background var(--t-fast), color var(--t-fast), border-color var(--t-fast);
    }
    .theme-toggle:hover {
        background: var(--panel-2);
        border-color: var(--accent);
        color: var(--accent);
    }
    .theme-toggle:focus-visible {
        outline: 2px solid var(--accent);
        outline-offset: 2px;
    }
</style>
