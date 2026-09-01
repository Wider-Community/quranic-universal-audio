import { describe, expect, it } from 'vitest';

import type { CurrentUser } from '../../../../lib/stores/current-user';
import { isSampleSlug, sampleEditingMode, visibleSubTabs } from '../../stores/samples';

function user(overrides: Partial<CurrentUser>): CurrentUser {
    return {
        login: 'u',
        hf_user_id: 'u1',
        role: 'maintainer',
        capabilities: ['samples.manage'],
        ...overrides,
    } as CurrentUser;
}

describe('samples sub-tab gating', () => {
    it('shows the samples tab only to samples.manage holders', () => {
        expect(visibleSubTabs(true)).toEqual(['editor', 'samples']);
        expect(visibleSubTabs(false)).toEqual(['editor']);
    });

    it('recognises the sample slug namespace', () => {
        expect(isSampleSlug('sample--0192')).toBe(true);
        expect(isSampleSlug('husary')).toBe(false);
        expect(isSampleSlug('')).toBe(false);
        expect(isSampleSlug(null)).toBe(false);
    });

    it('resolves the edit gate from the capability alone', () => {
        expect(sampleEditingMode(null)).toEqual({ kind: 'view', viewReason: 'unauthenticated' });
        expect(sampleEditingMode(user({ hf_user_id: null }))).toEqual({
            kind: 'view',
            viewReason: 'unauthenticated',
        });
        expect(sampleEditingMode(user({ capabilities: [] }))).toEqual({
            kind: 'view',
            viewReason: 'not-available',
        });
        expect(sampleEditingMode(user({}))).toEqual({ kind: 'maintainer' });
        expect(sampleEditingMode(user({ role: 'owner' }))).toEqual({ kind: 'owner' });
    });
});
