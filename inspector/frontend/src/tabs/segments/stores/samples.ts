/**
 * Segments tab — maintainer samples sub-tab state.
 *
 * A sample is addressed by the slug `sample--<id>`; the Segments view treats
 * it like any reciter slug. These stores tell the tab when it is looking at a
 * sample (no claim/lifecycle row, autosave always on, chips instead of the
 * validation accordion) and hold the samples list for the sub-tab.
 */

import { derived, writable } from 'svelte/store';

import { can } from '../../../lib/stores/capabilities';
import type { CurrentUser } from '../../../lib/stores/current-user';
import type { EditingMode } from '../../../lib/stores/editing-mode';
import type { SampleRow } from '../../../lib/types/generated/schemas';
import { selectedReciter } from './chapter';

export const SAMPLE_SLUG_PREFIX = 'sample--';
export const SAMPLES_CAPABILITY = 'samples.manage';

export type SegmentsSubTab = 'editor' | 'samples';

export function isSampleSlug(slug: string | null | undefined): boolean {
    return !!slug && slug.startsWith(SAMPLE_SLUG_PREFIX);
}

export const segmentsSubTab = writable<SegmentsSubTab>('editor');

export const samples = writable<SampleRow[]>([]);

export const canManageSamples = can(SAMPLES_CAPABILITY);

export const isSampleMode = derived(selectedReciter, (slug) => isSampleSlug(slug));

export const activeSample = derived(
    [selectedReciter, samples],
    ([slug, list]) => list.find((s) => s.slug === slug) ?? null,
);

/** Sub-tabs the current user may see; the samples tab exists only for
 *  `samples.manage` holders. */
export function visibleSubTabs(canManage: boolean): SegmentsSubTab[] {
    return canManage ? ['editor', 'samples'] : ['editor'];
}

/** Edit gate for a sample: no claim row to consult — any signed-in
 *  `samples.manage` holder edits, owners as owners. */
export function sampleEditingMode(user: CurrentUser | null): EditingMode {
    if (user === null || user.hf_user_id === null) {
        return { kind: 'view', viewReason: 'unauthenticated' };
    }
    if (!(user.capabilities ?? []).includes(SAMPLES_CAPABILITY)) {
        return { kind: 'view', viewReason: 'not-available' };
    }
    return { kind: user.role === 'owner' ? 'owner' : 'maintainer' };
}
