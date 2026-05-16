# YouTube audio integration design

## Summary

YouTube should be treated as an **ingestion source** by default, not as a native
Inspector audio transport.

The Inspector's editing surfaces assume an `HTMLAudioElement` backed by a direct
audio resource or a server-generated clip. That gives us file-absolute time,
repeatable segment playback, waveform/peaks extraction, Web Audio gain control,
and local cache behavior. Official YouTube playback does not expose that shape:
the supported browser API is an embedded player, not a raw audio URL.

## Options

| Option | Fit | Notes |
|---|---|---|
| Import YouTube audio into local/cache files | Best | Use YouTube as source metadata, then normalize into existing audio pipeline. |
| Official YouTube iframe playback | Limited | Good for listening, weak for precise trim/split, waveform, Web Audio, and cache. |
| Runtime `yt-dlp` + `ffmpeg` clipping | Technically possible, operationally fragile | Depends on signed expiring URLs and site internals; has policy risk. |

## Current manifest behavior

`docs/adding-a-reciter.md` already allows YouTube URLs in reciter manifests via
`scripts/playlist_manifest.py`. Validation treats YouTube reachability
differently from direct MP3 URLs and uses `yt-dlp --simulate`.

That is a metadata/ingestion convenience. It should not be confused with a
stable direct audio URL that the Inspector can put into `<audio src=...>`.

## Why YouTube is different

Direct MP3/FLAC/WAV sources:

- Browser can load the URL in `<audio>`.
- Server can run `ffmpeg` against the URL or a local cached file.
- Peaks endpoint can decode exact time windows.
- `AudioPort` can choose CBR full-file playback or VBR server-clip playback.

Official YouTube:

- Browser playback is via the YouTube iframe player.
- The app gets player controls such as load, play, pause, seek.
- The app does not get a stable audio file URL.
- The app does not get decoded samples for waveform drawing or Web Audio.
- Server-side clipping is not available through the official browser/player API.

Unofficial YouTube extraction:

- `yt-dlp` can resolve signed DASH/HLS audio URLs.
- `ffmpeg` can read those URLs and produce clips.
- URLs expire and may require cookies or authentication.
- Behavior can break when YouTube changes internals.
- Separating/downloading audio may be restricted by platform terms and rights.

## Recommended architecture

### Preferred: YouTube as import source

Pipeline:

```text
YouTube playlist/video URL
  -> yt-dlp metadata/probe
  -> rights/compliance gate
  -> download or transcode to managed audio file
  -> store/cache under a normal audio source
  -> Inspector uses existing AudioPort transport
```

After import, the Inspector sees a normal source:

- CBR direct-file transport, or
- VBR server-clip transport when metadata says the file needs it.

This preserves existing trim/split/playback behavior and avoids adding a second
media model to every editing surface.

### Secondary: embedded YouTube playback transport

Only use this when we want lightweight listening without precise editing tools.

Potential transport shape:

```ts
type AudioTransport =
    | { kind: 'direct-file' }
    | { kind: 'server-clip' }
    | { kind: 'youtube-iframe'; videoId: string };
```

The `youtube-iframe` strategy would need a separate player adapter:

- `load(startMs, endMs)` -> `player.loadVideoById({ videoId, startSeconds, endSeconds })`
- `seek(fileMs)` -> `player.seekTo(fileMs / 1000, true)`
- `currentTimeMs()` -> `player.getCurrentTime() * 1000`
- `play/pause` -> iframe API calls

Limitations:

- No native `<audio>` element.
- No Web Audio kill-switch.
- No local waveform/peaks unless a separate ingestion/clipping path exists.
- Less precise boundary enforcement because control is delegated to the iframe.
- Different event model from `HTMLAudioElement`.

This should be a separate strategy, not a hidden branch inside the current
CBR/VBR boolean.

## AudioPort implications

The current `AudioPort` should evolve from:

```ts
{ audioUrl, cbrSrc, reciter, vbr: boolean }
```

to an explicit transport/capability model:

```ts
type TransportCapabilities = {
    canSeekWithinLoaded: boolean;
    exposesAudioElement: boolean;
    supportsServerClips: boolean;
    supportsPeaks: boolean;
};
```

CBR direct files:

- `canSeekWithinLoaded = true`
- reusable by broad coverage

VBR server clips:

- `canSeekWithinLoaded = false`
- reusable only when clip start matches requested start

YouTube iframe:

- `exposesAudioElement = false`
- no direct peaks/cache/WebAudio support
- should probably live behind a separate player adapter

## Practical recommendation

For Inspector editing, implement YouTube support as:

1. Extend ingestion tooling and validation around YouTube manifests.
2. Download/transcode/cache audio only where we have permission to do so.
3. Normalize imported audio to managed files before opening in Inspector.
4. Keep runtime playback on existing direct-file/server-clip transports.

Only add a `youtube-iframe` runtime strategy for a read-only listening surface,
not for trim/split alignment editing.
