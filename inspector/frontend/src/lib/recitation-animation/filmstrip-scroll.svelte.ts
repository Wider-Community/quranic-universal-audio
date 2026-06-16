/**
 * Filmstrip scroll motion — the ONE controller that moves the strip `offset`,
 * shared by every motion model (snap / hybrid / tuner) and every state
 * (playing / paused). Factored out of `AyahFilmstrip` so the component is left
 * with recitation mapping + DOM, and all scroll motion lives in one place with
 * one curve and one set of constants.
 *
 * Two kinds of move, one curve:
 *   - INSTANT (`snap`, and forward continuous `follow`): the needle sits exactly
 *     on the live recited word — applied synchronously, no animation.
 *   - EASED (`glide` to a fixed point, and a `follow` catch-up after a
 *     loopback/seek): a single distance-proportional **Hermite** glide. From rest
 *     it is a smooth ease-in-out (the feel of a click/snap-center hop); a
 *     catch-up that must chase the still-moving replayed word RE-PLANS each frame
 *     it drifts, carrying the current velocity so the motion never jumps speed
 *     or inherits a stale cutoff — it stays smooth and re-adjusts to the moving
 *     target, then lands and hands back to instant tracking.
 *
 * The controller owns its own rAF (advancing any in-flight eased plan), so a
 * glide animates whether or not audio is playing — paused seeks ease, they
 * never teleport. Instant applies happen synchronously in `snap`/`follow`, so
 * forward tracking stays frame-locked to the audio (no added lag).
 */

/** ms per px of scroll distance — the eased glide's velocity (↑ = slower). */
export const GLIDE_MS_PER_PX = 0.9;
/** Floor so a tiny hop is still a visible glide, not a snap. */
export const GLIDE_MIN_MS = 300;
/** Cap so a full-film seek stays a smooth scroll-through, not endless. */
export const GLIDE_MAX_MS = 1500;
/** Distance (px) under which an eased plan is "landed" onto its target. */
export const SNAP_EPS_PX = 1;
/** A continuous catch-up re-plans toward the live target once it has drifted
 *  this far from the plan's destination — so the glide tracks the replayed word
 *  as it advances, instead of aiming at a stale snapshot. */
export const DRIFT_EPS_PX = 6;

const clamp = (lo: number, hi: number, v: number): number => Math.min(hi, Math.max(lo, v));

/** Distance-proportional glide duration (clamped). The shared "feel". */
export function glideDur(dist: number): number {
    return clamp(GLIDE_MIN_MS, dist * GLIDE_MS_PER_PX, GLIDE_MAX_MS);
}

/** A cubic-Hermite glide: starts at `from` with tangent `fromVel` (px/ms) and
 *  lands at `to` with zero velocity over `dur` ms. From rest (`fromVel = 0`) the
 *  basis collapses to smoothstep — a soft ease-in-out. */
interface Plan {
    from: number;
    fromVel: number; // px/ms at the plan's start (carried on re-plan)
    to: number;
    startT: number;
    dur: number;
    /** A `follow` catch-up re-plans toward the live target; a `fixed` glide does
     *  not (its target is final). */
    follow: boolean;
}

/** Hermite position at progress τ∈[0,1]. m0 is the start tangent scaled to the
 *  duration (px over the whole glide); the end tangent is 0. */
function hermitePos(p: Plan, tau: number): number {
    const t2 = tau * tau;
    const t3 = t2 * tau;
    const h00 = 2 * t3 - 3 * t2 + 1;
    const h10 = t3 - 2 * t2 + tau;
    const h01 = -2 * t3 + 3 * t2;
    return h00 * p.from + h10 * (p.fromVel * p.dur) + h01 * p.to;
}

/** Hermite velocity (px/ms) at progress τ — the derivative of `hermitePos`,
 *  used to carry velocity into a re-plan so speed stays continuous. */
function hermiteVel(p: Plan, tau: number): number {
    const t2 = tau * tau;
    const dh00 = 6 * t2 - 6 * tau;
    const dh10 = 3 * t2 - 4 * tau + 1;
    const dh01 = -6 * t2 + 6 * tau;
    return (dh00 * p.from + dh10 * (p.fromVel * p.dur) + dh01 * p.to) / p.dur;
}

export interface StripScrollerOpts {
    /** Max scrollable offset (px) — targets are clamped into [0, lastRight]. */
    readonly lastRight: number;
    /** Skip the eased glide (apply targets instantly). */
    readonly reducedMotion: boolean;
    /** Monotonic clock (ms). Defaults to performance.now; injectable for tests. */
    now?: () => number;
    /** rAF scheduler. Defaults to requestAnimationFrame; injectable for tests. */
    raf?: (_cb: (_t: number) => void) => number;
    /** rAF canceller. Defaults to cancelAnimationFrame. */
    caf?: (_id: number) => void;
}

