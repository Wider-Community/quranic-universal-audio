# Peaks prefetch — segment-level

## Context

In **streaming mode** (the default — no `/api/seg/prepare-audio/<reciter>` call) the
Inspector's chapter audio is served via `audio_proxy.py:24` which 302-redirects to
the CDN when the local cache file is missing. Because chapter MP3s never land on
disk, the bulk-peaks computer in `services/peaks.py::get_peaks_for_reciter`
short-circuits with `if not local_path.exists(): continue` — so
`/api/seg/peaks/<reciter>?chapters=N` returns `{peaks: {}, complete: false}` and
chapter-level peaks **never load** in streaming mode.

The only thing that *does* fire is `_fetchPeaksForClick` (waveform/utils.ts:203),
which POSTs `/api/seg/segment-peaks/<reciter>` with the current segment's range.
Server-side that hits `compute_segment_peaks` → CBR Range-decode (~0.4 s) or
VBR ffmpeg time-seek (~0.7 s). The user pays that latency on every first
segment click in a streaming-mode session.

The covering-range cache + on-disk peaks JSON cache absorb repeats once a
segment has been computed — but the *first* click on each new segment is slow.

This plan adds a one-segment-ahead peaks prefetch symmetric to the audio
prefetch already shipped in `prefetch.ts`. Hooked at the same three sites in
`playback.ts`. Same routing logic — chapter mode advances by `Segment.index`,
accordion mode by list-position via `nextSiblingSeg`.

---

## What's already in place (don't reinvent)

- `inspector/frontend/src/tabs/segments/utils/playback/prefetch.ts` —
  `prefetchNextSegAudio(list, currentIndex, currentSrc, cache, currentChapter?)`.
  We mirror its shape.
- `inspector/frontend/src/tabs/segments/utils/playback/resolvers.ts` —
  `nextDisplayedSeg`, `nextSiblingSeg`. Reused as-is.
- `inspector/frontend/src/tabs/segments/utils/waveform/peaks-cache.ts` —
  `_findCoveringPeaks(url, startMs, endMs)` does a true covering check
  (`entry.startMs <= startMs && entry.endMs >= endMs`), so a wider prefetched
  range satisfies a narrower click-time lookup automatically.
- `inspector/frontend/src/tabs/segments/utils/waveform/utils.ts:203` —
  `_fetchPeaksForClick` shows the exact range computation + POST shape we
  want to mirror so the server-side disk-cache key matches.
- `inspector/frontend/src/tabs/segments/stores/chapter.ts:85` —
  `getAdjacentSegments(chapter, index)` reads from `segAllData` (all
  chapters), so it works for cross-chapter accordion siblings without extra
  plumbing.
- `inspector/routes/peaks.py:62` — `/api/seg/segment-peaks/<reciter>` is the
  endpoint. Stateless POST, dedup-able client-side via in-flight cache map.

---

## The function

New helper in `prefetch.ts`:

```ts
export function prefetchNextSegPeaks(
    list: Segment[] | null,
    currentIndex: number,
    prefetchCache: Record<string, Promise<unknown>>,
    currentChapter: number | null = null,
): void;
```

Same shape as `prefetchNextSegAudio` minus the `currentAudioSrc` param
(peaks have nothing analogous to "skip if same URL as current"). Behavior:

1. Resolve `next` via `nextSiblingSeg` (accordion mode, `currentChapter != null`)
   or `nextDisplayedSeg` (chapter mode).
2. Bail if no next, no `audio_url`, no `next.chapter`, or no
   `$selectedReciter`.
3. Compute the **same trim-padded range** `_fetchPeaksForClick` would use,
   so server cache key matches:
   ```ts
   const { prev, next: after } = getAdjacentSegments(next.chapter, next.index);
   const cfg = get(segConfig);
   const startMs = Math.max(prev?.time_end ?? 0,
                            next.time_start - cfg.trimPadLeft, 0);
   const endMs = Math.min(after?.time_start ?? Number.POSITIVE_INFINITY,
                          next.time_end + cfg.trimPadRight);
   ```
