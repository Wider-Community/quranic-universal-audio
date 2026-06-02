/**
 * Open state for the project-overview modal ("About Qur'anic Universal Audio").
 *
 * Cross-tab: opened from the dashboard ⓘ button (beside Submit recitation) AND
 * from the segments first-edit gate (its "Overview" guide row). A single
 * `InfoModal` host mounted in `App.svelte` renders it, so it opens in place over
 * whatever tab/modal is active — identical look everywhere.
 */
import { writable } from 'svelte/store';

export const infoModalOpen = writable<boolean>(false);

export function openInfoModal(): void {
    infoModalOpen.set(true);
}

export function closeInfoModal(): void {
    infoModalOpen.set(false);
}
