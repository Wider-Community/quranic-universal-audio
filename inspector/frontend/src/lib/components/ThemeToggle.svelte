<!--
  ThemeToggle — a single icon button that flips light/dark via the theme store.

  Shows the icon of the theme you'd switch TO (moon while light, sun while dark),
  the conventional affordance. Styled to sit in the header's .auth-controls
  cluster alongside the auth button; fully token-driven so it re-skins itself.
-->
<script lang="ts">
    import { themeStore } from '../stores/theme.svelte';

    const isLight = $derived(themeStore.isLight);
    const label = $derived(isLight ? 'Switch to dark theme' : 'Switch to light theme');
</script>

<button
    type="button"
    class="theme-toggle"
    title={label}
    aria-label={label}
    onclick={() => themeStore.toggle()}
>
    {#if isLight}
        <!-- moon -->
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
        </svg>
    {:else}
        <!-- sun -->
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="4" />
            <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
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