4. Bail if `_findCoveringPeaks(audio_url, startMs, endMs)` already covers
   (chapter peaks loaded from non-streaming sources, or a prior fetch
   already covered the window).
5. Bail if `cacheKey = ${audio_url}:${startMs}:${endMs}` is already in
   `prefetchCache` (in-flight or completed).
6. Fire the POST and stash the promise. Index the result via
   `indexSegPeaksBulk` on success so `_findCoveringPeaks` finds it on the
   subsequent click.

The POST body matches `_fetchPeaksForClick` exactly:
```ts
fetchJson<SegSegmentPeaksResponse>(
  `/api/seg/segment-peaks/${reciter}`,
  { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ segments: [{ url, start_ms, end_ms }] }),
  },
).then(data => indexSegPeaksBulk(data.peaks ?? null))
 .catch(() => {});
```

No `cached_only` flag — we want to compute on a miss; that's the point of
prefetching.

---

## Call sites (mirror the audio-prefetch ones)

All three sites in `playback.ts` already call `prefetchNextSegAudio`. Add
`prefetchNextSegPeaks` next to each, with a separate module-level cache map.

### 1. Boundary auto-advance — `playback.ts:148`

```ts
prefetchNextSegAudio(displayed, next.index, _curChapterUrl(), _segPrefetchCache);
prefetchNextSegPeaks(displayed, next.index, _segPeaksPrefetchCache);
```

Chapter-mode autoplay only fires this site, so no chapter pointer needed.

### 2. `playFromSegment` — `playback.ts:250-256`

```ts
if (isAccordionPlay && opts?.accordionSiblings) {
    prefetchNextSegAudio(opts.accordionSiblings, segIndex,
                         _curChapterUrl(), _segPrefetchCache, resolvedChapter);
    prefetchNextSegPeaks(opts.accordionSiblings, segIndex,
                         _segPeaksPrefetchCache, resolvedChapter);
} else {
    prefetchNextSegAudio(displayed, segIndex,
                         _curChapterUrl(), _segPrefetchCache);
    prefetchNextSegPeaks(displayed, segIndex, _segPeaksPrefetchCache);
}
```

### 3. Cross-segment shared-audio detection — `playback.ts:362`

```ts
prefetchNextSegAudio(displayed, nextCurrentIdx, currentSrc, _segPrefetchCache);
prefetchNextSegPeaks(displayed, nextCurrentIdx, _segPeaksPrefetchCache);
```

Same chapter-mode shape.

### Module-level cache

In `playback.ts` next to the existing `_segPrefetchCache`:
```ts
const _segPeaksPrefetchCache: Record<string, Promise<unknown>> = {};
```

Cleared by `clearPerReciterState` — symmetric to `_segPrefetchCache`.

---

## Files modified

**`inspector/frontend/src/tabs/segments/utils/playback/prefetch.ts`**
- Add `prefetchNextSegPeaks` + necessary imports (`get`, `selectedReciter`,
  `getAdjacentSegments`, `segConfig`, `_findCoveringPeaks`,
  `indexSegPeaksBulk`, `fetchJson`, `SegSegmentPeaksResponse`).
- Update file-level comment to describe the two-prefetcher contract.

**`inspector/frontend/src/tabs/segments/utils/playback/playback.ts`**
- Import `prefetchNextSegPeaks`.
- Add `_segPeaksPrefetchCache` module-local.
- Add the three call-site additions above.

**`inspector/frontend/src/tabs/segments/utils/data/clear-per-reciter-state.ts`**
- Clear `_segPeaksPrefetchCache` alongside `_segPrefetchCache`. (Reciter
  change invalidates all peaks state — covering-range cache is already
  cleared via `clearSegPeaksCache`, and chapter-data is reloaded.)

