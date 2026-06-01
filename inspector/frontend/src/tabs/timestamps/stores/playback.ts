/**
 * Timestamps tab — playback control state.
 */

import { writable } from 'svelte/store';

import { AudioPort } from '../../../lib/playback/audio-port';

/** Auto-advance mode — null = off, 'next' = advance to next verse on end,
 *  'random-any' = load random verse from any reciter on end,
 *  'random-current' = load random verse from the currently-selected reciter on end. */
export type TsAutoMode = 'next' | 'random-any' | 'random-current' | null;

/** Current auto-advance mode. */
export const autoMode = writable<TsAutoMode>(null);

/** Guard against re-entry from the timeupdate handler when the end is crossed. */
export const autoAdvancing = writable<boolean>(false);

/** Audio element current time (seconds, absolute). Updated per animation frame. */
export const currentTime = writable<number>(0);

/** The <audio> element driving timestamps-tab playback. Set by TimestampsAudio
 *  on mount; cleared to null on destroy. Consumers null-check before use.
 *
 *  @deprecated Use `tsPort` instead. The audio element is now wrapped by
 *  the port; this export is retained transitionally. The Timestamps tab
 *  is currently CBR-only — when it gains VBR support, the port already
 *  carries the offset translation needed for clip-relative `currentTime`. */
export const tsAudioElement = writable<HTMLAudioElement | null>(null);

/** Single AudioPort for the Timestamps tab. TimestampsAudio attaches the
 *  bound `<audio>` element on mount; every consumer (waveform clicks,
 *  keyboard nudges, karaoke tick reads) imports this port and reads
 *  file-absolute milliseconds.
 *
 *  Coordinate space: file-absolute ms — always. The Timestamps tab is
 *  CBR-only today, so file-absolute equals `audio.currentTime * 1000`,
 *  but routing reads through the port keeps the codebase ready for VBR
 *  routing without a second-pass rewrite. */
export const tsPort: AudioPort = new AudioPort();

/** True when `tsPort` has an `<audio>` element bound. Mirrors the
 *  segments-tab `segPortReady` shape. */
export const tsPortReady = writable<boolean>(false);

/** Chapters of the selected timestamp reciter whose audio is known VBR. */
export const tsVbrChapters = writable<Set<number>>(new Set());

/**
 * Region loop state now lives in `lib/playback/loop` so the shared footer +
 * filmstrip (lib components) can also clear it. Re-exported here so existing
 * `../stores/playback` imports of `loopTarget` / `TsLoopTarget` keep working.
 * `exitLoop()` force-drops loop mode on any deliberate navigation.
 */
export { exitLoop, loopTarget } from '../../../lib/playback/loop';
export type { TsLoopTarget } from '../../../lib/playback/loop';
