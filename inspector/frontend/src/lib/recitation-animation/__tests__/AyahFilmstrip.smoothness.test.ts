import { render } from '@testing-library/svelte';
import { tick } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
    assembleOccasion,
    shardOccasions,
    type TsReciterAudio,
} from '../../recitation-data/ts-source';
import shard102 from '../../recitation-data/__tests__/fixtures/nasser_al_qatami_mp3quran_102.shard.json';
import type { TsShardResponse } from '../../types/ts-client';
import AyahFilmstrip from '../AyahFilmstrip.svelte';
import { buildChapterRecitation, type AssembledVerse } from '../chapter-words';
import { DEFAULT_RECITATION_CONFIG } from '../config';
import { buildFilmstripModel } from '../filmstrip-model';
import type { AnimUnit, TimeSpan } from '../types';

/**
 * Per-frame smoothness guard for the ayah-filmstrip motion fixes, driven against
 * the REAL nasser_al_qatami chapter-102 units (with multi-verse re-takes), a
 * synthetic uneven multi-verse loopback, and a synthetic floored-cell fixture:
 *
 *   1. FILL FROM CURSOR — the lit fill bar's leading edge sits under the center
 *      needle every non-silent frame (|fillEdge − cursorOffset| ≤ EPS_PX), incl.
 *      on a FLOORED short cell (w > aw).
 *   2. PER-VERSE CONFORMANCE — a multi-verse loopback replays EACH verse over its
 *      OWN re-take duration (the cursor crosses THAT verse's own cell at one
 *      constant velocity), never one velocity collapsed onto the loopback verse's
 *      duration. An uneven synthetic re-take makes the per-verse pace differ.
 *   3. INTER-TAKE SILENCE SCROLLS — a between-verse pause (forward OR backward)
 *      advances the greyed needle; a within-verse pause holds it.
 *   4. SNAP MODE — unchanged: no continuous-fill divergence, active cell centers
 *      on ayah change.
 */

const RECITER = 'nasser_al_qatami_mp3quran';
const RECITER_AUDIO: TsReciterAudio = { audio_category: 'by_surah' };
const EMPTY: Record<string, { text?: string }> = {};

const PX_PER_SEC = DEFAULT_RECITATION_CONFIG.filmstripPxPerSec; // 12
const MIN_PX = DEFAULT_RECITATION_CONFIG.filmstripMinCellPx; // 18
const MICRO_GAP_SEC = 0.06; // mirror AyahFilmstrip: sub-perceptual gaps lay out time-true
const CW = 600; // forced container width
const STEP = 16; // ms per frame
const END = 104_000;
/** Max tolerated gap between the fill bar's leading edge and the cursor (px). */
const EPS_PX = 1.5;

function unit(loc: string, ivs: Array<[number, number]>): AnimUnit {
    const [s, a, w] = loc.split(':').map(Number);
    const spans: TimeSpan[] = ivs.map(([st, en]) => ({ start: st, end: en }));
    return {
        location: loc, ayahKey: `${s}:${a}`, surah: s!, ayah: a!, word: w!, text: loc,
        start: spans[0]!.start, end: spans[spans.length - 1]!.end, intervals: spans, letters: [],
    };
}

function buildNasserUnits(): AnimUnit[] {
    const shard = shard102 as unknown as TsShardResponse;
    const occasions: AssembledVerse[] = shardOccasions(shard).map((occ) => ({
        verseRef: occ.ref,
        data: assembleOccasion(RECITER, occ, EMPTY, EMPTY, RECITER_AUDIO, ''),
    }));
    return buildChapterRecitation(RECITER, 102, occasions).units;
}

// Re-derive the same cell geometry the component derives (matches `cells` in
// AyahFilmstrip), so a test can map an ayah → its [cumBefore, w] independently.
interface DCell { ayah: number; w: number; aw: number; cumBefore: number; missing: string }
function deriveCells(model: ReturnType<typeof buildFilmstripModel>): DCell[] {
    const out: DCell[] = [];
    let cum = 0;
    for (const c of model.cells) {
        const aw = c.missing === 'full' ? 30 : Math.max(1, Math.round(c.canonDurSec * PX_PER_SEC));
        const w = c.missing === 'full' ? 30 : Math.max(MIN_PX, aw);
        const sec = c.nextGapSec;
        const gapAfter = Math.round(
            sec < MICRO_GAP_SEC ? sec * PX_PER_SEC : Math.max(DEFAULT_RECITATION_CONFIG.filmstripGapPx, sec * PX_PER_SEC),
        );
        out.push({ ayah: c.ayah, w, aw, cumBefore: cum, missing: c.missing });
        cum += w + gapAfter;
    }
    return out;
}

