import { fireEvent, render, waitFor } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';

import type {
    PublicBucket,
    PublicDelivery,
    PublicReciter,
} from '../../../types/public-state';
import type { CombinationSelection } from '../CombinationPicker.svelte';
import CombinationPicker from '../CombinationPicker.svelte';

function makeDelivery(slug: string, bucket: PublicBucket, riwayah = 'hafs'): PublicDelivery {
    return {
        slug,
        riwayah,
        style: 'murattal',
        recording_context: null,
        recording_year: null,
        source: 'mp3quran',
        channel: 'mp3quran',
        channel_name: 'mp3quran',
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
    return {
        reciter_id: name.toLowerCase().replace(/\s+/g, '_'),
        name,
        name_ar: null,
        country: null,
        primary_bucket: deliveries[0]?.bucket ?? 'available_for_review',
        buckets: deliveries.map((d) => d.bucket),
        deliveries,
        riwayat: [...new Set(deliveries.map((d) => d.riwayah))],
        styles: [...new Set(deliveries.map((d) => d.style))],
        recording_contexts: [],
        sources: [...new Set(deliveries.map((d) => d.source))],
        channels: [...new Set(deliveries.map((d) => d.channel))],
        deliveries_count: deliveries.length,
        chapter_count_total: 114,
        coverage_kind: 'full',
        last_activity: null,
    };
}

vi.mock('../../../api/public-reciters', () => ({
    fetchPublicReciters: vi.fn(() =>
        Promise.resolve({
            reciters: [
                makeReciter('Alpha', [makeDelivery('alpha-hafs', 'available_for_review')]),
                makeReciter('Beta', [makeDelivery('beta-hafs', 'published')]),
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
            publishing: 0,
            published: 1,
        }),
    ),
}));

describe('CombinationPicker', () => {
    it('emits a non-null delivery on first row click', async () => {
        const { container, component } = render(CombinationPicker, {
            props: { open: true, title: 'Switch reciter' },
        });

        const selected: CombinationSelection[] = [];
        component.$on('select', (e: CustomEvent<CombinationSelection>) => {
            selected.push(e.detail);
        });

        // Wait for load() to flush the rows in.
        const firstRow = await waitFor(() => {
            const row = container.querySelector<HTMLElement>('.combo-row');
            expect(row).not.toBeNull();
            return row!;
        });

        await fireEvent.click(firstRow);

        expect(selected.length).toBe(1);
        const picked = selected[0]!;
        expect(picked.kind).toBe('combination');
        expect(picked.delivery).not.toBeNull();
        expect(picked.delivery.slug).toBeTruthy();
    });
});
