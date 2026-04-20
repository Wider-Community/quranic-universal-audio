import type { Segment } from '../../../../lib/types/domain';
import { CONF_HIGH_THRESHOLD, CONF_MID_THRESHOLD } from '../constants';

export function getConfClass(seg: Segment | { matched_ref?: string; confidence?: number }): string {
    if (!seg.matched_ref) return 'conf-fail';
    const confidence = seg.confidence ?? 0;
    if (confidence >= CONF_HIGH_THRESHOLD) return 'conf-high';
    if (confidence >= CONF_MID_THRESHOLD) return 'conf-mid';
    return 'conf-low';
}