function trackOffset(c: HTMLElement): number {
    const t = c.querySelector<HTMLElement>('.track');
    const m = t ? /translateX\((-?[\d.]+)px\)/.exec(t.style.transform) : null;
    return m ? -Number(m[1]) : NaN;
}
function fillPct(c: HTMLElement): number {
    const v = c.querySelector<HTMLElement>('.filmstrip')?.style.getPropertyValue('--cell-active-fill').trim();
    return v ? Number(v.replace('%', '')) : NaN;
}
/** The ayah of the cell carrying the lit fill bar (`.cell.fillcell`). */
function fillAyah(c: HTMLElement): number | null {
    const el = c.querySelector<HTMLElement>('.cell.fillcell .cell-num');
    return el ? Number(el.textContent) : null;
}
function activeAyah(c: HTMLElement): number | null {
    const el = c.querySelector<HTMLElement>('.cell.active .cell-num');
    return el ? Number(el.textContent) : null;
}
function needlePresent(c: HTMLElement): boolean {
    return !!c.querySelector('.needle');
}
function needleGrey(c: HTMLElement): boolean {
    return !!c.querySelector('.needle.silent');
}

interface Frame {
    t: number;
    off: number;
    activeAyah: number | null;
    fillAyah: number | null;
    fillEdge: number; // track-coord px of the fill bar's leading edge
    needle: boolean;
    grey: boolean;
    silent: boolean;
    vel: number; // px/s vs previous frame
}

