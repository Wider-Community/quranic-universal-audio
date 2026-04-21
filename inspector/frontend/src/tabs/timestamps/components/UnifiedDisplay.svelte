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

    import { onDestroy } from 'svelte';
    import { get } from 'svelte/store';

    import { loadedVerse } from '../stores/verse';
    import {
        showLetters,
        showPhonemes,
        tsHoveredElement,
        tsWaveformHoverTime,
    } from '../stores/display';
    import { autoMode, loopTarget, tsAudioElement } from '../stores/playback';
    import type { TsLoopTarget } from '../stores/playback';
    import { IDGHAM_GHUNNAH_START, stripTashkeel } from '../../../lib/utils/arabic-text';
    import { safePlay } from '../../../lib/utils/audio';
    import { TS_CLICK_DELAY_MS } from '../utils/constants';
    import type { PhonemeInterval, TsWord } from '../../../lib/types/domain';

    // ---- Local structural state (derived declaratively from loadedVerse) ----

    interface BridgeInfo { fromPrev: number[]; fromCurr: number[]; }

    interface RenderedLetter {
        chars: string;
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

    // Reactive: rebuild rendered structure whenever loadedVerse changes.
    $: rendered = buildRendered($loadedVerse?.data.words ?? [], $loadedVerse?.data.intervals ?? []);

    // Reset previous-index cache when structure changes (new verse, etc.)
    $: rendered, (_prevActiveWordIdx = -1);
    $: rendered, (_prevActivePhonemeIdx = -1);

    // Waveform hover → re-run highlights. The rAF loop is stopped while paused,
    // so without this reactive trigger hover-driven previews wouldn't repaint.
    // Loop target changes also retrigger so `.loop` classes update.
    $: ($tsWaveformHoverTime, $loopTarget, updateHighlights());

    // ---- Pure helpers (state-free) ----

    function getLastBaseLetter(word: TsWord): string {
        const bare = stripTashkeel(word.text || '');
        return bare.length ? bare[bare.length - 1] ?? '' : '';
    }

    function getFirstBaseLetter(word: TsWord): string {
        const bare = stripTashkeel(word.text || '');
        for (const ch of bare) {
            if (ch !== '\u0671' && ch !== '\u0627') return ch;
        }
        return bare.length ? bare[0] ?? '' : '';
    }

    function hasTanween(word: TsWord): boolean {
        const text = word.text || '';
        const lastBase = stripTashkeel(text);
        const endsWithAlef =
            lastBase.length > 0 &&
            (lastBase[lastBase.length - 1] === '\u0627' ||
                lastBase[lastBase.length - 1] === '\u0649');
        if (endsWithAlef) return /[\u064B\u08F0]/.test(text);
        const tail = text.slice(-3);
        return /[\u064C\u064D\u08F1\u08F2]/.test(tail);
    }

    function computeBridgeAtBoundary(
        prevWord: TsWord,
        currWord: TsWord,
        intervals: PhonemeInterval[],
    ): BridgeInfo | null {
        const fromPrev: number[] = [];
        const fromCurr: number[] = [];

        const currIndices = currWord.phoneme_indices || [];
        const prevEndsNoon = getLastBaseLetter(prevWord) === '\u0646';
        const prevHasTanween = hasTanween(prevWord);
        const noonOrTanween = prevEndsNoon || prevHasTanween;

        for (const pi of currIndices) {
            const iv = intervals[pi];
            const phone = iv?.phone;
            if (!phone) break;
            const requiredLetter = IDGHAM_GHUNNAH_START[phone];
            if (!requiredLetter) break;
            if (noonOrTanween && getFirstBaseLetter(currWord) === requiredLetter) {
                fromCurr.push(pi);
            } else {
                break;
            }
        }

        const prevIndices = prevWord.phoneme_indices || [];
        if (
            getLastBaseLetter(prevWord) === '\u0645' &&
            getFirstBaseLetter(currWord) === '\u0645'
        ) {
            for (let k = prevIndices.length - 1; k >= 0; k--) {
                const pi = prevIndices[k];
                if (pi === undefined) continue;
                const iv = intervals[pi];
                const phone = iv?.phone;
                if (phone === 'm\u0303') fromPrev.push(pi);
                else break;
            }
            fromPrev.reverse();
        }

        if (fromPrev.length === 0 && fromCurr.length === 0) return null;
        return { fromPrev, fromCurr };
    }

    function letterGroupsFor(word: TsWord): RenderedLetter[] {
        const letters = word.letters || [];
        const groups: RenderedLetter[] = [];
        for (const letter of letters) {
            const isNull = letter.start == null || letter.end == null;
            const last = groups[groups.length - 1];
            if (
                !isNull &&
                last &&
                !last.isNull &&
                last.start === letter.start &&
                last.end === letter.end
            ) {
                last.chars += letter.char;
            } else {
                groups.push({
                    chars: letter.char,
                    start: letter.start,
                    end: letter.end,
                    isNull,
                });
            }
        }
        return groups;
    }

    function buildRendered(words: TsWord[], intervals: PhonemeInterval[]): RenderedBlock[] {
        if (!words.length) return [];

        // Pre-compute bridges per boundary + exclusion sets per word
        const bridges: Array<BridgeInfo | null> = [];
        for (let wi = 1; wi < words.length; wi++) {
            const prev = words[wi - 1];
            const curr = words[wi];
            bridges[wi] =
                prev && curr ? computeBridgeAtBoundary(prev, curr, intervals) : null;
        }
        const exclude: Set<number>[] = words.map(() => new Set<number>());
        for (let wi = 1; wi < words.length; wi++) {
            const b = bridges[wi];
            if (!b) continue;
            const exPrev = exclude[wi - 1];
            const exCurr = exclude[wi];
            if (exPrev) b.fromPrev.forEach((pi) => exPrev.add(pi));
            if (exCurr) b.fromCurr.forEach((pi) => exCurr.add(pi));
        }

        const blocks: RenderedBlock[] = [];
        for (let wi = 0; wi < words.length; wi++) {
            const word = words[wi];
            if (!word) continue;

            // Bridge before this block (not before the first block)
            let bridge: RenderedBridge | null = null;
            const b = bridges[wi];
            if (wi > 0 && b) {
                const all = [...b.fromPrev, ...b.fromCurr];
                const phs: RenderedPhoneme[] = [];
                for (const pi of all) {
                    const iv = intervals[pi];
                    if (iv && !iv.geminate_end) phs.push({ interval: iv, index: pi });
                }
                if (phs.length) bridge = { phonemes: phs };
            }

            // Phoneme row excluding bridge-moved ones
            const indices = word.phoneme_indices || [];
            const ex = exclude[wi] ?? new Set<number>();
            const phonemes: RenderedPhoneme[] = [];
            for (const pi of indices) {
                if (ex.has(pi)) continue;
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
        const audioEl = get(tsAudioElement);
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
        const showWaveformPreview = hoverTime != null && !!audioEl && !audioEl.paused;
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
        const isHoverDriven = hoverTime != null && !!audioEl && audioEl.paused;
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

        // Letter highlights — must check each frame (time-based within word)
        rootEl
            .querySelectorAll<HTMLElement>('.mega-letter:not(.null-ts)')
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
        const audio = get(tsAudioElement);
        if (!audio) return 0;
        // While paused, waveform hover drives a preview: treat the hovered
        // slice-relative time as the "current" time so block highlights
        // (active word / letter / phoneme) follow the pointer.
        const hoverT = get(tsWaveformHoverTime);
        if (hoverT != null && audio.paused) return hoverT;
        return audio.currentTime - segOffset;
    }

    /** Scroll the active mega-block into view (keyboard `J`). */
    export function scrollActiveIntoView(): void {
        if (!rootEl) return;
        const active = rootEl.querySelector<HTMLElement>('.mega-block.active');
        if (active) active.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }

    // ---- Click handlers: seek audio on click ----

    function seekToTime(absTime: number): void {
        const audio = get(tsAudioElement);
        if (!audio) return;
        audio.currentTime = absTime;
        // Clicking a block always starts playback — resumes if paused.
        if (audio.paused) void safePlay(audio);
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
            const audio = get(tsAudioElement);
            if (audio) {
                audio.currentTime = absSeek;
                if (audio.paused) void safePlay(audio);
            }
            updateHighlights();
            return;
        }
        // No loop active → pure seek.
        const audio = get(tsAudioElement);
        if (!audio) return;
        audio.currentTime = absSeek;
        if (audio.paused) void safePlay(audio);
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
     * exit loop mode; otherwise engage loop + seek to its start. Also
     * clears `autoMode` (loop + auto-advance are mutually exclusive).
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
        autoMode.set(null);
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
                        {ph.interval.phone || '(sil)'}
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
            <div
                class="mega-word"
                on:mouseenter={() => onWordEnter(block.word)}
                on:mouseleave={onHoverLeave}
            >{block.word.display_text || block.word.text}</div>
            {#if block.letters.length}
                <div class="mega-letters" class:hidden={!$showLetters} dir="rtl">
                    {#each block.letters as lt, li (li)}
                        {#if lt.isNull}
                            <span
                                class="mega-letter null-ts"
                                on:click|stopPropagation
                                on:keydown={() => {}}
                                role="button"
                                tabindex="-1"
                            >{lt.chars}</span>
                        {:else}
                            <span
                                class="mega-letter"
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
                            >{lt.chars}</span>
                        {/if}
                    {/each}
                </div>
            {/if}
            <div class="mega-phonemes" class:hidden={!$showPhonemes} dir="rtl">
                {#each block.phonemes as ph (ph.index)}
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
                        {ph.interval.phone || '(sil)'}
                    </span>
                {/each}
            </div>
        </div>
    {/each}
</div>
