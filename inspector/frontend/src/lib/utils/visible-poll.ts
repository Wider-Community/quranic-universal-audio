/**
 * Page-Visibility-aware polling utility.
 *
 * Wraps ``setInterval`` so subscribers receive fresh data while the tab
 * is visible and pause cleanly when the user switches away. Designed
 * for the Phase 6 public activity feed but generic enough for any
 * subscriber-driven public read endpoint.
 *
 * Lifecycle:
 *   - Caller invokes ``visiblePoll({...})``. The first fetch runs
 *     immediately *only if* the document is visible at start time.
 *     If hidden at start, the first fetch waits for ``visibilitychange``.
 *   - Subsequent fetches run on the supplied interval, but only when
 *     the document is visible.
 *   - When the document hides mid-flight, an in-flight ``AbortController``
 *     cancels the request. If the request resolves before abort
 *     completes, the result is discarded via a resolve-time visibility
 *     re-check.
 *   - On ``visibilitychange → visible``, the next fetch is scheduled
 *     immediately (the interval clock resets).
 *
 * Returns a teardown function that cancels any pending fetch, clears
 * the interval, and detaches the visibility listener.
 */

export interface VisiblePollOptions<T> {
    intervalMs: number;
    fetcher: (signal: AbortSignal) => Promise<T>;
    onResult: (result: T) => void;
    onError?: (err: unknown) => void;
}

export function visiblePoll<T>(opts: VisiblePollOptions<T>): () => void {
    const { intervalMs, fetcher, onResult, onError } = opts;

    let intervalId: ReturnType<typeof setInterval> | null = null;
    let controller: AbortController | null = null;
    let stopped = false;

    function isVisible(): boolean {
        return typeof document === 'undefined' || !document.hidden;
    }

    async function runOnce(): Promise<void> {
        if (stopped || !isVisible()) return;
        // Cancel any in-flight request before starting a new one.
        controller?.abort();
        controller = new AbortController();
        const myController = controller;
        try {
            const result = await fetcher(myController.signal);
            // Resolve-time visibility re-check: discard if the tab was
            // hidden while we were waiting.
            if (stopped || myController.signal.aborted || !isVisible()) return;
            onResult(result);
        } catch (err) {
            if (stopped || myController.signal.aborted) return;
            if (onError) onError(err);
        }
    }

    function startInterval(): void {
        if (intervalId !== null) return;
        intervalId = setInterval(runOnce, intervalMs);
    }

    function stopInterval(): void {
        if (intervalId === null) return;
        clearInterval(intervalId);
        intervalId = null;
    }

    function onVisibilityChange(): void {
        if (stopped) return;
        if (isVisible()) {
            // Returning visible — fetch immediately, then resume interval.
            runOnce();
            startInterval();
        } else {
            // Tab hidden — pause interval and cancel in-flight.
            stopInterval();
            controller?.abort();
        }
    }

    if (typeof document !== 'undefined') {
        document.addEventListener('visibilitychange', onVisibilityChange);
    }
    if (isVisible()) {
        runOnce();
        startInterval();
    }

    return function teardown(): void {
        stopped = true;
        stopInterval();
        controller?.abort();
        if (typeof document !== 'undefined') {
            document.removeEventListener('visibilitychange', onVisibilityChange);
        }
    };
}
