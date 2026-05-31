<script lang="ts">
    /**
     * One-line recitation teleprompter.
     *
     * Renders a single line of words for the current ayah from `pageStart`,
     * highlighting word-by-word (or char-by-char) in sync with playback. The
     * line clears + re-pages when:
     *   - the active word would overflow the line ("out of space"), or
     *   - the ayah finishes (restart from the new ayah's first word).
     *
     * The reveal engine (`engine/*`) is shared with the timestamps tab; the
     * paging + measurement is the line-specific layer here. All styling is
     * driven by CSS custom properties projected from `RecitationAnimConfig`,
     * so the throwaway playground can tune it live.
     */
    import { ayahUnitRanges } from './chapter-words';
    import { cssVarText, type RecitationAnimConfig } from './config';
    import { buildAnimStructure, type AnimSourceWord } from './engine/build-structure';
    import { activeIndexAt, sweepHighlights } from './engine/highlight';
    import {
        clearHighlights,
        indexCache,
        type HighlightCache,
    } from './engine/index-cache';
    import { fittedPrefixLength } from './line-window';
    import type { AnimUnit } from './types';

    interface Props {
        units: AnimUnit[];
        config: RecitationAnimConfig;
        /** Chapter-absolute current time, ms. */
        getTimeMs: () => number;
        /** Whether playback is running (drives the rAF loop). */
        playing: boolean;
        /** Click-to-seek: receives the clicked word's chapter-absolute ms. */
        onSeekToWord?: (ms: number) => void;
    }

    let { units, config, getTimeMs, playing, onSeekToWord }: Props = $props();

    // ---- paging state (reactive — drives the rendered page) ----
    let rootEl = $state<HTMLDivElement | undefined>(undefined);
    let pageStart = $state(0);
    let pageAyahKey = $state('');

    // ---- imperative per-frame state (not reactive) ----
    let wordCache: HighlightCache | null = null;
    let charCache: HighlightCache | null = null;
    let lastRevealIdx = -1;
    let globalActive = -1;
    let lastVisibleLocal = -1;

    const ayahRanges = $derived(ayahUnitRanges(units));
    const pageEnd = $derived(
        config.clearOnAyahEnd
            ? (ayahRanges.get(pageAyahKey)?.[1] ?? units.length)
            : units.length,
    );
    const pageUnits = $derived(units.slice(pageStart, pageEnd));
    const structure = $derived(
        buildAnimStructure(
            pageUnits.map(
                (u): AnimSourceWord => ({
                    text: u.text,
                    display_text: u.text,
                    start: u.start,
                    end: u.end,
                    letters: u.letters,
                }),
            ),
        ),
    );

    // Reset paging whenever the chapter (units identity) changes.
    $effect(() => {
        void units; // track
        pageStart = 0;
        pageAyahKey = units[0]?.ayahKey ?? '';
        globalActive = -1;
        lastRevealIdx = -1;
    });

    // Rebuild caches + remeasure after every render of the page (and on config
    // changes that affect layout). Runs post-DOM-commit, so the spans exist.
    $effect(() => {
        void structure; // re-run when the page content changes
        void config; // re-measure when font / spacing / granularity changes
        if (!rootEl) return;
        wordCache = indexCache(rootEl, '.ra-word');
        charCache = config.granularity === 'char' ? indexCache(rootEl, '.ra-char') : null;
        clearHighlights(rootEl);
        lastRevealIdx = -1;
        measureFits();
        doSweep();
    });

    // rAF loop — only alive while playing.
    $effect(() => {
        if (!playing) return;
        let raf = 0;
        const loop = (): void => {
            tick();
            raf = requestAnimationFrame(loop);
        };
        raf = requestAnimationFrame(loop);
        return () => cancelAnimationFrame(raf);
    });

    function measureFits(): void {
        if (!rootEl) return;
        const rowRect = rootEl.getBoundingClientRect();
        const eps = 0.75;
        const fits: boolean[] = [];
        rootEl.querySelectorAll<HTMLElement>('.ra-word').forEach((el) => {
            const r = el.getBoundingClientRect();
            fits.push(r.left >= rowRect.left - eps && r.right <= rowRect.right + eps);
        });
        lastVisibleLocal = fittedPrefixLength(fits) - 1;
    }

    function doSweep(): void {
        const cache = config.granularity === 'char' && charCache ? charCache : wordCache;
        if (!cache) return;
        const t = (getTimeMs() + config.leadMs) / 1000;
        lastRevealIdx = sweepHighlights(cache, t, lastRevealIdx, { mode: 'class' });
    }

    function repaginate(start: number, ayahKey: string): void {
        pageStart = start;
        pageAyahKey = ayahKey;
        lastRevealIdx = -1;
        // The structure effect re-measures + sweeps once the new page renders.
    }

    function tick(): void {
        if (!units.length) return;
        const t = (getTimeMs() + config.leadMs) / 1000;
        const ga = activeIndexAt(units, t, globalActive);
        if (ga < 0) return;
        const activeAyah = units[ga]!.ayahKey;

        // Ayah finished → restart from the new ayah's first word.
        if (config.clearOnAyahEnd && activeAyah !== pageAyahKey) {
            const range = ayahRanges.get(activeAyah);
            repaginate(range ? range[0] : ga, activeAyah);
            globalActive = ga;
            return;
        }

        // Out of space → restart the line from the active word.
        const localActive = ga - pageStart;
        if (config.clearOnOverflow && lastVisibleLocal >= 0 && localActive > lastVisibleLocal) {
            repaginate(ga, activeAyah);
            globalActive = ga;
            return;
        }

        globalActive = ga;
        doSweep();
    }

    /** Force a reveal update — call after a seek while paused. */
    export function refresh(): void {
        tick();
    }
