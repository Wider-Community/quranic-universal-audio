/**
 * Automatic word realign for samples. Any finalised op that can invalidate a
 * segment's word timings (trim / split / merge / reference edit / auto-fix)
 * queues a realign for each affected segment whose timings no longer cover
 * its ref. A REALIGN_DELAY_MS debounce absorbs the follow-up edits a split or
 * merge usually gets; another op on the same segment restarts its countdown.
 * When due, the segment is re-checked (still present, still uncovered, no
 * repetition wrap), the timing Space is asked, and the result is committed
 * as a `set_word_timings` op. `realignStatus` drives the row chip.
 */

import { get, writable } from 'svelte/store';

import { realignSampleSegment, SampleApiError } from '../../../../lib/api/samples';
import { pushToast } from '../../../../lib/stores/toast';
import type { EditOp, Segment } from '../../../../lib/types/view-models';
import { quranRefs } from '../../../../lib/refs/quran-refs';
import { getChapterSegments } from '../../stores/chapter';
import { onOpFinalized } from '../../stores/dirty';
import { activeSample, sampleHasWordTimings } from '../../stores/samples';
import { setWordTimingsOnSegment } from '../edit/setWordTimings';
import type { VerseWordCounts } from '../data/references';
import { needsRealign } from './word-timings';

export const REALIGN_DELAY_MS = 10_000;

const INVALIDATING_OPS: ReadonlySet<string> = new Set([
    'trim_segment', 'split_segment', 'merge_segments', 'edit_reference', 'auto_fix_missing_word',
]);

export type RealignPhase = { phase: 'countdown'; seconds: number } | { phase: 'running' };

/** Per-`segment_uid` realign state for the row chip. */
export const realignStatus = writable<Record<string, RealignPhase>>({});

interface Pending { chapter: number; dueAt: number; timer: ReturnType<typeof setTimeout> }
const _pending = new Map<string, Pending>();
let _ticker: ReturnType<typeof setInterval> | null = null;

function _setStatus(uid: string, phase: RealignPhase | null): void {
    realignStatus.update((cur) => {
        const next = { ...cur };
        if (phase) next[uid] = phase;
        else delete next[uid];
        return next;
    });
}

function _tick(): void {
    const now = Date.now();
    for (const [uid, p] of _pending) {
        _setStatus(uid, { phase: 'countdown', seconds: Math.max(1, Math.ceil((p.dueAt - now) / 1000)) });
    }
    if (_pending.size === 0 && _ticker) {
        clearInterval(_ticker);
        _ticker = null;
    }
}

function _findSeg(chapter: number, uid: string): Segment | undefined {
    return getChapterSegments(chapter).find((s) => s.segment_uid === uid);
}

function _vwc(): VerseWordCounts | undefined {
    return get(quranRefs)?.verse_word_counts as VerseWordCounts | undefined;
}

/** Queue (or re-queue) a realign for `uid`; the countdown restarts. */
export function scheduleRealign(chapter: number, uid: string): void {
    const prev = _pending.get(uid);
    if (prev) clearTimeout(prev.timer);
    const dueAt = Date.now() + REALIGN_DELAY_MS;
    const timer = setTimeout(() => void _run(chapter, uid), REALIGN_DELAY_MS);
    _pending.set(uid, { chapter, dueAt, timer });
    _setStatus(uid, { phase: 'countdown', seconds: REALIGN_DELAY_MS / 1000 });
    if (!_ticker) _ticker = setInterval(_tick, 1000);
}

export function cancelRealign(uid: string): void {
    const p = _pending.get(uid);
    if (p) clearTimeout(p.timer);
    _pending.delete(uid);
    _setStatus(uid, null);
}

async function _run(chapter: number, uid: string): Promise<void> {
    _pending.delete(uid);
    const sample = get(activeSample);
    const seg = _findSeg(chapter, uid);
    if (!sample || !seg || seg.wrap_word_ranges || !needsRealign(seg.matched_ref, seg.word_timings, _vwc())) {
        _setStatus(uid, null);
        return;
    }
    _setStatus(uid, { phase: 'running' });
    try {
        const words = await realignSampleSegment(sample.id, {
            segment_uid: uid,
            matched_ref: seg.matched_ref,
            time_start: seg.time_start,
            time_end: seg.time_end,
        });
        const live = _findSeg(chapter, uid);
        // A newer edit re-queued this segment while the Space was busy: its
        // own run will commit fresher timings.
        if (live && !_pending.has(uid)) setWordTimingsOnSegment(live, words);
    } catch (e) {
        pushToast({ kind: 'error', text: e instanceof SampleApiError ? e.message : String(e) });
    } finally {
        if (!_pending.has(uid)) _setStatus(uid, null);
    }
}

function _onOp(chapter: number, op: EditOp): void {
    if (!INVALIDATING_OPS.has(op.op_type) || !get(sampleHasWordTimings)) return;
    const vwc = _vwc();
    for (const snap of op.targets_after ?? []) {
        const uid = typeof snap.segment_uid === 'string' ? snap.segment_uid : null;
        const seg = uid ? _findSeg(chapter, uid) : undefined;
        if (!seg || seg.wrap_word_ranges) continue;
        if (needsRealign(seg.matched_ref, seg.word_timings, vwc)) scheduleRealign(chapter, uid!);
    }
}

/** Start observing finalised ops; returns the stop function (also clears
 *  every pending countdown). */
export function startAutoRealign(): () => void {
    const off = onOpFinalized(_onOp);
    return () => {
        off();
        for (const uid of [..._pending.keys()]) cancelRealign(uid);
    };
}
