import { get } from 'svelte/store';
import { afterEach, describe, expect, it } from 'vitest';

import { selectedReciter } from '../../../tabs/segments/stores/chapter';
import { activeTab, setActiveTab } from '../active-tab';
import { LS_KEYS, TAB_NAMES } from '../constants';
import { gotoSegments } from '../goto-segments';

afterEach(() => {
    selectedReciter.set('');
    setActiveTab(TAB_NAMES.DASHBOARD);
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

    it('is a no-op for an empty slug — does not overwrite existing state or localStorage', () => {
        // Pre-seed all three observables to non-default values so the no-op
        // assertion proves the function returned early (instead of trivially
        // matching the initialisation defaults).
        selectedReciter.set('existing');
        setActiveTab(TAB_NAMES.TIMESTAMPS);
        localStorage.setItem(LS_KEYS.SEG_RECITER, 'existing');

        gotoSegments('');

        expect(get(selectedReciter)).toBe('existing');
        expect(get(activeTab)).toBe(TAB_NAMES.TIMESTAMPS);
        expect(localStorage.getItem(LS_KEYS.SEG_RECITER)).toBe('existing');
    });
});
