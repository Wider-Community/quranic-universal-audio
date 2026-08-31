/** Native report targeting over the stable quran-cells DOM hooks. */

import * as m from '$lib/paraglide/messages';
import type { TsReportTarget } from '../../../lib/types/generated/schemas';

export type CellKey = string;
export type TimingDir = 'early' | 'late';

export function timingLabel(onset: TimingDir | null, offset: TimingDir | null): string {
    const both: Record<string, () => string> = {
        'early|late': m.ts_report_timing_label_too_long,
        'late|early': m.ts_report_timing_label_too_short,
        'early|early': m.ts_report_timing_label_shifted_earlier,
        'late|late': m.ts_report_timing_label_shifted_later,
    };
    const hit = both[`${onset ?? ''}|${offset ?? ''}`];
    if (hit) return hit();
    if (onset && !offset) {
        return onset === 'early'
            ? m.ts_report_timing_label_starts_early()
            : m.ts_report_timing_label_starts_late();
    }
    if (offset && !onset) {
        return offset === 'early'
            ? m.ts_report_timing_label_finishes_early()
            : m.ts_report_timing_label_finishes_late();
    }
    return m.ts_report_timing_label_default();
}

export function targetCellKey(target: TsReportTarget): CellKey {
    return `${target.reading_id}:${target.kind}:${target.target_id}`;
}

const hooks = [
    ['sound', 'data-qc-sound-id'],
    ['bridge', 'data-qc-bridge-id'],
    ['column', 'data-qc-column-id'],
    ['group', 'data-qc-group-key'],
    ['boundary', 'data-qc-boundary-id'],
    ['word', 'data-qc-word-id'],
] as const;

function nativeElement(start: Element): { element: Element; kind: TsReportTarget['kind']; id: string } | null {
    const bridge = start.closest<HTMLElement>('[data-qc-bridge-id]');
    if (bridge?.dataset.qcBridgeId) {
        return { element: bridge, kind: 'bridge', id: bridge.dataset.qcBridgeId };
    }
    let element: Element | null = start;
    while (element) {
        for (const [kind, attribute] of hooks) {
            const id = element.getAttribute(attribute);
            if (id) return { element, kind, id };
        }
        element = element.parentElement;
    }
    return null;
}

export function cellTargetFromEl(start: Element): TsReportTarget | null {
    const native = nativeElement(start);
    const reading = start.closest<HTMLElement>('[data-reading-id]');
    if (!native || !reading?.dataset.readingId) return null;
    return {
        reading_id: reading.dataset.readingId,
        kind: native.kind,
        target_id: native.id,
    };
}

export function elCellKey(element: Element): CellKey | null {
    const target = cellTargetFromEl(element);
    return target ? targetCellKey(target) : null;
}

export function elHasTajweed(element: Element): boolean {
    const native = nativeElement(element)?.element;
    return Boolean(native?.getAttribute('data-qc-rule-ids'));
}

export function ruleIdsFromEl(element: Element): string[] {
    const native = nativeElement(element)?.element;
    return (native?.getAttribute('data-qc-rule-ids') ?? '').split(' ').filter(Boolean);
}
