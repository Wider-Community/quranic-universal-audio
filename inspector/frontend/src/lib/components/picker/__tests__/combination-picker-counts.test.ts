import { render, waitFor } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import type { PublicDelivery, PublicReciter } from '../../../types/generated/schemas';
import type { PublicBucket } from '../../../types/public-bucket';
import CombinationPicker from '../CombinationPicker.svelte';

function makeDelivery(slug: string, bucket: PublicBucket): PublicDelivery {
    return {
        slug,
        riwayah: 'hafs',
        style: 'murattal',
        recording_context: null,
        recording_year: null,
        source: 'mp3quran',
        channel: 'mp3quran',
        channel_name: 'mp3quran',
        source_url: null,
        audio_category: 'studio',
        chapter_count: 114,
        coverage_kind: 'full',
        state_since: null,
        bitrate_kbps_nominal: 128,
        bitrate_mode: 'cbr',
        total_duration_sec: 3600,
        bucket,
    };
}

function makeReciter(name: string, deliveries: PublicDelivery[]): PublicReciter {
    // primary_bucket = most-progressed bucket; mirrors the backend rollup so a
    // reciter-level count would differ from the delivery-level one below.
    return {
        reciter_id: name.toLowerCase(),
        name,
        name_ar: null,
        country: null,
        primary_bucket: 'published',
        buckets: [...new Set(deliveries.map((d) => d.bucket))],
        deliveries,
        riwayat: ['hafs'],
        styles: ['murattal'],
        recording_contexts: [],
        sources: ['mp3quran'],
        channels: ['mp3quran'],
        deliveries_count: deliveries.length,
        chapter_count_total: 114,
        coverage_kind: 'full',
        last_activity: null,
    };
}

// One reciter spanning three buckets with TWO published deliveries, plus a solo
// reciter. Delivery-level counts (what the picker lists): available=1,
// under_review=1, published=2, All=4. Reciter-level stats (one per reciter, by
// primary_bucket): published=1, available=1, under_review=0, All=2 — the values
// the picker MUST NOT show, since its rows are deliveries.
vi.mock('../../../api/public-reciters', () => ({
    fetchPublicReciters: vi.fn(() =>
        Promise.resolve({
            reciters: [
                makeReciter('Multi', [
                    makeDelivery('multi-a', 'published'),
                    makeDelivery('multi-b', 'published'),
                    makeDelivery('multi-c', 'under_review'),
                ]),
                makeReciter('Solo', [makeDelivery('solo-a', 'available_for_review')]),
            ],
            total: 2,
            next_cursor: null,
        }),
    ),
    fetchPublicStats: vi.fn(() =>
        Promise.resolve({
            available_for_request: 0,
            requested: 0,
            available_for_review: 1,
            under_review: 0,
            published: 1,
        }),
    ),
}));

function tabCounts(container: HTMLElement): Record<string, number> {
    const out: Record<string, number> = {};
    for (const pill of container.querySelectorAll('.picker-controls-tabs .pill')) {
        const label = pill.querySelector('.label')?.textContent?.trim();
        const count = pill.querySelector('.pill-count')?.textContent?.trim();
        if (label && count !== undefined) out[label] = Number(count);
    }
    return out;
}

describe('CombinationPicker state-tab counts', () => {
    it('counts deliveries per bucket, not reciters by primary_bucket', async () => {
        const { container } = render(CombinationPicker, {
            props: { open: true, title: 'Switch reciter' },
        });

        await waitFor(() => {
            expect(container.querySelector('.combo-row')).not.toBeNull();
        });

        const counts = tabCounts(container);
        expect(counts.All).toBe(4);
        expect(counts.Published).toBe(2);
        expect(counts['Under review']).toBe(1);
        expect(counts['Available for review']).toBe(1);
    });

    it('makes the Published tab pill agree with the Published group head-count', async () => {
        const { container } = render(CombinationPicker, {
            props: { open: true, title: 'Switch reciter' },
        });

        await waitFor(() => {
            expect(container.querySelector('.bucket-head')).not.toBeNull();
        });

        // The group head-count is delivery-level; the tab pill must match it.
        const publishedHead = [...container.querySelectorAll('.bucket-head')].find((h) =>
            h.querySelector('.pill')?.textContent?.includes('Published'),
        );
        const headCount = Number(publishedHead?.querySelector('.head-count')?.textContent?.trim());
        expect(headCount).toBe(2);
        expect(tabCounts(container).Published).toBe(headCount);
    });
});
