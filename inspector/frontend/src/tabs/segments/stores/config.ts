import { writable } from 'svelte/store';

import { SCROLL_ANIM_DEFAULT, type ScrollAnimMode } from '../../../lib/utils/constants';

export interface SegConfig {
    validationCategories: string[] | null;
    muqattaatVerses: Set<string> | null;
    qalqalaLetters: Set<string> | null;
    standaloneRefs: Set<string> | null;
    standaloneWords: Set<string> | null;
    lcDefaultThreshold: number;
    showBoundaryPhonemes: boolean;
    accordionContext: Record<string, string> | null;
    trimPadLeft: number;
    trimPadRight: number;
    trimDimAlpha: number;
    scrollAnimMode: ScrollAnimMode;
}

const _defaults: SegConfig = {
    validationCategories: null,
    muqattaatVerses: null,
    qalqalaLetters: null,
    standaloneRefs: null,
    standaloneWords: null,
    lcDefaultThreshold: 80,
    showBoundaryPhonemes: true,
    accordionContext: null,
    trimPadLeft: 500,
    trimPadRight: 500,
    trimDimAlpha: 0.45,
    scrollAnimMode: SCROLL_ANIM_DEFAULT,
};

export const segConfig = writable<SegConfig>({ ..._defaults });
