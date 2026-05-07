/**
 * Active-tab state, extracted from `main.ts` so that sibling modules
 * (keyboard handlers in each tab) can query the current tab without
 * importing `main.ts` — which would create a cycle back through
 * `main.ts → {timestamps,segments}/index → {timestamps,segments}/keyboard`.
 */

let _activeTab = 'timestamps';

export function getActiveTab(): string {
    return _activeTab;
}

export function setActiveTab(tab: string): void {
    _activeTab = tab;
}
