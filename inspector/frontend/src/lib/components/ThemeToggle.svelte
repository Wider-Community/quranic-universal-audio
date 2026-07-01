<!--
  ThemeToggle — a single icon button cycling System → Light → Dark → System.

  System (the default) follows the device's prefers-color-scheme live; Light and
  Dark are explicit overrides. The icon shows the current MODE (monitor / sun /
  moon) so "following the device" is legible, not hidden. Fully token-driven so
  it re-skins itself.
-->
<script lang="ts">
    import { themeStore } from '../stores/theme.svelte';

    const mode = $derived(themeStore.mode);
    const label = $derived(
        mode === 'system'
            ? 'Theme: following your device — click for light'
            : mode === 'light'
              ? 'Theme: light — click for dark'
              : 'Theme: dark — click to follow your device',
    );
</script>

<button
    type="button"
    class="theme-toggle"
    title={label}
    aria-label={label}
    onclick={() => themeStore.cycle()}
>
    {#if mode === 'system'}
        <!-- monitor (following device) -->
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <rect x="2" y="3" width="20" height="14" rx="2" />
            <path d="M8 21h8M12 17v4" />
        </svg>
    {:else if mode === 'light'}
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
</button>

<style>
    .theme-toggle {
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
