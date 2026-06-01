<svelte:options runes={true} />

<script lang="ts">
    /**
     * Translations control for the Timestamps footer — a globe button that opens
     * a drop-up of word-by-word languages (complete first, then a "Partial"
     * group). Picking a language enables translations with it; the "Off" entry
     * disables. Globe shows active while translations are on. Reuses
     * `loadWbwLanguages` + the ordering convention from `TranslationLangSelect`.
     */
    import { onMount } from 'svelte';

    import { clickOutside } from '../../../lib/actions/click-outside';
    import { ControlIcon } from '../../../lib/recitation-animation';
    import { LS_KEYS } from '../../../lib/utils/constants';
    import { loadWbwLanguages, type WbwLanguage } from '../services/ts_client';
    import { showTranslations, translationLanguage } from '../stores/display';

    let open = $state(false);
    let languages = $state<WbwLanguage[]>([{ code: 'en', label: 'English', complete: true }]);

    onMount(() => {
        loadWbwLanguages()
            .then((l) => { if (l.length) languages = l; })
            .catch(() => { /* keep fallback */ });
    });

    const ordered = $derived([
        ...languages.filter((l) => l.complete),
        ...languages.filter((l) => !l.complete),
    ]);
    const firstPartial = $derived(ordered.findIndex((l) => !l.complete));

    function persist(key: string, v: string): void {
        try { localStorage.setItem(key, v); } catch { /* ignore */ }
    }

    function pick(code: string): void {
        open = false;
        translationLanguage.set(code);
        showTranslations.set(true);
        persist(LS_KEYS.TS_TRANSLATION_LANG, code);
        persist(LS_KEYS.TS_SHOW_TRANSLATIONS, 'true');
    }
    function turnOff(): void {
        open = false;
        showTranslations.set(false);
        persist(LS_KEYS.TS_SHOW_TRANSLATIONS, 'false');
    }
</script>

<div class="tg" use:clickOutside={() => (open = false)}>
    <button
        type="button" class="tg-btn" class:on={$showTranslations}
        aria-haspopup="listbox" aria-expanded={open}
        title="Translations" onclick={() => (open = !open)}
    ><ControlIcon name="globe" /></button>

    {#if open}
        <div class="tg-menu" role="listbox" aria-label="Translation language">
            <button
                type="button" class="tg-opt" class:sel={!$showTranslations}
                role="option" aria-selected={!$showTranslations} onclick={turnOff}
            >Off</button>
            {#each ordered as l, i (l.code)}
                {#if i === firstPartial && firstPartial > 0}
                    <div class="tg-group" role="presentation">Partial · English mixed in</div>
                {/if}
                <button
                    type="button" class="tg-opt"
                    class:sel={$showTranslations && $translationLanguage === l.code}
                    role="option" aria-selected={$showTranslations && $translationLanguage === l.code}
                    onclick={() => pick(l.code)}
                >
                    <span class="tg-label">{l.label}</span>
                    {#if !l.complete}<span class="tg-pill">partial</span>{/if}
                </button>
            {/each}
        </div>
    {/if}
</div>

<style>
    .tg { position: relative; display: inline-flex; }
    .tg-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 28px;
        height: 26px;
        color: var(--text-muted);
        background: transparent;
        border: 1px solid transparent;
        border-radius: var(--r-2);
        cursor: pointer;
        transition: color var(--t-fast), background var(--t-fast);
    }
    .tg-btn:hover { color: var(--text-primary); background: var(--panel-2); }
    .tg-btn.on { color: var(--accent); }
    .tg-menu {
        position: absolute;
        bottom: calc(100% + 4px);
        left: 0;
        z-index: 200;
        min-width: 160px;
        max-height: 300px;
        overflow-y: auto;
        padding: 4px;
        background: var(--panel);
        border: 1px solid var(--border-default);
        border-radius: var(--r-3);
        box-shadow: 0 16px 48px oklch(0 0 0 / 0.45);
    }
    .tg-opt {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        width: 100%;
        padding: 5px 8px;
        background: transparent;
        border: 0;
        border-radius: var(--r-2);
        color: var(--text-secondary);
        font: inherit;
        font-size: var(--fs-meta);
        text-align: left;
        cursor: pointer;
    }
    .tg-opt:hover { background: var(--panel-2); color: var(--text-primary); }
    .tg-opt.sel { color: var(--accent); font-weight: 600; }
    .tg-group {
        padding: 6px 8px 3px;
        font-size: 0.66rem;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--text-faint);
        border-top: 1px solid var(--border-quiet);
        margin-top: 4px;
    }
    .tg-pill {
        flex: 0 0 auto;
        padding: 1px 6px;
        border-radius: 999px;
        background: oklch(0.32 0.04 70);
        color: oklch(0.85 0.06 80);
        font-size: 0.62rem;
    }
</style>
