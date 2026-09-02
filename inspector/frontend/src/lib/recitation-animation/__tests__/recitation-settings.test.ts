import { beforeEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';

import { DEFAULT_RECITATION_CONFIG } from '../config';
import { loadPrefs } from '../nowreciting-prefs';
import {
    cycleUpcoming,
    eyeIconName,
    recitationConfigStore,
    recitationOpacityByGranularity,
    recitationSilentOmit,
    sizeUp,
    toggleGranularity,
    toggleSilentOmit,
} from '../recitation-settings';

describe('recitation upcoming visibility', () => {
    beforeEach(() => {
        localStorage.clear();
        recitationConfigStore.set({ ...DEFAULT_RECITATION_CONFIG });
        recitationOpacityByGranularity.set({
            word: DEFAULT_RECITATION_CONFIG.unreachedOpacity,
            char: DEFAULT_RECITATION_CONFIG.unreachedOpacity,
        });
        recitationSilentOmit.set(false);
    });

    it('uses literal opacity 1 for the Full preset', () => {
        recitationConfigStore.set({ ...DEFAULT_RECITATION_CONFIG, unreachedOpacity: 0.2 });

        cycleUpcoming();

        const config = get(recitationConfigStore);
        expect(config.unreachedOpacity).toBe(1);
        expect(eyeIconName(config)).toBe('eye-full');
    });

    it('migrates the old persisted 0.8 Full preset to opacity 1', () => {
        localStorage.setItem(
            'nowreciting-prefs',
            JSON.stringify({
                config: { ...DEFAULT_RECITATION_CONFIG, unreachedOpacity: 0.8 },
                collapsed: false,
            }),
        );

        expect(loadPrefs().config.unreachedOpacity).toBe(1);
    });

    it('recalls a separate upcoming opacity when word and letter modes switch', () => {
        recitationConfigStore.set({
            ...DEFAULT_RECITATION_CONFIG,
            granularity: 'word',
            unreachedOpacity: 0.2,
        });
        recitationOpacityByGranularity.set({ word: 0.2, char: 1 });

        toggleGranularity();
        expect(get(recitationConfigStore)).toMatchObject({
            granularity: 'char',
            unreachedOpacity: 1,
        });

        cycleUpcoming();
        expect(get(recitationConfigStore).unreachedOpacity).toBe(0);

        toggleGranularity();
        expect(get(recitationConfigStore)).toMatchObject({
            granularity: 'word',
            unreachedOpacity: 0.2,
        });

        toggleGranularity();
        expect(get(recitationConfigStore)).toMatchObject({
            granularity: 'char',
            unreachedOpacity: 0,
        });
    });

    it('loads the active mode opacity from the persisted per-mode map', () => {
        localStorage.setItem(
            'nowreciting-prefs',
            JSON.stringify({
                config: { ...DEFAULT_RECITATION_CONFIG, granularity: 'char' },
                unreachedOpacityByGranularity: { word: 0, char: 1 },
                collapsed: false,
            }),
        );

        const prefs = loadPrefs();
        expect(prefs.config.unreachedOpacity).toBe(1);
        expect(prefs.unreachedOpacityByGranularity).toEqual({ word: 0, char: 1 });
    });

    it('persists the silent-letter paint policy independently of granularity', () => {
        toggleSilentOmit();
        expect(get(recitationSilentOmit)).toBe(true);
        expect(loadPrefs().silentOmit).toBe(true);

        toggleGranularity();
        expect(get(recitationSilentOmit)).toBe(true);
    });

    it('allows three additional 2px text-size steps above the former 36px cap', () => {
        recitationConfigStore.set({ ...DEFAULT_RECITATION_CONFIG, fontSizePx: 36 });

        sizeUp();
        sizeUp();
        sizeUp();
        expect(get(recitationConfigStore).fontSizePx).toBe(42);

        sizeUp();
        expect(get(recitationConfigStore).fontSizePx).toBe(42);
    });
});
