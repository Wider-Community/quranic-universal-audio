import { describe, expect, it } from 'vitest';

import { resolveChapterDurationMs } from '../footer-duration';

describe('resolveChapterDurationMs', () => {
    it('prefers the live element duration in chapter (non-clip) mode', () => {
        expect(
            resolveChapterDurationMs({ elDurationMs: 41_000, inClip: false, manifestDurMs: 40_500 }),
        ).toBe(41_000);
    });

    it('falls back to the manifest duration when the element duration is non-finite (reported 0)', () => {
        // Headerless CDN stream-through: browser hasn't resolved a duration.
        expect(
            resolveChapterDurationMs({ elDurationMs: 0, inClip: false, manifestDurMs: 41_000 }),
        ).toBe(41_000);
    });

    it('uses the chapter-wide manifest duration in clip mode, ignoring the short clip duration', () => {
        // VBR clip: el.duration is the clip (~3s) but currentMs is file-absolute,
        // so the bar must be sized to the whole chapter.
        expect(
            resolveChapterDurationMs({ elDurationMs: 3_000, inClip: true, manifestDurMs: 360_000 }),
        ).toBe(360_000);
    });

    it('returns 0 when neither source yields a duration (caller hides the bar)', () => {
        expect(
            resolveChapterDurationMs({ elDurationMs: 0, inClip: false, manifestDurMs: 0 }),
        ).toBe(0);
    });

    it('returns 0 in clip mode when the manifest has no duration for the chapter', () => {
        expect(
            resolveChapterDurationMs({ elDurationMs: 3_000, inClip: true, manifestDurMs: 0 }),
        ).toBe(0);
    });
});
