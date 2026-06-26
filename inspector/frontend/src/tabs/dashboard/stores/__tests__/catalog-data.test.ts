import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';

import { setVisibility } from '../../../../lib/test-helpers/poll-helpers';

/** Drain queued promise microtasks (the immediate, non-timer first tick). */
async function settle(): Promise<void> {
    for (let i = 0; i < 30; i += 1) await Promise.resolve();
}

function res(status: number, body: unknown) {
    return { ok: status >= 200 && status < 300, status, json: async () => body };
}

describe('catalog-data poll resilience', () => {
    let teardown: (() => void) | null = null;

    beforeEach(() => {
        vi.resetModules();
        vi.useFakeTimers();
        setVisibility(false); // hidden=false → document visible
    });

    afterEach(() => {
        teardown?.();
        teardown = null;
        vi.useRealTimers();
        vi.unstubAllGlobals();
        setVisibility(false);
    });

    function stubFetch(state: { version: number; versionStatus: number }) {
        vi.stubGlobal(
            'fetch',
            vi.fn(async (input: RequestInfo | URL) => {
                const url = String(input);
                if (url.startsWith('/api/public/version')) {
                    return state.versionStatus === 200
                        ? res(200, { db_seq: state.version })
                        : res(state.versionStatus, null);
                }
                if (url.startsWith('/api/public/reciters')) {
                    return res(200, {
                        reciters: [
                            {
                                reciter_id: 'r1',
                                name: 'R',
                                last_activity: null,
                                primary_bucket: 'published',
                                deliveries_count: 1,
                                deliveries: [],
                            },
                        ],
                        total: 1,
                        next_cursor: null,
                    });
                }
                if (url.startsWith('/api/public/stats')) return res(200, {});
                return res(404, null);
            }),
        );
    }

    it('keeps last-good data on a transient failure and surfaces only after persistent failures', async () => {
        const state = { version: 1, versionStatus: 200 };
        stubFetch(state);
        const mod = await import('../catalog-data');
        teardown = mod.startCatalogPolling();
        await settle(); // immediate tick loads the roster

        expect(get(mod.catalogData).reciters).toHaveLength(1);
        expect(get(mod.catalogData).error).toBeNull();

        // The version probe starts 500ing.
        state.versionStatus = 500;
        await vi.advanceTimersByTimeAsync(30_000); // streak 1 — swallowed
        expect(get(mod.catalogData).error).toBeNull();
        expect(get(mod.catalogData).reciters).toHaveLength(1);
        await vi.advanceTimersByTimeAsync(30_000); // streak 2 — swallowed
        expect(get(mod.catalogData).error).toBeNull();
        await vi.advanceTimersByTimeAsync(30_000); // streak 3 — surfaced
        expect(get(mod.catalogData).error).toBeTruthy();

        // Recovery clears the transient error banner.
        state.versionStatus = 200;
        await vi.advanceTimersByTimeAsync(30_000);
        expect(get(mod.catalogData).error).toBeNull();
    });
});
