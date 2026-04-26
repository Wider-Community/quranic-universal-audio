import type { Segment } from '../../../../lib/types/domain';

export interface ActiveSegmentRef {
    chapter: number;
    index: number;
}

export interface AutoplayGapAdvance {
    justEnded: Segment;
    next: Segment;
}

interface ResolveAutoplayGapAdvanceOptions {
    active: ActiveSegmentRef | null;
    currentSrc: string;
    displayedSegments: Segment[] | null;
    playEndMs: number;
    timeMs: number;
}

function findJustEndedSegment(
    displayedSegments: Segment[],
    active: ActiveSegmentRef | null,
    currentSrc: string,
    playEndMs: number,
): Segment | null {
    if (active) {
        const activeSeg = displayedSegments.find(
            (seg) => seg.chapter === active.chapter && seg.index === active.index,
        );
        if (activeSeg) return activeSeg;
    }

    return displayedSegments.find(
        (seg) => seg.time_end === playEndMs && matchesAudioUrl(seg.audio_url, currentSrc),
    ) ?? null;
}

function matchesAudioUrl(audioUrl: string | null | undefined, currentSrc: string): boolean {
    if (!audioUrl || !currentSrc) return false;
    return currentSrc === audioUrl || currentSrc.endsWith(audioUrl);
}

export function resolveAutoplayGapAdvance({
    active,
    currentSrc,
    displayedSegments,
    playEndMs,
    timeMs,
}: ResolveAutoplayGapAdvanceOptions): AutoplayGapAdvance | null {
    if (!displayedSegments || displayedSegments.length === 0) return null;
    if (playEndMs <= 0 || timeMs < playEndMs) return null;

    const justEnded = findJustEndedSegment(displayedSegments, active, currentSrc, playEndMs);
    if (!justEnded) return null;

    const currentPos = displayedSegments.findIndex(
        (seg) => seg.chapter === justEnded.chapter && seg.index === justEnded.index,
    );
    if (currentPos < 0 || currentPos >= displayedSegments.length - 1) return null;

    const next = displayedSegments[currentPos + 1] ?? null;
    if (!next || next.index !== justEnded.index + 1) return null;
    if (!matchesAudioUrl(next.audio_url, currentSrc)) return null;

    return { justEnded, next };
}
