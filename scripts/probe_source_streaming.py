#!/usr/bin/env python3
"""Probe per-source streaming health for Inspector playback.

For each (host, sample-URL) pair, measure:
  * cold TTFB / total — time to first/last byte on a brand-new TLS connection
  * warm TTFB / total — same on a reused HTTP keep-alive connection
  * effective throughput on a 64 KB Range GET

Aggregates per source: ``cold_ttfb_p50/p95``, ``warm_ttfb_p50/p95``, and
``warm_throughput_kbps_p50``. Writes ``data/audio/<source>_streaming_health.json``.

Why separate from validate_audio.py
-----------------------------------
``validate_audio.py`` runs per-manifest and uses a fresh ``urllib`` request
per URL, so its ``latency_ms`` is dominated by DNS+TLS handshake. Streaming
behaviour seen by Inspector's ``<audio>`` element depends on warm-connection
TTFB and throughput — different probe shape, different cadence (run weekly,
not per-PR).

Usage
-----
    python3 scripts/probe_source_streaming.py \
        --manifest-dir data/audio/by_surah/quranicaudio \
        --source quranicaudio \
        --sample-size 30 \
        --workers 4

The sampling pulls one URL per reciter when possible, capped at
``--sample-size`` URLs total. Probes each URL twice: cold (new connection)
then warm (pooled). Sleeps ``--inter-request-delay`` between cold/warm to
let the kernel close the cold socket cleanly.
"""

from __future__ import annotations

import argparse
import http.client
import json
import random
import ssl
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST_DIR = REPO_ROOT / "data" / "audio" / "by_surah" / "quranicaudio"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "audio"
RANGE_BYTES = 65535  # first 64 KB — enough for header + first audio frame

USER_AGENT = "qua-streaming-probe/1.0"


def collect_sample_urls(manifest_dir: Path, sample_size: int,
                        rng: random.Random) -> list[tuple[str, str]]:
    """Return ``[(reciter_slug, url), ...]``. One URL per reciter if possible."""
    samples: list[tuple[str, str]] = []
    manifests = sorted(manifest_dir.glob("*.json"))
    rng.shuffle(manifests)
    for path in manifests:
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        urls = [v for k, v in data.items()
                if k != "_meta" and isinstance(v, str) and v.startswith("http")]
        if not urls:
            continue
        samples.append((path.stem, rng.choice(urls)))
        if len(samples) >= sample_size:
            break
    return samples


def probe_once(url: str, *, conn: http.client.HTTPSConnection | None,
               timeout: int) -> dict:
    """Issue a Range GET and time TTFB / total / bytes received.

    When ``conn`` is None, opens a brand-new connection (cold). Otherwise
    reuses ``conn`` (warm). Returns metrics + the connection (so caller can
    reuse for warm hits).
    """
    parsed = urlparse(url)
    host = parsed.hostname
    port = parsed.port or 443
    path = parsed.path + (f"?{parsed.query}" if parsed.query else "")

    cold = conn is None
    if cold:
        ctx = ssl.create_default_context()
        t_connect = time.perf_counter()
        conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
        conn.connect()
        connect_ms = int((time.perf_counter() - t_connect) * 1000)
    else:
        connect_ms = 0

    headers = {
        "User-Agent": USER_AGENT,
        "Range": f"bytes=0-{RANGE_BYTES}",
        "Accept": "*/*",
    }

    t_send = time.perf_counter()
    try:
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        # First byte = response.status received
        ttfb_ms = int((time.perf_counter() - t_send) * 1000)
        body = resp.read()
        total_ms = int((time.perf_counter() - t_send) * 1000)
        n_bytes = len(body)
        status = resp.status
        ct = resp.getheader("Content-Type")
    except Exception as e:
        return {
            "ok": False, "error": f"{type(e).__name__}: {e}",
            "connect_ms": connect_ms, "ttfb_ms": None, "total_ms": None,
            "bytes": 0, "status": None, "content_type": None, "conn": conn,
        }

    throughput_kbps = (n_bytes * 8) / max(total_ms, 1)
    return {
        "ok": 200 <= status < 400 and n_bytes > 0,
        "error": None if 200 <= status < 400 else f"HTTP {status}",
        "connect_ms": connect_ms,
        "ttfb_ms": ttfb_ms,
        "total_ms": total_ms,
        "bytes": n_bytes,
        "throughput_kbps": round(throughput_kbps, 1),
        "status": status,
        "content_type": ct,
        "conn": conn,
    }


