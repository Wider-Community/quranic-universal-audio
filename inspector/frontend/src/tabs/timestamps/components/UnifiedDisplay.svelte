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

    import { get } from 'svelte/store';

    import { loadedVerse } from '../stores/verse';
    import { showLetters, showPhonemes } from '../stores/display';
    import { tsAudioElement } from '../stores/playback';
    import { IDGHAM_GHUNNAH_START, stripTashkeel } from '../../../lib/utils/arabic-text';
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

        // Block highlights (.active / .past) — diff-only
        if (currentWordIndex !== _prevActiveWordIdx) {
            const blocks = rootEl.querySelectorAll<HTMLElement>('.mega-block');
            blocks.forEach((block) => {
                const wi = parseInt(block.dataset.wordIndex ?? '-1');
                block.classList.remove('active', 'past');
                if (wi === currentWordIndex) {
                    block.classList.add('active');
                    block.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                } else if (currentWordIndex >= 0 && wi < currentWordIndex) {
                    block.classList.add('past');
                }
            });
            _prevActiveWordIdx = currentWordIndex;
        }

        // Phoneme highlights — diff-only
        if (currentIndex !== _prevActivePhonemeIdx) {
            rootEl.querySelectorAll<HTMLElement>('.mega-phoneme').forEach((ph) => {
                ph.classList.toggle('active', parseInt(ph.dataset.index ?? '-1') === currentIndex);
            });
            _prevActivePhonemeIdx = currentIndex;
        }

        // Letter highlights — must check each frame (time-based within word)
        rootEl
            .querySelectorAll<HTMLElement>('.mega-letter:not(.null-ts)')
            .forEach((el) => {
                const s = parseFloat(el.dataset.letterStart ?? '0');
                const e = parseFloat(el.dataset.letterEnd ?? '0');
                el.classList.toggle('active', time >= s && time < e);
            });
    }

    function getSegRelTime(segOffset: number): number {
        const audio = get(tsAudioElement);
        if (!audio) return 0;
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
        // Force a repaint immediately after user seek (not waiting on timeupdate)
        updateHighlights();
    }

    function onWordClick(word: TsWord): void {
        const lv = get(loadedVerse);
        if (!lv) return;
        seekToTime(word.start + lv.tsSegOffset);
    }

    function onPhonemeClick(e: MouseEvent, iv: PhonemeInterval): void {
        e.stopPropagation();
        const lv = get(loadedVerse);
        if (!lv) return;
        seekToTime(iv.start + lv.tsSegOffset);
    }

    function onLetterClick(e: MouseEvent, startSec: number): void {
        e.stopPropagation();
        const lv = get(loadedVerse);
        if (!lv) return;
        seekToTime(startSec + lv.tsSegOffset);
    }
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
                        on:click={(e) => onPhonemeClick(e, ph.interval)}
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
            on:click={() => onWordClick(block.word)}
            on:keydown={() => {}}
            role="button"
            tabindex="-1"
        >
            <div class="mega-word">{block.word.display_text || block.word.text}</div>
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
                                on:click={(e) => onLetterClick(e, lt.start ?? 0)}
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
                        on:click={(e) => onPhonemeClick(e, ph.interval)}
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
