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
    import {
        clearHighlights,
        indexCache,
        type HighlightCache,
    } from './engine/index-cache';
    import { fittedPrefixLength } from './line-window';
    import { type ActiveHit, buildSortedIntervals, findActiveAt } from './recitation-active';
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
        onSeekToWord?: (_ms: number) => void;
    }

    let { units, config, getTimeMs, playing, onSeekToWord }: Props = $props();

    // ---- paging state (reactive — drives the rendered page) ----
    let rootEl = $state<HTMLDivElement | undefined>(undefined);
    let pageStart = $state(0);
    let pageAyahKey = $state('');
    /** Words rendered on the current page; null = "measure the remainder". */
    let pageCount = $state<number | null>(null);
    /** Set for the frame a layout/granularity switch re-pages the line, so the
     *  per-word opacity/color transitions are suppressed (words snap straight to
     *  their new-mode state). Without this, switching letter→word fades every
     *  word from char-mode opacity:1 down to the dim unreached level at once,
     *  reading as a flash of all-words-active. Cleared once the sweep settles. */
    let suppressTransition = $state(false);

    // ---- imperative per-frame state (not reactive) ----
    let wordCache: HighlightCache | null = null;
    let charCache: HighlightCache | null = null;
    let globalActive = -1;
    /** Reading index of the last active word (the cursor). On a jump-back it
     *  decreases; used to keep the trail revealed during a silence gap. */
    let lastActive = -1;

    const ayahRanges = $derived(ayahUnitRanges(units));

    // Flat sorted-by-start list of every occurrence interval across all units,
    // for binary-search active lookup on fast-path miss. Built once per chapter.
    const sortedIntervals = $derived(buildSortedIntervals(units));
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
                    // Letter timings are anchored to the FIRST occurrence; a
                    // repeated word's `u.start/u.end` are expanded to span every
                    // occurrence (min..max), which would stretch the char
                    // fallback range. Use the first occurrence's span instead.
                    start: u.intervals[0]?.start ?? u.start,
                    end: u.intervals[0]?.end ?? u.end,
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
        lastActive = -1;
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
        // Snap (no fade) across this re-page so a granularity switch doesn't
        // flash every word lit; re-enabled once the sweep below settles.
        suppressTransition = true;
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
        // Reuse the freshly-built caches' element refs instead of a second
        // `querySelectorAll` over the same line.
        clearHighlights(rootEl, wordCache, charCache);
        const fitted = measureFits();
        if (pageCount === null || fitted < pageCount) {
            pageCount = fitted; // re-renders the fitted set; this effect re-runs
            return; // sweep on the stabilized pass
        }
        doSweep();
        // The corrected per-word classes are now committed with transitions
        // off; re-enable smooth transitions once this paints (double rAF so
        // the snapped state lands first, then subsequent frames animate).
        if (suppressTransition) {
            requestAnimationFrame(() =>
                requestAnimationFrame(() => { suppressTransition = false; }),
            );
        }
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

    function doSweep(t?: number, hit?: ActiveHit | null): void {
        const tt = t ?? (getTimeMs() + config.leadMs) / 1000;
        // `tick()` already computed the active hit to drive paging; reuse its
        // result rather than re-bsearching. Structure-effect callers omit it.
        const h = hit !== undefined ? hit : findActiveAt(units, sortedIntervals, tt, globalActive);
        if (config.granularity === 'char') {
            sweepChar(tt, h);
            return;
        }
        sweepWord(h);
    }

    /** Translate a global unit index to its page-local position, or -1 if the
     *  active unit is off the current page. */
    function pageLocal(globalIdx: number): number {
        if (globalIdx < 0) return -1;
        const local = globalIdx - pageStart;
        return local >= 0 && local < pageUnits.length ? local : -1;
    }

    /** Word-granularity highlight from per-word occurrence intervals.
     *  active  = the word whose any occurrence span contains t (a repeat
     *            re-lights the existing word — no duplicate text), or none
     *            during a silence gap.
     *  reached = words strictly BEFORE the active cursor (reading order). When
     *            the reciter jumps back, the cursor moves to the repeated word
     *            and the words now AHEAD of it (already recited) revert to
     *            unreached. During a silence gap the trail up to the last active
     *            word stays revealed (so a pause doesn't blank the line). */
    function sweepWord(hit: ActiveHit | null): void {
        if (!wordCache) return;
        const items = wordCache.items;
        const active = pageLocal(hit?.unitIdx ?? -1);
        if (active >= 0) lastActive = active;
        for (let i = 0; i < items.length; i++) {
            const el = items[i]?.el;
            if (!el) continue;
            const isActive = i === active;
            const isReached = (active >= 0 ? i < active : i <= lastActive) && !isActive;
            el.classList.toggle('active', isActive);
            el.classList.toggle('reached', isReached);
        }
    }

    /** Char-granularity highlight — occurrence-aware, mirroring {@link sweepWord}.
     *  The naive time-based char sweep keyed each letter off its single canonical
     *  [start,end]; on a repeat / look-back the audio time is past every letter
     *  of the repeated word, so the whole word read `reached` and the active
     *  letter never travelled back. Instead we locate the active word's CURRENT
     *  occurrence interval and remap `t` onto the word's canonical letter
     *  timeline, so repeats re-reveal letter-by-letter.
     *
     *  Walk order matches the DOM: `.ra-char` spans exist only for words with
     *  `hasChars`, in `structure` order, so the flat `charCache` index advances
     *  in lockstep with the rendered spans. */
    function sweepChar(t: number, hit: ActiveHit | null): void {
        if (!charCache) return;
        const items = charCache.items;

        // Active word (local page index) + the occurrence interval containing t.
        const active = pageLocal(hit?.unitIdx ?? -1);
        const occStart = hit?.ivStart ?? 0;
        const occEnd = hit?.ivEnd ?? 0;
        if (active >= 0) lastActive = active;

        // Remap playback time into the active word's canonical letter timeline.
        // The letters are anchored to the FIRST occurrence (`intervals[0]`), so
        // we map the CURRENT occurrence's progress onto that span. (Using the
        // unit's start/end is wrong for repeats: they expand to cover every
        // occurrence, overshooting all letters → nothing animates on a repeat.)
        let localT = -1;
        if (active >= 0) {
            const canon = pageUnits[active]!.intervals[0] ?? { start: occStart, end: occEnd };
            const span = occEnd - occStart;
            const frac = span > 0 ? (t - occStart) / span : 0;
            localT = canon.start + frac * (canon.end - canon.start);
        }

        let ci = 0;
        for (let wi = 0; wi < structure.length; wi++) {
            const sw = structure[wi];
            const chars = sw && sw.hasChars ? sw.chars : [];
            // Words before the active cursor are reached; after it, unreached.
            // During a silence gap (active < 0) keep the trail up to lastActive.
            const wordReached = active >= 0 ? wi < active : wi <= lastActive;
            // Mark word-level state too (not just chars). In char mode, CSS
            // hides per-letter spans for non-active words so Arabic keeps its
            // joined whole-word silhouette. Cross-word co-timed letters are the
            // exception: if a non-current word has an active char, that word
            // must also become active or the highlighted char is hidden.
            const wordEl = wordCache?.items[wi]?.el;
            let wordHasActiveChar = false;
            for (let k = 0; k < chars.length; k++) {
                const el = items[ci]?.el;
                ci++;
                if (!el) continue;
                let isActive = false;
                let isReached = wordReached;
                const ch = chars[k]!;
                if (wi === active && localT >= 0) {
                    isActive = localT >= ch.start && localT < ch.end;
                    isReached = !isActive && localT >= ch.end;
                } else if (active >= 0 && sw && (ch.start !== sw.start || ch.end !== sw.end)) {
                    // Cross-word idgham/ghunnah: a real-timed letter in a
                    // NON-active word that's co-timed with the active letter
                    // must light together. The analysis tab does this because
                    // it highlights each letter purely by time, not scoped to
                    // the active word; mirror that here using raw playback time
                    // against the letter's own interval. Fallback (word-timed)
                    // chars are skipped so an overlapping word isn't flooded.
                    if (t >= ch.start && t < ch.end) { isActive = true; isReached = false; }
                    else if (t >= ch.end) isReached = true; // keep co-timed trail revealed
                }
                if (isActive) wordHasActiveChar = true;
                el.classList.toggle('active', isActive);
                el.classList.toggle('reached', isReached);
            }
            if (wordEl) {
                const wActive = wi === active || wordHasActiveChar;
                wordEl.classList.toggle('active', wActive);
                wordEl.classList.toggle('reached', wordReached && !wActive);
            }
        }
    }

    function repaginate(start: number, ayahKey: string): void {
        pageStart = start;
        pageAyahKey = ayahKey;
        pageCount = null;
        lastActive = -1;
        // The structure effect re-measures + sweeps once the new page renders.
    }

    function tick(): void {
        if (!units.length) return;
        const t = (getTimeMs() + config.leadMs) / 1000;
        const hit = findActiveAt(units, sortedIntervals, t, globalActive);
        const ga = hit?.unitIdx ?? -1;
        if (ga >= 0) {
            const activeAyah = units[ga]!.ayahKey;

            // Ayah finished → restart from the new ayah's first word.
            if (config.clearOnAyahEnd && activeAyah !== pageAyahKey) {
                const range = ayahRanges.get(activeAyah);
                repaginate(range ? range[0] : ga, activeAyah);
                globalActive = ga;
                return;
            }

            // Active word off the current page — overflow forward, or look-back
            // to an earlier page → re-page to the word so the highlight shows.
            const localActive = ga - pageStart;
            if (
                config.clearOnOverflow
                && pageCount !== null
                && (localActive >= pageCount || localActive < 0)
            ) {
                repaginate(ga, activeAyah);
                globalActive = ga;
                return;
            }

            globalActive = ga;
        }

        // Always sweep. During a silence gap (ga < 0) this clears the active
        // highlight — the just-finished word goes `reached`, nothing is active.
        // On look-back the time-based sweep travels the highlight backward.
        doSweep(t, hit);
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
    class:ra-no-transition={suppressTransition}
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
        >{#if config.granularity === 'char' && w.hasChars}<span
                    class="ra-word-ink"
                    aria-hidden="true"
                >{w.word.display_text || w.word.text}</span>{#each w.chars as ch, ci (ci)}<span
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
        /* Reserve vertical headroom so an active word scaled by `activeScale`
         *  (>1) isn't clipped top/bottom by `overflow:hidden`. content-box keeps
         *  `height` the text row; the padding adds the scale headroom around it. */
        padding-block: var(--ra-scale-pad, 0px);
        box-sizing: content-box;
        line-height: var(--ra-line-height);
        font-family: var(--ra-font);
        font-size: var(--ra-font-size);
        letter-spacing: var(--ra-letter-spacing);
        word-spacing: var(--ra-word-spacing);
        color: var(--ra-base-color);
    }

    /* End-of-ayah marker (۝ + Arabic-Indic numeral). Quiet divider; always
     *  visible (not part of the reveal). Inherits the line font + base color;
     *  gets the base outline. */
    .ra-ayah-marker {
        display: inline-block;
        color: var(--ra-base-color);
        text-shadow: var(--ra-word-shadow);
    }

    /* Word granularity: the word is the animated unit. Word mode renders the
     *  word as plain text (not per-char spans), so the outline traces the whole
     *  word silhouette rather than each joined letter. */
    .ra-word {
        display: inline-block;
        cursor: pointer;
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
     *  warns it as unused). Word-mode only — char mode reuses the same word-level
     *  classes for a different purpose (whole-word fallback, see below). */
    .ra-line:not(.ra-chars) .ra-word:global(.reached) {
        opacity: 1; /* visited words stay fully visible (no reached-dim) */
    }
    .ra-line:not(.ra-chars) .ra-word:global(.active) {
        opacity: 1;
        color: var(--ra-highlight);
        transform: scale(var(--ra-active-scale));
        text-shadow: var(--ra-word-shadow-active);
    }

    /* Char granularity: the word stays lit; characters are the animated unit.
     *  The legibility stroke is drawn ONCE at the word-silhouette level via the
     *  `.ra-word-ink` underlay (a transparent-fill copy of the whole word that
     *  carries the outline), so cursive-joined letters are never individually
     *  stroked — a per-char outline shows dark seams across the joins. */
    .ra-line.ra-chars .ra-word {
        opacity: 1;
        position: relative;
        /* Don't inherit the word outline down to each char span. */
        text-shadow: none;
    }
    .ra-line.ra-chars .ra-word-ink {
        position: absolute;
        inset: 0;
        z-index: 0;
        color: transparent;
        text-shadow: var(--ra-word-shadow);
        white-space: nowrap;
        pointer-events: none;
        /* Tie the stroke's strength to the upcoming-text level so it never
         *  dominates a faint fill (which read as inverted/dark text when the
         *  letters were Dim or Hidden). At Hidden (0) the outline vanishes too. */
        opacity: var(--ra-unreached-opacity);
    }
    .ra-line.ra-chars .ra-char {
        position: relative;
        z-index: 1;
        opacity: var(--ra-unreached-opacity);
        transition:
            opacity var(--ra-char-reveal) var(--ra-easing),
            color var(--ra-active-emphasis) var(--ra-easing),
            text-shadow var(--ra-active-emphasis) var(--ra-easing);
    }
    .ra-line.ra-chars .ra-char:global(.reached) {
        opacity: 1; /* visited words stay fully visible (no reached-dim) */
    }
    .ra-line.ra-chars .ra-char:global(.active) {
        opacity: 1;
        color: var(--ra-highlight);
        /* Glow only — never re-stroke the active letter. */
        text-shadow: var(--ra-glow);
    }

    /* Char mode: only the ACTIVE word is shown letter-by-letter. Previous and
     *  upcoming words fall back to the WHOLE-WORD silhouette so they read like
     *  word mode — splitting a word into per-letter spans breaks Arabic cursive
     *  joining (isolated forms with visible seams, the "letter borders"). The
     *  `.ra-word-ink` underlay is already the full word as one joined text node,
     *  so for non-active words we fill it (make it the visible text) and hide the
     *  per-letter spans. Independent of the upcoming-visibility (eye) setting —
     *  the ink still carries the unreached opacity for dimming. */
    .ra-line.ra-chars .ra-word:not(:global(.active)) .ra-word-ink {
        color: var(--ra-base-color);
    }
    .ra-line.ra-chars .ra-word:not(:global(.active)) .ra-char {
        opacity: 0;
    }
    /* Already-recited words stay fully visible, like word-mode reached. */
    .ra-line.ra-chars .ra-word:global(.reached) .ra-word-ink {
        opacity: 1;
    }

    /* One-frame transition kill across a granularity / layout re-page so words
     *  snap to their new-mode opacity instead of all fading together (the
     *  letter→word flash). */
    .ra-line.ra-no-transition .ra-word,
    .ra-line.ra-no-transition.ra-chars .ra-word,
    .ra-line.ra-no-transition.ra-chars .ra-char,
    .ra-line.ra-no-transition.ra-chars .ra-word-ink {
        transition: none;
    }

    @media (prefers-reduced-motion: reduce) {
        .ra-word,
        .ra-line.ra-chars .ra-char {
            transition: none;
        }
    }
</style>
