/**
 * Dashboard intent-driven look-ahead — keeps ONE warm `<audio>` element decoded
 * (and optionally seeked) for the chapter the user is most likely to play next,
 * so the play-click pays no cold-start (fetch + header parse + decode + canplay).
 *
 * Depth 1, single slot ('dash'): each intent replaces the prior warm target.
 * Two confidence tiers, matching the locked decision:
 *   - SPECULATIVE (`primeDashSpeculative`) — hovers over the next/prev button,
 *     a surah in the popover, the progress bar, or a filmstrip ayah. A cheap
 *     range-windowed warm (`shadowPrewarm` sets src + seeks → HTTP Range), no
 *     commitment.
 *   - COMMITTED (`primeDashCommitted`) — the imminent gapless-next chapter as
 *     the current surah nears its end. Same warm, but tracked as consumable so
 *     the near-end handoff can `consumeDashCommitted` → `adoptElement` the warm
 *     element gaplessly (mirrors the Timestamps shuffle adopt path).
 *
 * A committed target supersedes a speculative one (commitment wins the single
 * slot). `clearDashPrewarm()` cancels the in-flight warm on a reciter/chapter
 * switch so a stale warm can never be adopted (mirrors shuffle-prewarm's
 * `clearShuffle`).
 *
 * Thin wrapper over `shadow-audio.ts`: the shadow pool keys by URL only, so
 * this module remembers WHICH chapter the committed URL belongs to for the
 * adopt-time `setSource` triple + `playerContext` follow.
 */
import { cancelWarm, consumeWarm, shadowPrewarm } from './shadow-audio';
import { playUrl } from './play-url';

/** HTMLMediaElement.HAVE_CURRENT_DATA — enough decoded to play at the position. */
const HAVE_CURRENT_DATA = 2;
/** Dedicated shadow slot for the dashboard look-ahead (distinct from 'shuf'
 *  and the 'any' recycle bin). */
const DASH_SLOT = 'dash' as const;

/** A committed gapless-next target — the chapter the near-end handoff will
 *  adopt. */
export interface DashCommitted {
    deliverySlug: string;
    surahNum: number;
    /** Raw (un-proxied) chapter URL — for the adopt-time `setSource` triple. */
    rawUrl: string;
    /** Proxy URL the warm element is loaded with (matches what BottomPlayer
     *  would build) — the shadow-pool consume key + `adoptElement` src. */
    proxyUrl: string;
}

let _committed: DashCommitted | null = null;

/** Build the same play URL BottomPlayer / TimestampsTab build for a chapter
 *  CDN link — direct CDN when its host passed the CORS probe, else the
 *  audio-proxy wrapper (`play-url.ts`). Already-proxied (`/api/...`) URLs
 *  pass through untouched. Every dashboard site MUST build the src through
 *  here so the shadow-pool consume key and `adoptElement` src stay identical. */
export function dashProxyUrl(slug: string, rawUrl: string): string {
    return playUrl(slug, rawUrl);
}

/** Speculative warm — range-windowed decode at `seekSec` (default 0). Replaces
 *  any prior warm in the slot, BUT never displaces a committed target (a
 *  commitment outranks a hover). No-op for an empty URL. */
export function primeDashSpeculative(proxyUrl: string, seekSec = 0): void {
    if (!proxyUrl || _committed) return;
    shadowPrewarm(proxyUrl, { slot: DASH_SLOT, seekSec: Math.max(0, seekSec) });
}

/** Committed warm — the imminent gapless-next chapter. Tracks the target for
 *  adopt. Replaces any prior (speculative or committed) warm. Re-calling with
 *  the SAME proxy URL is a no-op (shadow dedupe). */
export function primeDashCommitted(c: DashCommitted): void {
    if (!c.proxyUrl) return;
    if (_committed?.proxyUrl === c.proxyUrl) return;
    _committed = c;
    shadowPrewarm(c.proxyUrl, { slot: DASH_SLOT, seekSec: 0 });
}

export interface ConsumedDash extends DashCommitted {
    el: HTMLAudioElement;
}

/**
 * Consume the committed target + its warm element, IFF the element is decoded
 * to a playable state. Returns null on a miss (no committed target, URL drift,
 * or element not ready) so the caller falls back to a plain (gapped) load. A
 * not-ready element is torn down rather than adopted (adopting a cold element
 * gaps worse than a fresh load).
 */
export function consumeDashCommitted(proxyUrl: string): ConsumedDash | null {
    const c = _committed;
    _committed = null;
    if (!c || c.proxyUrl !== proxyUrl) return null;
    const el = consumeWarm(proxyUrl);
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
    return { ...c, el };
}

/** Abandon any pending dashboard warmup — the committed-target ref AND the
 *  shadow element's in-flight fetch. Called on a reciter/chapter switch so a
 *  stale warm never adopts and rapid hovers don't stack audio-proxy sockets. */
export function clearDashPrewarm(): void {
    _committed = null;
    cancelWarm(DASH_SLOT);
}
