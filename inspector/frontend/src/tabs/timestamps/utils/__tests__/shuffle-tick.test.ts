import { describe, expect, it } from 'vitest';

import {
    resolveShuffleTick,
    shouldFireShuffle,
    verseAt,
    type ShuffleTickVerse,
} from '../shuffle-tick';

// Three ayahs recited continuously → contiguous (each end == next start), so
// the playhead crosses a seam with no gap. This is the shape that triggered the
// short-verse leak.
const CONTIGUOUS: ShuffleTickVerse[] = [
    { ref: '2:1', startMs: 0, endMs: 1000 },
    { ref: '2:2', startMs: 1000, endMs: 2000 },
    { ref: '2:3', startMs: 2000, endMs: 3000 },
];

const GUARD = 40;

describe('resolveShuffleTick', () => {
    it('fires against the auditioned ayah even when a skipped frame overshoots past its end', () => {
        // Auditioning 2:1 (ends at 1000). A starved rAF frame lands the playhead at
        // 1400 — already inside the contiguous next ayah. The fire must still resolve
        // against 2:1's end, NOT re-base onto 2:2 (which would leak 2:2 in full).
        const outcome = resolveShuffleTick({
            verses: CONTIGUOUS,
            ms: 1400,
            armed: true,
            focusEndMs: 1000,
            guardMs: GUARD,
            firedForCurrentFocus: false,
        });

        expect(outcome).toEqual({ kind: 'fire' });
    });

    it('fires within the early guard window before the exact ayah end', () => {
        const outcome = resolveShuffleTick({
            verses: CONTIGUOUS,
            ms: 970,
            armed: true,
            focusEndMs: 1000,
            guardMs: GUARD,
            firedForCurrentFocus: false,
        });

        expect(outcome).toEqual({ kind: 'fire' });
    });

    it('advances focus to the containing ayah, without firing, before the guard window', () => {
        const outcome = resolveShuffleTick({
            verses: CONTIGUOUS,
            ms: 950,
            armed: true,
            focusEndMs: 1000,
            guardMs: GUARD,
            firedForCurrentFocus: false,
        });

        expect(outcome).toEqual({ kind: 'focus', ref: '2:1' });
    });

    it('does not re-fire for an ayah it already fired for; advances focus instead', () => {
        const outcome = resolveShuffleTick({
            verses: CONTIGUOUS,
            ms: 1400,
            armed: true,
            focusEndMs: 1000,
            guardMs: GUARD,
            firedForCurrentFocus: true,
        });

        expect(outcome).toEqual({ kind: 'focus', ref: '2:2' });
    });

    it('does not fire when shuffle is disarmed; tracks focus normally', () => {
        const outcome = resolveShuffleTick({
            verses: CONTIGUOUS,
            ms: 1400,
            armed: false,
            focusEndMs: 1000,
            guardMs: GUARD,
            firedForCurrentFocus: false,
        });

        expect(outcome).toEqual({ kind: 'focus', ref: '2:2' });
    });
});

describe('shouldFireShuffle', () => {
    it('treats the guard as a lower bound — an arbitrarily large overshoot still fires', () => {
        expect(
            shouldFireShuffle({
                armed: true,
                ms: 9999,
                focusEndMs: 1000,
                guardMs: GUARD,
                firedForCurrentFocus: false,
            }),
        ).toBe(true);
    });

    it('does not fire when no verse is loaded (null end)', () => {
        expect(
            shouldFireShuffle({
                armed: true,
                ms: 9999,
                focusEndMs: null,
                guardMs: GUARD,
                firedForCurrentFocus: false,
            }),
        ).toBe(false);
    });
});

describe('verseAt', () => {
    it('returns the ayah whose span contains the playhead', () => {
        expect(verseAt(CONTIGUOUS, 1500)).toBe('2:2');
    });

    it('returns the nearest preceding ayah when the playhead sits in a gap', () => {
        const gapped: ShuffleTickVerse[] = [
            { ref: '7:1', startMs: 0, endMs: 1000 },
            { ref: '7:2', startMs: 2000, endMs: 3000 },
        ];

        expect(verseAt(gapped, 1500)).toBe('7:1');
    });

    it('returns the first ayah when the playhead precedes all spans', () => {
        const offset: ShuffleTickVerse[] = [
            { ref: '9:1', startMs: 100, endMs: 1000 },
            { ref: '9:2', startMs: 1000, endMs: 2000 },
        ];

        expect(verseAt(offset, 50)).toBe('9:1');
    });

    it('returns null when there are no verses', () => {
        expect(verseAt([], 100)).toBeNull();
    });
});
