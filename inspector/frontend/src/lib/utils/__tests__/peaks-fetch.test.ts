import { describe, expect, it, vi } from 'vitest';

import { fetchJson } from '../../api';
import { fetchSegmentPeaks } from '../peaks-fetch';

vi.mock('../../api', () => ({
    fetchJson: vi.fn(),
}));

describe('fetchSegmentPeaks', () => {
    it('includes chapter in the segment-peaks request when supplied', async () => {
        vi.mocked(fetchJson).mockResolvedValue({
            peaks: {
                'https://cdn.example/a.mp3:100:200': {
                    start_ms: 100,
                    end_ms: 200,
                    duration_ms: 100,
                    peaks: [[-0.1, 0.1]],
                },
            },
        });

        const data = await fetchSegmentPeaks('r', 'https://cdn.example/a.mp3', 100, 200, 7);

        expect(data?.duration_ms).toBe(100);
        const [, init] = vi.mocked(fetchJson).mock.calls[0]!;
        expect(JSON.parse(String(init?.body))).toEqual({
            segments: [{
                url: 'https://cdn.example/a.mp3',
                start_ms: 100,
                end_ms: 200,
                chapter: 7,
            }],
        });
    });
});
