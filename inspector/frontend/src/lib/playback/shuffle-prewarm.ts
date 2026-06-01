/**
 * Shuffle look-ahead — keeps ONE warm `<audio>` element decoded + seeked to the
 * next shuffle target's verse, so a cross-chapter / cross-reciter shuffle jump
 * can adopt it gaplessly instead of doing a fresh load.
 *
 * One slot, sized to the current shuffle mode: the orchestrator warms the single
 * target the active mode will jump to (ayah → same reciter random ayah; both →
 * random reciter + ayah) and re-warms whenever the mode cycles. Off → nothing
 * warm (no jump happens). If a mid-verse cycle races verse-end and the re-warm
 * hasn't landed, consume misses and the fire path rolls a fresh (gapped) target
 * — correct, just not gapless.
 *
 * This is a thin wrapper over `shadow-audio.ts`: it remembers WHICH target the
 * warmed URL corresponds to (the shadow pool only keys by URL), so the fire path
 * can consume the pre-rolled target and its element together.
 *
 * Range-windowed, not a full download: `shadowPrewarm` sets `src` + seeks to the
 * verse offset, which triggers an HTTP Range (206) request for a bounded window
 * around that offset (see shadow-audio.ts).
 */
import type { TsRandomTarget } from '../recitation-data/ts-source';
import { consumeWarm, shadowPrewarm } from './shadow-audio';

/** HTMLMediaElement.HAVE_CURRENT_DATA — enough decoded to play at the position. */
const HAVE_CURRENT_DATA = 2;
/** Dedicated shadow slot for the shuffle look-ahead (distinct from the 'any'
 *  recycle bin the fire path drops the old element into). */
const SHUFFLE_SLOT = 'shuf' as const;

interface Pending {
    target: TsRandomTarget;
    /** Proxy URL the warm element is loaded with (matches what the shared player
     *  would build for this target). */
    proxyUrl: string;
    /** Raw (un-proxied) chapter URL — for the `setSource` triple at adopt time. */
    rawUrl: string;
    /** Verse start (chapter-absolute seconds) the element seeked to. */
    seekSec: number;
}

let _pending: Pending | null = null;

/** Warm the next shuffle target. Replaces any prior pending target. */
export function primeShuffle(p: Pending): void {
    _pending = p;
    shadowPrewarm(p.proxyUrl, { slot: SHUFFLE_SLOT, seekSec: p.seekSec });
}

export interface ConsumedShuffle extends Pending {
    el: HTMLAudioElement;
}

/**
 * Consume the pre-rolled target + its warm element, IFF the element is ready to
 * play at the seek position. Returns null on a miss (no pending target, or the
 * element isn't decoded yet) so the caller falls back to a (gapped) load. A
 * not-ready element is torn down rather than adopted (adopting it would gap
 * worse than a plain load).
 */
export function consumeShuffle(): ConsumedShuffle | null {
    const p = _pending;
    _pending = null;
    if (!p) return null;
    const el = consumeWarm(p.proxyUrl);
    if (!el) return null;
    if (el.readyState < HAVE_CURRENT_DATA) {
        try {
            el.removeAttribute('src');
            el.load();
            el.remove();
        } catch {
            /* ignore */
        }
        return null;
    }
    return { ...p, el };
}

export function clearShuffle(): void {
    _pending = null;
}
