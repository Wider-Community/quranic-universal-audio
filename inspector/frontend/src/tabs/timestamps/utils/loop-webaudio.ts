/**
 * Sample-accurate Web Audio loop for the Timestamps loop.
 *
 * The main loop seeks `<audio>.currentTime` once per rAF frame, so each wrap
 * overshoots `end` by ~1 frame and bleeds the next phoneme into a tight
 * continuous-speech segment. This loops the exact `[start,end]` region via an
 * `AudioBufferSourceNode` (`loop=true`, `loopStart/loopEnd`): the audio engine
 * wraps it sample-accurately — zero overshoot, no bleed, no rAF in the path.
 *
 * The loop always plays at native rate; the caller locks the footer speed to
 * 1× while a loop is engaged (and restores it on exit), so no time-stretch is
 * needed here.
 *
 * The region is fetched as a small MP3 through the existing `segment-clip`
 * route, with generous padding then sliced out of the decoded PCM (a bare 40 ms
 * clip falls below the route's usable-audio guard and is buried in LAME
 * encoder-delay priming — padding clears both). An equal-power crossfade is
 * baked into the loop ends to mask the wrap click. The decoded clip is cached.
 *
 *   - `onReady` fires the instant WA audio starts, so the caller can mute the
 *     carrier `<audio>` element exactly at handoff — no silent gap.
 *   - `waLoopPosMs()` reports the playhead off the audio clock (minus output
 *     latency) so the caller can drive the highlight in sync with what's heard.
 *
 * Driven by `TimestampsTab`'s loop lifecycle.
 */

import { buildClipUrl } from '../../../lib/playback/audio-port';

/** Padding fetched on each side of the region, in ms — keeps the clip above
 *  the route's min-bytes guard and pushes encoder priming outside the slice. */
const PAD_MS = 200;
/** Equal-power crossfade baked into the loop ends to mask the wrap click. */
const CROSSFADE_MS = 4;

export interface WaLoopRequest {
	reciter: string;
	audioUrl: string;
	startMs: number;
	endMs: number;
	/** Fired synchronously the instant WA audio starts (for the mute handoff). */
	onReady?: () => void;
}

let ctx: AudioContext | null = null;
let node: AudioBufferSourceNode | null = null;
let gain: GainNode | null = null;
/** Bumped on every start/stop; an in-flight async start checks it to bail when superseded. */
let token = 0;
/** One-entry cache of the decoded padded clip, keyed by its clip URL. */
let clipCacheKey = '';
let clipCacheBuf: AudioBuffer | null = null;
/** Playhead bookkeeping for waLoopPosMs(). */
let posStartMs = 0;
let posLoopDurSec = 0;
let posStartedAt = 0;

function audioCtx(): AudioContext {
	if (!ctx) ctx = new AudioContext();
	return ctx;
}

async function decodedClip(c: AudioContext, url: string): Promise<AudioBuffer> {
	if (clipCacheKey === url && clipCacheBuf) return clipCacheBuf;
	const resp = await fetch(url);
	if (!resp.ok) throw new Error(`segment-clip ${resp.status}`);
	const buf = await c.decodeAudioData(await resp.arrayBuffer());
	clipCacheKey = url;
	clipCacheBuf = buf;
	return buf;
}

function teardown(): void {
	if (node) {
		try {
			node.stop();
		} catch {
			/* already stopped */
		}
		node.disconnect();
		node = null;
	}
	if (gain) {
		gain.disconnect();
		gain = null;
	}
	posLoopDurSec = 0;
}

/** Stop the current Web Audio loop (idempotent). */
export function stopWaLoop(): void {
	token += 1;
	teardown();
}

/** File-absolute ms of the WA playhead, synced to audible output, or null when
 *  no loop is running. Drives the highlight so it tracks what's actually heard. */
