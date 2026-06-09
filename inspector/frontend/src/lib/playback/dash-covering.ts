import { get } from 'svelte/store';

import { recitationAyahs } from '../recitation-animation/recitation-settings';
import { dashPort } from './dash-port';

export function ensureDashCovering(targetMs: number): void {
    if (!dashPort.source) return;
    if (!dashPort.source.vbr) {
        dashPort.loadCovering(0, Number.POSITIVE_INFINITY);
        return;
    }
    const ayah = ayahCovering(targetMs);
    if (ayah) {
        dashPort.loadCovering(ayah.startMs, ayah.endMs);
        return;
    }
    const start = Math.max(0, targetMs);
    dashPort.loadCovering(start, start + 30_000);
}

export function ensureDashCoveringRange(startMs: number, endMs: number): void {
    if (!dashPort.source) return;
    if (!dashPort.source.vbr) {
        dashPort.loadCovering(0, Number.POSITIVE_INFINITY);
        return;
    }
    dashPort.loadCovering(startMs, endMs);
}

function ayahCovering(targetMs: number) {
    const ayahs = get(recitationAyahs);
    if (!ayahs.length) return null;
    const hit = ayahs.find((a) => targetMs >= a.startMs && targetMs < a.endMs);
    if (hit) return hit;
    return [...ayahs].reverse().find((a) => a.startMs <= targetMs) ?? ayahs[0] ?? null;
}
