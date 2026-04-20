<script lang="ts">
    /**
     * TimestampsViewControls — view-mode, granularity, and auto-advance toggles.
     *
     * Rendered under the audio player (not in the top info-bar). The
     * granularity toggles (Letters/Phonemes in Analysis, Words/Letters in
     * Animation) double as keyboard-shortcut targets: `setView`,
     * `toggleModeA`, `toggleModeB` are exported for TimestampsTab to invoke
     * from its keyboard handler.
     */

    import { createEventDispatcher } from 'svelte';
    import { get } from 'svelte/store';

    import {
        TS_GRANULARITIES,
        TS_VIEW_MODES,
        granularity,
        showLetters,
        showPhonemes,
        viewMode,
    } from '../stores/display';
    import { autoMode, loopTarget, tsAudioElement } from '../stores/playback';
    import { loadedVerse } from '../stores/verse';
    import { findWordAt } from '../utils/loop-target';
    import { safePlay } from '../../../lib/utils/audio';
    import { LS_KEYS } from '../../../lib/utils/constants';

    const dispatch = createEventDispatcher<{
        randomAny: void;
        randomCurrent: void;
    }>();

    // ---- View / mode / auto toggles ----
    export function setView(mode: 'analysis' | 'animation'): void {
        viewMode.set(mode);
        localStorage.setItem(LS_KEYS.TS_VIEW_MODE, mode);
        if (mode === TS_VIEW_MODES.ANALYSIS) {
            showLetters.set(true);
            showPhonemes.set(false);
        } else {
            granularity.set(TS_GRANULARITIES.WORDS);
        }
    }

    export function toggleModeA(): void {
        if ($viewMode === TS_VIEW_MODES.ANALYSIS) {
            const nv = !$showLetters;
            showLetters.set(nv);
            localStorage.setItem(LS_KEYS.TS_SHOW_LETTERS, String(nv));
        } else {
            granularity.set(TS_GRANULARITIES.WORDS);
            localStorage.setItem(LS_KEYS.TS_GRANULARITY, TS_GRANULARITIES.WORDS);
        }
    }

    export function toggleModeB(): void {
        if ($viewMode === TS_VIEW_MODES.ANALYSIS) {
            const nv = !$showPhonemes;
            showPhonemes.set(nv);
            localStorage.setItem(LS_KEYS.TS_SHOW_PHONEMES, String(nv));
        } else {
            granularity.set(TS_GRANULARITIES.CHARACTERS);
            localStorage.setItem(LS_KEYS.TS_GRANULARITY, TS_GRANULARITIES.CHARACTERS);
        }
    }

    function toggleAuto(mode: 'next' | 'random-any' | 'random-current'): void {
        const cur = get(autoMode);
        const turningOn = cur !== mode;
        autoMode.set(turningOn ? mode : null);
        // Auto-advance and loop are mutually exclusive. Turning on Auto
        // cancels an active loop (turning Auto off leaves loop off too).
        if (turningOn) {
            loopTarget.set(null);
            // Random modes: load a random verse immediately on activation so
            // the click has a visible effect beyond arming the on-end handler.
            if (mode === 'random-any') dispatch('randomAny');
            else if (mode === 'random-current') dispatch('randomCurrent');
        }
    }

    function toggleLoop(): void {
        if (get(loopTarget)) {
            // Second click turns off — audio keeps playing/paused where it is.
            loopTarget.set(null);
            return;
        }
        const lv = get(loadedVerse);
        const audio = get(tsAudioElement);
        if (!lv || !audio) return;
        const words = lv.data.words;
        const relTime = audio.currentTime - lv.tsSegOffset;
        const w = findWordAt(relTime, words, true);
        if (!w) return; // empty verse → silent no-op
        const wi = words.indexOf(w);
        loopTarget.set({
            kind: 'word',
            startSec: w.start,
            endSec: w.end,
            wordIndex: wi,
        });
        // Jump to the word's start so the loop begins cleanly.
        audio.currentTime = w.start + lv.tsSegOffset;
        if (audio.paused) void safePlay(audio);
        // Loop cancels auto-advance.
        autoMode.set(null);
    }
</script>

<div class="ts-view-controls">
    <div class="ts-view-mode-group">
        <div class="ts-view-toggle">
            <button class="ts-view-btn" class:active={$viewMode === TS_VIEW_MODES.ANALYSIS}
                on:click={() => setView(TS_VIEW_MODES.ANALYSIS)}>Analysis</button>
            <button class="ts-view-btn" class:active={$viewMode === TS_VIEW_MODES.ANIMATION}
                on:click={() => setView(TS_VIEW_MODES.ANIMATION)}>Animation</button>
        </div>
        <div class="ts-mode-toggle">
            <button class="ts-mode-btn"
                class:active={$viewMode === TS_VIEW_MODES.ANALYSIS ? $showLetters : $granularity === TS_GRANULARITIES.WORDS}
                on:click={toggleModeA}>
                {$viewMode === TS_VIEW_MODES.ANALYSIS ? 'Letters' : 'Words'}
            </button>
            <button class="ts-mode-btn"
                class:active={$viewMode === TS_VIEW_MODES.ANALYSIS ? $showPhonemes : $granularity === TS_GRANULARITIES.CHARACTERS}
                on:click={toggleModeB}>
                {$viewMode === TS_VIEW_MODES.ANALYSIS ? 'Phonemes' : 'Letters'}
            </button>
        </div>
    </div>
    <div class="ts-auto-toggles">
        <div class="ts-auto-row">
            <button class="ts-auto-btn" class:active={$autoMode === 'next'}
                title="Auto-advance to next verse" on:click={() => toggleAuto('next')}>
                <img class="ts-auto-icon" src="/icons/auto_next.svg" alt="Auto Next" />
            </button>
            <button class="ts-auto-btn" class:active={$autoMode === 'random-any'}
                title="Random verse from any reciter (toggles auto)"
                on:click={() => toggleAuto('random-any')}>
                <img class="ts-auto-icon" src="/icons/reciter_random.svg" alt="Random Any Reciter" />
            </button>
        </div>
        <div class="ts-auto-row">
            <button class="ts-auto-btn" class:active={$loopTarget != null}
                title="Loop selected element — click a word, letter, or phoneme to change target"
                on:click={toggleLoop}>
                <img class="ts-auto-icon" src="/icons/loop.svg" alt="Loop" />
            </button>
            <button class="ts-auto-btn" class:active={$autoMode === 'random-current'}
                title="Random verse from current reciter (toggles auto)"
                on:click={() => toggleAuto('random-current')}>
                <img class="ts-auto-icon" src="/icons/reciter.svg" alt="Random Current Reciter" />
            </button>
        </div>
    </div>
</div>
