# Runtime probing — driving the live stack

Reproduce a flow, capture correlated signals from every layer at once, hand back a **ranked summary**. The value is correlation: lining up a browser event against the matching `/api/` request against the Flask log line. None alone tells the story. (This methodology was the old `inspector-runtime-prober` agent; `performance-expert` owns it now.)

## Bring up the stack (background — never foreground, it blocks)

```
# Already running? check first:
curl -s -o /dev/null -w '%{http_code}' http://localhost:5000/healthz   # want 200 (503 = degraded)
curl -s -o /dev/null -w '%{http_code}' http://localhost:5173/          # want 200

# If down, launch with Bash(run_in_background=true) and capture both shell IDs:
python3 inspector/app.py                          # Flask, 0.0.0.0:5000 (config.py DEFAULT_PORT=5000)
cd inspector/frontend && npm run dev              # Vite, :5173 strictPort, proxies /api + /audio → 5000
```

Wait until `/healthz` returns 200 and the Vite bg log shows `ready`. **Always drive the Vite origin `http://localhost:5173`** — it proxies `/api` to Flask, so one network panel shows both stacks. Don't foreground-`sleep` to wait (blocked); poll with `curl` or grep the bg log.

## Playwright MCP — exact tool names + what each returns

| Goal | Call | Returns |
|---|---|---|
| Load page | `mcp__plugin_playwright_playwright__browser_navigate {url}` | nav ack |
| DOM/a11y state | `browser_snapshot` | accessibility tree (better than a screenshot for asserting state before/after the bad moment) |
| **Network waterfall** | `browser_network_requests {static:false, filter:"/api/"}` | numbered request list. `static:false` drops images/fonts/scripts; `filter` is a URL regexp |
| One request's detail | `browser_network_request {index:N}` | full timing/status/size/headers for request N |
| Console | `browser_console_messages {level:"error"}` (each level includes more-severe; `all:true` = since session start) | console lines |
| **Perf metrics / anything** | `browser_evaluate {function:"() => {...}"}` | whatever the (serializable) fn returns |
| Wait | `browser_wait_for {text|textGone|time}` | — |

## browser_evaluate recipes (paste the function body)

```js
// Cold load — navigation + paint timings
() => { const n = performance.getEntriesByType('navigation')[0];
  return { ttfb:Math.round(n.responseStart), dcl:Math.round(n.domContentLoadedEventEnd),
    load:Math.round(n.loadEventEnd), transfer:n.transferSize,
    fcp:Math.round((performance.getEntriesByType('paint').find(p=>p.name==='first-contentful-paint')||{}).startTime||0) }; }

// Heaviest resources (confirm a dep didn't leak into the main chunk)
() => performance.getEntriesByType('resource')
  .map(r=>({f:r.name.split('/').pop(), kb:Math.round(r.transferSize/1024), ms:Math.round(r.duration)}))
  .sort((a,b)=>b.kb-a.kb).slice(0,15);

// Long Tasks (jank) — register BEFORE the suspect action
() => { window.__lt=[]; new PerformanceObserver(l=>l.getEntries().forEach(e=>window.__lt.push(Math.round(e.duration)))).observe({entryTypes:['longtask']}); return 'observing'; }
// ...do the action (open tab / scroll virtualized list / zoom waveform)...
() => window.__lt;   // each entry >50ms is a frame-blocking task

// JS heap (Chromium)
() => performance.memory && {usedMB:Math.round(performance.memory.usedJSHeapSize/1048576)};

// Total transfer bytes (before/after a change)
() => performance.getEntriesByType('resource').reduce((a,r)=>a+(r.transferSize||0),0);
```

## Correlate browser ↔ Flask log

Flask log format is `HH:MM:SS LVL name | msg` (`app.py:109-129`) — **no date, no request-id**. So correlate by (a) HH:MM:SS wall time and (b) the request **path**. Procedure: from `browser_network_requests {filter:"/api/"}` note the slow request's path + when it fired; then read the Flask bg shell log **once**, grepping for that path; align: browser issues request → Flask logs the route (same second, matching path) → Flask response → browser fires next event. Gaps or out-of-order = the anomaly. (`httpx`/`httpcore` are silenced to WARNING, so bucket-read INFO won't drown the log — but you also won't see per-read timing unless you raise that logger.)

**Reading bg logs without context overflow:** never re-dump a whole bg shell. Read it once, after the relevant browser action, filtered by the path/string you already identified. Same for `browser_network_requests` — use `filter:` + `static:false`; pull full detail for only the one offending index.

## Output discipline

Never paste a 200-line waterfall or full console dump. Rank to the **top 3–5 anomalies**, each one quoted line of evidence (network OR console OR backend log) + a `file:line` pointer, plus a one-paragraph hypothesis. (The `performance-expert` agent's output format encodes this.)

## Local-vs-HF (probing)

A local Playwright probe measures the **Flask dev server**, not deployed gunicorn-gthread `-w 1`. 

**Trustworthy locally** (FE-only, no server CPU/concurrency dependence): bundle/transfer sizes, paint timings, Long Tasks from FE rendering (waveform draw, list virtualization, `$effect` storms), client decode cost (`b64ToInt8`, quran-refs `JSON.parse`), the number/shape of `/api` requests a flow fires.

**Misleading locally:** absolute `/api` response times, concurrent-user contention, single-worker serialization, bucket-read latency (mount vs `hffs` differs both ways). Always state which class a measurement falls in. Reason about concurrency via "× N", not local wall-clock. Calibrate the bucket-I/O gap with `inspector/scripts/bench_storage.py --mount` vs no-mount before trusting any save/append number.

## Recipes (copy-pasteable)

**A. Measure cold page load.** Bring up stack, confirm `healthz`=200, then `browser_navigate` → the cold-load eval above → `browser_network_requests {static:true}` once to confirm `index-*.js`(~774KB)+`index-*.css`(~946KB) are the blockers and `charts-*.js` is ABSENT.

**B. Find the slow request in a flow.** Navigate, do the click path, `browser_network_requests {static:false, filter:"/api/"}` → scan for high duration/size → `browser_network_request {index:N}` for the worst → read the Flask bg shell once, grepping the same path → align HH:MM:SS. Repeat with a **second reciter/chapter/role** (dev role switcher) — a slowdown on only one input is a data/routing bug, not logic.

**C. Catch a Long Task / jank.** Register the observer (recipe above) BEFORE the action; perform it (open Segments, scroll the virtualized list, zoom the waveform); read `window.__lt`. Culprits to check: `lib/utils/waveform-draw.ts`, `waveform/draw-seg.ts`, `peaks-decode.ts`, `quran-refs.ts`, or an over-firing reactive block (`SegmentsTab.svelte:284-294`).

**D. Diff network payload before/after.** Capture total-transfer + heaviest-15 baseline → apply change → `cd inspector/frontend && npm run build` → re-probe. For build-only diffs, `ls -l inspector/frontend/dist/assets/` is fastest.
