import { describe, expect, it } from 'vitest';

import {
    DEFAULT_RIWAYAH,
    isHafs,
    isSupportedRiwayah,
    SUPPORTED_RIWAYAT,
    toInspectorSlug,
    toSdkSlug,
    verseMarkerPrefix,
} from '../riwayat';

describe('riwayah slug vocabularies', () => {
    it('round-trips every supported slug between the two vocabularies', () => {
        for (const [inspector, sdk] of Object.entries(SUPPORTED_RIWAYAT)) {
            expect(toSdkSlug(inspector)).toBe(sdk);
            expect(toInspectorSlug(sdk)).toBe(inspector);
        }
    });

    it('refuses a slug from the wrong vocabulary rather than guessing', () => {
        // `hafs` is a valid SDK slug and NOT a valid Inspector one; conflating
        // the two is what produced the 500s the resolver now guards against.
        expect(toSdkSlug('hafs')).toBeNull();
        expect(toInspectorSlug(DEFAULT_RIWAYAH)).toBeNull();
        expect(isSupportedRiwayah('hafs')).toBe(false);
        expect(isHafs(DEFAULT_RIWAYAH)).toBe(true);
    });

    it('sends the U+06DD ornament only for Hafs', () => {
        expect(verseMarkerPrefix('hafs')).toBe('۝');
        // Absent metadata means a pre-multi-riwayah shard, which is Hafs.
        expect(verseMarkerPrefix(null)).toBe('۝');
        for (const sdk of ['warsh', 'qalun', 'shuba']) {
            expect(verseMarkerPrefix(sdk)).toBe('');
        }
    });
});
