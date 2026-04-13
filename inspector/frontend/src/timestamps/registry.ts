/**
 * Timestamps-tab cross-module registry.
 *
 * The timestamps tab has a circular-dependency shape: `index.ts` owns some
 * pure lookups (`getSegRelTime`, `getSegDuration`) and some tab-level flows
 * (`jumpToTsVerse`, `loadRandomTimestamp`), while `playback.ts` owns
 * `updateDisplay` + `navigateVerse`. Every sibling (animation, waveform,
 * validation, keyboard, unified-display) needs to call a subset of these,
 * and `index.ts` / `playback.ts` in turn depend on the siblings. Letting
 * the siblings import from `./index` or `./playback` creates 5 observable
 * cycles that were previously documented with `// NOTE: circular
 * dependency` comments.
 *
 * Following the `segments/event-delegation.ts` pattern, the siblings now
 * import typed dispatch wrappers from this registry. At `DOMContentLoaded`
 * time, `index.ts` calls the setters once with the real function
 * references. Before registration the dispatch wrappers throw — this is a
 * strictly stronger invariant than the pre-existing "runtime only" comment,
 * because every call site goes through a single point of enforcement.
 *
 * Two setters (not six) reflect the two source modules. Grouping by
 * producer keeps `index.ts` wiring terse.
 */

// ---------------------------------------------------------------------------
// Function signatures
// ---------------------------------------------------------------------------

/** `getSegRelTime()` — `dom.audio.currentTime - state.tsSegOffset`. */
export type GetSegRelTimeFn = () => number;

/** `getSegDuration()` — `(state.tsSegEnd - state.tsSegOffset) || audio.duration || 1`. */
export type GetSegDurationFn = () => number;

/** `jumpToTsVerse(verseKey)` — set chapter select, wait for chapter load,
 *  pick verse option, refresh nav. */
export type JumpToTsVerseFn = (verseKey: string) => Promise<void>;

/** `loadRandomTimestamp(reciter?)` — fetch a random timestamp entry and
 *  render it. */
export type LoadRandomTimestampFn = (reciter?: string | null) => Promise<void>;

/** `onTsVerseChange()` — called when the segment select changes (also by
 *  `navigateVerse` + `jumpToTsVerse`). */
export type OnTsVerseChangeFn = () => Promise<void>;

/** `updateDisplay()` — per-frame (and on-seek) view refresh. */
export type UpdateDisplayFn = () => void;

/** `navigateVerse(delta)` — move segment select by `delta` positions. */
export type NavigateVerseFn = (delta: number) => void;

// ---------------------------------------------------------------------------
// Registry shapes — grouped by producer module
// ---------------------------------------------------------------------------

/** Functions owned by `timestamps/index.ts`. */
export interface TsIndexRegistry {
    getSegRelTime: GetSegRelTimeFn;
    getSegDuration: GetSegDurationFn;
    jumpToTsVerse: JumpToTsVerseFn;
    loadRandomTimestamp: LoadRandomTimestampFn;
    onTsVerseChange: OnTsVerseChangeFn;
}

/** Functions owned by `timestamps/playback.ts`. */
export interface TsPlaybackRegistry {
    updateDisplay: UpdateDisplayFn;
    navigateVerse: NavigateVerseFn;
}

// ---------------------------------------------------------------------------
// Registration — called exactly once from timestamps/index.ts during DOMContentLoaded.
// ---------------------------------------------------------------------------

let _indexFns: TsIndexRegistry | null = null;
let _playbackFns: TsPlaybackRegistry | null = null;

export function registerTsIndexFns(fns: TsIndexRegistry): void {
    _indexFns = fns;
}

export function registerTsPlaybackFns(fns: TsPlaybackRegistry): void {
    _playbackFns = fns;
}

// ---------------------------------------------------------------------------
// Dispatch wrappers — sibling modules import these instead of `./index` or
// `./playback`. Each wrapper throws if called before registration, which
// shouldn't happen in practice (all call sites are driven by DOM events
// that fire after DOMContentLoaded).
// ---------------------------------------------------------------------------

function _requireIndex(): TsIndexRegistry {
    if (!_indexFns) throw new Error('timestamps registry: index fns not registered');
    return _indexFns;
}

function _requirePlayback(): TsPlaybackRegistry {
    if (!_playbackFns) throw new Error('timestamps registry: playback fns not registered');
    return _playbackFns;
}

export function getSegRelTime(): number {
    return _requireIndex().getSegRelTime();
}

export function getSegDuration(): number {
    return _requireIndex().getSegDuration();
}

export function jumpToTsVerse(verseKey: string): Promise<void> {
    return _requireIndex().jumpToTsVerse(verseKey);
}

export function loadRandomTimestamp(reciter?: string | null): Promise<void> {
    return _requireIndex().loadRandomTimestamp(reciter);
}

export function onTsVerseChange(): Promise<void> {
    return _requireIndex().onTsVerseChange();
}

export function updateDisplay(): void {
    _requirePlayback().updateDisplay();
}

export function navigateVerse(delta: number): void {
    _requirePlayback().navigateVerse(delta);
}
