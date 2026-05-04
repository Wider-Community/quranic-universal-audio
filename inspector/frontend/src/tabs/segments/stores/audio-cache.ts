import { writable } from 'svelte/store';

export type CacheStatus = 'hidden' | 'idle' | 'downloading' | 'complete';

export interface CacheProgress {
    pct: number;
    text: string;
}

/** Overall cache bar visibility + state. */
export const cacheStatus = writable<CacheStatus>('hidden');

/** Status message shown in the cache bar (right side of bar). */
export const cacheStatusText = writable<string>('');

/** Progress bar fill percent (0-100) and label text. Null = no progress bar shown. */
export const cacheProgress = writable<CacheProgress | null>(null);

/** Prepare button: disabled state + label text + visibility. */
export const cachePrepareButton = writable<{ hidden: boolean; disabled: boolean; label: string }>({
    hidden: true,
    disabled: false,
    label: 'Download All Audio',
});

/** Delete button: disabled state + label text + visibility. */
export const cacheDeleteButton = writable<{ hidden: boolean; disabled: boolean; label: string }>({
    hidden: true,
    disabled: false,
    label: 'Delete Cache',
});
