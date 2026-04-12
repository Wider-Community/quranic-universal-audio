/**
 * Tiny requestAnimationFrame loop helper.
 *
 * Wraps a per-frame callback with `start` / `stop` controls and internal
 * frame-id tracking. The callback may return `false` to self-stop (the
 * helper then cancels its own frame), or anything else to continue.
 *
 * Currently unused by production callers — `segments/playback/index.ts` and
 * `timestamps/playback.ts` still manage their own RAF ids via `state.*AnimId`.
 * Migration is deferred to Phase 6 when those files are typed and their
 * stop-side-effects (button text reset, activeAudioSource clearing) can be
 * detangled from the loop lifecycle.
 */

export interface AnimationLoop {
    start(): void;
    stop(): void;
    running(): boolean;
}

export function createAnimationLoop(onFrame: () => boolean | void): AnimationLoop {
    let id: number | null = null;

    const tick = (): void => {
        const cont = onFrame();
        if (cont === false) {
            id = null;
            return;
        }
        id = requestAnimationFrame(tick);
    };

    return {
        start(): void {
            if (id !== null) return;
            id = requestAnimationFrame(tick);
        },
        stop(): void {
            if (id !== null) {
                cancelAnimationFrame(id);
                id = null;
            }
        },
        running(): boolean {
            return id !== null;
        },
    };
}