export interface StripScroller {
    /** Current strip offset (px) — reactive; read in the template. */
    readonly offset: number;
    /** Set the offset instantly (forward tracking, live drag/scrub, reduced
     *  motion). Clears any in-flight glide. */
    snap(_target: number): void;
    /** Ease to a FIXED target (click, key, snap-center, drag-release, paused
     *  refresh, snap-mode loopback). Re-plannable: calling mid-glide starts a
     *  fresh curve from the current position + velocity. */
    glide(_target: number): void;
    /** Continuous-mode per-frame entry (hybrid/tuner). Forward play (`!discont`,
     *  not mid-catch-up) tracks instantly; a discontinuity arms — and each later
     *  frame re-plans — an eased catch-up that chases the live moving target,
     *  then lands and resumes instant tracking. */
    follow(_target: number, _discont: boolean): void;
    /** Drop any in-flight glide and stop animating (drag start, chapter change). */
    cancel(): void;
    /** True while an eased glide is in flight. */
    readonly animating: boolean;
    /** Tear down the rAF (component destroy). */
    dispose(): void;
}

/**
 * Build a strip-scroll controller. `offset` is rune-reactive so a Svelte
 * template can bind `translateX(-offset)` directly.
 */
export function createStripScroller(opts: StripScrollerOpts): StripScroller {
    const now = opts.now ?? (() => performance.now());
    const raf = opts.raf ?? ((cb) => requestAnimationFrame(cb));
    const caf = opts.caf ?? ((id) => cancelAnimationFrame(id));

    let offset = $state(0);
    let velocity = 0; // px/ms — the live scroll speed, carried into re-plans
    let plan: Plan | null = null;
    let rafId = 0;
    let lastT = -1; // last frame timestamp, for instant-track velocity

    const clampOff = (v: number): number => clamp(0, Math.max(0, opts.lastRight), v);

    function ensureRaf(): void {
        if (!rafId) rafId = raf(tick);
    }
    function stopRaf(): void {
        if (rafId) caf(rafId);
        rafId = 0;
    }

    /** Apply an instant offset and record the implied velocity (for a later
     *  catch-up to start at the true scroll speed, not from rest). */
    function applyInstant(target: number): void {
        const to = clampOff(target);
        const t = now();
        if (lastT >= 0 && t > lastT) velocity = (to - offset) / (t - lastT);
        lastT = t;
        offset = to;
    }

    function planTo(target: number, follow: boolean): void {
        const to = clampOff(target);
        plan = {
            from: offset,
            fromVel: velocity,
            to,
            startT: now(),
            dur: glideDur(Math.abs(to - offset)),
            follow,
        };
        ensureRaf();
    }

    function tick(): void {
        rafId = 0;
        const p = plan;
        if (!p) return;
        const t = now();
        const tau = p.dur > 0 ? clamp(0, 1, (t - p.startT) / p.dur) : 1;
        offset = hermitePos(p, tau);
        velocity = hermiteVel(p, tau);
        lastT = t;
        const landed = tau >= 1 || Math.abs(offset - p.to) <= SNAP_EPS_PX;
        if (landed) {
            offset = p.to;
            velocity = 0;
            plan = null;
            return; // rAF stops; follow()/glide() restarts it on the next move
        }
        ensureRaf();
    }

    return {
        get offset() {
            return offset;
        },
        get animating() {
            return plan !== null;
        },
        snap(target: number): void {
            plan = null;
            stopRaf();
            applyInstant(target);
        },
        glide(target: number): void {
            const to = clampOff(target);
            if (opts.reducedMotion || Math.abs(to - offset) < 1) {
                this.snap(to);
                return;
            }
            planTo(to, false);
        },
        follow(target: number, discont: boolean): void {
            const to = clampOff(target);
            if (opts.reducedMotion) {
                this.snap(to);
                return;
            }
            if (plan?.follow) {
                // Mid-catch-up: keep chasing the live, still-moving target. A small
                // drift (the replay advancing word-by-word) just re-aims the curve's
                // endpoint, so the glide tracks the live word and lands on it. A
                // large sudden jump (a second loopback) re-plans a fresh curve,
                // carrying current velocity so the speed never jumps.
                if (Math.abs(to - plan.to) > DRIFT_EPS_PX) planTo(to, true);
                else plan.to = to;
                return;
            }
            if (discont && Math.abs(to - offset) >= 1) {
                planTo(to, true);
                return;
            }
            applyInstant(to); // forward play — needle locked on the recited word
        },
        cancel(): void {
            plan = null;
            velocity = 0;
            lastT = -1;
            stopRaf();
        },
        dispose(): void {
            plan = null;
            stopRaf();
        },
    };
}
