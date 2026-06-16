/**
 * Deep-link into the Timestamps tab at a specific reciter + verse.
 *
 * Used by the flag-notification redirect in the rail. Mirrors `gotoSegments`:
 * it sets the cross-tab `pendingTsNavigation` channel (with the target `slug`,
 * which `TimestampsTab` routes through `jumpToTarget`) and switches the active
 * tab. The TS tab is always mounted, so its manifest is ready by the time the
 * pending nav is consumed.
 */

import { pendingTsNavigation } from '../stores/navigation';
import { setActiveTab } from './active-tab';
import { TAB_NAMES } from './constants';

export function gotoTimestamps(slug: string, verseKey: string): void {
    if (!slug || !verseKey) return;
    const [s, a] = verseKey.split(':');
    const surah = Number(s);
    const ayah = Number(a);
    if (!Number.isFinite(surah) || !Number.isFinite(ayah)) return;
    pendingTsNavigation.set({ surah, ayah, autoplay: true, slug });
    setActiveTab(TAB_NAMES.TIMESTAMPS);
}
