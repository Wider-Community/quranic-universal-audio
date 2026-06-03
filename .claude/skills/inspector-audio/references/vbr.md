# VBR (variable bitrate) handling

VBR-MP3 is the single largest source of correctness bugs in the audio subsystem. This page is the consolidated reference for everything that exists *because* of VBR.

## Why VBR is hard

CBR-MP3 has a constant byte-rate, so `byte = bytes_per_sec * t` lets any client (browser, ffmpeg, byte-range-aware backend) seek to a time by computing a byte offset. VBR breaks that — the byte ↔ time map is non-linear and recoverable only via the **Xing TOC** header at the start of the file.

Without a Xing header the browser does not know where to land for `audio.currentTime = t`, so it linearly extrapolates from `bytes_per_sec` and lands seconds (sometimes tens of seconds) off. This is the canonical "VBR seek drift" symptom.

## The two-pronged fix

The subsystem fights VBR on two fronts:

1. **Inject the Xing TOC at extraction time** so the browser-side seek path Just Works for the chapter MP3 on the bucket. Done offline on Katana — `.local/extraction/segments/audio_persist.py::_ensure_xing`.
2. **Route per-segment playback through a server-side clip endpoint** so we don't need browser-side seeks at all. `routes/audio/clip.py` + `lib/playback/audio-port.ts` (VBR branch).

Both exist because (1) only covers chapters Katana has extracted + uploaded to the bucket; (2) covers the gap (anonymous browsing, pre-extraction onboarding, by_ayah deliveries served straight from the CDN).

## Xing TOC injection

