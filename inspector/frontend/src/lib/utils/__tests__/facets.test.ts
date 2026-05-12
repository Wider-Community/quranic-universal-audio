import { describe, expect, it } from 'vitest';

import { type FacetSpec, recomputeFacets } from '../facets';

interface Delivery {
    slug: string;
    riwayah: string;
    style: string;
}

const facets: FacetSpec<Delivery>[] = [
    { key: 'riwayah', tagsOf: (r) => [r.riwayah] },
    { key: 'style', tagsOf: (r) => [r.style] },
];

const rows: Delivery[] = [
    { slug: 'a', riwayah: 'hafs', style: 'murattal' },
    { slug: 'b', riwayah: 'hafs', style: 'mujawwad' },
    { slug: 'c', riwayah: 'warsh', style: 'murattal' },
    { slug: 'd', riwayah: 'warsh', style: 'mujawwad' },
    { slug: 'e', riwayah: 'qaloon', style: 'murattal' },
];

describe('recomputeFacets', () => {
    it('returns base counts when no filter is active', () => {
        const { rowVisibility, perFacetCounts } = recomputeFacets(rows, {}, facets);
        expect(rowVisibility).toEqual([true, true, true, true, true]);
        expect(perFacetCounts.riwayah).toEqual({ hafs: 2, warsh: 2, qaloon: 1 });
        expect(perFacetCounts.style).toEqual({ murattal: 3, mujawwad: 2 });
    });

    it('counts on perpendicular axes only — riwayah counts unaffected by riwayah filter', () => {
        const active = { riwayah: new Set(['hafs']) };
        const { perFacetCounts } = recomputeFacets(rows, active, facets);
        // Riwayah counts ignore the riwayah filter — sibling pills stay clickable.
        expect(perFacetCounts.riwayah).toEqual({ hafs: 2, warsh: 2, qaloon: 1 });
        // Style counts are filtered by riwayah=hafs (2 rows: a=murattal, b=mujawwad).
        expect(perFacetCounts.style).toEqual({ murattal: 1, mujawwad: 1 });
    });

    it('marks rows visible iff they pass every active facet', () => {
        const active = {
            riwayah: new Set(['hafs']),
            style: new Set(['murattal']),
        };
        const { rowVisibility } = recomputeFacets(rows, active, facets);
        // Only 'a' is hafs+murattal.
        expect(rowVisibility).toEqual([true, false, false, false, false]);
    });

    it('treats an empty active set as "no filter for this facet"', () => {
        const active = { riwayah: new Set<string>() };
        const { rowVisibility } = recomputeFacets(rows, active, facets);
        expect(rowVisibility.every(Boolean)).toBe(true);
    });

    it('zeros tags that have no rows passing perpendicular axes', () => {
        const active = { riwayah: new Set(['qaloon']) };
        const { perFacetCounts } = recomputeFacets(rows, active, facets);
        // qaloon has only murattal style; mujawwad should drop to 0.
        expect(perFacetCounts.style).toEqual({ murattal: 1 });
    });

    it('handles multi-tag rows (one row contributes to multiple tags within a facet)', () => {
        interface MultiTagged {
            tags: string[];
        }
        const multiFacets: FacetSpec<MultiTagged>[] = [
            { key: 'tags', tagsOf: (r) => r.tags },
        ];
        const multiRows: MultiTagged[] = [
            { tags: ['a', 'b'] },
            { tags: ['a'] },
        ];
        const { perFacetCounts } = recomputeFacets(multiRows, {}, multiFacets);
        expect(perFacetCounts.tags).toEqual({ a: 2, b: 1 });
    });

    it('handles empty rows array', () => {
        const { rowVisibility, perFacetCounts } = recomputeFacets([], {}, facets);
        expect(rowVisibility).toEqual([]);
        expect(perFacetCounts).toEqual({ riwayah: {}, style: {} });
    });
});
