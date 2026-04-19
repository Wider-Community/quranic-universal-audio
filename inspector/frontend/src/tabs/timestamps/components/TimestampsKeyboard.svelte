<script lang="ts">
    import { get } from 'svelte/store';
    import { createEventDispatcher } from 'svelte';

    import { safePlay } from '../../../lib/utils/audio';
    import { shouldHandleKey } from '../../../lib/utils/keyboard-guard';
    import { wordBoundaryScan } from '../../../lib/utils/word-boundary';
    import { viewMode } from '../stores/display';
    import { loadedVerse, selectedReciter } from '../stores/verse';

    import type TimestampsAudio from './TimestampsAudio.svelte';

    // ---- Props ----
    /** Bound ref to the audio component — keyboard shortcuts call its methods. */
    export let audioComp: TimestampsAudio | null = null;

    const dispatch = createEventDispatcher<{
        navigateVerse: number;
        randomAny: void;
        randomCurrent: void;
        setView: 'analysis' | 'animation';
        toggleModeA: void;
        toggleModeB: void;
        scrollActive: void;
        tick: void;
    }>();

    function handleKeydown(e: KeyboardEvent): void {
        if (!shouldHandleKey(e, 'timestamps')) return;
        const audio = audioComp?.element();
        if (!audio) return;
        const lv = get(loadedVerse);
        const segOffset = lv?.tsSegOffset ?? 0;
        const segEnd = lv?.tsSegEnd ?? 0;

        switch (e.code) {
            case 'Space':
                e.preventDefault();
                if (audio.paused) {
                    if (segEnd > 0 && audio.currentTime >= segEnd) {
                        audio.currentTime = segOffset;
                    }
                    safePlay(audio);
                } else {
                    audio.pause();
                }
                break;
            case 'ArrowLeft':
                e.preventDefault();
                audio.currentTime = Math.max(segOffset, audio.currentTime - 3);
                dispatch('tick');
                break;
            case 'ArrowRight':
                e.preventDefault();
                audio.currentTime = Math.min(segEnd || audio.duration, audio.currentTime + 3);
                dispatch('tick');
                break;
            case 'ArrowUp': {
                e.preventDefault();
                const t = audio.currentTime - segOffset;
                const ws = lv?.data.words ?? [];
                const prevStart = wordBoundaryScan(ws, t, 'up');
                audio.currentTime = prevStart !== null ? prevStart + segOffset : segOffset;
                dispatch('tick');
                break;
            }
            case 'ArrowDown': {
                e.preventDefault();
                const t = audio.currentTime - segOffset;
                const ws = lv?.data.words ?? [];
                const nextStart = wordBoundaryScan(ws, t, 'down');
                audio.currentTime =
                    nextStart !== null ? nextStart + segOffset : segEnd || audio.duration;
                dispatch('tick');
                break;
            }
            case 'Period':
            case 'Comma':
                e.preventDefault();
                audioComp?.cycleSpeed(e.code === 'Period' ? 'up' : 'down');
                break;
            case 'KeyR':
                if (e.shiftKey) dispatch('randomAny');
                else dispatch('randomCurrent');
                break;
            case 'KeyA':
                e.preventDefault();
                dispatch('setView', get(viewMode) === 'analysis' ? 'animation' : 'analysis');
                break;
            case 'KeyL':
                e.preventDefault();
                dispatch('toggleModeA');
                break;
            case 'KeyP':
                e.preventDefault();
                dispatch('toggleModeB');
                break;
            case 'BracketLeft':
                dispatch('navigateVerse', -1);
                break;
            case 'BracketRight':
                dispatch('navigateVerse', +1);
                break;
            case 'KeyJ':
                e.preventDefault();
                dispatch('scrollActive');
                break;
        }
    }
</script>

<svelte:window on:keydown={handleKeydown} />
