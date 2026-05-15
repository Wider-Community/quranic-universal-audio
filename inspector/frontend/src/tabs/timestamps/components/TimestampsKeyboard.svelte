<script lang="ts">
    import { createEventDispatcher } from 'svelte';
    import { get } from 'svelte/store';

    import { shouldHandleKey } from '../../../lib/utils/keyboard-guard';
    import { wordBoundaryScan } from '../../../lib/utils/word-boundary';
    import { TS_VIEW_MODES,viewMode } from '../stores/display';
    import { tsPort } from '../stores/playback';
    import { loadedVerse } from '../stores/verse';
    import type TimestampsAudio from './TimestampsAudio.svelte';

    // ---- Props ----
    /** Bound ref to the audio component — kept for backwards compat with
     *  callers that still pass it; keyboard shortcuts now route through
     *  `tsPort` directly so the prop is unused inside this component.
     *  `export const` form (rather than `let`) advertises external-only
     *  reference so svelte-check doesn't flag it as unused. */
    export const audioComp: TimestampsAudio | null = null;

    const dispatch = createEventDispatcher<{
        navigateVerse: number;
        randomAny: void;
        randomCurrent: void;
        setView: 'analysis' | 'animation';
        toggleModeA: void;
        toggleModeB: void;
        scrollActive: void;
        tick: void;
        cycleSpeed: 'up' | 'down';
    }>();

    function handleKeydown(e: KeyboardEvent): void {
        if (!shouldHandleKey(e, 'timestamps')) return;
        if (!tsPort.element) return;
        const lv = get(loadedVerse);
        const segOffset = lv?.tsSegOffset ?? 0;
        const segEnd = lv?.tsSegEnd ?? 0;

        // Read in seconds (file-absolute under the port; same value as
        // audio.currentTime under the current Timestamps-tab CBR-only
        // setup, but routed through the port so a future VBR migration
        // is a no-op for these handlers).
        const cur = tsPort.currentTimeMs() / 1000;

        switch (e.code) {
            case 'Space':
                e.preventDefault();
                if (tsPort.paused) {
                    if (segEnd > 0 && cur >= segEnd) {
                        tsPort.seek(segOffset * 1000);
                    }
                    tsPort.play();
                } else {
                    tsPort.pause();
                }
                break;
            case 'ArrowLeft':
                e.preventDefault();
                tsPort.seek(Math.max(segOffset, cur - 3) * 1000);
                dispatch('tick');
                break;
            case 'ArrowRight': {
                e.preventDefault();
                const dur = tsPort.element.duration || 0;
                tsPort.seek(Math.min(segEnd || dur, cur + 3) * 1000);
                dispatch('tick');
                break;
            }
            case 'ArrowUp': {
                e.preventDefault();
                const t = cur - segOffset;
                const ws = lv?.data.words ?? [];
                const prevStart = wordBoundaryScan(ws, t, 'up');
                tsPort.seek((prevStart !== null ? prevStart + segOffset : segOffset) * 1000);
                dispatch('tick');
                break;
            }
            case 'ArrowDown': {
                e.preventDefault();
                const t = cur - segOffset;
                const ws = lv?.data.words ?? [];
                const nextStart = wordBoundaryScan(ws, t, 'down');
                const dur = tsPort.element.duration || 0;
                tsPort.seek((nextStart !== null ? nextStart + segOffset : segEnd || dur) * 1000);
                dispatch('tick');
                break;
            }
            case 'Period':
            case 'Comma':
                e.preventDefault();
                dispatch('cycleSpeed', e.code === 'Period' ? 'up' : 'down');
                break;
            case 'KeyR':
                if (e.shiftKey) dispatch('randomAny');
                else dispatch('randomCurrent');
                break;
            case 'KeyA':
                e.preventDefault();
                dispatch('setView', get(viewMode) === TS_VIEW_MODES.ANALYSIS ? TS_VIEW_MODES.ANIMATION : TS_VIEW_MODES.ANALYSIS);
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
