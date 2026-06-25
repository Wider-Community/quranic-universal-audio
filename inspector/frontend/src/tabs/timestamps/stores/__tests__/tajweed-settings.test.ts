import { get } from 'svelte/store';
import { afterEach, describe, expect, it } from 'vitest';

import { LS_KEYS } from '../../../../lib/utils/constants';
import {
    initTajweedSettings,
    isRuleEnabled,
    resetAllTajweed,
    setRuleColor,
    setRuleEnabled,
    type TajweedSettings,
    tajweedSettings,
} from '../tajweed-settings';

describe('tajweed-settings store', () => {
    afterEach(() => {
        localStorage.clear();
        resetAllTajweed();
        document.documentElement.removeAttribute('style');
    });

    it('seeds defaults — everything on except iẓhar and madd ṭabīʿī', () => {
        resetAllTajweed();
        const s = get(tajweedSettings);
        expect(isRuleEnabled(s, 'ikhfaa')).toBe(true);
        expect(isRuleEnabled(s, 'tafkheem')).toBe(true);
        expect(isRuleEnabled(s, 'qalqala')).toBe(true);
        expect(isRuleEnabled(s, 'izhar')).toBe(false);
        expect(isRuleEnabled(s, 'izhar_shafawi')).toBe(false);
        expect(isRuleEnabled(s, 'madd_tabii')).toBe(false);
    });

    it('persists a toggle to localStorage and rehydrates on init', () => {
        resetAllTajweed();
        setRuleEnabled('qalqala', false);
        const raw = JSON.parse(localStorage.getItem(LS_KEYS.TS_TAJWEED)!) as TajweedSettings;
        expect(raw.qalqala!.enabled).toBe(false);
        // wipe the in-memory store, then re-hydrate from storage
        tajweedSettings.set({});
        initTajweedSettings();
        expect(isRuleEnabled(get(tajweedSettings), 'qalqala')).toBe(false);
    });

    it('writes a colour override to the rule CSS var and clears it on reset', () => {
        resetAllTajweed();
        setRuleColor('tafkheem', '#123456');
        expect(document.documentElement.style.getPropertyValue('--tj-tafkheem')).toBe('#123456');
        expect(get(tajweedSettings).tafkheem!.color).toBe('#123456');
        resetAllTajweed();
        expect(document.documentElement.style.getPropertyValue('--tj-tafkheem')).toBe('');
        expect(get(tajweedSettings).tafkheem!.color).toBeNull();
    });
});
