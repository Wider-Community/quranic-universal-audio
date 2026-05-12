/**
 * Dashboard-tab local state.
 *
 * One writable store covering list-view filtering, sort, search, and
 * the list↔detail view toggle. Mounted at the DashboardTab root so
 * back-navigation from a detail view preserves the list-view filters
 * without remounting CatalogList.
 *
 * Intentionally independent of player-context — the BottomPlayer in
 * slice I is decoupled from list filtering.
 */
import { derived, writable } from 'svelte/store';

import type { PublicBucket } from '../../../lib/types/public-state';

export type DashboardView =
    | { kind: 'list' }
    | { kind: 'detail'; reciterName: string };

export type DashboardSort = 'recent' | 'alphabetical' | 'deliveries';

export interface DashboardState {
    view: DashboardView;
    activeBucket: PublicBucket | null;
    activeFilters: Record<string, Set<string>>;
    sort: DashboardSort;
    search: string;
}

function initial(): DashboardState {
    return {
        view: { kind: 'list' },
        activeBucket: null,
        activeFilters: {},
        sort: 'recent',
        search: '',
    };
}

export const dashboardState = writable<DashboardState>(initial());

export function setBucket(bucket: PublicBucket | null): void {
    dashboardState.update((s) => ({ ...s, activeBucket: bucket }));
}

export function toggleFacet(axisKey: string, tag: string): void {
    dashboardState.update((s) => {
        const next = new Set(s.activeFilters[axisKey] ?? []);
        if (next.has(tag)) next.delete(tag);
        else next.add(tag);
        return { ...s, activeFilters: { ...s.activeFilters, [axisKey]: next } };
    });
}

export function setSort(sort: DashboardSort): void {
    dashboardState.update((s) => ({ ...s, sort }));
}

export function setSearch(search: string): void {
    dashboardState.update((s) => ({ ...s, search }));
}

export function clearAllFilters(): void {
    dashboardState.update((s) => ({
        ...s,
        activeBucket: null,
        activeFilters: {},
        search: '',
    }));
}

export function openDetail(reciterName: string): void {
    dashboardState.update((s) => ({ ...s, view: { kind: 'detail', reciterName } }));
}

export function backToList(): void {
    dashboardState.update((s) => ({ ...s, view: { kind: 'list' } }));
}

export const dashboardView = derived(dashboardState, (s) => s.view);
