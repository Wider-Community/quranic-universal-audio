/**
 * Schema descriptor for the ReciterPicker secondary facet rail.
 *
 * Pure function of the observed reciter set: derives the axes,
 * searchable fields, and sort keys from data, so the picker stays
 * taxonomy-agnostic. No ``riwayah`` / ``style`` / ``source`` string
 * literals leak into picker components.
 *
 * When the project adds a new facet (e.g. recitation_style refinements),
 * the descriptor picks it up automatically as long as the wire shape
 * exposes the field on PublicReciter.
 */

import type { PublicBucket, PublicReciter } from '../types/public-state';

export interface AxisOption {
    /** Stable identifier sent back to the picker's active-filters set. */
    key: string;
    /** Human label rendered on the pill. */
    label: string;
}

export interface Axis {
    /** Stable identifier (e.g. ``'riwayah'``). */
    key: string;
    /** Section heading rendered above the pill group. */
    label: string;
    /** Tags this reciter contributes for this axis. */
    tagsOf: (reciter: PublicReciter) => readonly string[];
    /** Ordered options derived from observed tags. */
    options: AxisOption[];
}

export type SortKey = 'recent' | 'alphabetical' | 'deliveries';

export interface SchemaDescriptor {
    axes: Axis[];
    sortKeys: readonly SortKey[];
}

const TITLE_CASE_OVERRIDES: Record<string, string> = {
    mp3quran: 'mp3quran',
    quranicaudio: 'quranicaudio',
    qul: 'qul',
    archive_org: 'archive.org',
};

function titleCase(slug: string): string {
    const override = TITLE_CASE_OVERRIDES[slug];
    if (override) return override;
    return slug
        .split(/[_-]/)
        .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
        .join(' ');
}

function uniqueSorted(values: Iterable<string>): string[] {
    return Array.from(new Set(values)).sort();
}

export function buildSchemaDescriptor(reciters: readonly PublicReciter[]): SchemaDescriptor {
    const allRiwayat: string[] = [];
    const allStyles: string[] = [];
    const allSources: string[] = [];
    const allContexts: string[] = [];
    for (const r of reciters) {
        allRiwayat.push(...r.riwayat);
        allStyles.push(...r.styles);
        allSources.push(...r.sources);
        allContexts.push(...r.recording_contexts);
    }

    const optionFor = (slug: string): AxisOption => ({ key: slug, label: titleCase(slug) });

    const axes: Axis[] = [
        {
            key: 'riwayah',
            label: 'Riwayah',
            tagsOf: (r) => r.riwayat,
            options: uniqueSorted(allRiwayat).map(optionFor),
        },
        {
            key: 'style',
            label: 'Style',
            tagsOf: (r) => r.styles,
            options: uniqueSorted(allStyles).map(optionFor),
        },
        {
            key: 'coverage',
            label: 'Mushaf coverage',
            tagsOf: (r) => [r.coverage_kind],
            options: [
                { key: 'full', label: 'Full mushaf' },
                { key: 'partial', label: 'Partial' },
                { key: 'mixed', label: 'Mixed' },
            ],
        },
        {
            key: 'source',
            label: 'Source',
            tagsOf: (r) => r.sources,
            options: uniqueSorted(allSources).map(optionFor),
        },
    ];
    if (allContexts.length > 0) {
        axes.push({
            key: 'recording_context',
            label: 'Recording context',
            tagsOf: (r) => r.recording_contexts,
            options: uniqueSorted(allContexts).map(optionFor),
        });
    }

    return {
        axes,
        sortKeys: ['recent', 'alphabetical', 'deliveries'],
    };
}

/** Six public buckets in display order — stable across schema rebuilds. */
export const PICKER_BUCKETS: readonly PublicBucket[] = [
    'available_for_review',
    'under_review',
    'publishing',
    'published',
    'requested',
    'available_for_request',
] as const;