export function waLoopPosMs(): number | null {
	if (!node || !ctx || posLoopDurSec <= 0) return null;
	let elapsed = ctx.currentTime - posStartedAt - (ctx.outputLatency || 0);
	if (elapsed < 0) elapsed = 0;
	return posStartMs + (elapsed % posLoopDurSec) * 1000;
}

/** Start (or replace) the sample-accurate loop for a region. Throws if the
 *  clip fetch/decode fails so the caller can fall back to the rAF element. */
export async function startWaLoop(req: WaLoopRequest): Promise<void> {
	token += 1;
	const mine = token;
	teardown();

	const clipStartMs = Math.max(0, req.startMs - PAD_MS);
	const clipEndMs = req.endMs + PAD_MS;
	const url = buildClipUrl(req.reciter, req.audioUrl, Math.round(clipStartMs), Math.round(clipEndMs));
	const c = audioCtx();
	const decoded = await decodedClip(c, url);
	if (mine !== token) return; // superseded while fetching/decoding

	const region = sliceRegion(c, decoded, (req.startMs - clipStartMs) / 1000, (req.endMs - req.startMs) / 1000);
	const { buffer, loopEndSec } = bakeCrossfade(c, region, CROSSFADE_MS);
	await c.resume();
	if (mine !== token) return;

	const src = c.createBufferSource();
	src.buffer = buffer;
	src.loop = true;
	src.loopStart = 0;
	src.loopEnd = loopEndSec;
	const g = c.createGain();
	src.connect(g).connect(c.destination);
	req.onReady?.(); // mute the carrier element exactly at the WA handoff
	src.start(0, 0);
	posStartMs = req.startMs;
	posLoopDurSec = loopEndSec;
	posStartedAt = c.currentTime;
	node = src;
	gain = g;
}

/** Cut the exact `[offsetSec, offsetSec+durSec]` region out of a decoded
 *  (padded) clip, in sample space — independent of the clip's own padding. */
function sliceRegion(c: AudioContext, buf: AudioBuffer, offsetSec: number, durSec: number): AudioBuffer {
	const sr = buf.sampleRate;
	const channels = buf.numberOfChannels;
	const start = Math.min(Math.max(0, Math.round(offsetSec * sr)), buf.length);
	const len = Math.min(Math.round(durSec * sr), buf.length - start);
	const out = c.createBuffer(channels, Math.max(1, len), sr);
	for (let ch = 0; ch < channels; ch += 1) {
		out.getChannelData(ch).set(buf.getChannelData(ch).subarray(start, start + len));
	}
	return out;
}

/** Overlap-add the last `fade` samples onto the first `fade` so a native
 *  `loop` wraps seamlessly. Returns the shortened buffer + its loop end.
 *  At the wrap, sample `L-1` (= original `s[L-1]`) flows into sample `0`
 *  (≈ original `s[L]`) — continuous in the source signal. */
function bakeCrossfade(
	c: AudioContext,
	buf: AudioBuffer,
	fadeMs: number,
): { buffer: AudioBuffer; loopEndSec: number } {
	const sr = buf.sampleRate;
	const channels = buf.numberOfChannels;
	const n = buf.length;
	const fade = Math.min(Math.floor((fadeMs / 1000) * sr), Math.floor(n / 2));
	if (fade < 1) return { buffer: buf, loopEndSec: n / sr };

	const loopLen = n - fade;
	const out = c.createBuffer(channels, loopLen, sr);
	for (let ch = 0; ch < channels; ch += 1) {
		const inD = buf.getChannelData(ch);
		const outD = out.getChannelData(ch);
		outD.set(inD.subarray(0, loopLen));
		for (let i = 0; i < fade; i += 1) {
			const t = (i + 0.5) / fade;
			const wIn = Math.sin(0.5 * Math.PI * t);
			const wOut = Math.cos(0.5 * Math.PI * t);
			const head = inD[i] ?? 0;
			const tail = inD[loopLen + i] ?? 0;
			outD[i] = head * wIn + tail * wOut;
		}
	}
	return { buffer: out, loopEndSec: loopLen / sr };
}
