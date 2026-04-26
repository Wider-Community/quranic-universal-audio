/**
 * Segments tab — playback control state.
 */

import { writable } from 'svelte/store';

import { LS_KEYS } from '../../../lib/utils/constants';

/**
 * Whether auto-play (continuous segment advance) is enabled.
 * Persisted to localStorage via LS_KEYS.SEG_AUTOPLAY.
 */
export const autoPlayEnabled = writable<boolean>(
    localStorage.getItem(LS_KEYS.SEG_AUTOPLAY) !== 'false',
);

/**
 * Whether auto-scroll (keep the playing segment visible in #seg-list) is
 * enabled. Persisted to localStorage via LS_KEYS.SEG_AUTOSCROLL; default ON.
 */
export const autoScrollEnabled = writable<boolean>(
    localStorage.getItem(LS_KEYS.SEG_AUTOSCROLL) !== 'false',
);


/** Whether continuous-play (auto-advance to next segment after one ends) is
 *  currently engaged. Short-lived — toggled per play session, not persisted. */
export const continuousPlay = writable<boolean>(false);

/** Timestamp (ms, within the current audio source) at which the current
 *  play-range should stop. Written when starting a segment or range; read by
 *  the rAF tick to decide when to pause. */
export const playEndMs = writable<number>(0);

/** Which audio element is currently driving playback: 'main' = the main
 *  segments tab audio element, or `null` when idle. Retained as a typed
 *  token (rather than a bare boolean) so a future secondary audio source
 *  can extend the union. */
export const activeAudioSource = writable<'main' | null>(null);

/** The <audio> element driving segments-tab playback. Populated by
 *  SegmentsAudioControls.svelte via bind:this once AudioPlayer mounts.
 *  Consumers read via get(segAudioElement) and null-check. */
export const segAudioElement = writable<HTMLAudioElement | null>(null);

/** The #seg-list scroll container. Populated by SegmentsList.svelte via
 *  bind:this. Consumers read via get(segListElement) and null-check. */
export const segListElement = writable<HTMLDivElement | null>(null);

/** Set of mounted container elements that host seg-row canvases. Populated
 *  by each consuming component's onMount via registerWaveformContainer.
 *  `redrawPeaksWaveforms` iterates this set to find canvases needing redraw
 *  without hardcoding DOM IDs. */
export const waveformContainers = writable<Set<HTMLElement>>(new Set());

/** Register a container element that hosts seg-row canvases. Returns a
 *  cleanup function to call from the component's onMount teardown. */
export function registerWaveformContainer(el: HTMLElement): () => void {
    waveformContainers.update((s) => {
        s.add(el);
        return s;
    });
    return () => {
        waveformContainers.update((s) => {
            s.delete(el);
            return s;
        });
    };
}

/** Svelte action: registers the element as a waveform container for its
 *  lifetime in the DOM. Use as `<div use:waveformContainer>...</div>`.
 *  Re-runs correctly when the element is destroyed and recreated by an
 *  `{#if}` block. */
export function waveformContainer(node: HTMLElement): { destroy(): void } {
    const cleanup = registerWaveformContainer(node);
    return { destroy: cleanup };
}

/** Current playback speed multiplier. Persisted to localStorage via
 *  LS_KEYS.SEG_SPEED. SegmentsAudioControls' speed <select> writes to it;
 *  hot paths that need to set audioEl.playbackRate read via
 *  get(playbackSpeed). */
export const playbackSpeed = writable<number>(1);

/** Label on the main play/pause button. Reactive markup in
 *  SegmentsAudioControls. */
export const playButtonLabel = writable<'Play' | 'Pause'>('Play');

/** The {chapter, index} pair currently being played back, or `null` when
 *  nothing is playing. SegmentRow reactively applies class:playing when both
 *  chapter and index match its seg. Written by updateSegHighlight from the
 *  rAF tick; the Svelte safe_not_equal check plus the getter identity guard
 *  in setPlayingSegment() make same-value sets no-ops, keeping the 60fps hot
 *  path from triggering unnecessary subscriber work.
 *
 *  Chapter-scoped so a segment with the same index in different chapters (as
 *  happens when the validation panel shows "All Chapters") does not light
 *  up every same-indexed row across the chapter set. */
export interface PlayingSegment {
    chapter: number;
    index: number;
}
export const playingSegmentIndex = writable<PlayingSegment | null>(null);

/** Identity-guarded setter for `playingSegmentIndex` so the 60fps rAF tick
 *  does not allocate a fresh object when the active pair has not changed.
 *  Svelte's safe_not_equal returns true for any two object literals even
 *  when their contents match; this guard avoids the resulting subscriber
 *  wake-up storm on every frame. */
export function setPlayingSegment(next: PlayingSegment | null): void {
    playingSegmentIndex.update((cur) => {
        if (cur === next) return cur;
        if (cur && next && cur.chapter === next.chapter && cur.index === next.index) return cur;
        return next;
    });
}

/** True when main-tab audio is playing (not paused, and activeAudioSource
 *  === 'main'). Drives the per-row play-button glyph (stop vs play). */
export const isMainAudioPlaying = writable<boolean>(false);
