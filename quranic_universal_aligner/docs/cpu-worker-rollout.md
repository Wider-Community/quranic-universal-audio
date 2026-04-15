# CPU Worker Pool — Rollout Plan

Plan for hardening the main↔worker CPU dispatch, wiring it through all endpoints, building the test and observability story, and deciding when to scale beyond 1 worker.

## 0. Current state

- 1 worker Space (`hetchyy/quranic-universal-aligner-cpu1`)
- Transport layer deployed: `float32`, `int16` (default), `ogg` on worker side
- Worker `concurrency_limit=1`, main `concurrency_limit=20` — concurrent GPU+CPU on main verified
- fp32-on-CPU fix deployed (no fp16 inference on commodity x86)
- Hook point: `gpu_with_fallback.wrapper` in `src/core/zero_gpu.py`
- Demand analysis (Mar 16 – Apr 12, 1,716 rows): **19 CPU req/day mean, peak distinct-user concurrency = 2** (twice in 26 days). One worker stays under 2 % utilisation. Don't scale yet.

## 1. Hardening (before scaling, before prod)

Ordered by priority. Each item is self-contained and testable.

### 1.1 Pool status endpoint
`/pool_status` returns per-worker state: `slug`, `busy`, `unhealthy_since`, `total_jobs`, `last_duration`, `last_error`, (future) `queue_depth`, `eta_free_at`. HF-token-gated. Used for debugging, external monitoring, and admission-control decisions.

### 1.2 Health-check auto-recovery
Today `unhealthy_since` gets set on failure and never cleared — one blip kills a worker until main restarts. Add a background thread that every 30 s pings each unhealthy worker with a trivial `cpu_exec` call (`is_user_forced_cpu` returns immediately). On success, clear `unhealthy_since` under the condition-variable lock and notify waiters.

### 1.3 HTTP session reuse
Swap per-call `requests.post(...)` for `requests.Session()` per worker. Saves one TCP handshake + TLS per dispatch (~100–300 ms). Minor but compounds.

### 1.4 Clearer pool-exhausted errors
Max acquire timeout → 2 min (down from 3600 s). Surface as `gr.Error("System busy, try again in a minute")` to the UI. Distinguish in logs: pool-exhausted vs worker-crashed vs worker-timeout.

### 1.5 Max queue depth (admission control)
If the pool has been fully-busy for longer than some threshold, new requests get rejected early instead of piling up. Prevents cascading degradation under runaway load. Paired with the friendly error above.

### 1.6 Transport default — two viable options

Benchmark summary (encode + upload, for the same compute):

| Audio | int16 transport total | ogg transport total |
|---|---|---|
| 17 s | ~1.98 s | ~1.70 s |
| 128 s | ~3.04 s | ~2.56 s |
| 977 s | ~16.8 s | ~6.08 s |

Payload reduction: int16 = 2× smaller than float32; ogg (ffmpeg libvorbis) = 17× smaller. ogg is net faster at every size tested, including short audio. Encode cost is small but non-zero (0.14 s at 17 s audio, 3.3 s at 977 s); upload savings always exceed it.

**Option A — always OGG (simpler code, slightly faster at every size)**
- Single path, no branching logic
- Requires ffmpeg on-host — HF Gradio Spaces include ffmpeg by default (verified in build log, v5.1.8 with libvorbis)
- Caveat: OGG Vorbis is lossy. At ~30 kbps on speech, perceptually transparent — but the effect on wav2vec2 phoneme posteriors is unverified. Needs an accuracy test before committing.

**Option B — adaptive (int16 default, OGG above threshold) — safer starting point**
- Default `CPU_TRANSPORT_DEFAULT=int16` — lossless (already 16-bit source from MP3), zero encode cost
- Auto-escalate to `ogg` when encoded body > `CPU_TRANSPORT_OGG_THRESHOLD_BYTES` (~30 MB). Fires on audio > ~7 min — exactly where int16 upload dominates.
- Preserves current accuracy guarantees while capturing the big-payload win
- Also treat HTTP 413 on submit as a signal to auto-retry with OGG (belt-and-suspenders)

**Recommended starting choice: Option B.** Ship adaptive first. Once the accuracy test confirms OGG is a no-op for ASR, flip the default to OGG (Option A) and simplify.

Implementation sketch (`worker_pool.run_on_worker_cpu`, after initial encode):
```python
if transport != "ogg" and body_bytes > CPU_TRANSPORT_OGG_THRESHOLD_BYTES:
    print(f"[TRANSPORT] body={body_bytes/1e6:.1f} MB > threshold — re-encoding as ogg")
    transport = "ogg"
    encoded_args, meta = encode_args_for_transport(args, "ogg")
    args_b64 = base64.b64encode(pickle.dumps(encoded_args)).decode()
    meta_json = json.dumps(meta)
```

