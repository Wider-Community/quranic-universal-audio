import { writable } from 'svelte/store';

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
};

export const segConfig = writable<SegConfig>({ ..._defaults });
