/**
 * Faceted-count helper shared by ``HistoryFilters`` (segments tab),
 * the Phase 6 Dashboard filter rail, and ``ReciterPicker``'s secondary
 * facet rail.
 *
 * Faceted semantics:
 *   For each facet F, the per-tag counts are computed against rows that
 *   pass all OTHER facets' active filters — i.e. clicking a tag inside
 *   F should not zero out F's siblings, only narrow the perpendicular
 *   axes.
 *
 * A row is "visible" iff it passes every facet whose active filter set
 * is non-empty (a row passes a facet when at least one of its tags is
 * in the active set, OR the facet's active set is empty).
 *
 * Generic over row type. Consumers supply a ``tagsOf`` extractor per
 * facet; the helper makes no assumption about row shape.
 */

export type FacetKey = string;
export type TagValue = string;

export interface FacetSpec<Row> {
    /** Stable identifier (e.g. ``'riwayah'``, ``'op_type'``). */
    key: FacetKey;
    /** Tags this row contributes to the facet. Multi-tag rows allowed. */
    tagsOf: (row: Row) => Iterable<TagValue>;
}

export interface FacetResult {
    /** Parallel to the input ``rows`` array — true iff the row passes every facet. */
    rowVisibility: boolean[];
    /** Per-facet counts of rows tagged with each value, faceted on the perpendicular axes. */
    perFacetCounts: Record<FacetKey, Record<TagValue, number>>;
}

function passesFacet<Row>(
    row: Row,
    spec: FacetSpec<Row>,
    active: Set<TagValue> | undefined,
): boolean {
    if (!active || active.size === 0) return true;
    for (const tag of spec.tagsOf(row)) {
        if (active.has(tag)) return true;
    }
    return false;
}

export function recomputeFacets<Row>(
    rows: Row[],
    activeFilters: Record<FacetKey, Set<TagValue>>,
    facets: FacetSpec<Row>[],
): FacetResult {
    const rowVisibility: boolean[] = new Array(rows.length).fill(false);
    const perFacetCounts: Record<FacetKey, Record<TagValue, number>> = {};
    for (const facet of facets) perFacetCounts[facet.key] = {};

    rows.forEach((row, i) => {
        // For each facet F, count this row's tags if the row passes every
        // OTHER facet's active filter.
        for (const facet of facets) {
            let passesOthers = true;
            for (const other of facets) {
                if (other.key === facet.key) continue;
                if (!passesFacet(row, other, activeFilters[other.key])) {
                    passesOthers = false;
                    break;
                }
            }
            if (!passesOthers) continue;
            const facetCounts = perFacetCounts[facet.key]!;
            for (const tag of facet.tagsOf(row)) {
                facetCounts[tag] = (facetCounts[tag] || 0) + 1;
            }
        }

        // Row visibility: passes every facet.
        let visible = true;
        for (const facet of facets) {
            if (!passesFacet(row, facet, activeFilters[facet.key])) {
                visible = false;
                break;
            }
        }
        rowVisibility[i] = visible;
    });

    return { rowVisibility, perFacetCounts };
}
