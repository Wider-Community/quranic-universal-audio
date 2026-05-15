/**
 * Tiny requestAnimationFrame loop helper.
 *
 * Wraps a per-frame callback with `start` / `stop` controls and internal
 * frame-id tracking. The callback may return `false` to self-stop (the
 * helper then cancels its own frame), or anything else to continue.
 *
 * Used by `segments/playback/index.ts` (`_segAnimLoop`) and
 * `timestamps/playback.ts` (`_tsAnimLoop`). Both keep their legacy sentinel
 * `state.*AnimId` in sync (1 when running, null when stopped) so that
 * external truthiness checks continue to work.
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
