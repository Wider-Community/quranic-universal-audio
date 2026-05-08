/**
 * Playback-layer constants shared across `AudioPort` / `AudioRange` consumers.
 */

/**
 * Coverage padding (ms) that edit-mode entry adds around `[seg.time_start,
 * seg.time_end]` when calling `port.loadCovering(...)`. Under VBR routing,
 * this means edit-mode loads a wider per-segment clip ONCE so subsequent
 * trim/split adjustments and split-left/split-right toggles stay inside the
 * loaded window — no fresh ffmpeg invocation per press.
 *
 * 2 s is enough for typical edit nudges; if a drag pushes the trim window
 * past the loaded edge, the trim handler issues a fresh `loadCovering` with
 * the new wider range. See the edit-mode entry sites in `utils/edit/`.
 */
export const EDIT_LOAD_PAD_MS = 2000;
