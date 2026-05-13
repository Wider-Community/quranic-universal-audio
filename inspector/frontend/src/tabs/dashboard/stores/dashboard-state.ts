/**
 * Dashboard-tab local state.
 *
 * Covers filter state (faceted on combinations), sort, search, and the
 * detail-modal open flag. Mounted at the DashboardTab root so closing
 * the modal preserves list-view filters without remounting CatalogList.
 *
 * Status is just another facet axis (`activeFilters['status']`); the
 * sidebar pill rail is the only path to set it.
 */
import { derived, writable } from 'svelte/store';

export type DashboardView =
    | { kind: 'list' }
    | { kind: 'detail'; reciterId: string };

export type DashboardSort = 'status' | 'recent' | 'alphabetical' | 'combinations';

export interface DashboardState {
    view: DashboardView;
    activeFilters: Record<string, Set<string>>;
    sort: DashboardSort;
    search: string;
}

function initial(): DashboardState {
    return {
        view: { kind: 'list' },
        activeFilters: {},
        sort: 'recent',
        search: '',
    };
}

export const dashboardState = writable<DashboardState>(initial());

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
        activeFilters: {},
        search: '',
    }));
}

export function openDetail(reciterId: string): void {
    dashboardState.update((s) => ({ ...s, view: { kind: 'detail', reciterId } }));
}

export function closeDetail(): void {
    dashboardState.update((s) => ({ ...s, view: { kind: 'list' } }));
}

export const dashboardView = derived(dashboardState, (s) => s.view);
