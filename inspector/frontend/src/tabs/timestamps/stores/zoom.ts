/**
 * Timestamps tab — waveform zoom state.
 *
 * `tsZoom` holds the currently visible time range on the waveform, in
 * SLICE-RELATIVE seconds (matching the coordinate system used by
 * `TsLoopTarget.startSec` / `tsWaveformHoverTime` / waveform `tToX`). When
 * `null`, the waveform shows the full slice [`tsSegOffset`, `tsSegEnd`].
 *
 * Set by:
 *   - `zoomToWord(...)` — fires from the loop-entry code paths (token
 *     double-click in Analysis view, Loop button in Analysis view) and
 *     centers the view on the loop target's word ± 50 % of word duration.
 *   - `applyTsWheelZoom(...)` — mouse wheel on the waveform canvas, in
 *     either Analysis or Animation view. Centered on mouse cursor time.
 *
 * Reset to `null` by:
 *   - `loopTarget` becoming `null` (loop turned off).
 *   - `loadedVerse` audio_url changing (user navigated to a different verse).
 *
 * The `setupZoomLifecycle()` helper in `utils/zoom.ts` wires those triggers;
 * `TimestampsTab.svelte` calls it once on mount.
 */

import { writable } from 'svelte/store';

export interface TsZoom {
    /** Slice-relative seconds. */
    viewStart: number;
    /** Slice-relative seconds. */
    viewEnd: number;
}

export const tsZoom = writable<TsZoom | null>(null);

/**
 * Reactive mirror of the zoom-tween `_animatingFlag` in `utils/zoom.ts`.
 * Components subscribe to this to invalidate cached canvas state (e.g.
 * `_baseImageData` in `TimestampsWaveform`) exactly when a sweep starts,
 * so putImageData doesn't restore a pre-sweep base containing overlays
 * into a later frame.
 *
 * The non-reactive `isTsZoomAnimating()` is still the right read inside
 * render code; this store exists so `$:` reactives can FIRE on transitions.
 */
export const tsZoomAnimating = writable<boolean>(false);
