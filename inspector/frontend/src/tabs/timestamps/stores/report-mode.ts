/**
 * Timestamps "report mode" — the in-grid contribution state machine.
 *
 * Entered from the footer Report drop-up for `timing` / `tajweed`: the waveform
 * is replaced by a control strip and the analysis grid becomes the click
 * surface. Annotations STAGE here (keyed by cell) and persist as a batch on
 * Submit; Cancel discards. The caller's own open reports of the active category
 * are seeded on entry so they show as editable flags.
 *
 * - `timing` forces letters-only (snapshots + restores the display toggles) and
 *   loops the selected cell (the loop is driven by `loopTarget`, set by the
 *   grid click). Each flagged cell is its own row; rows group by word at submit.
 * - `tajweed` keeps the current rows; the wrong/missing subtype toggle flips the
 *   spotlight (UnifiedDisplay reads `reportMode`). Each flagged cell is its own
 *   report. wrong_rule carries the picked internal rule tag(s).
 */
import { derived, get, writable } from 'svelte/store';

import { exitLoop } from '../../../lib/playback/loop';
import type { TsReportTarget } from '../../../lib/types/generated/schemas';
import { type CellKey, targetCellKey } from '../utils/report-target';
import { showLetters, showPhonemes } from './display';
import { currentVerseReports } from './ts-reports';

export type TimingSubtype = 'too_long' | 'too_short' | 'other';
export type TajweedSubtype = 'wrong_rule' | 'missing_rule';

export type ReportMode =
    | { kind: 'inactive' }
    | { kind: 'timing' }
    | { kind: 'tajweed'; subtype: TajweedSubtype };

export const reportMode = writable<ReportMode>({ kind: 'inactive' });
export const reportModeActive = derived(reportMode, (m) => m.kind !== 'inactive');

export interface StagedTiming {
    kind: 'timing';
    cellKey: CellKey;
    target: TsReportTarget;
    wordIndex: number;
    subtype: TimingSubtype | null;
    comment: string;
    /** Set when seeded from the caller's own existing report (→ delete on remove). */
    originalId?: number;
}
export interface StagedTajweed {
    kind: 'tajweed';
    cellKey: CellKey;
    target: TsReportTarget;
    subtype: TajweedSubtype;
    /** Internal rule tag ids present on the cell (the picker's options). */
    ruleOptions: string[];
    selectedRuleTags: string[];
    comment: string;
    originalId?: number;
}
export type StagedAnnotation = StagedTiming | StagedTajweed;

export const staged = writable<Map<CellKey, StagedAnnotation>>(new Map());
export const focusedCellKey = writable<CellKey | null>(null);
export const reportContext = writable<{ slug: string; verseKey: string } | null>(null);

function mutate(fn: (m: Map<CellKey, StagedAnnotation>) => void): void {
    staged.update((prev) => {
        const m = new Map(prev);
        fn(m);
        return m;
    });
}

export function upsertStaged(a: StagedAnnotation): void {
    mutate((m) => m.set(a.cellKey, a));
}

export function removeStaged(key: CellKey): void {
    mutate((m) => m.delete(key));
    focusedCellKey.update((f) => (f === key ? null : f));
}

export function clearStaged(): void {
    staged.set(new Map());
}

let displaySnapshot: { letters: boolean; phonemes: boolean } | null = null;

function seedOwnFlags(category: 'timing' | 'tajweed'): void {
    const m = new Map<CellKey, StagedAnnotation>();
    for (const r of get(currentVerseReports)) {
        if (!r.mine || r.status !== 'open' || r.category !== category) continue;
        const key = targetCellKey(r.target);
        if (category === 'timing') {
            m.set(key, {
                kind: 'timing',
                cellKey: key,
                target: r.target,
                wordIndex: r.target.word_index ?? -1,
                subtype: (r.subtype as TimingSubtype | null) ?? null,
                comment: r.comment ?? '',
                originalId: r.id,
            });
        } else {
            const tags = r.selected_rule_tags ?? [];
            m.set(key, {
                kind: 'tajweed',
                cellKey: key,
                target: r.target,
                subtype: (r.subtype as TajweedSubtype) ?? 'wrong_rule',
                ruleOptions: tags,
                selectedRuleTags: tags,
                comment: r.comment ?? '',
                originalId: r.id,
            });
        }
    }
    staged.set(m);
}

export function enterTiming(slug: string, verseKey: string): void {
    displaySnapshot = { letters: get(showLetters), phonemes: get(showPhonemes) };
    showLetters.set(true);
    showPhonemes.set(false);
    reportContext.set({ slug, verseKey });
    focusedCellKey.set(null);
    seedOwnFlags('timing');
    reportMode.set({ kind: 'timing' });
}

export function enterTajweed(slug: string, verseKey: string, subtype: TajweedSubtype): void {
    displaySnapshot = null; // tajweed keeps whatever rows are on
    reportContext.set({ slug, verseKey });
    focusedCellKey.set(null);
    seedOwnFlags('tajweed');
    reportMode.set({ kind: 'tajweed', subtype });
}

export function setTajweedSubtype(subtype: TajweedSubtype): void {
    reportMode.update((m) => (m.kind === 'tajweed' ? { kind: 'tajweed', subtype } : m));
}

export function exitReportMode(): void {
    if (displaySnapshot) {
        showLetters.set(displaySnapshot.letters);
        showPhonemes.set(displaySnapshot.phonemes);
        displaySnapshot = null;
    }
    exitLoop();
    clearStaged();
    focusedCellKey.set(null);
    reportContext.set(null);
    reportMode.set({ kind: 'inactive' });
}