def probe_url_pair(slug: str, url: str, *, timeout: int,
                   inter_delay: float) -> dict:
    """Cold + warm probe of a single URL. Returns combined record."""
    cold = probe_once(url, conn=None, timeout=timeout)
    if inter_delay:
        time.sleep(inter_delay)
    warm_conn = cold.get("conn") if cold.get("ok") else None
    warm = probe_once(url, conn=warm_conn, timeout=timeout) if warm_conn else None
    if cold.get("conn"):
        try:
            cold["conn"].close()
        except Exception:
            pass
    cold.pop("conn", None)
    if warm:
        warm.pop("conn", None)
    return {"reciter": slug, "url": url, "cold": cold, "warm": warm}


def percentile(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = min(len(xs) - 1, int(len(xs) * p))
    return xs[k]


def aggregate(records: list[dict]) -> dict:
    cold_connect = [r["cold"]["connect_ms"] for r in records
                    if r["cold"].get("ok") and r["cold"].get("connect_ms") is not None]
    cold_ttfb = [r["cold"]["ttfb_ms"] for r in records
                 if r["cold"].get("ok") and r["cold"].get("ttfb_ms") is not None]
    warm_ttfb = [r["warm"]["ttfb_ms"] for r in records
                 if r.get("warm") and r["warm"].get("ok")
                 and r["warm"].get("ttfb_ms") is not None]
    warm_throughput = [r["warm"]["throughput_kbps"] for r in records
                       if r.get("warm") and r["warm"].get("ok")
                       and r["warm"].get("throughput_kbps") is not None]

    return {
        "n_probed": len(records),
        "n_cold_ok": sum(1 for r in records if r["cold"].get("ok")),
        "n_warm_ok": sum(1 for r in records if r.get("warm") and r["warm"].get("ok")),
        "cold_connect_ms": {
            "p50": percentile(cold_connect, 0.5),
            "p95": percentile(cold_connect, 0.95),
        },
        "cold_ttfb_ms": {
            "p50": percentile(cold_ttfb, 0.5),
            "p95": percentile(cold_ttfb, 0.95),
        },
        "warm_ttfb_ms": {
            "p50": percentile(warm_ttfb, 0.5),
            "p95": percentile(warm_ttfb, 0.95),
        },
        "warm_throughput_kbps": {
            "p50": percentile(warm_throughput, 0.5),
            "p95": percentile(warm_throughput, 0.95),
        },
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    p.add_argument("--source", required=True,
                   help="Source slug (used as filename for the output JSON)")
    p.add_argument("--sample-size", type=int, default=30)
    p.add_argument("--workers", type=int, default=4,
                   help="Concurrent probes. Keep low — too many parallel "
                        "cold connections distort warm measurements.")
    p.add_argument("--timeout", type=int, default=15)
    p.add_argument("--inter-request-delay", type=float, default=0.5,
                   help="Seconds between cold and warm hits per URL (default 0.5)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = p.parse_args()

    rng = random.Random(args.seed)
    samples = collect_sample_urls(args.manifest_dir, args.sample_size, rng)
    if not samples:
        print(f"no URLs sampled from {args.manifest_dir}", file=sys.stderr)
        sys.exit(1)
    print(f"sampled {len(samples)} URLs", file=sys.stderr)

    records: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(probe_url_pair, slug, url,
                      timeout=args.timeout,
                      inter_delay=args.inter_request_delay): slug
            for slug, url in samples
        }
        for f in as_completed(futs):
            rec = f.result()
            records.append(rec)
            c = rec["cold"]
            w = rec.get("warm") or {}
            print(
                f"  {rec['reciter']:40} cold ttfb={c.get('ttfb_ms')}ms "
                f"connect={c.get('connect_ms')}ms  warm ttfb={w.get('ttfb_ms')}ms "
                f"thr={w.get('throughput_kbps')}kbps",
                file=sys.stderr,
            )

    summary = {
        "source": args.source,
        "manifest_dir": str(args.manifest_dir.relative_to(REPO_ROOT)),
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "range_bytes": RANGE_BYTES,
        "aggregate": aggregate(records),
        "records": records,
    }
    out_path = args.out_dir / f"{args.source}_streaming_health.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"wrote {out_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
