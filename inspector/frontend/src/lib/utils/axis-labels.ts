/**
 * Display-label helpers that walk a `SchemaDescriptor` to resolve axis
 * keys ("riwayah", "channel", …) and tag values ("hafs", "mp3quran", …)
 * to their human-friendly labels.
 *
 * Both the dashboard's facet chips bar and the picker's row meta line
 * need this exact lookup; centralizing here keeps them in lockstep.
 */
import type { SchemaDescriptor } from '../catalog/schema-descriptor';
import { titleCaseSlug } from './delivery-label';

/** Display label for an axis (e.g. "riwayah" → "Riwayah"). */
export function axisLabel(
    descriptor: SchemaDescriptor | null,
    axisKey: string,
): string {
    if (!descriptor) return axisKey;
    return descriptor.axes.find((a) => a.key === axisKey)?.label ?? axisKey;
}

/**
 * Display label for a tag value within an axis (e.g. ('riwayah','hafs') →
 * 'Hafs'). Falls back to `titleCaseSlug(tag)` so unknown values still
 * render presentably instead of leaking the raw slug.
 */
export function tagLabel(
    descriptor: SchemaDescriptor | null,
    axisKey: string,
    tag: string | null | undefined,
): string {
    if (!tag) return '';
    if (!descriptor) return titleCaseSlug(tag);
    const axis = descriptor.axes.find((a) => a.key === axisKey);
    const opt = axis?.options.find((o) => o.key === tag);
    return opt?.label ?? titleCaseSlug(tag);
}
