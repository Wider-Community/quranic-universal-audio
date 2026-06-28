/**
 * Timestamps "report mode" — the in-grid contribution state machine.
 *
 * Entered from the footer Report drop-up for `timing` / `tajweed` / `phonemes`:
 * the waveform is replaced by a control strip and the analysis grid becomes the
 * click surface. Annotations STAGE here (keyed by cell) and persist as a batch on
 * Submit; Cancel discards. The caller's own open reports of the active category
 * are seeded on entry so they show as editable flags.
 *
 * - `timing` loops the selected cell (the loop is driven by `loopTarget`, set by
 *   the grid click). Each flagged cell is its own row; rows group by word at submit.
 *   Forces letters-only (snapshot + restore).
 * - `tajweed` additionally forces every legend colour on (snapshot + restore) so
 *   all rules are visible to target, and does NOT loop the cell — playback keeps
 *   its play/pause state and the whole-verse loop. The subtype (`wrong_rule` /
 *   `missing_rule`) is fixed at entry. Each flagged cell is its own report, unique
 *   per cell PER subtype; wrong_rule carries the picked internal rule tag(s).
 *   Forces letters-only.
 * - `phonemes` forces the phoneme row ON while leaving the letters row at the
 *   user's current setting (the inverse of timing/tajweed). Any number of phoneme
 *   cells are flagged, no comment, no per-cell control; rows group by word at
 *   submit. Cross-word merger (bridge) phonemes carry `phoneme_flat_index = -1`.
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
/** Silence subtypes — a wrong-boundary pause (dual-axis, like timing), a pause
 *  that shouldn't exist (should be waṣl), and a missing pause. The latter two are
 *  binary (select-to-flag, no controls). */
export type SilenceSubtype = 'pause_boundary' | 'pause_wasl' | 'pause_missed';

export type ReportMode =
    | { kind: 'inactive' }
    | { kind: 'timing' }
    | { kind: 'tajweed'; subtype: TajweedSubtype }
    | { kind: 'phonemes' }
    | { kind: 'silence'; subtype: SilenceSubtype };

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
export interface StagedPhoneme {
    kind: 'phonemes';
    cellKey: CellKey;
    target: TsReportTarget;
    wordIndex: number;
    /** The phone glyph, for the compact chip label (may be '' if unknown). */
    glyph: string;
    /** Set when seeded from the caller's own existing report (→ delete on remove). */
    originalId?: number;
}
export interface StagedSilence {
    kind: 'silence';
    cellKey: CellKey;
    target: TsReportTarget;
    /** The word before the flagged boundary (= the gap target's `word_index`). */
    gapWordIndex: number;
    subtype: SilenceSubtype;
    /** Boundary axes — `pause_boundary` only (≥1 set to be complete). The binary
     *  subtypes (`pause_wasl` / `pause_missed`) leave both null. */
    onset: TimingDir | null;
    offset: TimingDir | null;
    /** Set when seeded from the caller's own existing report (→ delete on remove). */
    originalId?: number;
}
export type StagedAnnotation = StagedTiming | StagedTajweed | StagedPhoneme | StagedSilence;

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
    if (a.kind === 'phonemes') {
        return true; // a flagged phoneme has no required fields — selection is the report
    }
    if (a.kind === 'silence') {
        // pause_boundary needs ≥1 axis; the binary subtypes are complete on select.
        return a.subtype === 'pause_boundary' ? a.onset !== null || a.offset !== null : true;
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

function seedOwnFlags(
    category: 'timing' | 'tajweed' | 'phonemes' | 'silence',
    subtype?: TajweedSubtype | SilenceSubtype,
): void {
    const m = new Map<CellKey, StagedAnnotation>();
    for (const r of get(currentVerseReports)) {
        if (!r.mine || r.status !== 'open' || r.category !== category) continue;
        // A tajweed/silence session is single-subtype — only seed the matching one.
        if ((category === 'tajweed' || category === 'silence') && subtype && r.subtype !== subtype) {
            continue;
        }
        const key = targetCellKey(r.target);
        if (category === 'silence') {
            m.set(key, {
                kind: 'silence',
                cellKey: key,
                target: r.target,
                gapWordIndex: r.target.word_index ?? -1,
                subtype: (r.subtype as SilenceSubtype) ?? 'pause_missed',
                onset: (r.onset as TimingDir | null) ?? null,
                offset: (r.offset as TimingDir | null) ?? null,
                originalId: r.id,
            });
        } else if (category === 'timing') {
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
        } else if (category === 'phonemes') {
            m.set(key, {
                kind: 'phonemes',
                cellKey: key,
                target: r.target,
                wordIndex: r.target.word_index ?? -1,
                glyph: r.snapshot?.chars ?? '',
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

export function enterPhonemes(slug: string, verseKey: string): void {
    dashPort.pause();
    // Force the phoneme row ON (the click surface) but leave letters at the user's
    // current setting — the inverse of timing/tajweed. Restored on exit.
    displaySnapshot = { letters: get(showLetters), phonemes: get(showPhonemes) };
    showPhonemes.set(true);
    reportContext.set({ slug, verseKey });
    focusedCellKey.set(null);
    seedOwnFlags('phonemes');
    reportMode.set({ kind: 'phonemes' });
}

export function enterSilence(slug: string, verseKey: string, subtype: SilenceSubtype): void {
    dashPort.pause();
    // Letters-only: the click surface is the inter-word pause tiles / missed slots,
    // not phonemes. Force letters on + phonemes off (restored on exit) so the grid
    // stays clean. The toggles are disabled in report mode (reportModeActive).
    displaySnapshot = { letters: get(showLetters), phonemes: get(showPhonemes) };
    showLetters.set(true);
    showPhonemes.set(false);
    reportContext.set({ slug, verseKey });
    focusedCellKey.set(null);
    seedOwnFlags('silence', subtype);
    reportMode.set({ kind: 'silence', subtype });
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
