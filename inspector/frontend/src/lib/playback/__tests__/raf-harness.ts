/**
 * rAF harness for happy-dom (which has no native requestAnimationFrame).
 *
 * Usage:
 *   const raf = installRafMock();
 *   ... start a frame loop ...
 *   raf.flushFrames(3);   // run 3 frames synchronously
 *   raf.queueLength();    // pending callbacks
 *   raf.restore();        // teardown
 *
 * Each call to `requestAnimationFrame(cb)` enqueues `cb` and returns a numeric
 * id. `cancelAnimationFrame(id)` removes it from the queue. `flushFrames(n)`
 * pops up to n callbacks and invokes each — matching the real-browser shape
 * where each frame drains the queue snapshot taken at frame start.
 */

import { vi } from 'vitest';

export interface RafMock {
    flushFrames: (n?: number) => number;
    queueLength: () => number;
    restore: () => void;
    rafSpy: ReturnType<typeof vi.fn>;
    cafSpy: ReturnType<typeof vi.fn>;
}

export function installRafMock(): RafMock {
    interface QueuedFrame { id: number; cb: FrameRequestCallback }
    let queue: QueuedFrame[] = [];
    let nextId = 1;

    const raf = (cb: FrameRequestCallback): number => {
        const id = nextId++;
        queue.push({ id, cb });
        return id;
    };
    const caf = (id: number): void => {
        queue = queue.filter((f) => f.id !== id);
    };

    const rafSpy = vi.fn(raf);
    const cafSpy = vi.fn(caf);

    const prevRaf = globalThis.requestAnimationFrame;
    const prevCaf = globalThis.cancelAnimationFrame;
    globalThis.requestAnimationFrame = rafSpy as unknown as typeof requestAnimationFrame;
    globalThis.cancelAnimationFrame = cafSpy as unknown as typeof cancelAnimationFrame;

    function flushFrames(n = 1): number {
        let fired = 0;
        for (let i = 0; i < n; i++) {
            // Snapshot — a callback that re-queues should run on the NEXT flush, not this one.
            const snapshot = queue;
            queue = [];
            if (snapshot.length === 0) break;
            for (const f of snapshot) {
                f.cb(performance.now());
                fired++;
            }
        }
        return fired;
    }

    return {
        flushFrames,
        queueLength: () => queue.length,
        restore: () => {
            queue = [];
            globalThis.requestAnimationFrame = prevRaf;
            globalThis.cancelAnimationFrame = prevCaf;
        },
        rafSpy,
        cafSpy,
    };
}

// ---------------------------------------------------------------------------
// Audio element stub
// ---------------------------------------------------------------------------

export interface AudioStub {
    currentTime: number;
    paused: boolean;
    src: string;
    readyState: number;
    playbackRate: number;
    _listeners: Map<string, Set<EventListener>>;
    _fireEvent: (type: string) => void;
    play: ReturnType<typeof vi.fn>;
    pause: ReturnType<typeof vi.fn>;
    load: ReturnType<typeof vi.fn>;
    addEventListener: ReturnType<typeof vi.fn>;
    removeEventListener: ReturnType<typeof vi.fn>;
}

/**
 * Build a minimal HTMLAudioElement stub for frame-loop tests. Tracks
 * play/pause/load calls as vitest spies; addEventListener / removeEventListener
 * are tracked so tests can synthesize 'canplay' events for src-swap sequences.
 *
 * `paused` flips true on pause(), false on play(); tests can override directly
 * to simulate the post-seek/pre-resolve transient.
 */
export function makeAudioStub(initial: { src?: string; readyState?: number } = {}): AudioStub {
    const listeners = new Map<string, Set<EventListener>>();

    const stub = {
        currentTime: 0,
        paused: true,
        src: initial.src ?? '',
        readyState: initial.readyState ?? 4,
        playbackRate: 1,
        _listeners: listeners,
    } as unknown as AudioStub;

    stub._fireEvent = (type: string): void => {
        const set = listeners.get(type);
        if (!set) return;
        for (const fn of [...set]) fn(new Event(type));
    };
    stub.play = vi.fn((): Promise<void> => {
        stub.paused = false;
        return Promise.resolve();
    });
    stub.pause = vi.fn((): void => {
        stub.paused = true;
    });
    stub.load = vi.fn();
    stub.addEventListener = vi.fn((type: string, cb: EventListener) => {
        if (!listeners.has(type)) listeners.set(type, new Set());
        listeners.get(type)!.add(cb);
    });
    stub.removeEventListener = vi.fn((type: string, cb: EventListener) => {
        listeners.get(type)?.delete(cb);
    });

    return stub;
}
