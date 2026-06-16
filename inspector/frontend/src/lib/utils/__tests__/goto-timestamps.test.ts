import { get } from 'svelte/store';
import { afterEach, describe, expect, it } from 'vitest';

import { pendingTsNavigation } from '../../stores/navigation';
import { activeTab, setActiveTab } from '../active-tab';
import { TAB_NAMES } from '../constants';
import { gotoTimestamps } from '../goto-timestamps';

afterEach(() => {
    pendingTsNavigation.set(null);
    setActiveTab(TAB_NAMES.DASHBOARD);
});

describe('gotoTimestamps', () => {
    it('sets the pending nav to the reciter + parsed verse and switches tabs', () => {
        gotoTimestamps('reciter-x', '2:45');
        expect(get(pendingTsNavigation)).toEqual({
            surah: 2,
            ayah: 45,
            autoplay: true,
            slug: 'reciter-x',
        });
        expect(get(activeTab)).toBe(TAB_NAMES.TIMESTAMPS);
    });

    it('is a no-op for an unparseable verse key', () => {
        setActiveTab(TAB_NAMES.DASHBOARD);
        gotoTimestamps('reciter-x', 'not-a-verse');
        expect(get(pendingTsNavigation)).toBeNull();
        expect(get(activeTab)).toBe(TAB_NAMES.DASHBOARD);
    });

    it('is a no-op for an empty slug', () => {
        gotoTimestamps('', '2:45');
        expect(get(pendingTsNavigation)).toBeNull();
    });
});
