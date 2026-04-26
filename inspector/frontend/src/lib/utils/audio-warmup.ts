/**
 * Warm the browser's audio pipeline on the first user gesture.
 *
 * The first <audio>.play() in a tab pays a one-time cost: the browser
 * allocates a media decoder, acquires the OS audio output device, and
 * walks through autoplay-policy gesture verification. This adds 200ms–
 * 1s+ to the first global play even when the bytes are already cached.
 * Subsequent plays reuse the warm pipeline and start instantly.
 *
 * Trick: on the first user gesture, play+pause a tiny silent MP3 via a
 * throwaway HTMLAudioElement. This drives the cold paths without
 * touching the real chapter audio. By the time the user clicks the
 * Play button (a later gesture), the pipeline is already warm.
 *
 * The MP3 below is a ~0.05s silent frame (data URI, ~250 bytes).
 * Decoded by the same MP3 decoder the chapter audio will use.
 */

const SILENT_MP3 =
    'data:audio/mpeg;base64,SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU4LjQ1LjEwMAAAAAAAAAAAAAAA//tQwAAAAAAAAAAAAAAAAAAAAABJbmZvAAAADwAAAAEAAAJAAJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiY//////////////////////////////////////////////////////////////////8AAAAATGF2YzU4LjkxAAAAAAAAAAAAAAAAJAYwAAAAAAAAAkBJSwQ4//tQxAADwAABpAAAACAAADSAAAAETEFNRTMuMTAwVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV//tSxAADwAABpAAAACAAADSAAAAEVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVVV';

let _warmed = false;

function _warm(): void {
    if (_warmed) return;
    _warmed = true;
    const a = new Audio();
    a.src = SILENT_MP3;
    a.preload = 'auto';
    a.volume = 0;
    const cleanup = (): void => {
        a.pause();
        a.removeAttribute('src');
        a.load();
    };
    a.play().then(cleanup, cleanup);
}

/**
 * Register a one-shot listener that fires on the first pointerdown,
 * keydown, or touchstart anywhere on the page. Idempotent — calling
 * twice is a no-op.
 */
export function installAudioWarmup(): void {
    if (_warmed) return;
    const opts = { once: true, capture: true } as const;
    document.addEventListener('pointerdown', _warm, opts);
    document.addEventListener('keydown', _warm, opts);
    document.addEventListener('touchstart', _warm, opts);
}
