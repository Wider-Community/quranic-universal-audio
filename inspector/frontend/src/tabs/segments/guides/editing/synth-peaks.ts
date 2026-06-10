import type { PeakBucket } from '../../../../lib/types/peaks-transport';

/**
 * A synthetic, speech-like waveform for the editing guide's mock cards. No
 * audio is involved — it just feeds `WaveformCanvas` a believable `PeakBucket[]`
 * (`[min, max]` tuples) so the illustration looks like a real segment.
 *
 * Deterministic for a given `seed` (no Math.random) so the picture is stable
 * across renders. The envelope fades at both ends and clusters into syllable
 * bursts in the middle.
 */
export function synthPeaks(count = 150, seed = 7): PeakBucket[] {
    const peaks: PeakBucket[] = [];
    let s = (seed * 9301 + 49297) % 233280;
    const rand = (): number => {
        s = (s * 9301 + 49297) % 233280;
        return s / 233280;
    };
    for (let i = 0; i < count; i++) {
        const t = i / (count - 1);
        const edge = Math.sin(t * Math.PI); // 0 at the ends, 1 in the middle
        const syllable = 0.5 + 0.5 * Math.sin(t * Math.PI * 6.5);
        const amp = edge * (0.3 + 0.55 * syllable) * (0.65 + 0.6 * rand());
        const a = Math.max(0.04, Math.min(1, amp));
        peaks.push([-a, a]);
    }
    return peaks;
}
