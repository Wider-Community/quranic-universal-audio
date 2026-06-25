<script lang="ts">
    /**
     * Tajweed legend + per-rule settings drop-up for the Timestamps footer. Each
     * rule shows a colour swatch (click → native colour picker, live recolour) with
     * a mini enable toggle beneath it, its label and ḥarakāt duration. Grouped by
     * category; the qalqala row demos the ṣughrā bar vs the taller kubrā fill. All
     * state lives in the `tajweed-settings` store (localStorage-cached); colours
     * apply via `--tj-*` CSS-var overrides, toggles drive the per-cell underline.
     */
    import { LEGEND, type LegendRow } from '../utils/tajweed-rules';
    import {
        resetAllTajweed,
        setRuleColor,
        setRuleEnabled,
        tajweedSettings,
    } from '../stores/tajweed-settings';

    // Hidden native colour inputs, one per rule, opened by clicking the swatch.
    let inputs: Record<string, HTMLInputElement | undefined> = $state({});

    /** Normalise any CSS colour (oklch / rgb / hex) to a `#rrggbb` the native
     *  picker accepts, via a throwaway canvas (Chromium parses oklch). */
    function cssColorToHex(input: string): string {
        const s = input.trim();
        if (/^#[0-9a-f]{6}$/i.test(s)) return s;
        try {
            const ctx = document.createElement('canvas').getContext('2d');
            if (ctx) {
                ctx.fillStyle = '#000000';
                ctx.fillStyle = s;
                const v = ctx.fillStyle;
                if (/^#[0-9a-f]{6}$/i.test(v)) return v;
                const m = v.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
                if (m) {
                    return (
                        '#' +
                        [1, 2, 3]
                            .map((i) => Number(m[i]).toString(16).padStart(2, '0'))
                            .join('')
                    );
                }
            }
        } catch {
            /* unsupported parse — fall through */
        }
        return '#888888';
    }

    /** The rule's current effective colour as hex (override, else the live CSS var). */
    function effectiveHex(row: LegendRow): string {
        const override = $tajweedSettings[row.legendKey]?.color;
        if (override) return override;
        const raw = getComputedStyle(document.documentElement).getPropertyValue(row.colorVar);
        return cssColorToHex(raw || '#888888');
    }
</script>

<div class="tjs">
    <div class="tjs-head">
        <span class="tjs-title">Tajweed rules</span>
        <button type="button" class="tjs-reset" onclick={() => resetAllTajweed()}>Reset all</button>
    </div>
    <div class="tjs-cols">
        {#each LEGEND as group (group.title)}
            <section class="tjs-group">
                <h4>{group.title}</h4>
                {#each group.rows as row (row.legendKey)}
                    {@const on = $tajweedSettings[row.legendKey]?.enabled ?? true}
                    <div class="tjs-row" class:off={!on}>
                        <div class="tjs-control">
                            {#if row.demo === 'qalqala'}
                                <button
                                    type="button"
                                    class="tjs-swatch demo"
                                    style:--sw={`var(${row.colorVar})`}
                                    title="Qalqala — ṣughrā (thin) vs kubrā (fill)"
                                    onclick={() => inputs[row.legendKey]?.click()}
                                >
                                    <span class="demo-cell sughra"></span>
                                    <span class="demo-cell kubra"></span>
                                </button>
                            {:else}
                                <button
                                    type="button"
                                    class="tjs-swatch"
                                    style:--sw={`var(${row.colorVar})`}
                                    title="Change colour"
                                    onclick={() => inputs[row.legendKey]?.click()}
                                ></button>
                            {/if}
                            <input
                                bind:this={inputs[row.legendKey]}
                                type="color"
                                class="tjs-color-input"
                                value={effectiveHex(row)}
                                oninput={(e) => setRuleColor(row.legendKey, e.currentTarget.value)}
                                tabindex="-1"
                                aria-hidden="true"
                            />
                            <button
                                type="button"
                                class="tjs-toggle"
                                class:on
                                role="switch"
                                aria-checked={on}
                                aria-label={`${row.label} ${on ? 'on' : 'off'}`}
                                onclick={() => setRuleEnabled(row.legendKey, !on)}
                            ><span class="knob"></span></button>
                        </div>
                        <span class="tjs-label">{row.label}</span>
                        {#if row.duration}<span class="tjs-dur">[{row.duration}]</span>{/if}
                    </div>
                {/each}
            </section>
        {/each}
    </div>
</div>

<style>
    .tjs {
        display: flex;
        flex-direction: column;
        gap: var(--s-2);
        min-width: 460px;
        max-width: 620px;
    }
    .tjs-head {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding-bottom: var(--s-1);
        border-bottom: 1px solid var(--border-quiet);
    }
    .tjs-title {
        font-size: var(--fs-meta);
        font-weight: 600;
        color: var(--text-primary);
    }
    .tjs-reset {
        font-size: 10px;
        color: var(--text-muted);
        background: transparent;
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        padding: 1px 7px;
        cursor: pointer;
        transition: color var(--t-fast), border-color var(--t-fast);
    }
    .tjs-reset:hover {
        color: var(--text-primary);
        border-color: var(--border-default);
    }
    .tjs-cols {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: var(--s-3) var(--s-4);
    }
    .tjs-group h4 {
        margin: 0 0 var(--s-1);
        font-size: var(--fs-meta);
        color: var(--text-primary);
    }
    .tjs-row {
        display: flex;
        align-items: center;
        gap: var(--s-2);
        margin-bottom: 3px;
        font-size: var(--fs-meta);
        color: var(--text-secondary);
        white-space: nowrap;
        transition: opacity var(--t-fast);
    }
    .tjs-row.off {
        opacity: 0.45;
    }
    .tjs-control {
        position: relative;
        display: inline-flex;
        align-items: center;
        gap: var(--s-1);
        flex: 0 0 auto;
    }
    .tjs-swatch {
        width: 26px;
        height: 16px;
        padding: 0;
        border: 1px solid var(--border-quiet);
        border-radius: var(--r-1);
        background: var(--canvas-inset);
        box-shadow: inset 0 -3px 0 var(--sw);
        cursor: pointer;
    }
    .tjs-swatch.demo {
        display: inline-flex;
        align-items: stretch;
        gap: 2px;
        box-shadow: none;
        overflow: hidden;
        padding: 1px;
    }
    .demo-cell {
        flex: 1 1 auto;
        background: var(--canvas-inset);
    }
    .demo-cell.sughra {
        box-shadow: inset 0 -2px 0 var(--sw);
    }
    .demo-cell.kubra {
        box-shadow: inset 0 -7px 0 var(--sw);
    }
    /* The native picker is invisible; the swatch button proxies the click. */
    .tjs-color-input {
        position: absolute;
        left: 0;
        bottom: 0;
        width: 1px;
        height: 1px;
        opacity: 0;
        pointer-events: none;
    }
    .tjs-toggle {
        width: 22px;
        height: 12px;
        padding: 0;
        border: 1px solid var(--border-default);
        border-radius: 999px;
        background: var(--panel);
        cursor: pointer;
        transition: background var(--t-fast), border-color var(--t-fast);
    }
    .tjs-toggle .knob {
        display: block;
        width: 8px;
        height: 8px;
        margin: 1px;
        border-radius: 50%;
        background: var(--text-muted);
        transition: transform var(--t-fast), background var(--t-fast);
    }
    .tjs-toggle.on {
        background: var(--accent-tint);
        border-color: var(--accent);
    }
    .tjs-toggle.on .knob {
        transform: translateX(10px);
        background: var(--accent);
    }
    .tjs-label {
        flex: 1 1 auto;
    }
    .tjs-dur {
        flex: 0 0 auto;
        font-family: var(--font-mono);
        font-size: 10px;
        color: var(--text-faint);
        font-variant-numeric: tabular-nums;
    }
</style>
