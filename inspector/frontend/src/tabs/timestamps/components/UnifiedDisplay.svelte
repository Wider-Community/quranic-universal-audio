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

    import { dashPort } from '../../../lib/playback/dash-port';
    import type { PhonemeInterval, TsWord } from '../../../lib/types/domain';
    import type { BridgeInfo } from '../../../lib/types/generated/schemas';
    import {
        showLetters,
        showPhonemes,
        showTranslations,
        tsHoveredElement,
        tsWaveformHoverTime,
        verseTranslations,
    } from '../stores/display';
    import type { TsLoopTarget } from '../stores/playback';
    import { autoMode, loopTarget } from '../stores/playback';
    import { loadedTajweedBridges, loadedVerse } from '../stores/verse';
    import { TS_CLICK_DELAY_MS } from '../utils/constants';
    import WordTranslation from './WordTranslation.svelte';

    // ---- Local structural state (derived declaratively from loadedVerse) ----

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

    // Reactive: rebuild rendered structure whenever loadedVerse OR its bridges
    // change. Bridges arrive asynchronously after the verse paints (the
    // /api/ts/tajweed fetch is independent), so we re-run buildRendered when
    // they land — that's what flips the cross-word phoneme out of the regular
    // mega-phoneme row and into the gold bridge tile.
    $: rendered = buildRendered(
        $loadedVerse?.data.words ?? [],
        $loadedVerse?.data.intervals ?? [],
        $loadedTajweedBridges,
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

    /** Parse the trailing word number from a ``surah:ayah:word`` location.
     *  Returns 0 when the location is malformed — caller filters those out. */
    function wordNumOf(word: TsWord): number {
        const parts = word.location.split(':');
        const n = parseInt(parts[parts.length - 1] ?? '0', 10);
        return Number.isFinite(n) ? n : 0;
    }

    /** Does this shard phoneme carry the merger signature for our 8 cross-word
     *  rules? Mirrors the backend's :func:`_is_merger_phoneme` (pharyngeal-aware
     *  doubled-prefix + ghunnah tilde) — *required on the FE* because MFA's
     *  word-segmentation can put the merged phoneme on the OTHER side of the
     *  boundary than the phonemizer's per-word convention says it should be
     *  (e.g. Ahmed Talib 46:29: phonemizer-without-stops puts ``m̃`` at curr's
     *  first position of ``مِّنَ``; MFA appended it to the prev word's tail on
     *  ``نَفَرࣰا`` after the trigger letter's vowel). The backend's ``side`` is a
     *  hint built from the phonemizer's per-letter output; we override it with
     *  the actual shard placement so the bridge tile shows the real merger
     *  phoneme, never an adjacent haraka. */
    const GHUNNAH_TILDE = '̃';
    const PHARYNGEAL = 'ˤ';
    function isMergerPhoneme(p: string | undefined): boolean {
        if (!p) return false;
        if (p.includes(GHUNNAH_TILDE) || p.includes('ñ')) return true;
        const base = p.replaceAll(PHARYNGEAL, '');
        return base.length >= 2 && base[0] === base[1];
    }

    function buildRendered(
        words: TsWord[],
        intervals: PhonemeInterval[],
        bridgeInfos: BridgeInfo[],
    ): RenderedBlock[] {
        if (!words.length) return [];

        // Shards intentionally carry duplicate word occurrences when the
        // reciter repeats a phrase (the second take is part of the
        // recitation, not a pathology). For each shard pair we therefore
        // ask: are these two adjacent occurrences a real (N-1 → N) Quran
        // boundary? If they are AND the backend predicted a bridge for that
        // boundary, render it in this specific pair. Pairs that are
        // restart-bounded (next word number ≤ this one) get no bridge — the
        // cross-word rule legitimately can't fire across a repetition jump.
        // This yields one bridge tile per real adjacent crossing, including
        // the second tile in a (16,17,18,19, 17,18,19, 20) repeat sequence.
        const bridgeByWordNum = new Map<number, BridgeInfo>();
        for (const b of bridgeInfos) bridgeByWordNum.set(b.before_word_idx, b);

        const bridgePhoneByBlock = new Map<number, number>();
        const excluded = new Set<number>();
        for (let i = 1; i < words.length; i++) {
            const prev = words[i - 1]!;
            const curr = words[i]!;
            const prevWn = wordNumOf(prev);
            const currWn = wordNumOf(curr);
            if (prevWn === 0 || currWn === 0 || currWn !== prevWn + 1) continue;
            const b = bridgeByWordNum.get(currWn);
            if (!b) continue;

            // The backend's ``side`` hint is built from the phonemizer's
            // per-letter output, which assumes a stable convention for where
            // the merged phoneme lives. MFA shards don't always agree — the
            // same idgham can land at prev's tail or curr's head depending on
            // how the aligner segmented the audio (Ahmed Talib 46:29 word 17→
            // 18 shafawi: ``m̃`` lands at prev[-2] because MFA pulled the
            // dammah of ``مُّن`` into the prev word along with the geminated
            // meem). So we ignore the hint and scan a small window from both
            // sides of the boundary, picking the first merger phoneme found —
            // ghunnah-tilde or doubled-consonant prefix. If neither side has
            // a merger within the window the rule didn't fire in this
            // recording (waqf without timing gap), and we suppress the bridge
            // so the tile never shows a stray haraka.
            const SCAN_WINDOW = 3;
            const prevIdx = prev.phoneme_indices;
            const currIdx = curr.phoneme_indices;
            let pi: number | undefined;
            if (prevIdx && prevIdx.length > 0) {
                for (let k = 0; k < Math.min(SCAN_WINDOW, prevIdx.length); k++) {
                    const idx = prevIdx[prevIdx.length - 1 - k]!;
                    if (isMergerPhoneme(intervals[idx]?.phone)) { pi = idx; break; }
                }
            }
            if (pi === undefined && currIdx && currIdx.length > 0) {
                for (let k = 0; k < Math.min(SCAN_WINDOW, currIdx.length); k++) {
                    const idx = currIdx[k]!;
                    if (isMergerPhoneme(intervals[idx]?.phone)) { pi = idx; break; }
                }
            }
            if (pi === undefined || pi < 0) continue;
            bridgePhoneByBlock.set(i, pi);
            excluded.add(pi);
        }

        const blocks: RenderedBlock[] = [];
        for (let wi = 0; wi < words.length; wi++) {
            const word = words[wi];
            if (!word) continue;

            // Bridge before this block (never before the first block).
            let bridge: RenderedBridge | null = null;
            const bridgePi = bridgePhoneByBlock.get(wi);
            if (bridgePi !== undefined) {
                const iv = intervals[bridgePi];
                if (iv && !iv.geminate_end) {
                    bridge = { phonemes: [{ interval: iv, index: bridgePi }] };
                }
            }

            // Phoneme row, excluding any index claimed by an adjacent bridge.
            const indices = word.phoneme_indices || [];
            const phonemes: RenderedPhoneme[] = [];
            for (const pi of indices) {
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
        dashPort.seek(absTime * 1000);
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
                dashPort.seek(absSeek * 1000);
                if (dashPort.paused) dashPort.play();
            }
            updateHighlights();
            return;
        }
        // No loop active → pure seek.
        if (!dashPort.element) return;
        dashPort.seek(absSeek * 1000);
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