### 1.7 Worker warmup on main startup
Daemon thread: for each worker in `POOL`, fire a no-op `/cpu_exec` after main comes up. Warms DNS, TLS session, HF Xet cache, and on the worker side touches `ensure_models_on_cpu()` early. Non-blocking on main startup.

## 2. Stateful endpoints on the worker pool

Currently only `process_audio_session` / `process_url_session` dispatch to the worker. The other session endpoints either hit the same `gpu_with_fallback` path (so they already benefit, transitively) or need explicit attention:

| Endpoint | Dispatch path today | Action |
|---|---|---|
| `process_audio_session` | `run_vad_and_asr_gpu` → pool | Already works |
| `process_url_session` | same as above, after URL DL on main | Already works |
| `resegment` | `run_phoneme_asr_gpu` → pool (VAD skipped) | Verify + test |
| `retranscribe` | `run_phoneme_asr_gpu` → pool | Verify + test |
| `realign_from_timestamps` | `run_phoneme_asr_gpu` → pool | Verify + test |
| `timestamps` / `timestamps_direct` | calls external MFA Space | Out of scope for CPU pool |
| `debug_process` | same as `process_audio_session` | Already works |

**Stateless-workers principle**: main owns the session (`/tmp/aligner_sessions/<id>/`). For each dispatch, main ships audio bytes + any stage inputs (VAD intervals, boundaries) directly in `args`. Worker never reads session storage. This is already how the code works because `run_*_gpu` functions take audio numpy as their first argument.

No architectural change needed — just verify each endpoint end-to-end on CPU (Section 3) and confirm session state on main remains consistent after a worker-dispatched call.

## 3. Testing plan

### 3.1 Unit / local
- `audio_transport.py` round-trip: float32 ↔ int16 ↔ ogg with tolerance checks
- `worker_pool.acquire/release` with synthetic workers (no HTTP) for condition-var correctness
- Pickle compatibility of all function args across main/worker Python versions

### 3.2 Integration matrix (dev Space → cpu1)

Canonical fixtures: `112.mp3` (17 s), `84.mp3` (128 s), optionally `046.mp3` (977 s).

| Endpoint | Device | Transport | Audio | Notes |
|---|---|---|---|---|
| process_audio_session | GPU | — | 112, 84 | Baseline |
| process_audio_session | CPU | int16 | 112, 84 | Default path |
| process_audio_session | CPU | float32 | 112 | Regression check |
| process_audio_session | CPU | ogg | 84, 046 | Long-audio path |
| process_url_session | CPU | int16 | URL sample | Download on main |
| resegment | CPU | int16 | 112 (after initial) | State re-use |
| retranscribe | CPU | int16 | 112 (after initial) | Skip VAD |
| realign_from_timestamps | CPU | int16 | 112 (after initial) | Custom intervals |
| debug_process | CPU | int16 | 112 | Auth + profiling |

Record: total wall time, transport timings, result segment count, any `gr.Warning`.

### 3.3 Concurrency & failure scenarios

- 2 concurrent CPU requests → second queues, both complete
  - **Verified 2026-04-12**: two 112.mp3 CPU requests, Request 1 finished in 20.5 s, Request 2 finished in 41.1 s — exact FIFO serialization on worker (concurrency_limit=1)
- GPU + CPU concurrent on main → parallel, no blocking
  - **Verified 2026-04-12**: GPU request completed in 6.4 s while CPU request (637 s pre-fp32-fix) was in flight. 5.4 s overlap window. Main's `demo.queue(default_concurrency_limit=20)` in `app.py` is what enables this.
- Kill worker container mid-flight → pool marks unhealthy, retry succeeds on recovered worker
- All workers unhealthy → user sees clear error, not a silent hang
- Payload > 30 MB → transport auto-switch kicks in (see §1.6 Option B)

### 3.4 UI smoke tests

Against dev Space:
- Extract Segments (GPU) — verify render + download JSON
- Extract Segments (CPU) — verify render, progress, no "processed on CPU" fall-back warning unless GPU quota is exhausted
- Resegment with different min_silence values
- Retranscribe with Large model
- Inline ref editing still works after CPU run
- Compute Timestamps after CPU run (MFA path unaffected)

### 3.5 Load / regression

- Burst: 5 CPU requests in 10 s via script. Expect pool queue to hold 4.
- Long audio: 046.mp3 CPU with ogg transport. Expect completion under ~20 min on 1 worker.

## 4. Logging strategy

### 4.1 Who writes to the dataset?

**Decision: main writes all rows. Workers return structured timings in their response.**

Reasons:
- Main has the full request context (user, session id, endpoint name, front-end selections). Worker doesn't.
- Single writer = no dataset fragmentation, no permissions drift.
- Transport + queue + dispatch timing only exist on main anyway.
- Worker compute timing is small and structured; already returned in `worker_timings`.

