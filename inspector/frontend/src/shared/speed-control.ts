/**
 * Shared playback speed cycling utility.
 */

/**
 * Cycle an audio speed <select> up or down, mirror to the playback element,
 * and persist the new value to localStorage. Used by both the segments and
 * timestamps tabs via their keyboard shortcuts (`.` speeds up, `,` slows down).
 */
export function cycleSpeed(
    selectEl: HTMLSelectElement,
    audioEl: HTMLAudioElement,
    direction: 'up' | 'down',
    lsKey: string,
): void {
    const opts = Array.from(selectEl.options).map(o => parseFloat(o.value));
    const curRate = parseFloat(selectEl.value);
    const curIdx = opts.findIndex(s => Math.abs(s - curRate) < 0.01);
    const idx = curIdx === -1 ? opts.indexOf(1) : curIdx;
    const newIdx = direction === 'up'
        ? Math.min(idx + 1, opts.length - 1)
        : Math.max(idx - 1, 0);
    const newVal = opts[newIdx];
    if (newVal === undefined) return;
    selectEl.value = String(newVal);
    audioEl.playbackRate = newVal;
    localStorage.setItem(lsKey, selectEl.value);
}
