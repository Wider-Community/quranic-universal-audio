/**
 * Schema descriptor for the dashboard secondary facet rail.
 *
 * Operates on combinations (PublicDelivery), since status / riwayah /
 * style / recording_context / channel are properties of a combination,
 * not of the reciter. The dashboard groups visible combinations back
 * under each reciter for display.
 *
 * Non-status axes have their options pre-sorted by overall combination
 * count desc — static ordering captured at load time, so the rail does
 * not reshuffle as the user toggles filters.
 *
 * Status axis options use a fixed display order (the public bucket
 * lifecycle), independent of counts.
 */

import type { PublicBucket, PublicDelivery } from '../types/public-state';

export interface AxisOption {
    key: string;
    label: string;
}

export interface Axis {
    key: string;
    label: string;
    tagsOf: (delivery: PublicDelivery) => readonly string[];
    options: AxisOption[];
}

export type SortKey = 'recent' | 'alphabetical' | 'combinations';

export interface SchemaDescriptor {
    axes: Axis[];
    sortKeys: readonly SortKey[];
}

const TITLE_CASE_OVERRIDES: Record<string, string> = {
    mp3quran: 'mp3quran',
    quranicaudio: 'quranicaudio',
    qul: 'qul',
    archive_org: 'archive.org',
    tvquran: 'tvquran',
    everyayah: 'everyayah',
    tarteel: 'tarteel',
};

function titleCase(slug: string): string {
    if (!slug) return '';
    const override = TITLE_CASE_OVERRIDES[slug];
    if (override) return override;
    return slug
        .split(/[_-]/)
        .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
        .join(' ');
}

const STATUS_ORDER: readonly PublicBucket[] = [
    'available_for_review',
    'under_review',
    'publishing',
    'published',
    'requested',
    'available_for_request',
] as const;

const STATUS_LABELS: Record<PublicBucket, string> = {
    available_for_review: 'Available to claim',
    under_review: 'Under review',
    publishing: 'Publishing',
    published: 'Published',
    requested: 'Requested',
    available_for_request: 'Available for request',
};

function countBy(values: Iterable<string | null>): Map<string, number> {
    const out = new Map<string, number>();
    for (const v of values) {
        if (!v) continue;
        out.set(v, (out.get(v) ?? 0) + 1);
    }
    return out;
}

function optionsByCount(counts: Map<string, number>): AxisOption[] {
    return [...counts.entries()]
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .map(([slug]) => ({ key: slug, label: titleCase(slug) }));
}

/** Six public buckets in display order — stable across schema rebuilds. */
export const PICKER_BUCKETS: readonly PublicBucket[] = STATUS_ORDER;

export function buildSchemaDescriptor(deliveries: readonly PublicDelivery[]): SchemaDescriptor {
    const riwayahCounts = countBy(deliveries.map((d) => d.riwayah));
    const styleCounts = countBy(deliveries.map((d) => d.style));
    const channelCounts = countBy(deliveries.map((d) => d.channel));
    const contextCounts = countBy(deliveries.map((d) => d.recording_context));

    const axes: Axis[] = [
        {
            key: 'status',
            label: 'Status',
            tagsOf: (d) => [d.bucket],
            options: STATUS_ORDER.map((b) => ({ key: b, label: STATUS_LABELS[b] })),
        },
        {
            key: 'riwayah',
            label: 'Riwayah',
            tagsOf: (d) => [d.riwayah],
            options: optionsByCount(riwayahCounts),
        },
        {
            key: 'style',
            label: 'Style',
            tagsOf: (d) => [d.style],
            options: optionsByCount(styleCounts),
        },
        {
            key: 'coverage',
            label: 'Mushaf coverage',
            tagsOf: (d) => [d.coverage_kind],
            options: [
                { key: 'full', label: 'Full mushaf' },
                { key: 'partial', label: 'Partial' },
            ],
        },
    ];
    if (contextCounts.size > 0) {
        axes.push({
            key: 'recording_context',
            label: 'Recording context',
            tagsOf: (d) => (d.recording_context ? [d.recording_context] : []),
            options: optionsByCount(contextCounts),
        });
    }
    axes.push({
        key: 'channel',
        label: 'Channel',
        tagsOf: (d) => [d.channel],
        options: optionsByCount(channelCounts),
    });

    return {
        axes,
        sortKeys: ['recent', 'alphabetical', 'combinations'],
    };
}
