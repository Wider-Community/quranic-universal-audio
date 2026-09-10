import { writable } from 'svelte/store';

import { SCROLL_ANIM_DEFAULT, type ScrollAnimMode } from '../../../lib/utils/constants';

export interface SegConfig {
    validationCategories: string[] | null;
    /** `"<surah>:<ayah>"` of verses that OPEN with the disconnected letters. */
    muqattaatVerses: Set<string> | null;
    /**
     * `"<surah>:<ayah>:<word>"` of the openings themselves. Not derivable from
     * `muqattaatVerses` — Warsh merges two Hafs openings into one verse, so
     * that verse carries a muqattaat at word 1 AND at word 2.
     */
    muqattaatWords: Set<string> | null;
    qalqalaLetters: Set<string> | null;
    standaloneRefs: Set<string> | null;
    standaloneWords: Set<string> | null;
    lcDefaultThreshold: number;
    accordionContext: Record<string, string> | null;
    trimPadLeft: number;
    trimPadRight: number;
    trimDimAlpha: number;
    scrollAnimMode: ScrollAnimMode;
}

const _defaults: SegConfig = {
    validationCategories: null,
    muqattaatVerses: null,
    muqattaatWords: null,
    qalqalaLetters: null,
    standaloneRefs: null,
    standaloneWords: null,
    lcDefaultThreshold: 80,
    accordionContext: null,
    trimPadLeft: 500,
    trimPadRight: 500,
    trimDimAlpha: 0.45,
    scrollAnimMode: SCROLL_ANIM_DEFAULT,
};

export const segConfig = writable<SegConfig>({ ..._defaults });

/** Back to the neutral defaults — every edition-specific vocabulary empty. */
export function resetSegConfig(): void {
    segConfig.set({ ..._defaults });
}
