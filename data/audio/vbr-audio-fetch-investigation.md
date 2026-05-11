# VBR Audio Fetch Investigation

Date: 2026-05-09

## Scope

Investigated Inspector VBR playback/fetch performance using real manifests and segment data.

Benchmark targets:

- `mohammed_alghazali`: all VBR chapters, `surah-quran` / Archive.org
- `yasser_al_dosari`: chapter 4, `mp3quran`
- `maher_al_meaqli`: chapter 76, `mp3quran`

Primary code path tested:

```bash
ffmpeg -hide_banner -loglevel error \
  -ss <start_sec> -i <url> -t <duration_sec> \
  -c:a libmp3lame -b:a 96k -ac 1 -f mp3 -
```

This matches the backend behavior of `/api/seg/segment-clip/<reciter>` when the source chapter is not already in the local audio cache.

## Summary

Ghazali slowness is mainly remote HTTP seek/fetch latency from Archive.org, not ffmpeg CPU.

Evidence:

- Archive.org TTFB was much slower than `mp3quran`.
- Remote ffmpeg on Ghazali often waited multiple seconds before producing the first byte.
- Some deep Ghazali seeks timed out before first byte.
- The same ffmpeg clip extraction from a local cached Ghazali chapter completed in under 0.5s.

Conclusion:

- `ffmpeg` is not the main bottleneck.
- The bottleneck is remote time-seeking into VBR MP3s hosted on Archive.org.
- Full-chapter local caching is the safest optimization.

## Network Timing

Tiny `curl -r 0-0` probes:

| Source | URLs | TTFB p50 | TTFB p90 | Max |
| --- | ---: | ---: | ---: | ---: |
| `ia601406.us.archive.org` / Ghazali | 114 | 1.48s | 1.55s | 6.49s |
| `server11.mp3quran.net` / Dosari | 1 | 0.18s | 0.18s | 0.18s |
| `server12.mp3quran.net` / Maher | 1 | 0.08s | 0.08s | 0.08s |

Archive.org is already slow before ffmpeg starts decoding useful audio.

## Remote ffmpeg Timing

Selected real segment windows:

| Source | Successful clips | Timeouts | First-byte p50 | First-byte p90 |
| --- | ---: | ---: | ---: | ---: |
| Ghazali / Archive.org | 11/18 | 7 | 4.9s | 11.4s |
| Dosari / mp3quran | 3/3 | 0 | 0.98s | 0.98s |
| Maher / mp3quran | 3/3 | 0 | 0.66s | 0.66s |

Observed Ghazali behavior:

- Early short surahs: roughly 3.1-6.6s first byte.
- Some deeper starts: 10-13s first byte.
- Several chapter 2 / chapter 4 windows timed out at 14s before producing any bytes.

Clip duration was not the main factor. Start position and remote source behavior mattered more.

## Local Cache Baseline

Downloaded full chapter once, then ran the same ffmpeg extraction locally:

| Source | Remote clip timing | Local clip timing |
| --- | ---: | ---: |
| Ghazali chapter 76 | 4.7-13.1s | 0.16-0.46s |
| Dosari chapter 4 | 0.69-1.02s | 0.17-0.75s |
| Maher chapter 76 | 0.58-0.74s | 0.12-0.37s |

This isolates the bottleneck: local ffmpeg is fast; remote Archive.org seeking is slow.

## Codec Strategy Check

Tested `-c:a copy` against the current transcode command:

| Source | Transcode | Stream copy |
| --- | ---: | ---: |
| Ghazali chapter 76 | 7.47s | 4.81s |
| Maher chapter 76 | 0.55s | 0.47s |
| Dosari chapter 4 | 1.00s | 0.78s |

`-c:a copy` can help, especially for Ghazali, but it does not remove the Archive.org remote seek cost. It also needs browser/playback validation before replacing transcode, because output frame boundaries and container behavior may differ.

## Source Catalog Shape

By-surah source manifests under `data/audio/by_surah/`:

| Source folder | Manifest count |
| --- | ---: |
| `mp3quran` | 281 |
| `surah-quran` | 42 |
| `qul` | 12 |
| `youtube` | 0 |

