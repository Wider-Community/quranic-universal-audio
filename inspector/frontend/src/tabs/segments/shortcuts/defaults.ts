/**
 * Segments keyboard-shortcut catalogue — the single source of truth for every
 * key the Segments tab listens for, shared by the dispatch resolver
 * (utils/keyboard.ts) and the footer reference/edit popover (ShortcutsGuide).
 *
 * Each action carries the CONTEXT pool it lives in:
 *   - 'default'   — main-list browsing. Also active inside an open accordion
 *                   (the accordion pool extends, never replaces, default).
 *   - 'accordion' — only while a validation accordion is open; acts on the
 *                   focused (playing, non-context) card row.
 *   - 'edit'      — only while in trim / split edit mode; the stepper + cursor
 *                   keys that override seek/seek.
 *
 * A key TOKEN is `e.code` with an optional `Ctrl+` prefix (e.g. `KeyA`,
 * `Space`, `ArrowUp`, `Comma`, `Ctrl+KeyS`). Only `rebindable` actions can be
 * remapped by the user; structural keys (arrows in edit, Tab, Enter, Escape,
 * Ctrl+S) are fixed and shown as reference only.
 */

export type ShortcutContext = 'default' | 'accordion' | 'edit';

export interface ShortcutAction {
    /** Stable id — also the localStorage override key. */
    id: string;
    /** Human label shown in the popover. */
    label: string;
    /** Which dispatch pool this action belongs to. */
    context: ShortcutContext;
    /** Default key token (`e.code`, optional `Ctrl+` prefix). */
    defaultKey: string;
    /** False = fixed structural key (cannot be remapped). */
    rebindable: boolean;
}

/** Display grouping for the popover — each section maps 1:1 to a list of
 *  action ids, in render order. Kept separate from the flat catalogue so the
 *  resolver stays a simple id→action lookup. */
export interface ShortcutSection {
    title: string;
    /** One-line orientation shown under the section title. */
    hint: string;
    ids: string[];
}

export const SHORTCUT_ACTIONS: ShortcutAction[] = [
    // ---- Playback (default) ----
    { id: 'play_pause',    label: 'Play / pause',              context: 'default',   defaultKey: 'Space',      rebindable: false },
    { id: 'seek_back',     label: 'Seek back 3s',              context: 'default',   defaultKey: 'ArrowLeft',  rebindable: false },
    { id: 'seek_fwd',      label: 'Seek forward 3s',           context: 'default',   defaultKey: 'ArrowRight', rebindable: false },
    { id: 'nav_prev',      label: 'Previous segment',          context: 'default',   defaultKey: 'ArrowUp',    rebindable: false },
    { id: 'nav_next',      label: 'Next segment',              context: 'default',   defaultKey: 'ArrowDown',  rebindable: false },
    { id: 'speed_down',    label: 'Slower',                    context: 'default',   defaultKey: 'Comma',      rebindable: true },
    { id: 'speed_up',      label: 'Faster',                    context: 'default',   defaultKey: 'Period',     rebindable: true },
    { id: 'scroll_current',label: 'Scroll current into view',  context: 'default',   defaultKey: 'KeyJ',       rebindable: true },
    { id: 'autoplay',      label: 'Toggle autoplay-next',      context: 'default',   defaultKey: 'KeyK',       rebindable: true },

    // ---- Editing (default — acts on current / focused segment) ----
    { id: 'adjust',        label: 'Adjust (trim boundaries)',  context: 'default',   defaultKey: 'KeyA',       rebindable: true },
    { id: 'split',         label: 'Split / autosplit',         context: 'default',   defaultKey: 'KeyS',       rebindable: true },
    { id: 'edit_ref',      label: 'Edit reference',            context: 'default',   defaultKey: 'KeyE',       rebindable: true },
    { id: 'history',       label: 'Toggle history',            context: 'default',   defaultKey: 'KeyH',       rebindable: true },
    { id: 'save',          label: 'Save changes',              context: 'default',   defaultKey: 'Ctrl+KeyS',  rebindable: false },

    // ---- Inside a flagged card (accordion) ----
    { id: 'goto',          label: 'Go to card in surah',       context: 'accordion', defaultKey: 'KeyG',       rebindable: true },
    { id: 'toggle_context',label: 'Toggle context rows',       context: 'accordion', defaultKey: 'KeyC',       rebindable: true },
    { id: 'ignore',        label: 'Ignore issue',              context: 'accordion', defaultKey: 'KeyL',       rebindable: true },
    { id: 'autofill',      label: 'Auto-fill',                 context: 'accordion', defaultKey: 'KeyF',       rebindable: true },

    // ---- While adjusting / splitting (edit) ----
    { id: 'edit_step_back',label: 'Nudge cursor back',         context: 'edit',      defaultKey: 'ArrowLeft',  rebindable: false },
    { id: 'edit_step_fwd', label: 'Nudge cursor forward',      context: 'edit',      defaultKey: 'ArrowRight', rebindable: false },
    { id: 'edit_cycle',    label: 'Cycle cursor / region',     context: 'edit',      defaultKey: 'Tab',        rebindable: false },
    { id: 'edit_confirm',  label: 'Confirm',                   context: 'edit',      defaultKey: 'Enter',      rebindable: false },
    { id: 'edit_cancel',   label: 'Cancel',                    context: 'edit',      defaultKey: 'Escape',     rebindable: false },
];

export const SHORTCUT_SECTIONS: ShortcutSection[] = [
    {
        title: 'Playback',
        hint: 'Anywhere on the tab',
        ids: ['play_pause', 'seek_back', 'seek_fwd', 'nav_prev', 'nav_next', 'speed_down', 'speed_up', 'scroll_current', 'autoplay'],
    },
    {
        title: 'Editing',
        hint: 'Acts on the current segment',
        ids: ['adjust', 'split', 'edit_ref', 'history', 'save'],
    },
    {
        title: 'Inside a flagged card',
        hint: 'When an accordion is open — acts on its focused card',
        ids: ['goto', 'toggle_context', 'ignore', 'autofill'],
    },
    {
        title: 'While adjusting / splitting',
        hint: 'During trim or split — fixed keys',
        ids: ['edit_step_back', 'edit_step_fwd', 'edit_cycle', 'edit_confirm', 'edit_cancel'],
    },
];

const _BY_ID = new Map(SHORTCUT_ACTIONS.map((a) => [a.id, a]));

export function actionById(id: string): ShortcutAction | undefined {
    return _BY_ID.get(id);
}
