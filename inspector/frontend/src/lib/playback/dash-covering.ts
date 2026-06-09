import { get } from 'svelte/store';

import { recitationAyahs } from '../recitation-animation/recitation-settings';
import { dashPort } from './dash-port';
import { vbrCoveringRangeFor } from './vbr-covering';

export function ensureDashCovering(targetMs: number): void {
    if (!dashPort.source) return;
    if (!dashPort.source.vbr) {
        dashPort.loadCovering(0, Number.POSITIVE_INFINITY);
        return;
    }
    dashPort.loadCovering(...vbrCoveringRangeFor(targetMs, get(recitationAyahs)));
}

export function ensureDashCoveringRange(startMs: number, endMs: number): void {
    if (!dashPort.source) return;
    if (!dashPort.source.vbr) {
        dashPort.loadCovering(0, Number.POSITIVE_INFINITY);
        return;
    }
    dashPort.loadCovering(...vbrCoveringRangeFor(startMs, get(recitationAyahs), endMs));
}
