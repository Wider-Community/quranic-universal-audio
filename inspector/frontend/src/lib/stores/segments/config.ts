import { writable } from 'svelte/store';

export interface SegConfig {
    validationCategories: string[] | null;
    muqattaatVerses: Set<string> | null;
    qalqalaLetters: Set<string> | null;
    standaloneRefs: Set<string> | null;
    standaloneWords: Set<string> | null;
    lcDefaultThreshold: number;
    showBoundaryPhonemes: boolean;
}

const _defaults: SegConfig = {
    validationCategories: null,
    muqattaatVerses: null,
    qalqalaLetters: null,
    standaloneRefs: null,
    standaloneWords: null,
    lcDefaultThreshold: 80,
    showBoundaryPhonemes: true,
};

export const segConfig = writable<SegConfig>({ ..._defaults });
