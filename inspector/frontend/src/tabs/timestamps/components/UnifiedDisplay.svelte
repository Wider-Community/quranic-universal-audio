<script lang="ts">
    /**
     * UnifiedDisplay — the analysis-mode view for the Timestamps tab.
     *
     * Structure is rendered declaratively via `{#each}` from the `$loadedVerse`
     * store. Per-frame highlights (current word / phoneme / letter) are applied
     * imperatively via `updateHighlights()` — the caller invokes this from the
     * per-frame animation loop, avoiding a reactive re-render at 60fps.
     *
     * Hybrid pattern: Svelte `{#each}` owns structure (words, letter rows,
     * phoneme rows); `bind:this` gives us the container; `querySelectorAll`
     * pulls elements to apply `.active` / `.past` classList imperatively.
     * Scoped styles use `:global()` selectors for the dynamic classes.
     */

    import { onDestroy, untrack } from 'svelte';
    import { get } from 'svelte/store';

    import { ensureDashCovering } from '../../../lib/playback/dash-covering';
    import { dashPort } from '../../../lib/playback/dash-port';
    import type { PhonemeInterval, TsWord } from '../../../lib/types/ts-client';
    import {
        showLetters,
        showPhonemes,
        showTranslations,
        tsHoveredElement,
        tsWaveformHoverTime,
        verseTranslations,
    } from '../stores/display';
    import type { TsLoopTarget } from '../stores/playback';
    import { loopTarget } from '../stores/playback';
    import { loadedVerse } from '../stores/verse';
    import { TS_CLICK_DELAY_MS } from '../utils/constants';
    import WordTranslation from './WordTranslation.svelte';

    // ---- Local structural state (derived declaratively from loadedVerse) ----

    interface RenderedLetter {
        /** One grapheme = one cell (letters are never grouped, even when they
         *  share timing) — the sole exception is alef-maksura + dagger alef (ىٰ),
         *  one long-vowel unit folded into a single cell. A `silent` grapheme is
         *  greyed, non-interactive, and never highlighted — the highlight/hover/
         *  click land on the pronounced letter that shares its timing. */
        ch: string;
        silent: boolean;
        start: number | null;
        end: number | null;
        isNull: boolean;
    }

    interface RenderedPhoneme {
        interval: PhonemeInterval;
        /** Flat interval index (for highlight matching + click seek). */
        index: number;
    }

    interface RenderedBridge {
        phonemes: RenderedPhoneme[];
    }

    interface RenderedBlock {
        word: TsWord;
        wordIndex: number;
        letters: RenderedLetter[];
        phonemes: RenderedPhoneme[];
        /** Optional bridge to render before this block. */
        bridge: RenderedBridge | null;
    }

    // Container ref used for imperative highlight updates.
    let rootEl: HTMLDivElement;

    // Reactive: rebuild rendered structure whenever loadedVerse changes. Bridges
    // are baked into the shard (each merger phone carries a ``bridge`` rule), so
    // there's nothing async to wait for — buildRendered just lifts the tagged
    // phones into gold bridge tiles.
    $: rendered = buildRendered(
        $loadedVerse?.data.words ?? [],
        $loadedVerse?.data.intervals ?? [],
    );

    // Reset previous-index cache when structure changes (new verse, etc.)
    $: rendered, (_prevActiveWordIdx = -1);
    $: rendered, (_prevActivePhonemeIdx = -1);
    // Clear stale highlight classes on verse change. The keyed `{#each}` reuses
    // DOM nodes whose `block.wordIndex` matches across verses (typically 0,1,2…),
    // so without this the prior verse's `.active`/`.past` classes survive on
    // reused nodes until the next rAF tick. Between auto-next pause-and-flush
    // and the new audio's `play` event the rAF loop is stopped, so the user
    // sees the stale highlight pinned on the old word until playback resumes.
    $: rendered, _resetHighlightClasses();
    function _resetHighlightClasses(): void {
        if (!rootEl) return;
        rootEl.querySelectorAll<HTMLElement>('.mega-block').forEach((b) => {
            b.classList.remove('active', 'past', 'hover-preview');
        });
        rootEl.querySelectorAll<HTMLElement>('.mega-phoneme').forEach((p) => {
            p.classList.remove('active', 'hover-preview');
        });
        rootEl.querySelectorAll<HTMLElement>('.mega-letter:not(.null-ts)').forEach((l) => {
            l.classList.remove('active', 'hover-preview');
        });
    }

    // Waveform hover → re-run highlights. The rAF loop is stopped while paused,
    // so without this reactive trigger hover-driven previews wouldn't repaint.
    // Loop target changes also retrigger so `.loop` classes update.
    //
    // `untrack` is critical here: `updateHighlights()` mutates `_prevActiveWordIdx`
    // / `_prevActivePhonemeIdx` (top-level `let`s, which Svelte 5 legacy mode
    // treats as reactive state). Without `untrack` the imperative reads of
    // those fields inside `updateHighlights` would become dependencies of THIS
    // effect, and the subsequent writes inside the same function would re-fire
    // the effect — Svelte 5 raises `effect_update_depth_exceeded` after ~200
    // such re-runs, which broke first-load reactivity wholesale.
    $: ($tsWaveformHoverTime, $loopTarget, untrack(() => updateHighlights()));

    // ---- Pure helpers (state-free) ----

    // Alef-maksura (ى U+0649) + dagger alef (ٰ U+0670) is one long-vowel unit
    // (علىٰ, موسىٰ, إلىٰ). The aligner splits the dagger into its own shard letter,
    // but the two render as a single cell. Folding by char is safe — an alef-
    // maksura never carries an independent dagger. Every other grapheme stays its
    // own cell: a carrier waw keeps its (silent) waw + dagger split, a consonant's
    // dagger stays independent.
    const ALEF_MAKSURA = 'ى';
    const DAGGER_ALEF = 'ٰ';

    function letterGroupsFor(word: TsWord): RenderedLetter[] {
        const out: RenderedLetter[] = [];
        for (const letter of word.letters || []) {
            const prev = out[out.length - 1];
            if (prev && letter.char.startsWith(DAGGER_ALEF) && prev.ch.endsWith(ALEF_MAKSURA)) {
                // Fold the dagger onto the maksura cell: one combined unit spanning
                // both timings, sounding unless both graphemes are silent.
                prev.ch += letter.char;
                if (letter.end != null) prev.end = letter.end;
                prev.silent = prev.silent && letter.silent === true;
                prev.isNull = prev.isNull || letter.start == null || letter.end == null;
                continue;
            }
            out.push({
                ch: letter.char,
                silent: letter.silent === true,
                start: letter.start,
                end: letter.end,
                isNull: letter.start == null || letter.end == null,
            });
        }
        return out;
    }

    /** Split a phone string into base character(s) and trailing IPA modifiers
     *  (length ː, emphatic ˤ, ghunnah tilde ̃). The modifier is rendered as a
     *  superscript so the base stays visually centred in the cell. */
    // Only length marks (ː / ASCII :) are detached modifiers; ˤ is integral to
    // the consonant symbol (rˤ, aˤ) and must stay in the base.
    const PHONE_MOD_RE = /([ː:]+)$/u;
    function splitPhone(phone: string | undefined): { base: string; mod: string } {
        if (!phone || phone === 'sil' || phone === 'sp') return { base: phone ?? '', mod: '' };
        const m = PHONE_MOD_RE.exec(phone);
        return m ? { base: phone.slice(0, -m[0].length), mod: m[0] } : { base: phone, mod: '' };
    }

    /** Parse the trailing word number from a ``surah:ayah:word`` location.
     *  Returns 0 when the location is malformed — caller filters those out. */
    function buildRendered(
        words: TsWord[],
        intervals: PhonemeInterval[],
    ): RenderedBlock[] {
        if (!words.length) return [];

        // Cross-word bridges are baked into the shard at generation: a phoneme
        // carrying a ``bridge`` rule is the idgham merger that fuses two words.
        // Lift it out of its inline row into the gold tile at the boundary — no
        // scanning, no side inference. A merger at a word's head renders before
        // that block; one in a word's tail (idgham shafawi) bridges into the
        // next block. The generator placed the tag on the exact merger interval,
        // so there's nothing to disambiguate here.
        const bridgeBeforeBlock = new Map<number, RenderedPhoneme>();
        const excluded = new Set<number>();
        for (let wi = 0; wi < words.length; wi++) {
            const indices = words[wi]?.phoneme_indices ?? [];
            for (let k = 0; k < indices.length; k++) {
                const pi = indices[k]!;
                if (!intervals[pi]?.bridge) continue;
                const target = k === 0 ? wi : wi + 1;
                if (target < words.length) {
                    bridgeBeforeBlock.set(target, { interval: intervals[pi]!, index: pi });
                    excluded.add(pi);
                }
            }
        }

        const blocks: RenderedBlock[] = [];
        for (let wi = 0; wi < words.length; wi++) {
            const word = words[wi];
            if (!word) continue;

            const bp = bridgeBeforeBlock.get(wi);
            const bridge: RenderedBridge | null = bp ? { phonemes: [bp] } : null;

            const phonemes: RenderedPhoneme[] = [];
            for (const pi of word.phoneme_indices ?? []) {
                if (excluded.has(pi)) continue;
                const iv = intervals[pi];
                if (iv && !iv.geminate_end) phonemes.push({ interval: iv, index: pi });
            }

            blocks.push({
                word,
                wordIndex: wi,
                letters: letterGroupsFor(word),
                phonemes,
                bridge,
            });
        }
        return blocks;
    }

    // ---- Per-frame imperative highlight update (called from animation loop) ----

    let _prevActiveWordIdx = -1;
    let _prevActivePhonemeIdx = -1;

    /**
     * Apply current-time-based highlights imperatively. Called from the
     * animation loop via bind:this; does NOT go through Svelte reactivity
     * so we stay at 60fps with minimal GC pressure.
     */
    export function updateHighlights(): void {
        if (!rootEl) return;
        const lv = get(loadedVerse);
        if (!lv) return;
        const time = getSegRelTime(lv.tsSegOffset);

        const intervals = lv.data.intervals;
        const words = lv.data.words;
        const portReady = !!dashPort.element;
        const portPaused = dashPort.paused;
        const hoverTime = get(tsWaveformHoverTime);

        // Current phoneme (skip geminate_end)
        let currentIndex = -1;
        for (let i = 0; i < intervals.length; i++) {
            const iv = intervals[i];
            if (!iv) continue;
            if (time >= iv.start && time < iv.end) {
                currentIndex = iv.geminate_end ? i - 1 : i;
                break;
            }
        }

        // Current word
        let currentWordIndex = -1;
        for (let i = 0; i < words.length; i++) {
            const w = words[i];
            if (!w) continue;
            if (time >= w.start && time < w.end) {
                currentWordIndex = i;
                break;
            }
        }

        // Block highlights (.active / .past) — diff-only.
        // Suppress scrollIntoView when the update is driven by waveform hover
        // (user is actively scrubbing; auto-scrolling would fight the pointer).
        let hoverWordIndex = -1;
        let hoverPhonemeIndex = -1;
        const showWaveformPreview = hoverTime != null && portReady && !portPaused;
        if (showWaveformPreview) {
            for (let i = 0; i < words.length; i++) {
                const w = words[i];
                if (!w) continue;
                if (hoverTime >= w.start && hoverTime < w.end) {
                    hoverWordIndex = i;
                    break;
                }
            }
            if (hoverWordIndex === currentWordIndex) {
                hoverWordIndex = -1;
            } else {
                for (let i = 0; i < intervals.length; i++) {
                    const iv = intervals[i];
                    if (!iv) continue;
                    if (hoverTime >= iv.start && hoverTime < iv.end) {
                        hoverPhonemeIndex = iv.geminate_end ? i - 1 : i;
                        break;
                    }
                }
            }
        }
        const isHoverDriven = hoverTime != null && portReady && portPaused;
        if (currentWordIndex !== _prevActiveWordIdx) {
            const blocks = rootEl.querySelectorAll<HTMLElement>('.mega-block');
            blocks.forEach((block) => {
                const wi = parseInt(block.dataset.wordIndex ?? '-1');
                block.classList.remove('active', 'past');
                if (wi === currentWordIndex) {
                    block.classList.add('active');
                    if (!isHoverDriven) block.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                } else if (currentWordIndex >= 0 && wi < currentWordIndex) {
                    block.classList.add('past');
                }
            });
            _prevActiveWordIdx = currentWordIndex;
        }
        rootEl.querySelectorAll<HTMLElement>('.mega-block').forEach((block) => {
            const wi = parseInt(block.dataset.wordIndex ?? '-1');
            block.classList.toggle('hover-preview', wi === hoverWordIndex);
        });

        // Phoneme highlights — diff-only
        if (currentIndex !== _prevActivePhonemeIdx) {
            rootEl.querySelectorAll<HTMLElement>('.mega-phoneme').forEach((ph) => {
                ph.classList.toggle('active', parseInt(ph.dataset.index ?? '-1') === currentIndex);
            });
            _prevActivePhonemeIdx = currentIndex;
        }
        rootEl.querySelectorAll<HTMLElement>('.mega-phoneme').forEach((ph) => {
            ph.classList.toggle('hover-preview', parseInt(ph.dataset.index ?? '-1') === hoverPhonemeIndex);
        });

        // Letter highlights — must check each frame (time-based within word).
        // Silent cells are excluded: at a shared [start,end] the highlight lands
        // on the pronounced letter alone.
        rootEl
            .querySelectorAll<HTMLElement>('.mega-letter:not(.null-ts):not(.silent)')
            .forEach((el) => {
                const s = parseFloat(el.dataset.letterStart ?? '0');
                const e = parseFloat(el.dataset.letterEnd ?? '0');
                const wi = parseInt(el.dataset.wordIndex ?? '-1');
                el.classList.toggle('active', time >= s && time < e);
                el.classList.toggle(
                    'hover-preview',
                    hoverTime != null && wi === hoverWordIndex && hoverTime >= s && hoverTime < e,
                );
            });

        // Loop perma-highlight — outline the looped element on its tier.
        const lp = get(loopTarget);
        rootEl.querySelectorAll<HTMLElement>('.mega-block').forEach((block) => {
            const wi = parseInt(block.dataset.wordIndex ?? '-1');
            block.classList.toggle(
                'loop',
                lp?.kind === 'word' && lp.wordIndex === wi,
            );
        });
        rootEl.querySelectorAll<HTMLElement>('.mega-letter:not(.null-ts)').forEach((el) => {
            const wi = parseInt(el.dataset.wordIndex ?? '-1');
            const li = parseInt(el.dataset.letterIndex ?? '-1');
            el.classList.toggle(
                'loop',
                lp?.kind === 'letter' && lp.wordIndex === wi && lp.childIndex === li,
            );
        });
        rootEl.querySelectorAll<HTMLElement>('.mega-phoneme').forEach((el) => {
            const idx = parseInt(el.dataset.index ?? '-1');
            el.classList.toggle(
                'loop',
                lp?.kind === 'phoneme' && lp.childIndex === idx,
            );
        });
    }

    function getSegRelTime(segOffset: number): number {
        if (!dashPort.element) return 0;
        // While paused, waveform hover drives a preview: treat the hovered
        // slice-relative time as the "current" time so block highlights
        // (active word / letter / phoneme) follow the pointer.
        const hoverT = get(tsWaveformHoverTime);
        if (hoverT != null && dashPort.paused) return hoverT;
        return dashPort.currentTimeMs() / 1000 - segOffset;
    }

    /** Scroll the active mega-block into view (keyboard `J`). */
    export function scrollActiveIntoView(): void {
        if (!rootEl) return;
        const active = rootEl.querySelector<HTMLElement>('.mega-block.active');
        if (active) active.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    // ---- Click handlers: seek audio on click ----

    function seekToTime(absTime: number): void {
        if (!dashPort.element) return;
        const targetMs = absTime * 1000;
        ensureDashCovering(targetMs);
        dashPort.seek(targetMs);
        // Clicking a block always starts playback — resumes if paused.
        if (dashPort.paused) dashPort.play();
        // Force a repaint immediately after user seek (not waiting on timeupdate)
        updateHighlights();
    }

    // Single-click handlers are DEFERRED by `TS_CLICK_DELAY_MS` to
    // disambiguate from double-click. The DOM fires `click` before
    // `dblclick`, so without this defer the sequence for a user double-
    // clicking word B while looped on word A would be:
    //   click#1 → swap loop A → B → zoom animates to B
    //   click#2 → no-op (already on B)
    //   dblclick → toggleLoopOn(B) sees sameTarget → clears loop → zoom
    //              resets to full view. Net effect: "dblclick on B
    //              destroyed my loop". Deferring click and cancelling it
    //              on dblclick gives dblclick exclusive say over loop
    //              toggling.
    //
    // When in loop mode and the click lands on a DIFFERENT word (or tier
    // target), the committed click swaps the loop target — matching the
    // waveform and Animation-view click surfaces so all three behave
    // identically.
    let _pendingClick: number | null = null;

    function _cancelPendingClick(): void {
        if (_pendingClick !== null) {
            clearTimeout(_pendingClick);
            _pendingClick = null;
        }
    }

    function _deferClick(fn: () => void): void {
        _cancelPendingClick();
        _pendingClick = window.setTimeout(() => {
            _pendingClick = null;
            fn();
        }, TS_CLICK_DELAY_MS);
    }

    function _swapLoopOrSeek(target: TsLoopTarget, absSeek: number): void {
        const cur = get(loopTarget);
        if (cur) {
            const same =
                cur.kind === target.kind
                && cur.wordIndex === target.wordIndex
                && cur.childIndex === target.childIndex;
            if (same) return;
            loopTarget.set(target);
            if (dashPort.element) {
                const targetMs = absSeek * 1000;
                ensureDashCovering(targetMs);
                dashPort.seek(targetMs);
                if (dashPort.paused) dashPort.play();
            }
            updateHighlights();
            return;
        }
        // No loop active → pure seek.
        if (!dashPort.element) return;
        const targetMs = absSeek * 1000;
        ensureDashCovering(targetMs);
        dashPort.seek(targetMs);
        if (dashPort.paused) dashPort.play();
        updateHighlights();
    }

    function onWordClick(word: TsWord, wordIndex: number): void {
        _deferClick(() => {
            const lv = get(loadedVerse);
            if (!lv) return;
            _swapLoopOrSeek(
                { kind: 'word', startSec: word.start, endSec: word.end, wordIndex },
                word.start + lv.tsSegOffset,
            );
        });
    }

    function onPhonemeClick(
        e: MouseEvent,
        iv: PhonemeInterval,
        phonemeIndex: number,
        wordIndex: number,
    ): void {
        e.stopPropagation();
        _deferClick(() => {
            const lv = get(loadedVerse);
            if (!lv) return;
            _swapLoopOrSeek(
                {
                    kind: 'phoneme',
                    startSec: iv.start,
                    endSec: iv.end,
                    wordIndex,
                    childIndex: phonemeIndex,
                },
                iv.start + lv.tsSegOffset,
            );
        });
    }

    // ---- Double-click handlers: toggle loop on the clicked token ----

    /**
     * Toggle loop on the given token. If it's already the looped target,
     * exit loop mode; otherwise engage loop + seek to its start.
     */
    function toggleLoopOn(target: TsLoopTarget): void {
        const lv = get(loadedVerse);
        if (!lv) return;
        const cur = get(loopTarget);
        const sameTarget =
            cur?.kind === target.kind
            && cur.wordIndex === target.wordIndex
            && cur.childIndex === target.childIndex;
        if (sameTarget) {
            loopTarget.set(null);
            return;
        }
        loopTarget.set(target);
        seekToTime(target.startSec + lv.tsSegOffset);
        // Zoom/pan is handled by the centralized `loopTarget` subscription in
        // `utils/zoom.ts::setupZoomLifecycle` — no per-callsite hook needed.
    }

    function onWordDblClick(word: TsWord, wordIndex: number): void {
        _cancelPendingClick();
        toggleLoopOn({ kind: 'word', startSec: word.start, endSec: word.end, wordIndex });
    }

    function onLetterDblClick(
        e: MouseEvent,
        startSec: number,
        endSec: number,
        wordIndex: number,
        letterIndex: number,
    ): void {
        e.stopPropagation();
        _cancelPendingClick();
        toggleLoopOn({ kind: 'letter', startSec, endSec, wordIndex, childIndex: letterIndex });
    }

    function onPhonemeDblClick(
        e: MouseEvent,
        iv: PhonemeInterval,
        phonemeIndex: number,
        wordIndex: number,
    ): void {
        e.stopPropagation();
        _cancelPendingClick();
        toggleLoopOn({
            kind: 'phoneme',
            startSec: iv.start,
            endSec: iv.end,
            wordIndex,
            childIndex: phonemeIndex,
        });
    }

    function onLetterClick(
        e: MouseEvent,
        startSec: number,
        endSec: number,
        wordIndex: number,
        letterIndex: number,
    ): void {
        e.stopPropagation();
        _deferClick(() => {
            const lv = get(loadedVerse);
            if (!lv) return;
            _swapLoopOrSeek(
                { kind: 'letter', startSec, endSec, wordIndex, childIndex: letterIndex },
                startSec + lv.tsSegOffset,
            );
        });
    }

    // ---- Hover handlers: publish to tsHoveredElement for waveform sync ----

    function onWordEnter(word: TsWord): void {
        tsHoveredElement.set({ kind: 'word', startSec: word.start, endSec: word.end });
    }

    function onLetterEnter(startSec: number | null, endSec: number | null): void {
        if (startSec == null || endSec == null) return;
        tsHoveredElement.set({ kind: 'letter', startSec, endSec });
    }

    function onPhonemeEnter(iv: PhonemeInterval): void {
        tsHoveredElement.set({ kind: 'phoneme', startSec: iv.start, endSec: iv.end });
    }

    function onHoverLeave(): void {
        tsHoveredElement.set(null);
    }

    // Safety net: if the component unmounts while a hover is active (e.g. view
    // switch), clear the store so the waveform doesn't keep a stale band.
    // Also drop any pending deferred click so it doesn't fire post-unmount.
    onDestroy(() => {
        tsHoveredElement.set(null);
        _cancelPendingClick();
    });
</script>

<div
    bind:this={rootEl}
    class="unified-display"
    dir="rtl"
    class:hidden={$loadedVerse === null}
>
    {#each rendered as block (block.wordIndex)}
        {#if block.bridge}
            <div class="crossword-bridge" class:hidden={!$showPhonemes}>
                {#each block.bridge.phonemes as ph (ph.index)}
                    {@const parts = splitPhone(ph.interval.phone)}
                    <span
                        class="mega-phoneme"
                        class:silence={!ph.interval.phone ||
                            ph.interval.phone === 'sil' ||
                            ph.interval.phone === 'sp'}
                        class:geminate={ph.interval.geminate_start}
                        data-index={ph.index}
                        on:click={(e) => onPhonemeClick(e, ph.interval, ph.index, block.wordIndex)}
                        on:dblclick={(e) => onPhonemeDblClick(e, ph.interval, ph.index, block.wordIndex)}
                        on:mouseenter={() => onPhonemeEnter(ph.interval)}
                        on:mouseleave={onHoverLeave}
                        on:keydown={() => {}}
                        role="button"
                        tabindex="-1"
                    >
                        <span class="ph-base">{parts.base || '(sil)'}</span>{#if parts.mod}<sup class="ph-mod">{parts.mod}</sup>{/if}
                    </span>
                {/each}
            </div>
        {/if}
        <div
            class="mega-block"
            data-word-index={block.wordIndex}
            on:click={() => onWordClick(block.word, block.wordIndex)}
            on:dblclick={() => onWordDblClick(block.word, block.wordIndex)}
            on:keydown={() => {}}
            role="button"
            tabindex="-1"
        >
            {#if $showTranslations}
                <WordTranslation text={$verseTranslations[block.word.location] ?? ''} />
            {/if}
            <div
                class="mega-word"
                role="group"
                on:mouseenter={() => onWordEnter(block.word)}
                on:mouseleave={onHoverLeave}
            >{block.word.display_text || block.word.text}</div>
            {#if block.letters.length}
                <div class="mega-letters" class:hidden={!$showLetters} dir="rtl">
                    {#each block.letters as lt, li (li)}
                        {#if lt.isNull}
                            <span
                                class="mega-letter null-ts"
                                class:silent={lt.silent}
                                on:click|stopPropagation
                                on:keydown={() => {}}
                                role="button"
                                tabindex="-1"
                            >{lt.ch}</span>
                        {:else}
                            <span
                                class="mega-letter"
                                class:silent={lt.silent}
                                data-letter-start={lt.start}
                                data-letter-end={lt.end}
                                data-word-index={block.wordIndex}
                                data-letter-index={li}
                                on:click={(e) =>
                                    onLetterClick(e, lt.start ?? 0, lt.end ?? 0, block.wordIndex, li)}
                                on:dblclick={(e) =>
                                    onLetterDblClick(e, lt.start ?? 0, lt.end ?? 0, block.wordIndex, li)}
                                on:mouseenter={() => onLetterEnter(lt.start, lt.end)}
                                on:mouseleave={onHoverLeave}
                                on:keydown={() => {}}
                                role="button"
                                tabindex="-1"
                            >{lt.ch}</span>
                        {/if}
                    {/each}
                </div>
            {/if}
            <div class="mega-phonemes" class:hidden={!$showPhonemes} dir="rtl">
                {#each block.phonemes as ph (ph.index)}
                    {@const parts = splitPhone(ph.interval.phone)}
                    <span
                        class="mega-phoneme"
                        class:silence={!ph.interval.phone ||
                            ph.interval.phone === 'sil' ||
                            ph.interval.phone === 'sp'}
                        class:geminate={ph.interval.geminate_start}
                        data-index={ph.index}
                        on:click={(e) => onPhonemeClick(e, ph.interval, ph.index, block.wordIndex)}
                        on:dblclick={(e) => onPhonemeDblClick(e, ph.interval, ph.index, block.wordIndex)}
                        on:mouseenter={() => onPhonemeEnter(ph.interval)}
                        on:mouseleave={onHoverLeave}
                        on:keydown={() => {}}
                        role="button"
                        tabindex="-1"
                    >
                        <span class="ph-base">{parts.base || '(sil)'}</span>{#if parts.mod}<sup class="ph-mod">{parts.mod}</sup>{/if}
                    </span>
                {/each}
            </div>
        </div>
    {/each}
</div>