**`inspector/frontend/src/tabs/segments/utils/playback/__tests__/prefetch.test.ts`**
- Add a `prefetchNextSegPeaks` test block. Mirrors the existing
  `prefetchNextSegAudio` test layout: chapter-mode hit, accordion sibling
  hit, covering-cache early-out, in-flight dedup, missing reciter, no-next.
  Mock `_findCoveringPeaks` and the `fetchJson` POST.

---

## Edge cases the design handles

1. **Repeat fires for the same next-seg** (autoplay then user clicks the
   same row mid-gap): `prefetchCache[cacheKey]` is set on first call →
   second call early-outs.
2. **Chapter peaks load mid-session** (e.g. user has clicked five segments
   so the per-segment cache is populated, then a non-streaming peaks load
   fills `getWaveformPeaks(audioUrl)`): `_findCoveringPeaks` short-circuits
   to the chapter-level entry → prefetch no-ops.
3. **Accordion sibling from a different chapter** —
   `getAdjacentSegments(next.chapter, next.index)` reads
   `segAllData` (which holds *all* chapters) so it works regardless of
   active chapter. No new plumbing required.
4. **Network failure** — the `.catch(() => {})` swallows; `_fetchPeaksForClick`
   on click runs the same POST and may succeed. Stash stays as a rejected
   promise in the cache map, so we don't retry under prefetch — but click
   is a fresh `fetchJson` outside the prefetch cache, so the user-visible
   path is unaffected.
5. **`segConfig.trimPadLeft/Right` changed mid-session** — prefetch caches
   the previously-padded range; click computes the new padded range. If the
   new range fits inside the old, `_findCoveringPeaks` still hits.
   Otherwise click misses cache and re-fetches with new padding (correct).
6. **`next.chapter == null`** — bail. Prevents `getAdjacentSegments(null, …)`
   silliness; matches `prefetchNextSegAudio`'s sibling-mode early-out.
7. **`audio_url` missing on next** — bail. (Same as the audio prefetcher.)

---

## Non-goals

- **CBR audio prefetch** — separately analyzed and dropped: HTTP cache-key
  alignment between our prefetched Range and the media element's later
  Range request is unreliable, and the browser's pre-buffer covers the
  consecutive-autoplay case for free.
- **Bulk chapter-peaks prefetch on accordion open** — too speculative.
  Server-side compute is 5–30 s per chapter; the user might never click
  any segment from the alt-chapter. Targeted next-sibling prefetch (this
  plan) wins on hit-rate and cost.
- **Two-segment-ahead prefetch** — diminishing returns, more compute load.
  By the time the user is on segment N+1, segment N+2's prefetch fires from
  the boundary-advance hook.
- **Background polling for chapter peaks in streaming mode** — that's a
  separate, larger change (would require server-side downloading the
  chapter file or using `compute_segment_peaks`-style Range decode for
  whole-chapter peaks). Out of scope here.

---

## Verification

End-of-change gate:

```sh
cd inspector/frontend
npm run check
npm run test
npm run lint
npm run build
```

Manual smoke (streaming mode, no `prepare-audio` call):

| Surface | Before | After |
|---|---|---|
| Chapter mode autoplay seg N → N+1 | ~0.4–0.7 s peaks delay on N+1 first display | instant (peaks pre-cached during N play) |
| Click row in main list → autoplays | first row pays ~0.4–0.7 s; row N+1 prefetched | next row instant on click |
| Accordion same-chapter sibling click | ~0.4–0.7 s on first click | instant (sibling prefetched on prior play) |
| Accordion cross-chapter sibling click | ~0.4–0.7 s on first click | instant (sibling prefetched, cross-chapter padding correctly resolved via `getAdjacentSegments(otherChapter, …)`) |
| Re-click already-played seg | instant | instant (no regression) |
| Reciter change | clears all peaks state | still clears (incl. `_segPeaksPrefetchCache`) |

Network panel check: while playing seg N in streaming mode, expect a
single background POST to `/api/seg/segment-peaks/<reciter>` for seg N+1
(or the next sibling). On click, no fresh POST should fire — the
covering-range cache absorbs.