`surah-quran` manifests are mostly Archive.org-hosted. That does not mean every reciter is VBR, but it does mean they are more exposed to slow first-byte and remote seek behavior.

## surah-quran VBR Probe

Ran the same VBR detection logic as `scripts/probe_audio_meta.py` against `data/audio/by_surah/surah-quran/*.json`.

Implementation note:

- The stock script targets reciters globally and can hang on slow Archive URLs.
- For this investigation, the same `mutagen + frame-scan` classification logic was used with a hard `curl --max-time` wrapper.
- No changes were written to `data/.audio_meta.json`.

Results:

| Bucket | Count |
| --- | ---: |
| Total `surah-quran` manifests | 42 |
| Fully probed | 24 |
| Fully VBR | 6 |
| Mixed VBR/CBR | 5 |
| CBR-only among fully probed | 15 |
| Unknown-only | 2 |
| Fully unreachable under timeout | 4 |

Fully VBR:

```text
ahmed_nasr
khalil_alsaghir
mohammed_alghazali
muhammad_alsabil
rayan_almuhaisni
salah_aljamal
```

Likely fully VBR, but one chapter timed out:

```text
fahad_almutairi: 113/114 VBR
```

Mixed:

```text
saeed_alkhatib: 72/114 VBR
abdelmoujib_benkirane: chapter 7 only
ammar_louay_almulla_ali: chapter 18 only
anas_almiman: chapter 16 only
fahad_almutairi: 113/114 VBR, one timed-out chapter
```

Unknown, not classified as VBR:

```text
abdualhaleem_hussain: 114 UNKNOWN
ishak_danish: 114 UNKNOWN
anas_jalhoum: 1 UNKNOWN, 112 CBR, 1 timeout
```

Unreachable under timeout during spot checks:

```text
fatih_cholak
ghassan_alshorbagy
maher_alwan
salah_baothman
```

These URLs timed out even on a simple `curl -I --max-time 20` spot check.

## Interpretation

`surah-quran` should be treated as a slow/fragile source class because it is Archive.org-heavy.

But `surah-quran` should not be treated as universally VBR:

- Many probed reciters are CBR-only.
- A smaller set is all-VBR.
- A few are mixed.
- Some Archive hosts are currently too slow or unreachable to classify reliably.

The high-risk combination is:

```text
surah-quran / Archive.org + VBR + remote ffmpeg seek
```

Ghazali is in that high-risk bucket for every chapter.

## Recommendations

1. Add or expose a full-chapter VBR cache warmup.

   The current `/api/seg/segment-clip` route already prefers `cache.audio_cache_path(reciter, url)` when present. Once a chapter is cached locally, Ghazali clip extraction drops from multi-second/timeout behavior to sub-second behavior.

2. Warm the selected VBR chapter when entering edit/play surfaces.

   Good default: selected chapter only. Optional next step: nearby accordion chapters or an explicit "cache reciter audio" action.

3. Do not eagerly cache all Ghazali audio by default.

   Ghazali is approximately 31.5 hours of audio and roughly 2.17 GB estimated. Full-reciter cache should be explicit or background-managed.

4. Keep VBR routing per chapter, not per source folder.

   `surah-quran` is not uniformly VBR. Use `data/.audio_meta.json` / per-reciter VBR maps as the source of truth.

5. Consider `-c:a copy` as a secondary optimization.

   It reduces some processing time, but the dominant Ghazali cost remains remote seek/fetch. Validate browser behavior before changing the endpoint.

6. Longer-term: mirror or preprocess problematic Archive-hosted VBR reciters.

   Best options:

   - mirror to faster object storage/CDN;
   - normalize to seek-friendly CBR MP3;
   - generate cached chapter derivatives on demand.

## Not Recommended

Do not optimize VBR playback by estimating byte ranges from timestamp and downloading only that range.

Reason:

- It can be faster in benchmarks.
- But it relies on average bitrate time-to-byte math.
- That recreates the CBR assumption that caused wrong-range VBR behavior.
- It can silently drift or cut the wrong audio.

Correctness is more important here than shaving remote fetch time with unsafe byte arithmetic.
