/**
 * Adopt coordination signal — a tiny module-level ref shared between the
 * Timestamps gapless-shuffle fire path and the shared `BottomPlayer`.
 *
 * When a shuffle jump adopts a prewarmed `<audio>` element onto `dashPort`
 * (gapless, no fresh load), it ALSO mutates `playerContext` so the rest of the
 * app (chip, surah popover, analysis data) follows. That `playerContext` change
 * re-fires `BottomPlayer.reactToContext`, which would otherwise pause + reload
 * the freshly-adopted element — undoing the gapless swap. The fire path sets
 * this signal BEFORE the store write; `reactToContext` checks it and skips its
 * transport work (doing only bookkeeping) when the source is already satisfied
 * by the adopted element.
 *
 * Kept out of `player-context.ts` (that store is UI state) — this is transport
 * coordination. Single-shot: `take` clears it so it can't leak into a later
 * unrelated context change.
 */

export interface AdoptedSource {
    deliverySlug: string;
    surahNum: number;
    /** The element's loaded src (proxy URL) — what `dashPort.window.src` becomes
     *  after `adoptElement`. The guard cross-checks this to avoid acting on a
     *  stale signal. */
    srcUrl: string;
}

let _adopted: AdoptedSource | null = null;

export function setAdoptedSource(s: AdoptedSource): void {
    _adopted = s;
}

/** Read-and-clear. Returns the pending adopted source once, then null. */
export function takeAdoptedSource(): AdoptedSource | null {
    const s = _adopted;
    _adopted = null;
    return s;
}