`.local/extraction/segments/audio_persist.py::_ensure_xing` (`audio_persist.py:85-119`). Runs **offline on Katana**, not in the Space — there is no in-Flask remux anymore. Applied to every by_surah chapter (no `is_vbr` gate at this layer — it's a no-op for already-seekable CBR):

```
ffmpeg -y -i <src> -c:a copy -f mp3 -v error <dest>
```

`-c:a copy` means no re-encode. The trick is `-f mp3`: ffmpeg's mp3 **muxer** writes a Xing/Info header (Frames count + TOC + bytes) at file start whenever the output is seekable. No `-bsf:a mp3_to_xing` bitstream filter — that filter is non-existent in ffmpeg and was the reason the old in-Space worker silently shipped raw bytes (see `prefetch.md` "what's gone"). The browser uses the frame count for `<audio>.duration` and the TOC for byte-offset seeks. Fixes both true VBR and CBR-with-unset-padding-bit drift.

**Failure mode:** if ffmpeg returns non-zero / output is empty, `_ensure_xing` returns `False`; `_process_one` falls back to copying the source as-is. That chapter then has the legacy mis-seek issue — playback works, seek drifts. There is **no Space-side remux to retrigger** — re-run Katana extraction for the chapter. (No `ffmpeg_remuxed` audit field exists post-worker-removal.)

**Detect at runtime:**

```bash
ffmpeg -i reciters/<slug>/audio/<chapter>.mp3 2>&1 | grep -iE 'xing|vbri|info'
```

Presence of `Xing`, `VBRI`, or `Info` tags ⇒ seekable. Absence with `bitrate_mode == "vbr"` in the sidecar ⇒ remux failed.

## Segment-clip route

`routes/audio/clip.py` — `seg_segment_clip(reciter)`, `segment_clip_bp`. Endpoint `/api/seg/segment-clip/<reciter>?url=…&start_ms=…&end_ms=…`. Streams an ffmpeg-extracted clip:

```
ffmpeg -hide_banner -loglevel error \
       -ss <start_sec> -i <source> -t <dur_sec> \
       -vn -c:a libmp3lame -b:a 96k -ac 1 -f mp3 -
```

**`-vn` is load-bearing.** The stripped static ffmpeg has no png encoder; an mp3-mux of a source with embedded APIC cover-art fails to "200 OK / 0 bytes" without it. Any new ffmpeg-mux path must replicate this.

Key properties:

| Property | Value | Why |
|---|---|---|
| Output bitrate | 96 kbps mono | matches audio_proxy tradeoff — speech-friendly, ~10 KB/s wire |
| Chunk size | 64 KB (`STREAM_CHUNK_BYTES`) | tight TTFB, amortised syscall overhead |
| Source preference | local file (mount/bytes) if present, else upstream URL | drops ffmpeg seek work from ~0.7 s (HTTP fetch) to ~0.15 s (local read) |
| URL allowlist | `_is_known_chapter_url` = `audio_meta.chapter_for_url(reciter, url) is not None` (**sidecar-keyed, not `detailed.json`** — the per-entry `audio` field is `""` post-migration-#5) | rejects open-proxy abuse |
| Scheme allowlist | `http` / `https` only | parsed via `urlparse` |
| CORS | `Access-Control-Allow-Origin: *` | required by `MediaElementAudioSourceNode` for the kill-switch to silence |
| Cache-Control | `public, max-age=31_536_000, immutable` | clip URL is deterministic on `(url, start_ms, end_ms)` so browser HTTP cache absorbs repeat plays |
| Process cleanup | timeout `FFMPEG_FULL_TIMEOUT = 300 s`, kill on timeout | logs `cmd` on timeout for forensics |

**ffmpeg can fetch HTTPS in the deployed image** (since the Dockerfile flipped to `--enable-openssl` + `http,https,tcp,tls`). The upstream-URL fallback path now works in deployed mode; the local-cache short-circuit is purely a latency optimization (~0.7 s → ~0.15 s for ffmpeg seek/decode).

## AudioPort VBR mode

`lib/playback/audio-port.ts` (~694 lines). The port owns the CBR-vs-VBR transport decision per call to `loadCovering(startMs, endMs, pad?)`.

VBR branch (`audio-port.ts:307-333`):

```ts
const clipStart = Math.max(0, startMs);
const clipEnd = needEnd;             // pad applied to end only
desiredUrl = buildClipUrl(reciter, audioUrl, clipStart, clipEnd);
desiredWin = { startMs: clipStart, endMs: clipEnd, offsetMs: clipStart, src: desiredUrl, isClip: true };
```

`offsetMs = clipStart` is the recovery: callers see file-absolute ms, port writes `(fileMs - offsetMs) / 1000` into `el.currentTime`. The clip plays from byte 0, no in-clip seek needed.

**Reuse rule for VBR clips** (`_canReuseWindow`, `audio-port.ts:426-440`; the strict-equality clip line is `:437`):

```ts
return current.startMs === desired.startMs && current.endMs >= needEnd;
```

Reusing a clip whose start is **earlier** than the requested start would force `currentTime` to seek inside the streamed clip — and a seek into a not-yet-buffered streamed response can stall or be ignored. This is exactly the failure mode the abstraction is supposed to hide. Strict equality on `startMs` is intentional. CBR reuse is more permissive: `current.startMs <= needStart && current.endMs >= needEnd`.

**Padding semantics:** `pad` extends `endMs` only in VBR mode. Padding the start would shift the clip start, breaking the reuse rule and forcing a re-fetch every call.

**Pending-promise reuse** (`audio-port.ts:342-349`): a follow-up `loadCovering` arriving during a swap that's already covered by the in-flight target window returns the same `pendingPromise` with `swapped: true`, so the caller awaits canplay instead of seeking into a still-loading element.

**Sync `_window` write** (inside `_swapTo`, `audio-port.ts:591-630`; `this._window = win` at `:605`): `_window` is set the moment the swap *starts*, not when canplay fires. A follow-up call during the swap sees the new window's `offsetMs` and either reuses (covers) or aborts and starts a fresh swap (doesn't cover) — instead of fast-pathing against stale data and writing wrong `currentTime` into a still-loading element. The audible regression this prevents: in VBR Adjust mode, an immediate split-left/right click after enter would seek and play before the wider clip's canplay had updated `_window`, landing the playhead in the wrong file-absolute position.

## Frontend VBR routing

`audio_meta.vbr_chapters_for_reciter(reciter)` is shipped to the frontend as a sorted list of VBR chapter numbers. `tabs/segments/utils/playback/range-spec.ts::vbrClipForChapter` consults this list to decide CBR vs VBR per segment — works for cross-chapter accordion rows (sibling jumps that span chapters with different encoding).

Non-integer keys (by_ayah `"<s>:<a>"`) are skipped — only by_surah deliveries expose VBR today.

## VBR-only bug shapes

| Symptom | Root | First probe |
|---|---|---|
| Seek lands seconds off, only on Adjust mode | `_window` not yet updated when split-click fires; pending-promise reuse logic skipped | check `audio-port.ts:342-349` is not bypassed by a custom load path |
| Seek lands seconds off, all modes | Xing remux failed → raw VBR shipped | `ffmpeg -i reciters/<slug>/audio/<ch>.mp3` look for Xing tag |
| Clip URL works in dev but 500s in deployed | upstream URL fetch failed inside ffmpeg — usually network egress block, not the binary | check Space outbound rules; confirm `curl -I <url>` works from inside the container |
| Reusing same clip plays wrong content | reuse-rule violation — `startMs` not equal | log `current.startMs`, `desired.startMs` from `_canReuseWindow` |
| Cross-chapter accordion plays wrong transport | frontend `vbr_chapters_for_reciter` stale (sidecar updated, FE didn't refetch) | check the per-reciter VBR map exposed to the frontend |
| Audible glitch at clip boundary in advance mode | `endMs` clip end didn't have post-roll pad — boundary flush has no audio to drain | bump `defaultPadMs` on the AudioPort instance |
| Clip 403s in browser | `_is_known_chapter_url` rejected — URL not in `detailed.json` for that reciter | check `entry.audio` in `detailed.json` matches exactly |
| Clip plays but stops short by ~0.5s | ffmpeg `-t` truncation at frame boundary; expected for VBR | acceptable, document if user reports |

## Dataset packaging — slicing chapter audio

The HF dataset (`scripts/release/build_reciter.py`) slices per-ayah audio out of chapter files. When it sources from the **bucket** chapter (provenance: same bytes MFA aligned against) instead of re-downloading from the CDN, two VBR-specific gotchas apply — both measured, not theoretical:

**Per-slice Xing depends on the output being seekable, not on `-f mp3`.** A mid-chapter `-c copy` slice written to a `.mp3` **file** gets a fresh per-slice Xing TOC automatically (the `.mp3` extension already selects the mp3 muxer, and the muxer backfills the frame count because the file is seekable). The `-f mp3` flag only matters when the output path has no `.mp3` extension. The real failure case is **piping to stdout** (`-f mp3 -`): ffmpeg can't seek back to backfill the count, Xing offset comes out `-1`, and the slice reintroduces the canonical VBR seek-drift bug. **Rule for the packaging writer: slice VBR chapters to seekable files, never through a pipe.** (CBR slices need no Xing — linearly seekable.)

**`-c copy` is sample-inaccurate; re-encode VBR.** Frame-boundary snap is ~26.12 ms at 44.1 kHz (24.00 ms at 48 k), and the bit-reservoir + 529-sample decoder priming put a click at each copy-slice head. The current pydub path cuts sample-accurately. So: copy CBR ≥128k chapters (accept ~26 ms snap, or re-offset stored clip-relative timestamps), but **re-encode VBR chapters** (`-c:a libmp3lame` at ~source bitrate) — sample-accurate, clean gapless info, near-source quality. FLAC isn't worth the size for speech.

**Audio durability.** Chapter audio lives **only** at `reciters/<slug>/audio/<ch>.mp3` (`storage_paths.py`) — lifecycle state is a DB attribute, not a folder, and nothing copies audio on publish. Audio + peaks now **persist indefinitely** (the wip-audio sweeper was removed), so packaging that sources from the bucket can run at any time without a TTL race. When the bucket genuinely lacks a chapter, the script falls back to CDN re-download.

## When to add a new mitigation

VBR mitigations should live in either Xing-injection (extraction-time, on Katana) or segment-clip (request-time). Don't add a third path — adding a "fix in the AudioPort" is debt; adding a "let the frontend probe encoding mode" duplicates the sidecar.

YouTube / yt-dlp sources sidestep this entirely: extraction re-encodes them to **forced CBR** (128k / 44.1k / mono — see `extraction-intake.md`), so they never carry the VBR-without-Xing drift the mitigations above exist for.

If a new bug class shows up, prefer:

1. **Offline fix at extraction time** (modify `audio_persist.py::_ensure_xing` flags, add a fallback codec path; re-run extraction). No in-Space remux path exists to patch.
2. **Backend fix at request time** (segment-clip parameters, source preference).
3. **AudioPort transport tweak** only when the bug is genuinely browser-only (e.g. specific browser autoplay policy interaction).

Don't try to fix VBR bugs in `audio-range.ts` or per-component playback code — the abstraction exists exactly to keep that contamination out.
