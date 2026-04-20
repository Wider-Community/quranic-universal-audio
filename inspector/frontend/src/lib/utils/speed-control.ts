/**
 * Shared playback speed cycling utility.
 */

import type { Writable } from 'svelte/store';
import { get } from 'svelte/store';

/** Canonical speed options shared across all speed controls. */
export const SPEEDS: readonly number[] = [0.5, 0.75, 1, 1.25, 1.5, 2, 3, 4, 5];
export const DEFAULT_SPEED = 1;

/** @deprecated Internal alias — use SPEEDS */
const _SPEEDS = SPEEDS;

/**
 * Cycle an audio speed <select> up or down, mirror to the playback element,
 * and persist the new value to localStorage. Used by the timestamps tab via
 * its keyboard shortcut helpers.
 */
export function cycleSpeed(
    selectEl: HTMLSelectElement,
    audioEl: HTMLAudioElement,
    direction: 'up' | 'down',
    lsKey: string,
): void {
    const opts = Array.from(selectEl.options).map(o => parseFloat(o.value));
    const curRate = parseFloat(selectEl.value);
    const curIdx = opts.findIndex(s => Math.abs(s - curRate) < 0.01);
    const idx = curIdx === -1 ? opts.indexOf(1) : curIdx;
    const newIdx = direction === 'up'
        ? Math.min(idx + 1, opts.length - 1)
        : Math.max(idx - 1, 0);
    const newVal = opts[newIdx];
    if (newVal === undefined) return;
    selectEl.value = String(newVal);
    audioEl.playbackRate = newVal;
    localStorage.setItem(lsKey, selectEl.value);
}

/**
 * Store-driven variant used by the segments tab. Updates the playbackSpeed
 * store (which drives the reactive speed <select>); the subscriber in
 * SegmentsAudioControls writes the new rate to the audio element, and
 * localStorage is updated here.
 */
export function cycleSpeedStore(
    speedStore: Writable<number>,
    direction: 'up' | 'down',
    lsKey: string,
): number {
    const cur = get(speedStore);
    const curIdx = _SPEEDS.findIndex(s => Math.abs(s - cur) < 0.01);
    const idx = curIdx === -1 ? _SPEEDS.indexOf(1) : curIdx;
    const newIdx = direction === 'up'
        ? Math.min(idx + 1, _SPEEDS.length - 1)
        : Math.max(idx - 1, 0);
    const newVal = _SPEEDS[newIdx];
    if (newVal === undefined) return cur;
    speedStore.set(newVal);
    localStorage.setItem(lsKey, String(newVal));
    return newVal;
}
