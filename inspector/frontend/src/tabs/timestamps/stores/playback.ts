/**
 * Timestamps tab — region-loop re-export shim.
 *
 * Live playback state for the tab flows through the shared `dashPort`; the only
 * tab-local playback state is the region loop, which lives in `lib/playback/loop`
 * so the shared footer + filmstrip (lib components) can also clear it. It's
 * re-exported here so the tab's `../stores/playback` imports resolve.
 * `exitLoop()` force-drops loop mode on any deliberate navigation.
 */

export { exitLoop, loopTarget } from '../../../lib/playback/loop';
export type { TsLoopTarget } from '../../../lib/playback/loop';
