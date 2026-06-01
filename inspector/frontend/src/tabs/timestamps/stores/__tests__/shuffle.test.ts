import { get } from 'svelte/store';
import { beforeEach, describe, expect, it } from 'vitest';

import {
    cycleShuffle,
    manualShuffleRequest,
    requestManualShuffle,
    shuffleAyah,
    shuffleMode,
    shuffleReciter,
} from '../shuffle';

describe('timestamps shuffle store', () => {
    beforeEach(() => {
        localStorage.clear();
        shuffleReciter.set(false);
        shuffleAyah.set(false);
        manualShuffleRequest.set(0);
    });

    it('cycles shuffle mode without requesting an immediate jump', () => {
        cycleShuffle();

        expect(get(shuffleMode)).toBe(1);
        expect(get(manualShuffleRequest)).toBe(0);
    });

    it('keeps mode cycling separate from manual jump requests', () => {
        cycleShuffle();
        cycleShuffle();

        expect(get(shuffleMode)).toBe(2);
        expect(get(manualShuffleRequest)).toBe(0);
    });

    it('exposes an explicit manual jump request for paused shuffle clicks', () => {
        requestManualShuffle();
        requestManualShuffle();

        expect(get(manualShuffleRequest)).toBe(2);
    });
});
