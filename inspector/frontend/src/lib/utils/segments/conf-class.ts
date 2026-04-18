import type { Segment } from '../../types/domain';

export function getConfClass(seg: Segment | { matched_ref?: string; confidence?: number }): string {
    if (!seg.matched_ref) return 'conf-fail';
    const confidence = seg.confidence ?? 0;
    if (confidence >= 0.80) return 'conf-high';
    if (confidence >= 0.60) return 'conf-mid';
    return 'conf-low';
}
