/**
 * Timestamps "report mode" — the in-grid contribution state machine.
 *
 * Entered from the footer Report drop-up for `timing` / `tajweed`: the waveform
 * is replaced by a control strip and the analysis grid becomes the click
 * surface. Annotations STAGE here (keyed by cell) and persist as a batch on
 * Submit; Cancel discards. The caller's own open reports of the active category
 * are seeded on entry so they show as editable flags.
 *
 * Both modes force letters-only (phonemes are never a targetable rule/timing
 * surface) and snapshot + restore the display toggles on exit.
 *
 * - `timing` loops the selected cell (the loop is driven by `loopTarget`, set by
 *   the grid click). Each flagged cell is its own row; rows group by word at submit.
 * - `tajweed` additionally forces every legend colour on (snapshot + restore) so
 *   all rules are visible to target, and does NOT loop the cell — playback keeps
 *   its play/pause state and the whole-verse loop. The subtype (`wrong_rule` /
 *   `missing_rule`) is fixed at entry. Each flagged cell is its own report, unique
 *   per cell PER subtype; wrong_rule carries the picked internal rule tag(s).
 *
 * Switching focus to a new cell auto-discards the previously focused annotation
 * when it is still incomplete (missing a required subtype / rule pick / comment),
 * so only complete items survive to Submit.
 */
import { derived, get, writable } from 'svelte/store';

import { dashPort } from '../../../lib/playback/dash-port';
import { exitLoop } from '../../../lib/playback/loop';
import type { TsReportTarget } from '../../../lib/types/generated/schemas';
import { type CellKey, targetCellKey, type TimingDir } from '../utils/report-target';
import { showLetters, showPhonemes } from './display';
import {
    forceAllTajweedEnabled,
    restoreTajweedSettings,
    type TajweedSettings,
} from './tajweed-settings';
import { currentVerseReports } from './ts-reports';

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
    /** Boundary axes — at least one must be set for the report to be complete.
     *  `null` on an axis = that boundary is fine. */
    onset: TimingDir | null;
    offset: TimingDir | null;
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

/** Whether a staged annotation has all its required fields — the bar for it to
 *  survive Submit (and not be auto-discarded when focus moves away). */
export function isStagedComplete(a: StagedAnnotation): boolean {
    if (a.kind === 'timing') {
        return a.onset !== null || a.offset !== null; // ≥1 boundary flagged; comment optional
    }
    const needsRule = a.subtype === 'wrong_rule' && a.ruleOptions.length > 0;
    if (needsRule && a.selectedRuleTags.length === 0) return false;
    return a.comment.trim().length > 0; // every tajweed report needs a comment
}

/** Move focus to `key`, auto-discarding the previously focused annotation when it
 *  is still incomplete (no hard block — abandoning an unfinished cell drops it). */
export function focusCell(key: CellKey | null): void {
    const prev = get(focusedCellKey);
    if (prev && prev !== key) {
        const a = get(staged).get(prev);
        if (a && !isStagedComplete(a)) removeStaged(prev);
    }
    focusedCellKey.set(key);
}

let displaySnapshot: { letters: boolean; phonemes: boolean } | null = null;
let tajweedSnapshot: TajweedSettings | null = null;

function seedOwnFlags(category: 'timing' | 'tajweed', subtype?: TajweedSubtype): void {
    const m = new Map<CellKey, StagedAnnotation>();
    for (const r of get(currentVerseReports)) {
        if (!r.mine || r.status !== 'open' || r.category !== category) continue;
        // A tajweed session is single-subtype — only seed the matching subtype.
        if (category === 'tajweed' && subtype && r.subtype !== subtype) continue;
        const key = targetCellKey(r.target);
        if (category === 'timing') {
            m.set(key, {
                kind: 'timing',
                cellKey: key,
                target: r.target,
                wordIndex: r.target.word_index ?? -1,
                onset: (r.onset as TimingDir | null) ?? null,
                offset: (r.offset as TimingDir | null) ?? null,
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
    // Pause so the focus verse can't auto-advance out from under the session.
    dashPort.pause();
    displaySnapshot = { letters: get(showLetters), phonemes: get(showPhonemes) };
    showLetters.set(true);
    showPhonemes.set(false);
    reportContext.set({ slug, verseKey });
    focusedCellKey.set(null);
    seedOwnFlags('timing');
    reportMode.set({ kind: 'timing' });
}

export function enterTajweed(slug: string, verseKey: string, subtype: TajweedSubtype): void {
    dashPort.pause();
    // Letters-only: phonemes never carry a targetable tajweed rule, so hide them
    // and force letters on (restored on exit) to keep the click surface clean.
    displaySnapshot = { letters: get(showLetters), phonemes: get(showPhonemes) };
    showLetters.set(true);
    showPhonemes.set(false);
    tajweedSnapshot = forceAllTajweedEnabled(); // every rule visible to target
    reportContext.set({ slug, verseKey });
    focusedCellKey.set(null);
    seedOwnFlags('tajweed', subtype);
    reportMode.set({ kind: 'tajweed', subtype });
}

export function exitReportMode(): void {
    if (displaySnapshot) {
        showLetters.set(displaySnapshot.letters);
        showPhonemes.set(displaySnapshot.phonemes);
        displaySnapshot = null;
    }
    if (tajweedSnapshot) {
        restoreTajweedSettings(tajweedSnapshot);
        tajweedSnapshot = null;
    }
    exitLoop();
    clearStaged();
    focusedCellKey.set(null);
    reportContext.set(null);
    reportMode.set({ kind: 'inactive' });
}
