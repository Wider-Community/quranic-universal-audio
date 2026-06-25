<script lang="ts">
    /**
     * Accent Lab — a DEV-ONLY floating panel to preview the user's main highlight
     * colour applied per-surface across the footer / player / filmstrip /
     * teleprompter, so we can decide which surfaces should adopt it.
     *
     * Mechanism (see `accent-lab-rules.ts`): the panel owns one injected
     * stylesheet element and two root vars (`--lab` = the picked colour,
     * `--lab-ink` = its auto-contrast ink). Each enabled toggle adds its CSS block
     * (scoped under `body.accent-lab`) to that sheet, recolouring the LIVE surface
     * over its real class names — real motion, scroll and hover preserved. Nothing
     * is written to the persisted recitation config; the lab colour is ephemeral
     * (seeded from the current highlight). Mounted only in dev / `?accent-lab=1`.
     */
    import { onMount } from 'svelte';
    import { get } from 'svelte/store';

    import { recitationConfigStore } from '../recitation-animation/recitation-settings';
    import {
        buildLabSheet,
        inkFor,
        LAB_GROUPS,
        LAB_TOGGLE_IDS,
        LAB_TOGGLES,
    } from './accent-lab-rules';

    let labColor = $state(get(recitationConfigStore).highlightColor || '#7c5cff');
    let enabled = $state<Record<string, boolean>>(
        Object.fromEntries(LAB_TOGGLE_IDS.map((id) => [id, false])),
    );
    let collapsed = $state(false);
    let styleEl = $state<HTMLStyleElement | null>(null);

    onMount(() => {
        document.body.classList.add('accent-lab');
        const el = document.createElement('style');
        el.id = 'accent-lab-sheet';
        document.head.appendChild(el);
        styleEl = el;
        return () => {
            document.body.classList.remove('accent-lab');
            el.remove();
            styleEl = null;
            document.documentElement.style.removeProperty('--lab');
            document.documentElement.style.removeProperty('--lab-ink');
        };
    });

    // Lab colour → root vars (the sheet references these, so colour changes need
    // no sheet rebuild).
    $effect(() => {
        document.documentElement.style.setProperty('--lab', labColor);
        document.documentElement.style.setProperty('--lab-ink', inkFor(labColor));
    });

    // Enabled toggles → injected sheet.
    $effect(() => {
        if (!styleEl) return;
        const on = new Set(LAB_TOGGLE_IDS.filter((id) => enabled[id]));
        styleEl.textContent = buildLabSheet(on);
    });

    const onCount = $derived(LAB_TOGGLE_IDS.filter((id) => enabled[id]).length);

    function setAll(v: boolean): void {
        enabled = Object.fromEntries(LAB_TOGGLE_IDS.map((id) => [id, v]));
    }
    function toggle(id: string): void {
        enabled = { ...enabled, [id]: !enabled[id] };
    }
    function togglesFor(group: string) {
        return LAB_TOGGLES.filter((t) => t.group === group);
    }
</script>