### 4.2 Schema additions

Today the log row has `profiling` (ProfilingData dataclass) and `gpu` (lease info). Add a new JSON column `worker_dispatch` (or nest into `profiling`) with this shape — populated only when the run used the worker pool:

```json
"worker_dispatch": {
  "used": true,
  "worker_slug": "hetchyy/quranic-universal-aligner-cpu1",
  "transport": "int16",
  "attempts": 1,
  "queue_wait_s": 0.12,
  "main_encode_s": 0.02,
  "main_upload_submit_s": 2.31,
  "main_decode_s": 0.00,
  "sse_total_s": 18.9,
  "req_body_mb": 5.47,
  "resp_b64_mb": 0.004,
  "worker_timings": {
    "transport": "int16",
    "unpickle_s": 0.01,
    "audio_decode_s": 0.002,
    "compute_s": 18.7,
    "result_encode_s": 0.0,
    "result_bytes": 4096
  }
}
```

All fields come from `worker_pool.run_on_worker_cpu` (already computes these) — just needs to be stashed on `ProfilingData` / log row instead of only printed.

### 4.3 What this unlocks

- **CPU estimate regression**: refit `ESTIMATE_CPU_BASE_SLOPE/INTERCEPT` against `compute_s` from worker (the pure model cost), excluding transport overhead, for a cleaner estimator.
- **Per-worker slowness detection**: group by `worker_slug`, plot `compute_s / audio_duration_s`. Outlier workers surface automatically.
- **Transport comparison**: historical evidence for choosing a default, not just the 9-point Phase 1/2 matrix.
- **Queue latency analysis**: once we have multiple workers, `queue_wait_s` distribution tells us utilization and informs scale-up triggers.
- **Debugging**: a failed dispatch with `attempts > 1` and a non-null `last_error` per worker gives a clear forensic trail.

### 4.4 Ephemeral Space logs vs. the dataset

`[CPU WORKER]` and `[TRANSPORT STATS]` `print()` lines on main / worker end up in HF Space live logs (stream via `/api/spaces/.../logs/run`). These are ephemeral. They're useful live but shouldn't be relied on for analysis — the dataset row is the durable record.

Optional later: a second, lighter dataset `hetchyy/aligner-worker-dispatch-logs` keyed on dispatch id for more granular analysis. Not needed until traffic justifies it.

## 5. Scaling beyond 1 worker

### 5.1 Triggers (from the demand analysis)

Add a 2nd worker only when any of:
- Distinct-user CPU overlap > 1 % of arrivals (currently 0.0 %)
- Sustained throughput > 20 req/hr (currently 0.79 req/hr)
- p95 `queue_wait_s` > 30 s
- Pool-exhausted errors > 0

### 5.2 Mechanical steps

1. `huggingface_hub.duplicate_space(from_id="hetchyy/quranic-universal-aligner-cpu1", to_id="hetchyy/quranic-universal-aligner-cpu2")`
2. Set secrets on cpu2: `WORKER_MODE=cpu` (variable), `HF_TOKEN` (secret)
3. Update main's `WORKER_SPACES` var: append `,hetchyy/quranic-universal-aligner-cpu2`
4. Deploy current code to cpu2 (via script below)
5. Restart main — picks up new slug; warmup thread primes it

### 5.3 Deploy helper

`scripts/deploy_workers.py`:

- Reads worker list from a single config source
- `hf upload` to each worker in parallel (ThreadPool)
- Post-deploy smoke test: wait for `RUNNING`, fire trivial `/cpu_exec`, assert success
- Also pushes to dev main by default, prod on `--prod`
- Replaces the manually-extended `hf-dev` alias

### 5.4 Dispatch strategy evolution

- Now: **least-jobs** (good for homogeneous, concurrency-1 workers)
- At 4+ workers or mixed hardware: **power-of-two-choices**
- If mixing paid + free tiers: **weighted round-robin**
- When estimates prove accurate: **earliest-available by predicted free time** (see estimate-driven ETA design)

## 6. Production readiness checklist

Flip `hf-prod` only when every item below is green:

- [ ] 1.1 Pool status endpoint deployed + smoke-tested
- [ ] 1.2 Health-check recovery verified (induced worker failure → recovers)
- [ ] 1.3 HTTP session reuse in place
- [ ] 1.4 Clear error messages on UI and API
- [ ] 1.5 Max queue depth + admission control
- [ ] 1.6 Transport auto-switch exercised on a >40 MB payload
- [ ] 1.7 Warmup thread running on main startup
- [ ] Section 2: all session endpoints tested on CPU
- [ ] Section 3: integration matrix runs clean on dev
- [ ] Section 4: `worker_dispatch` fields visible in a real log row
- [ ] Rollback tested: set `WORKER_SPACES=""` on main → dispatch falls back to subprocess (or surfaces clean error if subprocess not viable)
- [ ] Dev Space has run this config for at least 1 week without manual intervention
- [ ] `WORKER_SPACES` + secrets documented in repo

