/**
 * Playback-layer constants shared across `AudioPort` / `AudioRange` consumers.
 */

/**
 * Coverage padding (ms) that edit-mode entry adds around `[seg.time_start,
 * seg.time_end]` when calling `port.loadCovering(...)`. Under VBR routing,
 * the port treats this as post-roll only: the clip still begins at
 * `seg.time_start` so playback starts from clip time 0 and does not rely on
 * seeking inside the streamed clip.
 *
 * 2 s is enough for typical end-boundary nudges; if an edit changes the
 * start boundary under VBR, the port intentionally issues a fresh clip whose
 * byte 0 is the new playback start. See the edit-mode entry sites in
 * `utils/edit/`.
 */
export const EDIT_LOAD_PAD_MS = 2000;