{#if collapsed}
    <button class="lab-chip" onclick={() => (collapsed = false)} title="Open Accent Lab">
        <span class="dot" style:background={labColor}></span>
        Accent Lab{#if onCount}<span class="chip-count">{onCount}</span>{/if}
    </button>
{:else}
    <section class="lab" aria-label="Accent Lab (dev)">
        <header class="lab-head">
            <span class="lab-title"><span class="dot" style:background={labColor}></span>Accent Lab</span>
            <span class="lab-dev">dev</span>
            <button class="icon" onclick={() => (collapsed = true)} title="Collapse" aria-label="Collapse">–</button>
        </header>

        <div class="lab-color">
            <label class="swatch" style:background={labColor} title="Lab colour">
                <input type="color" bind:value={labColor} aria-label="Lab colour" />
            </label>
            <code class="hex">{labColor}</code>
            <button
                class="mini"
                onclick={() => (labColor = get(recitationConfigStore).highlightColor || labColor)}
                title="Reset to the current highlight colour"
            >from highlight</button>
        </div>

        <div class="lab-groups">
            {#each LAB_GROUPS as group (group)}
                <div class="lab-group">
                    <div class="lab-group-h">{group}</div>
                    {#each togglesFor(group) as t (t.id)}
                        <button
                            class="row"
                            role="switch"
                            aria-checked={enabled[t.id]}
                            class:on={enabled[t.id]}
                            onclick={() => toggle(t.id)}
                        >
                            <span class="label">{t.label}</span>
                            <span class="track" aria-hidden="true"><span class="knob"></span></span>
                        </button>
                    {/each}
                </div>
            {/each}
        </div>

        <footer class="lab-foot">
            <button class="mini" onclick={() => setAll(true)}>All on</button>
            <button class="mini" onclick={() => setAll(false)} disabled={onCount === 0}>Reset</button>
            <span class="note">recolors live surfaces · nothing persists</span>
        </footer>
    </section>
{/if}

<style>
    .lab {
        position: fixed;
        top: 12px;
        left: 12px;
        z-index: 99999;
        width: 232px;
        display: flex;
        flex-direction: column;
        gap: 10px;
        padding: 12px;
        background: var(--elevated, #1f3360);
        border: 1px solid var(--border-default, #2a3a5e);
        border-radius: var(--r-2, 8px);
        box-shadow: 0 8px 28px oklch(0 0 0 / 0.4);
        color: var(--text-primary, #eef);
        font-family: var(--font-sans, system-ui, sans-serif);
        max-height: calc(100vh - 24px);
    }
    .lab-head {
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .lab-title {
        display: flex;
        align-items: center;
        gap: 7px;
        font-size: 13px;
        font-weight: 500;
        color: var(--text-primary, #eef);
    }
    .dot {
        width: 11px;
        height: 11px;
        border-radius: 50%;
        flex: 0 0 auto;
        box-shadow: 0 0 0 1px oklch(1 0 0 / 0.18) inset;
    }
    .lab-dev {
        font-family: var(--font-mono, monospace);
        font-size: 10px;
        letter-spacing: 0.04em;
        text-transform: uppercase;
        color: var(--accent, #4cc9f0);
        border: 1px solid color-mix(in srgb, var(--accent, #4cc9f0) 45%, transparent);
        border-radius: 3px;
        padding: 0 4px;
        margin-right: auto;
    }
    .icon {
        width: 22px;
        height: 22px;
        display: grid;
        place-items: center;
        background: transparent;
        border: 1px solid var(--border-quiet, #2a3050);
        border-radius: var(--r-1, 4px);
        color: var(--text-secondary, #aab);
        cursor: pointer;
        font-size: 16px;
        line-height: 1;
    }
    .icon:hover {
        color: var(--text-primary, #fff);
        border-color: var(--border-strong, #44557e);
    }

    .lab-color {
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .swatch {
        position: relative;
        width: 30px;
        height: 24px;
        border-radius: var(--r-1, 4px);
        border: 1px solid oklch(1 0 0 / 0.2);
        cursor: pointer;
        overflow: hidden;
        flex: 0 0 auto;
    }
    .swatch input {
        position: absolute;
        inset: -4px;
        width: calc(100% + 8px);
        height: calc(100% + 8px);
        border: 0;
        padding: 0;
        background: transparent;
        cursor: pointer;
        opacity: 0;
    }
    .hex {
        font-family: var(--font-mono, monospace);
        font-size: 12px;
        color: var(--text-secondary, #aab);
        text-transform: uppercase;
    }
    .mini {
        font-size: 11px;
        color: var(--text-secondary, #aab);
        background: transparent;
        border: 1px solid var(--border-quiet, #2a3050);
        border-radius: var(--r-1, 4px);
        padding: 3px 8px;
        cursor: pointer;
    }
    .mini:hover:not(:disabled) {
        color: var(--text-primary, #fff);
        border-color: var(--border-strong, #44557e);
    }
    .mini:disabled {
        opacity: 0.4;
        cursor: not-allowed;
    }
    .lab-color .mini {
        margin-left: auto;
    }

    .lab-groups {
        display: flex;
        flex-direction: column;
        gap: 8px;
        overflow-y: auto;
        margin: 0 -4px;
        padding: 0 4px;
    }
    .lab-group-h {
        font-family: var(--font-mono, monospace);
        font-size: 10.5px;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        color: var(--text-faint, #66789c);
        padding: 4px 2px 2px;
    }
    .row {
        width: 100%;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 10px;
        padding: 5px 6px;
        background: transparent;
        border: 0;
        border-radius: var(--r-1, 4px);
        cursor: pointer;
        color: var(--text-secondary, #aab);
    }
    .row:hover {
        background: var(--panel-2, #243a5e);
        color: var(--text-primary, #fff);
    }
    .row.on {
        color: var(--text-primary, #fff);
    }
    .label {
        font-family: var(--font-mono, monospace);
        font-size: 12px;
    }
    .track {
        position: relative;
        width: 30px;
        height: 16px;
        border-radius: 999px;
        background: var(--canvas-inset, #11182e);
        border: 1px solid var(--border-default, #2a3a5e);
        flex: 0 0 auto;
        transition: background var(--t-fast, 0.15s), border-color var(--t-fast, 0.15s);
    }
    .row.on .track {
        background: color-mix(in srgb, var(--accent, #4cc9f0) 40%, transparent);
        border-color: var(--accent, #4cc9f0);
    }
    .knob {
        position: absolute;
        top: 1px;
        left: 1px;
        width: 12px;
        height: 12px;
        border-radius: 50%;
        background: var(--text-muted, #8090b0);
        transition: transform var(--t-fast, 0.15s), background var(--t-fast, 0.15s);
    }
    .row.on .knob {
        transform: translateX(14px);
        background: var(--accent, #4cc9f0);
    }
    .row:focus-visible {
        outline: 2px solid var(--accent, #4cc9f0);
        outline-offset: 1px;
    }

    .lab-foot {
        display: flex;
        align-items: center;
        gap: 6px;
        padding-top: 2px;
    }
    .note {
        font-size: 10px;
        color: var(--text-faint, #66789c);
        margin-left: auto;
        text-align: right;
        line-height: 1.25;
    }

    .lab-chip {
        position: fixed;
        top: 12px;
        left: 12px;
        z-index: 99999;
        display: inline-flex;
        align-items: center;
        gap: 7px;
        padding: 6px 10px;
        background: var(--elevated, #1f3360);
        border: 1px solid var(--border-default, #2a3a5e);
        border-radius: 999px;
        color: var(--text-secondary, #aab);
        font-size: 12px;
        cursor: pointer;
        box-shadow: 0 4px 16px oklch(0 0 0 / 0.35);
    }
    .lab-chip:hover {
        color: var(--text-primary, #fff);
    }
    .chip-count {
        background: var(--accent, #4cc9f0);
        color: var(--accent-fg, #08121a);
        border-radius: 999px;
        font-size: 10px;
        font-weight: 600;
        padding: 0 5px;
        line-height: 16px;
    }

    @media (prefers-reduced-motion: reduce) {
        .track,
        .knob {
            transition: none;
        }
    }
</style>
