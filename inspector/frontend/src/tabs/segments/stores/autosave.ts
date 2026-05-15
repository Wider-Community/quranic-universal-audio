import { writable } from 'svelte/store';

import { LS_KEYS } from '../../../lib/utils/constants';

// Load initial preference from localStorage (default to true)
const initialValue = localStorage.getItem(LS_KEYS.SEG_AUTOSAVE) !== 'false';

export const autoSaveEnabled = writable<boolean>(initialValue);

export function toggleAutoSave(enabled: boolean) {
    autoSaveEnabled.set(enabled);
    localStorage.setItem(LS_KEYS.SEG_AUTOSAVE, enabled ? 'true' : 'false');
}