describe('AyahFilmstrip smoothness (per-frame)', () => {
    vi.setConfig({ testTimeout: 20000 }); // each case steps ~6500 frames

    let rafCbs: FrameRequestCallback[] = [];
    let nowMs = 0;
    const getTimeMs = (): number => nowMs;

    beforeEach(() => {
        rafCbs = [];
        vi.stubGlobal('requestAnimationFrame', (cb: FrameRequestCallback): number => {
            rafCbs.push(cb);
            return rafCbs.length;
        });
        vi.stubGlobal('cancelAnimationFrame', () => {});
        vi.spyOn(performance, 'now').mockImplementation(() => nowMs);
        vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} }));
    });
    afterEach(() => {
        vi.unstubAllGlobals();
        vi.restoreAllMocks();
    });

    async function flushFrame(): Promise<void> {
        for (let i = 0; i < 3 && rafCbs.length; i++) {
            const batch = rafCbs;
            rafCbs = [];
            for (const cb of batch) cb(nowMs);
            await tick();
        }
    }

    /** Render the strip, force a width, then step 0→END at 16ms, capturing one
     *  Frame per step (fillEdge from the `.cell.fillcell` geometry the component
     *  actually rendered). */
    async function traceChapter(
        units: AnimUnit[],
        motion: 'hybrid' | 'snap',
        endMs = END,
    ): Promise<{ frames: Frame[]; cells: DCell[] }> {
        const model = buildFilmstripModel(units, 'duration');
        const cells = deriveCells(model);
        const byAyah = new Map(cells.map((c) => [c.ayah, c]));
        const { container } = render(AyahFilmstrip, {
            units, model, durationMs: endMs, getTimeMs, playing: true,
            config: { ...DEFAULT_RECITATION_CONFIG, leadMs: 0, filmstripMotion: motion },
            onSeek: () => {},
        });
        await tick();
        const strip = container.querySelector<HTMLElement>('.filmstrip')!;
        Object.defineProperty(strip, 'clientWidth', { configurable: true, value: CW });
        await tick();

        const frames: Frame[] = [];
        let prevOff = NaN;
        for (let t = 0; t <= endMs; t += STEP) {
            nowMs = t;
            await flushFrame();
            const off = trackOffset(container);
            const fp = fillPct(container);
            const fa = fillAyah(container);
            const aa = activeAyah(container);
            const fc = fa != null ? byAyah.get(fa) : undefined;
            const fillEdge = fc && !Number.isNaN(fp) ? fc.cumBefore + (fp / 100) * fc.w : NaN;
            const vel = Number.isNaN(prevOff) ? 0 : (off - prevOff) / (STEP / 1000);
            frames.push({
                t, off, activeAyah: aa, fillAyah: fa, fillEdge,
                needle: needlePresent(container), grey: needleGrey(container),
                silent: aa == null, vel,
            });
            prevOff = off;
        }
        return { frames, cells };
    }

    it('keeps the fill bar leading edge under the cursor every non-silent frame', async () => {
        const { frames, cells } = await traceChapter(buildNasserUnits(), 'hybrid');
        const byAyah = new Map(cells.map((c) => [c.ayah, c]));
        let worst = 0;
        let worstT = -1;
        let sampled = 0;
        for (const f of frames) {
            if (f.silent || f.fillAyah == null || Number.isNaN(f.fillEdge) || Number.isNaN(f.off)) continue;
            const c = byAyah.get(f.fillAyah)!;
            // Only the cursor INSIDE the fill cell's visible span has a fill-bar edge
            // that can sit on it — when the needle floats over an inter-cell gap the
            // bar is correctly pinned at 0%/100% (no edge to align). Skip those.
            if (f.off < c.cumBefore - 0.5 || f.off > c.cumBefore + c.w + 0.5) continue;
            sampled++;
            const div = Math.abs(f.fillEdge - f.off);
            if (div > worst) { worst = div; worstT = f.t; }
        }
        expect(sampled, 'sampled in-cell non-silent frames').toBeGreaterThan(100);
        expect(worst, `max |fillEdge − cursor| = ${worst.toFixed(2)}px at t=${worstT}ms`).toBeLessThanOrEqual(EPS_PX);
    });

    it('aligns the fill bar with the cursor on a FLOORED short cell (w > aw)', async () => {
        // Verse 2 is a 0.5s single word → aw = round(0.5×12) = 6 < minPx 18, so its
        // cell is floored to 18px (w − aw = 12px of surplus). The fill must still
        // track the cursor through it.
        const units: AnimUnit[] = [
            unit('1:1:1', [[0, 2]]), // verse 1: 2s, not floored
            unit('1:2:1', [[3, 3.5]]), // verse 2: 0.5s → FLOORED
            unit('1:3:1', [[5, 7]]), // verse 3: 2s
        ];
        const model = buildFilmstripModel(units, 'duration');
        const cells = deriveCells(model);
        const v2 = cells[1]!;
        expect(v2.aw).toBe(Math.round(0.5 * PX_PER_SEC)); // 6
        expect(v2.w).toBe(MIN_PX); // 18 — confirmed floored
        expect(v2.w).toBeGreaterThan(v2.aw);

        const { frames } = await traceChapter(units, 'hybrid');
        let sampled = 0;
        let worst = 0;
        for (const f of frames) {
            if (f.silent || f.fillAyah !== 2 || Number.isNaN(f.fillEdge) || Number.isNaN(f.off)) continue;
            sampled++;
            worst = Math.max(worst, Math.abs(f.fillEdge - f.off));
        }
        expect(sampled, 'verse 2 (floored) was active for some frames').toBeGreaterThan(0);
        expect(worst, `floored-cell max |fillEdge − cursor| = ${worst.toFixed(2)}px`).toBeLessThanOrEqual(EPS_PX);
    });

    it('keeps each looped-back verse cursor inside its OWN cell (conforms per verse)', async () => {
        const { frames, cells } = await traceChapter(buildNasserUnits(), 'hybrid');
        const byAyah = new Map(cells.map((c) => [c.ayah, c]));
        // Group non-silent frames into runs (one contiguous stretch on one active
        // cell). A run is a REPLAY when that ayah was already active in an earlier
        // run — the multi-verse 4→1 loopback re-recites 1,2,3,4, so each gets a
        // second run. Each replay verse must keep the cursor inside its OWN cell
        // span while active: it conforms to THAT verse, never drifting along the
        // loopback envelope (the bug, which would carry the cursor past the verse's
        // own cell as the run progresses). Constant in-cell velocity is proven by
        // the synthetic uneven cases below + AyahFilmstrip.uneven-replay; here a real
        // run can also contain a within-verse loopback hop, so velocity is not flat.
        const seen = new Set<number>();
        const replays: { ayah: number; mids: Frame[] }[] = [];
        let i = 0;
        while (i < frames.length) {
            const f = frames[i]!;
            if (f.silent || f.activeAyah == null) { i++; continue; }
            const ayah = f.activeAyah;
            const start = i;
            while (i < frames.length && !frames[i]!.silent && frames[i]!.activeAyah === ayah) i++;
            const run = frames.slice(start, i);
            // Drop the first/last 2 frames (landing ease-in, exit transition).
            if (seen.has(ayah) && run.length >= 8) replays.push({ ayah, mids: run.slice(2, -2) });
            seen.add(ayah);
        }
        expect(replays.length, 'multi-verse loopback produced replay runs').toBeGreaterThanOrEqual(3);
        for (const r of replays) {
            const c = byAyah.get(r.ayah)!;
            for (const f of r.mids) {
                if (Number.isNaN(f.off)) continue;
                expect(
                    f.off >= c.cumBefore - 1 && f.off <= c.cumBefore + c.w + 1,
                    `replay verse ${r.ayah}@${f.t}ms cursor ${f.off.toFixed(1)} inside cell [${c.cumBefore}, ${c.cumBefore + c.w}]`,
                ).toBe(true);
            }
        }
    });

    it('replays a multi-verse loopback at each verse\'s OWN pace (uneven re-take), not one collapsed velocity', async () => {
        // Forward 1,2,3 (canonical 2 / 1.6 / 2s), then a loopback to verse 1 that
        // re-recites all three UNEVENLY: v1 fast (0.5s), v2 slow (3s), v3 fast (0.5s).
        // Per-verse conformance ⇒ the cursor crosses each verse's OWN cell over that
        // verse's OWN re-take, so the slow verse scrolls far slower than the fast one.
        // The collapsed-velocity bug would scroll all three at one envelope rate.
        const synth: AnimUnit[] = [
            unit('1:1:1', [[0, 2], [6, 6.5]]),
            unit('1:2:1', [[2, 3.6], [6.5, 9.5]]),
            unit('1:3:1', [[3.6, 5.6], [9.5, 10]]),
        ];
        const { frames, cells } = await traceChapter(synth, 'hybrid', 11_000);
        const byAyah = new Map(cells.map((c) => [c.ayah, c]));
        const aw = (a: number): number => byAyah.get(a)!.aw;
        // Average velocity (endpoint displacement / time — immune to per-frame
        // smoothing) inside a verse's replay window.
        const avgVel = (lo: number, hi: number, ayah: number): number => {
            const seg = frames.filter((f) => f.t >= lo && f.t <= hi && !f.silent
                && f.activeAyah === ayah && !Number.isNaN(f.off));
            if (seg.length < 2) return NaN;
            const a = seg[0]!;
            const b = seg[seg.length - 1]!;
            return (b.off - a.off) / ((b.t - a.t) / 1000);
        };
        const expV2 = aw(2) / 3; //   slow re-take: own cell aw over 3s
        const expV3 = aw(3) / 0.5; // fast re-take: own cell aw over 0.5s
        const v2 = avgVel(6_700, 9_400, 2);
        const v3 = avgVel(9_550, 9_980, 3);
        // Each verse conforms to its OWN re-take pace (±35% for easing/sampling).
        expect(v2, `v2 replay ≈ ${expV2.toFixed(1)}px/s`).toBeGreaterThan(expV2 * 0.65);
        expect(v2, `v2 replay ≈ ${expV2.toFixed(1)}px/s`).toBeLessThan(expV2 * 1.35);
        expect(v3, `v3 replay ≈ ${expV3.toFixed(1)}px/s`).toBeGreaterThan(expV3 * 0.65);
        // The slow verse scrolls MUCH slower than the fast one — proof the replay is
        // NOT one collapsed velocity (which would make v2 ≈ v3).
        expect(v3, 'fast v3 replay ≫ slow v2 replay').toBeGreaterThan(v2 * 3);
    });

    it('scrolls a greyed needle through every inter-take silence, holds within-verse', async () => {
        const { frames } = await traceChapter(buildNasserUnits(), 'hybrid');
        // Group consecutive silent frames into runs (ignore single-frame blips).
        let i = 0;
        let between = 0;
        let backward = 0;
        let within = 0;
        while (i < frames.length) {
            if (!frames[i]!.silent) { i++; continue; }
            const start = i;
            while (i < frames.length && frames[i]!.silent) i++;
            const end = i - 1;
            if (frames[end]!.t - frames[start]!.t < 32) continue; // skip blips
            const prevAyah = start > 0 ? frames[start - 1]!.activeAyah : null;
            const nextAyah = i < frames.length ? frames[i]!.activeAyah : null;
            if (prevAyah == null || nextAyah == null) continue; // leading/trailing
            const off0 = frames[start]!.off;
            const off1 = frames[end]!.off;
            const advanced = Math.abs(off1 - off0);
            if (prevAyah === nextAyah) {
                // WITHIN-VERSE silence — must HOLD (no scroll, needle absent).
                within++;
                expect(advanced, `within-verse silence ${prevAyah}@${frames[start]!.t}ms held`).toBeLessThan(1);
                expect(frames[end]!.needle, `within-verse needle hidden @${frames[start]!.t}ms`).toBe(false);
            } else {
                // INTER-TAKE silence (forward OR backward) — must SCROLL with a grey
                // needle present.
                between++;
                if (nextAyah < prevAyah) backward++;
                expect(advanced, `inter-take silence ${prevAyah}→${nextAyah}@${frames[start]!.t}ms scrolled`).toBeGreaterThan(1);
                expect(frames[end]!.needle, `inter-take needle present @${frames[start]!.t}ms`).toBe(true);
                expect(frames[end]!.grey, `inter-take needle grey @${frames[start]!.t}ms`).toBe(true);
            }
        }
        expect(within, 'some within-verse silences exist').toBeGreaterThan(0);
        expect(between, 'some inter-take silences exist').toBeGreaterThan(0);
        // The three backward inter-take silences (4→1, 7→6, 8→7) all scroll.
        expect(backward, 'the three backward inter-take silences scrolled').toBeGreaterThanOrEqual(3);
    });

    it('holds a sub-perceptual inter-verse micro-gap without greying or snapping', async () => {
        // Verse 1 → verse 2 with a 30ms gap (< MICRO_GAP_SEC: connected flow, not a
        // waqf stop). The needle must stay lit across it (never grey) and the cursor
        // must glide, not snap — the cells lay out gapless so verse 2 picks up where
        // verse 1 ended. (The pre-fix behaviour bursted ~2px in one frame + greyed.)
        const synth: AnimUnit[] = [
            unit('1:1:1', [[0, 1]]),
            unit('1:1:2', [[1, 2]]),
            unit('1:2:1', [[2.03, 3]]),
            unit('1:2:2', [[3, 4]]),
        ];
        const { frames } = await traceChapter(synth, 'hybrid', 5000);
        // Around the 1→2 boundary (~2000ms): never grey, highlight never drops, and
        // no single-frame cursor snap (12px/s flow ≈ 0.2px/frame; 2px is a generous
        // ceiling that the old floored-gap burst would have blown past).
        const near = frames.filter((f) => f.t >= 1500 && f.t <= 2500);
        expect(near.some((f) => f.grey), 'no greyed needle across the micro-gap').toBe(false);
        expect(near.every((f) => f.activeAyah != null), 'highlight held across the micro-gap').toBe(true);
        const maxJump = Math.max(...near.map((f) => Math.abs(f.vel) * (STEP / 1000)));
        expect(maxJump, `max per-frame cursor move ${maxJump.toFixed(2)}px`).toBeLessThan(2);
    });

    it('snap mode centers the active cell on ayah change with no continuous-fill divergence', async () => {
        const { frames, cells } = await traceChapter(buildNasserUnits(), 'snap');
        const byAyah = new Map(cells.map((c) => [c.ayah, c]));
        // Snap has no needle, so there is no cursor-vs-fill alignment to hold — the
        // fill follows the recited word fraction. The guard here is that the active
        // cell's CENTER sits under screen-center (offset) whenever the ayah is
        // stable (a few frames after a change, once the snap glide has landed).
        // The snap glide eases over many frames, so "settled" = the active ayah AND
        // the offset have both been stable for a stretch (the glide has landed). Only
        // then must the active cell's center sit under screen-center.
        let checked = 0;
        for (let i = 8; i < frames.length; i++) {
            const f = frames[i]!;
            if (f.silent || f.activeAyah == null) continue;
            const win = frames.slice(i - 8, i);
            const ayahStable = win.every((p) => p.activeAyah === f.activeAyah);
            const offStable = win.every((p) => Math.abs(p.off - f.off) < 0.5); // glide landed
            if (!ayahStable || !offStable) continue;
            const c = byAyah.get(f.activeAyah);
            if (!c) continue;
            const center = c.cumBefore + c.w / 2;
            // The needle never renders in snap mode (no continuous cursor).
            expect(f.needle, `no needle in snap mode @${f.t}ms`).toBe(false);
            expect(Math.abs(f.off - center), `active cell centered @${f.t}ms ayah ${f.activeAyah}`).toBeLessThan(2);
            checked++;
        }
        expect(checked, 'sampled settled snap-mode frames').toBeGreaterThan(10);
    });
});
