/**
 * Releases tab filter + sort state (Svelte 5 rune store).
 *
 * Mirrors ``reviews.svelte.ts`` minus the drawer/selection slots — the
 * Releases compartment doesn't open detail drawers (mutations land via the
 * row action button + a global Cut modal). Filters and sort persist across
 * modal open/close (the store is a module-level singleton); they reset on
 * page reload (see the matching Reviews TODO for the localStorage path).
 *
 * Convention parity with Reviews keeps the two tabs visually + interaction-
 * consistent: same facet chip groups, same "sort by stalest first" semantics,
 * same clear-all behaviour.
 */

export type ReleasesSort = 'stalest' | 'name';

export interface ReleasesFilters {
    q: string;
    riwayah: string | null;
    style: string | null;
    channel: string | null;
}

class ReleasesStore {
    filters = $state<ReleasesFilters>({
        q: '',
        riwayah: null,
        style: null,
        channel: null,
    });
    sortBy = $state<ReleasesSort>('stalest');

    /** Monotonic refresh signal. Bumping it makes the Releases compartment
     *  refetch — used after a Publish-to-HF or Cut launch so the in-flight
     *  block reflects the new job without waiting for the 30 s poll. */
    refreshSeq = $state(0);

    requestRefresh(): void {
        this.refreshSeq += 1;
    }

    setQ(q: string): void {
        this.filters.q = q;
    }

    /** Toggle a facet: clicking the active value clears it. */
    toggleFacet(key: 'riwayah' | 'style' | 'channel', value: string): void {
        this.filters[key] = this.filters[key] === value ? null : value;
    }

    clearFilters(): void {
        this.filters.q = '';
        this.filters.riwayah = null;
        this.filters.style = null;
        this.filters.channel = null;
    }

    setSort(s: ReleasesSort): void {
        this.sortBy = s;
    }

    get hasActiveFilters(): boolean {
        const f = this.filters;
        return f.q.trim() !== '' || f.riwayah !== null || f.style !== null || f.channel !== null;
    }
}

export const releasesStore = new ReleasesStore();
