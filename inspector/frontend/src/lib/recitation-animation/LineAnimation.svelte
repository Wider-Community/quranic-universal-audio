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
    import { toArabicNumeral } from '../utils/arabic-text';
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

    /** U+06DD ARABIC END OF AYAH — the same glyph segment cards use. */
    const AYAH_END = '۝';

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
    /** Words rendered on the current page; null = "measure the remainder". */
    let pageCount = $state<number | null>(null);

    // ---- imperative per-frame state (not reactive) ----
    let wordCache: HighlightCache | null = null;
    let charCache: HighlightCache | null = null;
    let lastRevealIdx = -1;
    let globalActive = -1;

    const ayahRanges = $derived(ayahUnitRanges(units));
    const ayahEndIdx = $derived(
        config.clearOnAyahEnd
            ? (ayahRanges.get(pageAyahKey)?.[1] ?? units.length)
            : units.length,
    );
    // While measuring (pageCount null) render the whole remainder so the fit
    // probe sees every candidate; once measured, render exactly the fitted set
    // (which `text-align` then centers).
    const pageEnd = $derived(
        pageCount === null ? ayahEndIdx : Math.min(pageStart + pageCount, ayahEndIdx),
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
        pageCount = null;
        globalActive = -1;
        lastRevealIdx = -1;
    });

    // Layout-affecting config changes force a re-measure (re-page) of the line.
    // Kept separate from color/timing tweaks so tuning those doesn't re-page.
    $effect(() => {
        void config.fontSizePx;
        void config.lineHeight;
        void config.wordSpacingPx;
        void config.letterSpacingPx;
        void config.fontFamily;
        void config.granularity;
        void config.showAyahMarker;
        pageCount = null;
    });

    // Re-measure once webfonts finish loading. The display font (DigitalKhatt)
    // loads async; a first measure against the fallback font has different
    // metrics and would otherwise lock in a too-small page on cold load.
    $effect(() => {
        if (typeof document === 'undefined' || !document.fonts) return;
        let cancelled = false;
        void document.fonts.ready.then(() => {
            if (!cancelled) pageCount = null;
        });
        return () => {
            cancelled = true;
        };
    });

    // Rebuild caches + measure fit after each render. Settles the fitted page
    // count in two passes (measure-all → render-fitted), then sweeps. Runs
    // post-DOM-commit, so the spans exist.
    $effect(() => {
        void structure; // re-run when the page content changes
        if (!rootEl) return;
        wordCache = indexCache(rootEl, '.ra-word');
        charCache = config.granularity === 'char' ? indexCache(rootEl, '.ra-char') : null;
        clearHighlights(rootEl);
        lastRevealIdx = -1;
        const fitted = measureFits();
        if (pageCount === null || fitted < pageCount) {
            pageCount = fitted; // re-renders the fitted set; this effect re-runs
            return; // sweep on the stabilized pass
        }
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

    /** Count of leading words that fully fit the line (always ≥1). */
    function measureFits(): number {
        if (!rootEl) return 1;
        const rowRect = rootEl.getBoundingClientRect();
        const eps = 0.75;
        const fits: boolean[] = [];
        rootEl.querySelectorAll<HTMLElement>('.ra-word').forEach((el) => {
            const r = el.getBoundingClientRect();
            fits.push(r.left >= rowRect.left - eps && r.right <= rowRect.right + eps);
        });
        return fittedPrefixLength(fits);
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
        pageCount = null;
        lastRevealIdx = -1;
        // The structure effect re-measures + sweeps once the new page renders.
    }

    function tick(): void {
        if (!units.length) return;
        const t = (getTimeMs() + config.leadMs) / 1000;
        const ga = activeIndexAt(units, t, globalActive);
        if (ga >= 0) {
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
            if (config.clearOnOverflow && pageCount !== null && localActive >= pageCount) {
                repaginate(ga, activeAyah);
                globalActive = ga;
                return;
            }

            globalActive = ga;
        }

        // Always sweep. During a silence gap (ga < 0) this clears the active
        // highlight — the just-finished word goes `reached`, nothing is active.
        // On look-back the time-based sweep travels the highlight backward.
        doSweep();
    }

    /** Force a reveal update — call after a seek while paused. */
    export function refresh(): void {
        tick();
    }
</script>

<div
    bind:this={rootEl}
    class="ra-line"
    class:ra-chars={config.granularity === 'char'}
    style={cssVarText(config)}
    style:text-align={pageCount === null ? 'right' : null}
>
    {#each structure as w, i (pageStart + '-' + i)}
        {@const u = pageUnits[i]}
        {#if i > 0}{' '}{/if}<span
            class="ra-word"
            data-start={w.start}
            data-end={w.end}
            role="button"
            tabindex="-1"
            onclick={() => onSeekToWord?.((pageUnits[i]?.start ?? 0) * 1000)}
            onkeydown={() => {}}
        >{#if config.granularity === 'char' && w.hasChars}{#each w.chars as ch, ci (ci)}<span
                    class="ra-char"
                    data-start={ch.start}
                    data-end={ch.end}
                    data-group-id={ch.groupId}
                >{ch.text}</span>{/each}{:else}{w.word.display_text || w.word.text}{/if}</span>{#if config.showAyahMarker && u && ayahRanges.get(u.ayahKey)?.[1] === pageStart + i + 1}{' '}<span class="ra-ayah-marker">{AYAH_END}{toArabicNumeral(u.ayah)}</span>{/if}
    {/each}
</div>

<style>
    .ra-line {
        /* RTL: first (recitation-order) word sits at the right, the line fills
         *  leftward, overflow clips on the left. `unicode-bidi: plaintext`
         *  must NOT be used here — it reorders the inline-block word boxes
         *  left-to-right. Plain `direction: rtl` flows the words right-to-left. */
        direction: rtl;
        /* Default alignment from config (`--ra-align`); the component overrides
         *  to `right` for the one-frame measure pass so the fitted-prefix probe
         *  isn't offset by centering. */
        text-align: var(--ra-align);
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
    }

    /* End-of-ayah marker (۝ + Arabic-Indic numeral). Quiet divider; always
     *  visible (not part of the reveal). Inherits the line font; gets the base
     *  outline. */
    .ra-ayah-marker {
        display: inline-block;
        color: var(--text-faint);
        text-shadow: var(--ra-word-shadow);
    }

    /* Word granularity: the word is the animated unit. Word mode renders the
     *  word as plain text (not per-char spans), so the outline traces the whole
     *  word silhouette rather than each joined letter. */
    .ra-word {
        display: inline-block;
        opacity: var(--ra-unreached-opacity);
        text-shadow: var(--ra-word-shadow);
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
        text-shadow: var(--ra-word-shadow-active);
    }

    /* Char granularity: the word stays lit; characters are the animated unit. */
    .ra-line.ra-chars .ra-word {
        opacity: 1;
    }
    .ra-line.ra-chars .ra-char {
        opacity: var(--ra-unreached-opacity);
        text-shadow: var(--ra-word-shadow);
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
        text-shadow: var(--ra-word-shadow-active);
    }

    @media (prefers-reduced-motion: reduce) {
        .ra-word,
        .ra-line.ra-chars .ra-char {
            transition: none;
        }
    }
</style>
