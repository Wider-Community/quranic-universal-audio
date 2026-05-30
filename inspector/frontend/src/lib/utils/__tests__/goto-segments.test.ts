import { get } from 'svelte/store';
import { afterEach, describe, expect, it } from 'vitest';

import { activeTab } from '../active-tab';
import { LS_KEYS, TAB_NAMES } from '../constants';
import { gotoSegments } from '../goto-segments';
import { selectedReciter } from '../../../tabs/segments/stores/chapter';

afterEach(() => {
    selectedReciter.set('');
    activeTab.set(TAB_NAMES.DASHBOARD);
    try {
        localStorage.removeItem(LS_KEYS.SEG_RECITER);
    } catch {
        /* ignore */
    }
});

describe('gotoSegments', () => {
    it('selects the reciter, switches to the segments tab, and persists the slug', () => {
        gotoSegments('reciter-x');
        expect(get(selectedReciter)).toBe('reciter-x');
        expect(get(activeTab)).toBe(TAB_NAMES.SEGMENTS);
        expect(localStorage.getItem(LS_KEYS.SEG_RECITER)).toBe('reciter-x');
    });

    it('is a no-op for an empty slug', () => {
        gotoSegments('');
        expect(get(selectedReciter)).toBe('');
        expect(get(activeTab)).toBe(TAB_NAMES.DASHBOARD);
    });
});
