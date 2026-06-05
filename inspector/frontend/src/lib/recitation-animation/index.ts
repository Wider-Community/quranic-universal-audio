/**
 * Recitation-animation feature — shared, surface-agnostic.
 *
 * Public surface: the collapsible section + line animation, the ayah
 * filmstrip, the chapter-words assembly, and the tunable config. Wired
 * into the dashboard now; designed for the timestamps tab to re-adopt
 * later (same footer + section). No tab-store coupling lives here.
 */

export { default as RecitationSection } from './RecitationSection.svelte';
export { default as LineAnimation } from './LineAnimation.svelte';
export { default as AyahFilmstrip } from './AyahFilmstrip.svelte';
export { default as ControlIcon } from './ControlIcon.svelte';

export {
    buildChapterRecitation,
    ayahUnitRanges,
    type AssembledVerse,
} from './chapter-words';
export {
    DEFAULT_RECITATION_CONFIG,
    cssVarText,
    type FilmstripMotion,
    type Granularity,
    type RecitationAnimConfig,
} from './config';
export {
    buildSortedIntervals,
    findActiveAt,
    type ActiveHit,
    type SortedInterval,
} from './recitation-active';
export {
    buildFilmstripModel,
    type FilmstripModel,
    type VerseCell,
    type WordFrac,
    type WordWeighting,
} from './filmstrip-model';
export type {
    AnimUnit,
    AyahBoundary,
    ChapterRecitation,
} from './types';
