/**
 * Timestamps tab — tuneable constants.
 *
 * Currently hosts only the waveform-zoom knobs. Other tab-wide constants live
 * either in `lib/utils/constants.ts` (cross-tab) or alongside the code that
 * uses them.
 */

/** Minimum visible window (slice-relative seconds) for the waveform wheel-zoom.
 *  Internal sanity floor — prevents division-by-zero / degenerate hit-detect
 *  when a user wheels in past usefulness. The action-triggered zoom (loop
 *  entry → ±50% × word-duration) is NOT bounded by this — short words get a
 *  sub-100 ms view by design (no user-facing minimum). */
export const TS_MIN_VIEW_SEC = 0.01;

/** Multiplicative factor per wheel tick on the Timestamps waveform canvas.
 *  Same value as the Segments tab's trim/split zoom (mirrors that UX so
 *  reviewers who use both tabs build a single muscle memory). Wheel-in
 *  multiplies the visible range by this; wheel-out divides. Symmetric so
 *  zoom-in followed by an equal zoom-out lands back at the original width. */
export const TS_WHEEL_ZOOM_FACTOR = 0.85;

/** Floor for the sliding pan animation fired by `setupZoomLifecycle`.
 *  Short jumps (e.g. neighbouring words) settle here so the slide still
 *  reads as intentional rather than a teleport. */
export const TS_ZOOM_ANIMATE_MIN_MS = 180;

/** Cap on the sliding pan animation. Full-verse jumps clamp here so the
 *  "reel through the waveform" preview doesn't feel sluggish. */
export const TS_ZOOM_ANIMATE_MAX_MS = 900;

/** Sweep speed: ms of animation per second of center-distance travelled.
 *  A jump of `d` seconds animates for `d * TS_ZOOM_ANIMATE_MS_PER_SEC` ms,
 *  clamped to [TS_ZOOM_ANIMATE_MIN_MS, TS_ZOOM_ANIMATE_MAX_MS]. Controls
 *  how much intermediate waveform you actually get to see. */
export const TS_ZOOM_ANIMATE_MS_PER_SEC = 35;

/** Back-compat alias — same value as the new MIN. Kept because a handful
 *  of callsites import the old name; safe to remove once they migrate. */
export const TS_ZOOM_ANIMATE_MS = TS_ZOOM_ANIMATE_MIN_MS;

/** Delay in ms for single-click handlers in `UnifiedDisplay`. The DOM fires
 *  `click` before `dblclick`, so a deferred single-click that dblclick cancels
 *  is the clean way to disambiguate "seek / swap loop" from "toggle loop". */
export const TS_CLICK_DELAY_MS = 220;

/** Middle-mouse-button pan speed on the zoomed waveform. At a cursor offset
 *  of half the canvas width from the press anchor, the view pans by
 *  `TS_PAN_HALF_CANVAS_VIEWS_PER_SEC` view-widths per second. Scales linearly
 *  with offset below that and past it (no saturation). Using "view-widths per
 *  second" (rather than absolute seconds per second) keeps the pan speed
 *  perceptually consistent across zoom depths — at 10x zoom, you cover 10x
 *  less audio time per second but the view still sweeps at a familiar rate. */
export const TS_PAN_HALF_CANVAS_VIEWS_PER_SEC = 1.0;
