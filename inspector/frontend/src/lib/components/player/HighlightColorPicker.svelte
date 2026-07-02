<script lang="ts">
    /**
     * Concise highlight-colour picker for the recitation droplet.
     *
     * Replaces the native OS colour input: the user controls HUE + SATURATION
     * only; lightness is LOCKED to the shipped legible band
     * (`DEFAULT_HIGHLIGHT_MODEL`), so every pick is used verbatim and stays
     * legible on the dark analysis cells with the fixed inks — no contrast,
     * opacity, or ink compensation. Writes the accent through `setHighlight`, the
     * single source the footer/teleprompter/cells all read.
     *
     * Renders the droplet trigger + a small upward popover (preset swatches + two
     * OKLCh sliders whose tracks preview the actual landed colours). Used by
     * `NowReciting`'s control row.
     */
    import { ControlIcon } from '../../recitation-animation';
    import { recitationConfigStore, setHighlight } from '../../recitation-animation/recitation-settings';
    import { oklchHex, parseOklch } from '../../utils/color-derive';
    import { DEFAULT_HIGHLIGHT_MODEL, SHIPPED_HIGHLIGHT_PRESETS } from '../../utils/highlight-model';

    // Lightness is pinned to the middle of the shipped legible band; chroma is
    // capped where the band stays in sRGB gamut across hues.
    const LOCK_L = (DEFAULT_HIGHLIGHT_MODEL.bandMinL + DEFAULT_HIGHLIGHT_MODEL.bandMaxL) / 2;
    const C_MAX = 0.22;
    const PRESETS = SHIPPED_HIGHLIGHT_PRESETS;

    const config = $derived($recitationConfigStore);

    let open = $state(false);
    let root = $state<HTMLDivElement>();
    let seed = $state(readSeed());

    function readSeed(): { C: number; h: number } {
        const o = parseOklch($recitationConfigStore.highlightColor) ?? { L: LOCK_L, C: 0.14, h: 200 };
        return { C: Math.min(C_MAX, Math.round(o.C * 1000) / 1000), h: Math.round((o.h + 360) % 360) };
    }
    function push(): void {
        setHighlight(oklchHex(LOCK_L, seed.C, seed.h));
    }
    function setSeed(p: Partial<typeof seed>): void {
        seed = { ...seed, ...p };
        push();
    }
    function pick(hex: string): void {
        const o = parseOklch(hex);
        if (!o) return;
        seed = { C: Math.min(C_MAX, o.C), h: Math.round((o.h + 360) % 360) };
        push();
    }
    // A colour as it will actually land (L pinned), so the chip equals the result.
    function landed(hex: string): string {
        const o = parseOklch(hex);
        return o ? oklchHex(LOCK_L, Math.min(C_MAX, o.C), o.h) : hex;
    }

    // Slider tracks previewed at the locked L so they show the true gamut.
    const hueTrack = $derived(
        `linear-gradient(to right, ${Array.from({ length: 13 }, (_, i) => oklchHex(LOCK_L, seed.C, i * 30)).join(',')})`,
    );
    const satTrack = $derived(
        `linear-gradient(to right, ${oklchHex(LOCK_L, 0, seed.h)}, ${oklchHex(LOCK_L, C_MAX, seed.h)})`,
    );

    function toggle(): void {
        if (!open) seed = readSeed();
        open = !open;
    }

    $effect(() => {
        if (!open) return;
        const onDown = (e: PointerEvent): void => {
            if (root && !root.contains(e.target as Node)) open = false;
        };
        const onKey = (e: KeyboardEvent): void => {
            if (e.key === 'Escape') open = false;
        };
        document.addEventListener('pointerdown', onDown, true);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('pointerdown', onDown, true);
            document.removeEventListener('keydown', onKey);
        };
    });
</script>

<div class="hl-pick" bind:this={root}>
    <button
        type="button"
        class="trigger"
        aria-label="Highlight colour"
        aria-haspopup="dialog"
        aria-expanded={open}
        title="Highlight colour"
        style:color={config.highlightColor}
        onclick={toggle}
    ><ControlIcon name="droplet" /></button>

    {#if open}
        <div class="pop" role="dialog" aria-label="Highlight colour">
            <div class="sw-row">
                {#each PRESETS as p (p)}
                    <button
                        type="button"
                        class="sw"
                        style:background={landed(p)}
                        aria-label="Preset colour"
                        onclick={() => pick(p)}
                    ></button>
                {/each}
            </div>
            <label class="ax">
                <span>Hue</span>
                <input
                    type="range"
                    min="0"
                    max="360"
                    step="1"
                    value={seed.h}
                    style:background={hueTrack}
                    oninput={(e) => setSeed({ h: +e.currentTarget.value })}
                />
            </label>
            <label class="ax">
                <span>Saturation</span>
                <input
                    type="range"
                    min="0"
                    max={C_MAX}
                    step="0.005"
                    value={seed.C}
                    style:background={satTrack}
                    oninput={(e) => setSeed({ C: +e.currentTarget.value })}
                />
            </label>
        </div>
    {/if}
</div>

<style>
    .hl-pick {
        position: relative;
        display: inline-flex;
        flex: 0 0 auto;
    }
    /* Matches the sibling .nr-btn controls in the recitation handle row. */
    .trigger {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 26px;
        height: 20px;
        color: var(--text-muted);
        background: transparent;
        border: 1px solid transparent;
        border-radius: var(--r-2);
        cursor: pointer;
        transition: color var(--t-fast), background var(--t-fast), filter var(--t-fast);
    }
    .trigger:hover { color: var(--text-primary); background: var(--panel-2); filter: brightness(1.12); }
    .pop {
        position: absolute;
        bottom: calc(100% + 8px);
        right: 0;
        z-index: 120;
        width: 208px;
        display: flex;
        flex-direction: column;
        gap: 9px;
        padding: 10px;
        background: var(--panel-2);
        border: 1px solid var(--border-strong);
        border-radius: var(--r-2, 8px);
        box-shadow: var(--shadow-pop);
    }
    .sw-row {
        display: grid;
        grid-template-columns: repeat(8, 1fr);
        gap: 5px;
    }
    .sw {
        aspect-ratio: 1;
        border-radius: 4px;
        border: 1px solid var(--hairline-on-color);
        cursor: pointer;
        padding: 0;
    }
    .sw:hover {
        outline: 2px solid var(--text-primary);
        outline-offset: 1px;
    }
    .ax {
        display: flex;
        flex-direction: column;
        gap: 4px;
        font-size: 10.5px;
        color: var(--text-secondary);
    }
    .ax input[type='range'] {
        appearance: none;
        -webkit-appearance: none;
        width: 100%;
        height: 12px;
        border-radius: 6px;
        border: 1px solid var(--hairline-on-color);
        cursor: pointer;
    }
    .ax input[type='range']::-webkit-slider-thumb {
        -webkit-appearance: none;
        width: 14px;
        height: 14px;
        border-radius: 50%;
        background: var(--ink-on-color);
        border: 2px solid var(--knob-ring);
        cursor: pointer;
    }
    .ax input[type='range']::-moz-range-thumb {
        width: 14px;
        height: 14px;
        border-radius: 50%;
        background: var(--ink-on-color);
        border: 2px solid var(--knob-ring);
        cursor: pointer;
    }
</style>
