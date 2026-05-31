/**
 * Per-frame highlight sweep — extracted from the timestamps-tab
 * `AnimationDisplay.updateHighlights()`, with the store reads + scroll lifted
 * out so it's surface-agnostic. The caller passes the current time (seconds)
 * and the previously-active index; the function applies `active` / `reached`
 * classes + reveal opacity and returns the new active index.
 */

import { applyClass, applyRevealOpacity, type HighlightCache } from './index-cache';

export interface SweepOptions {
    /**
     * `class` (line animation): reveal is purely class-driven (`active` /
     * `reached` / neither), so the CSS config vars (`--ra-reached-opacity`,
     * `--ra-unreached-opacity`) own every state and backward seeks reconcile
     * cleanly. `opacity` (default, timestamps-tab faithful): drives a per-item
     * inline-opacity reveal via {@link applyRevealOpacity}.
     */
    mode?: 'class' | 'opacity';
}

/**
 * Resolve the active item for `timeSec`, apply highlight classes/opacity, and
 * return the new active index (or `lastIdx` unchanged when nothing moved).
 *
 * Uses the same fast-path tick as the original: check the current item, then
 * the next, then a full scan. Beyond the last item's start, the tail stays
 * active (so trailing silence keeps the final word lit).
 */
export function sweepHighlights(
    cache: HighlightCache,
    timeSec: number,
    lastIdx: number,
    opts: SweepOptions = {},
): number {
    const items = cache.items;
    if (items.length === 0) return lastIdx;

    if (opts.mode === 'class') {
        // Purely time-based per item (the page is one line, O(n) is cheap):
        //   active  = the unit currently being recited (start ≤ t < end)
        //   reached = a unit already finished (t ≥ end)
        // This makes silence GAPS clear the active highlight (the just-finished
        // word goes `reached`, nothing is active), and makes BACKWARD jumps
        // (look-back / repeats) travel the highlight back — units after the new
        // time lose `reached` and revert to unreached. No lastIdx fast-path.
        let active = -1;
        for (let i = 0; i < items.length; i++) {
            const it = items[i]!;
            const isActive = timeSec >= it.start && timeSec < it.end;
            applyClass(cache, i, 'active', isActive);
            applyClass(cache, i, 'reached', !isActive && timeSec >= it.end);
            if (isActive) active = i;
        }
        return active;
    }

    let newIdx = -1;
    const lastItem = lastIdx >= 0 && lastIdx < items.length ? items[lastIdx] : undefined;
    const nextItem = lastIdx + 1 < items.length ? items[lastIdx + 1] : undefined;
    if (lastItem && timeSec >= lastItem.start && timeSec < lastItem.end) {
        newIdx = lastIdx;
    } else if (nextItem && timeSec >= nextItem.start && timeSec < nextItem.end) {
        newIdx = lastIdx + 1;
    } else {
        for (let i = 0; i < items.length; i++) {
            const it = items[i];
            if (!it) continue;
            if (timeSec >= it.start && timeSec < it.end) {
                newIdx = i;
                break;
            }
        }
        const tail = items[items.length - 1];
        if (newIdx === -1 && tail && timeSec >= tail.start) {
            newIdx = items.length - 1;
        }
    }

    if (newIdx === lastIdx) return newIdx;

    if (lastIdx >= 0 && lastIdx < items.length) {
        applyClass(cache, lastIdx, 'active', false);
        applyClass(cache, lastIdx, 'reached', true);
    }
    if (newIdx >= 0) {
        applyClass(cache, newIdx, 'active', true);
        if (lastIdx === -1) {
            for (let j = 0; j < newIdx; j++) applyClass(cache, j, 'reached', true);
        }
        applyRevealOpacity(cache, newIdx, lastIdx);
    }
    return newIdx;
}

/**
 * Index of the unit whose [start, end) contains `timeSec` (seconds), or the
 * tail unit once time passes the last start, or -1 before the first unit.
 * Used for paging decisions independent of the reveal cache (works the same
 * for word + char granularity since paging is always word-keyed upstream).
 */
export function activeIndexAt(
    units: { start: number; end: number }[],
    timeSec: number,
    hint: number,
): number {
    const n = units.length;
    if (n === 0) return -1;
    const cur = hint >= 0 && hint < n ? units[hint] : undefined;
    if (cur && timeSec >= cur.start && timeSec < cur.end) return hint;
    const nxt = hint + 1 < n ? units[hint + 1] : undefined;
    if (nxt && timeSec >= nxt.start && timeSec < nxt.end) return hint + 1;
    for (let i = 0; i < n; i++) {
        const u = units[i]!;
        if (timeSec >= u.start && timeSec < u.end) return i;
    }
    const tail = units[n - 1]!;
    if (timeSec >= tail.start) return n - 1;
    return -1;
}