## 7. Implementation order

| Phase | What | Size |
|---|---|---|
| 1 | Pool status endpoint, health-check, HTTP session reuse, clear errors, max queue depth | ~200 lines, 1 day |
| 2 | Verify + test resegment / retranscribe / realign on CPU | mostly testing |
| 3 | Extend `ProfilingData` + log schema with `worker_dispatch` block | ~100 lines |
| 4 | Transport auto-switch + warmup | ~60 lines |
| 5 | `scripts/deploy_workers.py` with smoke test | ~150 lines |
| 6 | Production rollout + 1 week monitoring | process, not code |
| 7 | Add cpu2 if triggers fire | minutes, once Phase 5 exists |

Do not move to a phase until the prior one has tests passing and a log-row in the dataset.

## 8. API contract (implicit but load-bearing)

From auditing the **QuranCaption** desktop client (Svelte/Tauri, largest external API user we know of): they parse Gradio's HTTP/SSE surface by hand — no `gradio_client` in the loop. That means the following are implicit contract; breaking any silently breaks them:

- **Positional argument order** for `/process_audio_session`, `/estimate_duration` (they send `data: [...]` arrays, not keyword args).
- **FileData shape**: `{"path": ..., "meta": {"_type": "gradio.FileData"}}`. Gradio version bumps that change this break their uploader.
- **SSE event names**: `event: complete` and `event: error`. Renaming or adding envelopes will strip their completion handler.
- **`warning` field in the response** — they surface it as a toast for GPU→CPU fallback.
- **`audio_id` presence + 32-hex-char format** on session responses.

Actions:
- Document the above in `docs/client_api.md` as **"Stable contract — do not change without a deprecation cycle."**
- Any change that affects these must: bump a version header, include migration notes in the docs changelog, and ship behind a feature flag for at least one release.
- Clients that already pre-compress audio (QuranCaption ships OGG/Opus @ 64 kbps) won't see a difference from our transport work — it's purely an internal optimization. Don't expose `transport` selection on the public API; keep it internal.

## 9. Related audio optimizations (parallel track)

Audit of the wider aligner audio path found four other places where similar techniques pay off. None blocks the worker rollout, but they are cheap wins to fold into the same iteration:

| # | Change | File | Win | Risk |
|---|---|---|---|---|
| 1 | `full.wav` → `full.ogg` for mega-card playback | `pipeline.py:874,925` | ~8× bandwidth to browser | Low — browsers decode OGG natively with `#t=` fragments |
| 2 | Session cache audio: float32 → int16 | `session_api.py:88` | 2× disk (61 MB → 30 MB per session) | Low — MP3 source is already 16-bit |
| 3 | MFA upload payload: WAV → OGG | `mfa.py:41-50` | 4–8× bandwidth to MFA Space | Medium — needs decode support on MFA Space (coordinated deploy) |
| 4 | Consolidate three OGG encoders into `src/core/audio_encode.py` | `audio_transport._encode_ogg`, `usage_logger._encode_audio_ogg`, yt-dlp postprocessor | No user-visible change, removes duplication | Low |
| 5 | Replace `librosa.load` with direct ffmpeg | `pipeline.py` (process_audio, _download_url_core), `session_api.py` (_preprocess_api_audio) | **4–15× faster decode**: 17 s audio 1.9 s → 131 ms; 977 s audio 15.7 s → 3.6 s | Low — output bitwise-identical to soxr_lq for our files |

Already optimal (no action): `usage_logger` (OGG via ffmpeg), URL downloads (yt-dlp + ffmpeg → 128 kbps MP3), MFA split helper (int16 WAV), our new `audio_transport.py`.

Full audit at `/tmp/audio_optimization_audit.md`.

## 10. Known issues & deps

- **libsndfile 1.2.2 (bundled with soundfile 0.13.1) segfaults writing OGG Vorbis for audio > ~10 M samples** (~10 min @ 16 kHz). `audio_transport._encode_ogg` shells out to `ffmpeg` instead. `packages.txt` declares `ffmpeg` defensively but it's already in the HF Gradio base image.
- **OGG Vorbis vs ASR accuracy is unverified.** Action before making OGG the universal default: run same audio through worker with int16 vs ogg, compare raw phoneme strings + final segments. Gate is "phoneme strings match byte-for-byte" (strict) or "final segment boundaries within ±50 ms" (lenient). Budget: ~20 min of testing.

## 11. Related documents

- Log schema: `docs/usage-logging.md`
- Debug API: `docs/debug_api_schema.md`
- Overall architecture: root `CLAUDE.md` and aligner `CLAUDE.md`
