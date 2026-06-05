/**
 * Shared state for the dashboard now-reciting feature.
 *
 * Lives in a store (not a component) because the controls now render in the
 * persistent BottomPlayer footer while the animation renders in the separate
 * NowReciting section — two sibling components that must read/write one config.
 *
 *   - `recitationConfigStore` — the tunable config (persisted to localStorage)
 *   - `recitationOpen`        — line collapse state (persisted)
 *   - `recitationAvailable`   — true while the section is actually shown
 *     (published reciter + timestamps loaded); the footer controls gate on it.
 *
 * Mutations go through the exported helpers so the footer stays declarative.
 */
import { derived, get, writable, type Readable } from 'svelte/store';

import type { FilmstripMotion, RecitationAnimConfig } from './config';
import { loadPrefs, savePrefs } from './nowreciting-prefs';
import type { AyahBoundary } from './types';

const initial = loadPrefs();

export const recitationConfigStore = writable<RecitationAnimConfig>(initial.config);
export const recitationOpen = writable<boolean>(initial.collapsed === null ? true : !initial.collapsed);
export const recitationAvailable = writable<boolean>(false);
/** Ayah boundaries of the currently-loaded published chapter (chapter-absolute
 *  ms). Published by NowReciting; read by the footer seek buttons to jump
 *  ayah-by-ayah. Empty when nothing published is loaded. */
export const recitationAyahs = writable<AyahBoundary[]>([]);

/** Memoised ascending list of ayah `startMs` from the loaded chapter — feeds
 *  `adjacentAyahStartMs` / `nearestAyahStartMs` without an alloc + sort on
 *  every keypress / drag-release (Baqarah ≈ 286 entries; held arrow keys
 *  used to spam `.map() + [...].sort()`). The producer (NowReciting) already
 *  builds `recitationAyahs` in temporal order, so we just project the field. */
export const recitationAyahStarts: Readable<number[]> = derived(
    recitationAyahs,
    ($ayahs) => $ayahs.map((a) => a.startMs),
);

/** Surah/ayah currently under the playhead — published by the Timestamps tab
 *  while its per-frame tick is running (the tab already locates the focus
 *  verse via `focusAt(ms)` for its own use). Read by NowReciting's filmstrip
 *  bookmark button so it doesn't need a separate rAF loop scanning `ayahs`
 *  every frame just to mirror what the tab already knows. `null` outside
 *  Timestamps or before the first focus arrives — callers gate on it. */
export const recitationFocus = writable<{ surah: number; ayah: number } | null>(null);

/** Resolve the ayahKey ("surah:ayah") actually being RECITED at a chapter-
 *  absolute time (ms), via the recitation locator over the full-coverage units
 *  — or null in a real silence gap. Published by NowReciting (closes over the
 *  loaded chapter's units); read by the footer seek buttons so prev/next land
 *  one verse away even when the playhead sits inside a re-take whose canonical
 *  start ordering doesn't match the audio. `null` when no chapter is loaded. */
export const recitationAyahAt = writable<((ms: number) => string | null) | null>(null);

// Persist config + collapse on every change (skip the initial subscribe fire).
let persistReady = false;
function persist(): void {
    if (!persistReady) return;
    savePrefs({ config: get(recitationConfigStore), collapsed: !get(recitationOpen) });
}
recitationConfigStore.subscribe(persist);
recitationOpen.subscribe(persist);
persistReady = true;

const near = (a: number, b: number): boolean => Math.abs(a - b) < 0.001;

export const SIZE_MIN = 20;
export const SIZE_MAX = 36;
const SIZE_STEP = 2;
const UPCOMING_CYCLE = [0, 0.2, 0.8]; // invisible → dim → full (starts at dim → full)

function patch(p: Partial<RecitationAnimConfig>): void {
    recitationConfigStore.update((c) => ({ ...c, ...p }));
}

export function toggleGranularity(): void {
    patch({ granularity: get(recitationConfigStore).granularity === 'word' ? 'char' : 'word' });
}
export function cycleUpcoming(): void {
    const cur = get(recitationConfigStore).unreachedOpacity;
    const i = UPCOMING_CYCLE.findIndex((v) => near(v, cur));
    patch({ unreachedOpacity: UPCOMING_CYCLE[(i + 1) % UPCOMING_CYCLE.length] ?? 0.2 });
}
export function cycleMotion(): void {
    const next: FilmstripMotion =
        get(recitationConfigStore).filmstripMotion === 'hybrid' ? 'snap' : 'hybrid';
    patch({ filmstripMotion: next });
}
export function setHighlight(color: string): void {
    patch({ highlightColor: color });
}
export function sizeDown(): void {
    patch({ fontSizePx: Math.max(SIZE_MIN, get(recitationConfigStore).fontSizePx - SIZE_STEP) });
}
export function sizeUp(): void {
    patch({ fontSizePx: Math.min(SIZE_MAX, get(recitationConfigStore).fontSizePx + SIZE_STEP) });
}

// ---- icon-name resolvers (single source so footer + anywhere agree) ----
export function granIconName(c: RecitationAnimConfig): 'gran-word' | 'gran-letter' {
    return c.granularity === 'char' ? 'gran-letter' : 'gran-word';
}
export function eyeIconName(c: RecitationAnimConfig): 'eye-full' | 'eye-dim' | 'eye-hidden' {
    return near(c.unreachedOpacity, 0.8) ? 'eye-full' : near(c.unreachedOpacity, 0) ? 'eye-hidden' : 'eye-dim';
}
export function motionIconName(c: RecitationAnimConfig): 'motion-hybrid' | 'motion-snap' {
    return c.filmstripMotion === 'snap' ? 'motion-snap' : 'motion-hybrid';
}
