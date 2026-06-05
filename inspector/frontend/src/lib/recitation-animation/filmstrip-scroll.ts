/**
 * Filmstrip continuous-scroll stepper — the per-frame `offset` decision for the
 * hybrid/tuner motion models, factored out of `AyahFilmstrip` so it is testable
 * in isolation (the component itself is rAF/canvas-imperative).
 *
 * Forward playback tracks the live recited position INSTANTLY (the needle sits
 * exactly on the recited word). A loopback or seek arms a smooth catch-up: each
 * frame closes a fixed fraction of the gap toward the LIVE (still-moving) target
 * via exponential smoothing — so the strip chases the advancing position instead
 * of teleporting.
 *
 * The catch-up exists only to absorb the JUMP distance; the recited target keeps
 * moving during a replay, so a fixed-fraction smoothing alone would converge to a
 * constant lag (and never land), trailing the audio for the whole loopback. So
 * the landing test is velocity-aware: once the offset is within one frame's-worth
 * of the target's own motion (`SNAP_EPS_PX` + |Δtarget|), the catch-up is in
 * lockstep — snap onto the live target and resume instant tracking. `prevTarget`
 * (threaded through `ScrollState`) supplies that per-frame target velocity.
 *
 * Pure: no DOM, no rAF, no module state — `following`/`prevTarget` are threaded.
 */

/** Per-frame catch-up fraction during a loopback/seek glide (higher = snappier;
 *  ~0.28 absorbs a within-verse rewind in ~5 frames then lands in lockstep). */
export const GLIDE_FOLLOW = 0.28;
/** Base distance (px) under which the catch-up is "landed". The live landing
 *  threshold adds the target's per-frame motion so a moving target still lands. */
export const SNAP_EPS_PX = 1;

export interface ScrollState {
    /** New strip offset (px). */
    offset: number;
    /** Still smoothing toward a moving target next frame? */
    following: boolean;
    /** Clamped target this frame — fed back next frame to measure target velocity
     *  (so the catch-up can land on a moving target, not trail it). */
    prevTarget: number;
}

const clamp = (lo: number, hi: number, v: number): number => Math.min(hi, Math.max(lo, v));
const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

/**
 * Advance the continuous-mode scroll one frame.
 *
 * @param offset      current offset (px)
 * @param target      live target offset for the recited position (px)
 * @param discont     this frame is a loopback/seek discontinuity (arms catch-up)
 * @param following   were we mid-catch-up last frame?
 * @param prevTarget  last frame's clamped target (for target-velocity landing)
 * @param lastRight   max scrollable offset (px), for clamping
 * @param reducedMotion skip the eased catch-up (jump straight to target)
 */
export function stepScroll(
    offset: number,
    target: number,
    discont: boolean,
    following: boolean,
    prevTarget: number,
    lastRight: number,
    reducedMotion: boolean,
): ScrollState {
    const to = clamp(0, lastRight, target);
    if (reducedMotion) return { offset: to, following: false, prevTarget: to };
    const active = following || discont;
    if (!active) return { offset: to, following: false, prevTarget: to };
    // Velocity-aware landing: the recited target keeps moving during a replay, so
    // land once the offset is within one frame's target motion of it (lockstep) —
    // not just within a fixed px (which a moving target never reaches). On the arm
    // frame (`!following`) there is no prior target yet, so velocity is 0.
    const vel = following ? Math.abs(to - prevTarget) : 0;
    if (Math.abs(to - offset) <= SNAP_EPS_PX + vel) {
        return { offset: to, following: false, prevTarget: to };
    }
    return { offset: lerp(offset, to, GLIDE_FOLLOW), following: true, prevTarget: to };
}
