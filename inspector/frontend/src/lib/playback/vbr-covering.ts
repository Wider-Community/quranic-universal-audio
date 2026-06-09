import type { AyahBoundary } from '../recitation-animation/types';

const FALLBACK_CLIP_MS = 30_000;

export function vbrCoveringRangeFor(
    targetMs: number,
    ayahs: AyahBoundary[],
    fallbackEndMs?: number,
): [number, number] {
    if (ayahs.length === 0) {
        const start = Math.max(0, targetMs);
        return [start, fallbackEndMs ?? start + FALLBACK_CLIP_MS];
    }

    const ayah = ayahCovering(targetMs, ayahs);
    const chapterEndMs = ayahs[ayahs.length - 1]?.endMs;
    return [ayah.startMs, Math.max(ayah.endMs, chapterEndMs ?? ayah.endMs)];
}

function ayahCovering(targetMs: number, ayahs: AyahBoundary[]): AyahBoundary {
    const hit = ayahs.find((a) => targetMs >= a.startMs && targetMs < a.endMs);
    if (hit) return hit;
    return [...ayahs].reverse().find((a) => a.startMs <= targetMs) ?? ayahs[0]!;
}
