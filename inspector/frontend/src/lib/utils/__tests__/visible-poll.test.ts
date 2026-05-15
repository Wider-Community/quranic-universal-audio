import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { visiblePoll } from '../visible-poll';

function setVisibility(hidden: boolean): void {
    Object.defineProperty(document, 'hidden', { value: hidden, configurable: true });
    Object.defineProperty(document, 'visibilityState', {
        value: hidden ? 'hidden' : 'visible',
        configurable: true,
    });
}

function dispatchVisibilityChange(): void {
    document.dispatchEvent(new Event('visibilitychange'));
}

/** Flush queued microtasks without advancing the fake-timer clock. */
async function flushMicrotasks(): Promise<void> {
    // A handful of awaits drains promise chains created by runOnce()
    // (fetcher + onResult), without triggering the interval timer.
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

describe('visiblePoll', () => {
    beforeEach(() => {
        vi.useFakeTimers();
        setVisibility(false);
    });

    afterEach(() => {
        vi.useRealTimers();
        setVisibility(false);
    });

    it('fetches immediately when the document is visible at start', async () => {
        const fetcher = vi.fn().mockResolvedValue('payload');
        const onResult = vi.fn();
        const teardown = visiblePoll({ intervalMs: 1000, fetcher, onResult });
        await flushMicrotasks();
        expect(fetcher).toHaveBeenCalledTimes(1);
        expect(onResult).toHaveBeenCalledWith('payload');
        teardown();
    });

    it('skips the initial fetch when the document is hidden at start', async () => {
        setVisibility(true);
        const fetcher = vi.fn().mockResolvedValue('payload');
        const onResult = vi.fn();
        const teardown = visiblePoll({ intervalMs: 1000, fetcher, onResult });
        await flushMicrotasks();
        expect(fetcher).not.toHaveBeenCalled();
        expect(onResult).not.toHaveBeenCalled();
        teardown();
    });

    it('polls on the interval while visible', async () => {
        const fetcher = vi.fn().mockResolvedValue('p');
        const onResult = vi.fn();
        const teardown = visiblePoll({ intervalMs: 1000, fetcher, onResult });
        await flushMicrotasks();
        expect(fetcher).toHaveBeenCalledTimes(1);
        await vi.advanceTimersByTimeAsync(1000);
        expect(fetcher).toHaveBeenCalledTimes(2);
        await vi.advanceTimersByTimeAsync(1000);
        expect(fetcher).toHaveBeenCalledTimes(3);
        teardown();
    });

    it('pauses when the document hides and resumes (immediate fetch) when it returns', async () => {
        const fetcher = vi.fn().mockResolvedValue('p');
        const onResult = vi.fn();
        const teardown = visiblePoll({ intervalMs: 1000, fetcher, onResult });
        await flushMicrotasks();
        expect(fetcher).toHaveBeenCalledTimes(1);

        // Hide.
        setVisibility(true);
        dispatchVisibilityChange();
        await vi.advanceTimersByTimeAsync(5000);
        expect(fetcher).toHaveBeenCalledTimes(1);

        // Show again — immediate fetch.
        setVisibility(false);
        dispatchVisibilityChange();
        await flushMicrotasks();
        expect(fetcher).toHaveBeenCalledTimes(2);
        teardown();
    });

    it('discards an in-flight response that resolves after hide', async () => {
        let resolveFetch: (v: string) => void = () => {};
        const fetcher = vi.fn(
            () =>
                new Promise<string>((resolve) => {
                    resolveFetch = resolve;
                }),
        );
        const onResult = vi.fn();
        const teardown = visiblePoll({ intervalMs: 1000, fetcher, onResult });
        // Hide before the in-flight fetch resolves.
        setVisibility(true);
        dispatchVisibilityChange();
        resolveFetch('late-payload');
        await flushMicrotasks();
        expect(onResult).not.toHaveBeenCalled();
        teardown();
    });

    it('teardown stops further fetches and clears listeners', async () => {
        const fetcher = vi.fn().mockResolvedValue('p');
        const onResult = vi.fn();
        const teardown = visiblePoll({ intervalMs: 1000, fetcher, onResult });
        await flushMicrotasks();
        teardown();
        await vi.advanceTimersByTimeAsync(5000);
        expect(fetcher).toHaveBeenCalledTimes(1);
    });

    it('routes thrown fetcher errors to onError when supplied', async () => {
        const fetcher = vi.fn().mockRejectedValue(new Error('boom'));
        const onError = vi.fn();
        const onResult = vi.fn();
        const teardown = visiblePoll({ intervalMs: 1000, fetcher, onResult, onError });
        await flushMicrotasks();
        expect(onError).toHaveBeenCalled();
        expect(onResult).not.toHaveBeenCalled();
        teardown();
    });
});
