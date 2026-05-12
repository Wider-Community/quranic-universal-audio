import { describe, expect, it } from 'vitest';

import type { PublicReciter } from '../../types/public-state';
import { buildSchemaDescriptor } from '../schema-descriptor';

function reciter(overrides: Partial<PublicReciter> = {}): PublicReciter {
    return {
        reciter_id: 'test',
        name: 'Test',
        country: null,
        primary_bucket: 'published',
        buckets: ['published'],
        deliveries: [],
        riwayat: ['hafs'],
        styles: ['murattal'],
        recording_contexts: [],
        sources: ['mp3quran'],
        channels: ['mp3quran'],
        deliveries_count: 1,
        chapter_count_total: 114,
        coverage_kind: 'full',
        last_activity: null,
        ...overrides,
    };
}

describe('buildSchemaDescriptor', () => {
    it('derives axes from the observed reciter set', () => {
        const d = buildSchemaDescriptor([
            reciter({ riwayat: ['hafs'], styles: ['murattal'] }),
            reciter({ riwayat: ['warsh'], styles: ['mujawwad'] }),
        ]);
        const riwayah = d.axes.find((a) => a.key === 'riwayah')!;
        expect(riwayah.options.map((o) => o.key)).toEqual(['hafs', 'warsh']);
        const style = d.axes.find((a) => a.key === 'style')!;
        expect(style.options.map((o) => o.key)).toEqual(['mujawwad', 'murattal']);
    });

    it('always includes the coverage axis with full/partial/mixed', () => {
        const d = buildSchemaDescriptor([reciter()]);
        const coverage = d.axes.find((a) => a.key === 'coverage')!;
        expect(coverage.options.map((o) => o.key)).toEqual(['full', 'partial', 'mixed']);
    });

    it('omits the recording_context axis when no reciter has one', () => {
        const d = buildSchemaDescriptor([reciter({ recording_contexts: [] })]);
        expect(d.axes.find((a) => a.key === 'recording_context')).toBeUndefined();
    });

    it('includes the recording_context axis when at least one reciter has one', () => {
        const d = buildSchemaDescriptor([reciter({ recording_contexts: ['studio'] })]);
        const ax = d.axes.find((a) => a.key === 'recording_context')!;
        expect(ax.options.map((o) => o.key)).toEqual(['studio']);
    });

    it('tagsOf returns the right tags for facet computation', () => {
        const d = buildSchemaDescriptor([reciter({ sources: ['a', 'b'] })]);
        const source = d.axes.find((a) => a.key === 'source')!;
        const r = reciter({ sources: ['a', 'b'] });
        expect(Array.from(source.tagsOf(r))).toEqual(['a', 'b']);
    });
});
