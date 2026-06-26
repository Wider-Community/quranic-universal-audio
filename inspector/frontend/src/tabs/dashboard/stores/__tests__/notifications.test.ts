import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { setVisibility } from '../../../../lib/test-helpers/poll-helpers';

/** Drain queued promise microtasks (the immediate, non-timer first tick). */
async function settle(): Promise<void> {
    for (let i = 0; i < 30; i += 1) await Promise.resolve();
}

function res(status: number, body: unknown) {
    return { ok: status >= 200 && status < 300, status, json: async () => body };
}

describe('notifications poll resilience', () => {
    beforeEach(() => {
        vi.resetModules();
        vi.useFakeTimers();
        setVisibility(false); // hidden=false → document visible
    });

    afterEach(() => {
        vi.useRealTimers();
        vi.unstubAllGlobals();
        setVisibility(false);
    });

    function stubFetch(state: { status: number }) {
        vi.stubGlobal(
            'fetch',
            vi.fn(async (input: RequestInfo | URL) => {
                const url = String(input);
                if (url.startsWith('/api/me/notifications')) {
                    return state.status === 200
                        ? res(200, { notifications: [{ id: 1 }], unread: 2 })
                        : res(state.status, null);
                }
                return res(404, null);
            }),
        );
    }

    it('keeps the rail populated on a transient failure and surfaces only after persistent failures', async () => {
        const state = { status: 200 };
        stubFetch(state);
        const { notifications } = await import('../notifications.svelte');
        notifications.start();
        await settle(); // immediate tick loads the active list

        expect(notifications.active).toHaveLength(1);
        expect(notifications.error).toBeNull();

        state.status = 500;
        await vi.advanceTimersByTimeAsync(30_000); // streak 1 — swallowed
        expect(notifications.error).toBeNull();
        expect(notifications.active).toHaveLength(1);
        await vi.advanceTimersByTimeAsync(30_000); // streak 2 — swallowed
        expect(notifications.error).toBeNull();
        await vi.advanceTimersByTimeAsync(30_000); // streak 3 — surfaced
        expect(notifications.error).toBeTruthy();

        // Recovery clears the transient error.
        state.status = 200;
        await vi.advanceTimersByTimeAsync(30_000);
        expect(notifications.error).toBeNull();

        notifications.stop();
    });
});
