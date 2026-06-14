/**
 * Buffering controller for the shared `dashPort` (Dashboard + Timestamps).
 *
 * Drives the play-button LoadingSpinner so it reflects audio ACTUALLY loading
 * and clears the instant sound starts — the same honest click/seek→audible
 * contract the Segments footer uses (issue #172).
 *
 * Why a controller and not raw `onWaiting`/`onPlaying` in BottomPlayer:
 * Timestamps re-sources/seeks the shared port from many call sites (chapter
 * change, reciter change, shuffle, waveform verse click, drag-seek, keyboard
 * nav). Hand-instrumenting each one is brittle; instead the state is driven
 * PRIMARILY off the port's own events — which every one of those actions
 * funnels through — plus an explicit `signalDashSeekIntent()` raise at
 * seek/play initiation so the spinner appears immediately on a cold (re)load
 * rather than waiting a frame for the element to emit `waiting`.
 *
 *   raise  ← `signalDashSeekIntent()` (seek/play/source-change) OR `waiting`
 *   clear  ← `playing` (first audible frame) OR `pause` / `ended` / `error`
 *
 * A short DEBOUNCE on the raise (RAISE_DEBOUNCE_MS) swallows in-buffer
 * (re)seeks that resolve before the window elapses, so an instant in-buffer
 * jump never flickers the spinner. The clear is immediate (no debounce) so the
 * spinner can't outlive the first audible frame.
 *
 * The element/port is read LIVE through the port on every event, so the state
 * tracks across `adoptElement` element rotation (the gapless shuffle/next swap)
 * — a known staleness gotcha if you cache the element ref.
 *
 * Installed once by `BottomPlayer` (it owns the shared port + the player-context
 * store sink). `signalDashSeekIntent()` is a free function any seek call site
 * (BottomPlayer, TimestampsTab, TimestampsWaveform) calls; it no-ops until the
 * controller is installed.
 */

import { dashPort } from './dash-port';

/** Debounce before a seek-intent / waiting actually raises the spinner. An
 *  in-buffer seek that becomes audible within this window never shows it. */
const RAISE_DEBOUNCE_MS = 120;

let _raiseTimer: ReturnType<typeof setTimeout> | null = null;
let _setLoading: ((loading: boolean) => void) | null = null;
let _offs: Array<() => void> = [];

function cancelPendingRaise(): void {
    if (_raiseTimer !== null) {
        clearTimeout(_raiseTimer);
        _raiseTimer = null;
    }
}

function clearNow(): void {
    cancelPendingRaise();
    _setLoading?.(false);
}

function scheduleRaise(): void {
    if (!_setLoading) return;
    // Already audible → the (re)load is a no-op; don't arm the spinner.
    if (!dashPort.paused && (dashPort.element?.readyState ?? 0) >= 3) return;
    if (_raiseTimer !== null) return; // a raise is already pending
    _raiseTimer = setTimeout(() => {
        _raiseTimer = null;
        _setLoading?.(true);
    }, RAISE_DEBOUNCE_MS);
}

/**
 * Install buffering tracking on the shared `dashPort`. `setLoading` is the sink
 * that flips the UI state (`setIsLoading` on the player-context store) —
 * injected so this playback-layer module stays free of UI-store imports.
 * Returns a teardown fn; call on the owner's unmount.
 */
export function installDashBuffering(setLoading: (loading: boolean) => void): () => void {
    // Replace any prior install (HMR / remount) so we never double-subscribe.
    for (const off of _offs) off();
    cancelPendingRaise();
    _setLoading = setLoading;

    _offs = [
        dashPort.onWaiting(scheduleRaise),
        // `playing` = first audible frame: the single steady-state clear.
        dashPort.onPlaying(clearNow),
        // A pause/stop/error means the audible frame this load was for won't
        // come; drop the spinner so it can't strand.
        dashPort.onPause(clearNow),
        dashPort.onEnded(clearNow),
        dashPort.onError(clearNow),
    ];

    return (): void => {
        for (const off of _offs) off();
        _offs = [];
        cancelPendingRaise();
        _setLoading = null;
    };
}

/** Raise the spinner (debounced) because a seek / play / source-change was
 *  just initiated on the shared port and may need to (re)load before sound.
 *  Cancelled automatically if the element becomes audible within the debounce
 *  window. No-op until `installDashBuffering` has run. */
export function signalDashSeekIntent(): void {
    scheduleRaise();
}
