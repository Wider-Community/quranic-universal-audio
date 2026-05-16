/**
 * Active-tab state, extracted from `main.ts` so that sibling modules
 * (keyboard handlers in each tab) can query the current tab without
 * importing `main.ts` — which would create a cycle back through
 * `main.ts → {timestamps,segments}/index → {timestamps,segments}/keyboard`.
 *
 * Reactive subscribers (Svelte components) use `activeTab` (the store);
 * imperative callers use `getActiveTab()` / `setActiveTab()`. Both reflect
 * the same value — the store is the source of truth and the getter just
 * reads the cached scalar.
 */

import { writable } from 'svelte/store';

let _activeTab = 'dashboard';

export const activeTab = writable<string>(_activeTab);

export function getActiveTab(): string {
    return _activeTab;
}

export function setActiveTab(tab: string): void {
    _activeTab = tab;
    activeTab.set(tab);
}