</script>

<div bind:this={rootEl} class="ra-line" class:ra-chars={config.granularity === 'char'} style={cssVarText(config)}>
    {#each structure as w, i (pageStart + '-' + i)}
        {#if i > 0}{' '}{/if}<span
            class="ra-word"
            data-start={w.start}
            data-end={w.end}
            role="button"
            tabindex="-1"
            onclick={() => onSeekToWord?.((pageUnits[i]?.start ?? 0) * 1000)}
            onkeydown={() => {}}
        >{#if w.hasChars}{#each w.chars as ch, ci (ci)}<span
                    class="ra-char"
                    data-start={ch.start}
                    data-end={ch.end}
                    data-group-id={ch.groupId}
                >{ch.text}</span>{/each}{:else}{w.word.display_text || w.word.text}{/if}</span>
    {/each}
</div>

<style>
    .ra-line {
        /* RTL: first (recitation-order) word sits at the right, the line fills
         *  leftward, overflow clips on the left. `unicode-bidi: plaintext`
         *  must NOT be used here — it reorders the inline-block word boxes
         *  left-to-right. Plain `direction: rtl` flows the words right-to-left. */
        direction: rtl;
        text-align: right;
        white-space: nowrap;
        overflow: hidden;
        width: 100%;
        height: calc(var(--ra-font-size) * var(--ra-line-height));
        line-height: var(--ra-line-height);
        font-family: var(--ra-font);
        font-size: var(--ra-font-size);
        letter-spacing: var(--ra-letter-spacing);
        word-spacing: var(--ra-word-spacing);
        color: var(--text-muted);
        /* Base outline on all glyphs (text-stroke + paint-order are inherited),
         *  painted BEHIND the fill so it adds separation without thinning the
         *  letters. 0 width = off. Helps crowded short-ayah legibility. */
        -webkit-text-stroke: var(--ra-base-stroke) var(--ra-base-stroke-color);
        paint-order: stroke fill;
    }

    /* Word granularity: the word is the animated unit. */
    .ra-word {
        display: inline-block;
        opacity: var(--ra-unreached-opacity);
        transition:
            opacity var(--ra-word-reveal) var(--ra-easing),
            color var(--ra-active-emphasis) var(--ra-easing),
            transform var(--ra-active-emphasis) var(--ra-easing),
            text-shadow var(--ra-active-emphasis) var(--ra-easing);
    }
    /* `reached` / `active` are toggled imperatively by the engine, so scope
     *  only `.ra-word` and keep the state class global (else Svelte prunes /
     *  warns it as unused). */
    .ra-word:global(.reached) {
        opacity: var(--ra-reached-opacity);
    }
    .ra-word:global(.active) {
        opacity: 1;
        color: var(--ra-highlight);
        transform: scale(var(--ra-active-scale));
        text-shadow: 0 0 var(--ra-active-glow) var(--ra-highlight);
        -webkit-text-stroke: var(--ra-active-stroke) var(--ra-active-stroke-color);
    }

    /* Char granularity: the word stays lit; characters are the animated unit. */
    .ra-line.ra-chars .ra-word {
        opacity: 1;
    }
    .ra-line.ra-chars .ra-char {
        opacity: var(--ra-unreached-opacity);
        transition:
            opacity var(--ra-char-reveal) var(--ra-easing),
            color var(--ra-active-emphasis) var(--ra-easing),
            text-shadow var(--ra-active-emphasis) var(--ra-easing);
    }
    .ra-line.ra-chars .ra-char:global(.reached) {
        opacity: var(--ra-reached-opacity);
    }
    .ra-line.ra-chars .ra-char:global(.active) {
        opacity: 1;
        color: var(--ra-highlight);
        text-shadow: 0 0 var(--ra-active-glow) var(--ra-highlight);
        -webkit-text-stroke: var(--ra-active-stroke) var(--ra-active-stroke-color);
    }

    @media (prefers-reduced-motion: reduce) {
        .ra-word,
        .ra-line.ra-chars .ra-char {
            transition: none;
        }
    }
</style>
