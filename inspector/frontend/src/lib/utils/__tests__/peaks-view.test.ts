import { describe, expect, it } from 'vitest';

import type { PeakBucket } from '../../types/domain';
import { packPeaksB64, viewPeaks } from '../peaks-view';

/** Decode a base64 string to an Int8Array (mirror of peaks-decode.ts::b64ToInt8). */
function b64ToInt8(b64: string): Int8Array {
    const bin = atob(b64);
    const out = new Int8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = (bin.charCodeAt(i) << 24) >> 24;
    return out;
}

describe('packPeaksB64', () => {
    it('quantizes float buckets and round-trips through viewPeaks', () => {
        const peaks: PeakBucket[] = [[-1, 1], [-0.5, 0.5], [0, 0], [0.25, -0.25]];
        const b64 = packPeaksB64(peaks);
        const decoded = b64ToInt8(b64);
        expect(decoded.length).toBe(peaks.length * 2);

        const view = viewPeaks(decoded)!;
        expect(view.length).toBe(peaks.length);
        // Dequant tolerance: one int8 step (1/127).
        for (let i = 0; i < peaks.length; i++) {
            expect(Math.abs(view.min(i) - peaks[i]![0])).toBeLessThanOrEqual(1 / 127 + 1e-6);
            expect(Math.abs(view.max(i) - peaks[i]![1])).toBeLessThanOrEqual(1 / 127 + 1e-6);
        }
    });

    it('clamps out-of-range floats to [-127, 127]', () => {
        const b64 = packPeaksB64([[-2, 2]]);
        const decoded = b64ToInt8(b64);
        expect(decoded[0]).toBe(-127);
        expect(decoded[1]).toBe(127);
    });

    it('encodes an Int8Array as-is', () => {
        const src = new Int8Array([-3, 5, -2, 4]);
        const b64 = packPeaksB64(src);
        expect(Array.from(b64ToInt8(b64))).toEqual([-3, 5, -2, 4]);
    });
});
