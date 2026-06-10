/**
 * BottomPlayer context store — the "what is the dashboard player
 * currently bound to" surface.
 *
 * Independent of `dashboard-state` (catalog filters). The dashboard
 * row catalog and the player are two surfaces that happen to live in
 * the same tab; they don't share filter or sort state.
 *
 * Persists a thin slice (delivery slug + surah num + speed) to
 * ``LS_KEYS.DASH_RECITER`` so returning visitors resume context. The
 * full reciter object is re-resolved from the catalog payload on
 * mount; we don't try to cache the whole reciter.
 */
import { writable } from 'svelte/store';

import type { PublicDelivery, PublicReciter } from '../types/generated/schemas';
import { LS_KEYS } from '../utils/constants';

export interface PlayerContext {
    reciter: PublicReciter | null;
    delivery: PublicDelivery | null;
    surahNum: number | null;
    isPlaying: boolean;
    /** True between a source swap (or play() on a not-yet-ready element)
     *  and the moment the browser can actually produce audio. Drives the
     *  ring-pulse buffering indicator around the play button. */
    isLoading: boolean;
    positionMs: number;
    durationMs: number;
    speed: number;
}

const DEFAULT_SPEED = 1;

function initial(): PlayerContext {
    return {
        reciter: null,
        delivery: null,
        surahNum: null,
        isPlaying: false,
        isLoading: false,
        positionMs: 0,
        durationMs: 0,
        speed: DEFAULT_SPEED,
    };
}

export const playerContext = writable<PlayerContext>(initial());

interface PersistedSlice {
    deliverySlug: string | null;
    surahNum: number | null;
    speed: number;
}

export function loadPersistedSlice(): PersistedSlice {
    const raw = localStorage.getItem(LS_KEYS.DASH_RECITER);
    if (!raw) return { deliverySlug: null, surahNum: null, speed: DEFAULT_SPEED };
    try {
        const parsed = JSON.parse(raw) as Partial<PersistedSlice>;
        return {
            deliverySlug: parsed.deliverySlug ?? null,
            surahNum: parsed.surahNum ?? null,
            speed: parsed.speed ?? DEFAULT_SPEED,
        };
    } catch {
        return { deliverySlug: null, surahNum: null, speed: DEFAULT_SPEED };
    }
}

export function persistSlice(slice: PersistedSlice): void {
    localStorage.setItem(LS_KEYS.DASH_RECITER, JSON.stringify(slice));
}

export function setReciterAndDelivery(
    reciter: PublicReciter,
    delivery: PublicDelivery,
): void {
    playerContext.update((s) => ({
        ...s,
        reciter,
        delivery,
        surahNum: s.surahNum ?? 1,
        positionMs: 0,
    }));
}

export function setSurah(surahNum: number): void {
    playerContext.update((s) => ({ ...s, surahNum, positionMs: 0 }));
}

export function setSpeed(speed: number): void {
    playerContext.update((s) => ({ ...s, speed }));
}

export function setIsPlaying(isPlaying: boolean): void {
    playerContext.update((s) => ({ ...s, isPlaying }));
}

export function setIsLoading(isLoading: boolean): void {
    playerContext.update((s) => ({ ...s, isLoading }));
}

export function setPosition(positionMs: number, durationMs?: number): void {
    playerContext.update((s) => ({
        ...s,
        positionMs,
        durationMs: durationMs ?? s.durationMs,
    }));
}

export function setDuration(durationMs: number): void {
    playerContext.update((s) => ({ ...s, durationMs }));
}
