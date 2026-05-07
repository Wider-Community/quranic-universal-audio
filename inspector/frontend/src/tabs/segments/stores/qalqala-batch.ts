/**
 * Qalqala batch padding session — preview overlay + per-segment overrides before save.
 */

import { writable } from 'svelte/store';

import type { Segment } from '../../../lib/types/domain';
import { getAdjacentSegments } from './chapter';

export interface QalqalaBatchState {
    isActive: boolean;
    letter: string;
    padAmount: number;
    segments: Segment[];
    overrides: Map<string, number>;
    peaksFetching: boolean;
    peaksComplete: boolean;
}

const INITIAL: QalqalaBatchState = {
    isActive: false,
    letter: '',
    padAmount: 200,
    segments: [],
    overrides: new Map(),
    peaksFetching: false,
    peaksComplete: false,
};

export const qalqalaBatch = writable<QalqalaBatchState>({ ...INITIAL, overrides: new Map() });

export function startQalqalaBatch(
    letter: string,
    padAmount: number,
    resolvedSegments: Segment[],
): void {
    qalqalaBatch.set({
        isActive: true,
        letter,
        padAmount,
        segments: resolvedSegments,
        overrides: new Map(),
        peaksFetching: false,
        peaksComplete: false,
    });
}

export function setPeaksFetching(fetching: boolean): void {
    qalqalaBatch.update((s) => ({ ...s, peaksFetching: fetching }));
}

export function setPeaksComplete(done: boolean): void {
    qalqalaBatch.update((s) => ({ ...s, peaksComplete: done }));
}

export function updateQalqalaPadAmount(ms: number): void {
    qalqalaBatch.update((s) => (s.isActive ? { ...s, padAmount: ms } : s));
}

/** Clamp padded end so it does not cross the next segment on the same file. */
export function clampPadEnd(seg: Segment, proposedEnd: number): number {
    const ch = seg.chapter ?? 0;
    const { next } = getAdjacentSegments(ch, seg.index);
    if (next && next.audio_url === seg.audio_url) {
        return Math.min(proposedEnd, next.time_start - 1);
    }
    return proposedEnd;
}

export function getPaddedEnd(uid: string | undefined, seg: Segment, state: QalqalaBatchState): number {
    if (!uid) return seg.time_end;
    const raw = state.overrides.get(uid) ?? (seg.time_end + state.padAmount);
    return clampPadEnd(seg, raw);
}

export function setSegOverride(uid: string, seg: Segment, newEnd: number): void {
    const clamped = clampPadEnd(seg, newEnd);
    qalqalaBatch.update((s) => {
        if (!s.isActive) return s;
        const next = new Map(s.overrides);
        next.set(uid, clamped);
        return { ...s, overrides: next };
    });
}

export function uidInBatch(uid: string | undefined, state: QalqalaBatchState): boolean {
    if (!uid || !state.isActive) return false;
    return state.segments.some((s) => s.segment_uid === uid);
}

export function cancelQalqalaBatch(): void {
    qalqalaBatch.set({
        ...INITIAL,
        overrides: new Map(),
    });
}

export function resetQalqalaBatch(): void {
    cancelQalqalaBatch();
}
