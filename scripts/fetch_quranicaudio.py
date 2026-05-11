#!/usr/bin/env python3
"""Raw scrape of quranicaudio.com.

Walks index pages (`/`, `/section/2`, `/section/3`), then each `/quran/<id>`
page, and writes a single raw-data JSON to ``data/audio/quranicaudio_raw.json``.

Audio CDN pattern: ``https://download.quranicaudio.com/quran/<slug>/<NNN>.mp3``
where ``NNN`` is the zero-padded surah number.

Smoke coverage: HEAD probes surah 1, 57, 114 per reciter. Run with
``--full-coverage`` to probe all 114 surahs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from html import unescape
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = REPO_ROOT / "data" / "audio" / "quranicaudio_raw.json"

BASE = "https://quranicaudio.com"
CDN = "https://download.quranicaudio.com/quran"
UA = "qua-research-bot/1.0 (+https://github.com/Hetchy/quranic-universal-audio)"

SECTIONS = {
    "default": f"{BASE}/",
    "taraweeh": f"{BASE}/section/2",
    "non_hafs": f"{BASE}/section/3",
}

INDEX_LINK_RE = re.compile(r'href="(?:\.\./|\./|/)?quran/(\d+)"[^>]*>([^<]+)</a>')
H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
SLUG_RE = re.compile(r"download\.quranicaudio\.com/quran/(.+?)/(\d{3})\.mp3")
DESC_P_RE = re.compile(
    r"<h1[^>]*>.*?</h1>\s*(?:<!--\[?-->)*\s*<p\b[^>]*>(.*?)</p>", re.S
)
A_HREF_RE = re.compile(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
TAG_RE = re.compile(r"<[^>]+>")
SVELTE_COMMENT_RE = re.compile(r"<!--\[?!?\]?-->")
WS_RE = re.compile(r"\s+")
YEAR_HIJRI_RE = re.compile(r"\b(1[34]\d{2})\s*H\b")
YEAR_GREG_RE = re.compile(r"\b(19|20)\d{2}\s*A\.?\s*D\.?", re.I)
BITRATE_RE = re.compile(r"\b(\d{2,3})\s*kbps\b", re.I)


def fetch(url: str, *, retries: int = 3, sleep: float = 0.4) -> str:
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            last_err = e
            time.sleep(sleep * (attempt + 1))
    raise RuntimeError(f"fetch failed: {url} ({last_err})")


def head_probe(url: str, *, retries: int = 3, timeout: int = 15) -> dict:
    """HEAD a URL with retry on transient errors. 404 is terminal (no retry)."""
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return {
                    "ok": 200 <= r.status < 400,
                    "status": r.status,
                    "content_length": int(r.headers.get("Content-Length") or 0),
                    "final_url": r.url,
                }
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"ok": False, "status": 404, "content_length": 0, "final_url": url}
            last_err = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = str(e)
        time.sleep(0.5 * (attempt + 1))
    return {"ok": False, "status": None, "content_length": 0, "final_url": url, "error": last_err}


def parse_index(html: str) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    seen = set()
    for m in INDEX_LINK_RE.finditer(html):
        rid = int(m.group(1))
        if rid in seen:
            continue
        seen.add(rid)
        label = unescape(m.group(2)).strip()
        out.append((rid, label))
    return out


def clean_text(html: str) -> str:
    s = SVELTE_COMMENT_RE.sub("", html)
    s = TAG_RE.sub("", s)
    return WS_RE.sub(" ", unescape(s)).strip()


def parse_brackets(label: str) -> tuple[str, list[str]]:
    """Split tags wrapped in [ ] or ( ) off the trailing end of the name.

    'Foo [Mujawwad] [Taraweeh]' → ('Foo', ['Mujawwad', 'Taraweeh'])
    'Foo (with Children)'       → ('Foo', ['with Children'])
    Parentheses are *only* treated as tag markers when they sit at the end of
    the label, so legitimate parens in a name (none observed yet, but
    defensive) are not stripped from the middle.
    """
    tags: list[str] = []
    name = label
    while True:
        m = re.search(r"\s*[\[\(]([^\]\)]+)[\]\)]\s*$", name)
        if not m:
            break
        tags.insert(0, m.group(1).strip())
        name = name[: m.start()].rstrip()
    return name.strip(), tags


def parse_reciter_page(html: str) -> dict:
    title_m = TITLE_RE.search(html)
    h1_m = H1_RE.search(html)
    desc_m = DESC_P_RE.search(html)
    slug_m = SLUG_RE.search(html)

    title_full = unescape(title_m.group(1)).strip() if title_m else ""
    title_clean = re.sub(
        r"\s*-\s*QuranicAudio\.com\s*$", "", title_full
    ).replace("Holy Quran Recitation by ", "").strip()

    h1 = clean_text(h1_m.group(1)) if h1_m else ""
    desc_html = desc_m.group(1) if desc_m else ""
    desc_text = clean_text(desc_html)
    attributions = []
    if desc_html:
        for href, anchor_html in A_HREF_RE.findall(desc_html):
            attributions.append(
                {"url": href, "text": clean_text(anchor_html)}
            )

    slug = slug_m.group(1) if slug_m else None

    name, brackets = parse_brackets(title_clean or h1)
    year_h = YEAR_HIJRI_RE.search(desc_text)
    year_g = YEAR_GREG_RE.search(desc_text)
    bitrate = BITRATE_RE.search(desc_text)

    return {
        "title": title_clean,
        "name": name,
        "h1": h1,
        "brackets": brackets,
        "slug": slug,
        "description": desc_text,
        "attributions": attributions,
        "year_hijri": int(year_h.group(1)) if year_h else None,
        "year_gregorian": (year_g.group(0).rstrip(".") if year_g else None),
        "bitrate_kbps": int(bitrate.group(1)) if bitrate else None,
    }


def probe_all(slugs: list[str], surahs: list[int], *, workers: int,
              cache: dict | None = None, cache_path: Path | None = None) -> dict:
    """Probe (slug, surah) pairs in a single global pool. Returns nested dict
    {slug: {surah: probe_result}}. Optionally read/write a JSON cache."""
    cache = cache if cache is not None else {}
    results: dict[str, dict[int, dict]] = {s: cache.get(s, {}).copy() for s in slugs}
    todo: list[tuple[str, int]] = []
    for slug in slugs:
        for n in surahs:
            if str(n) not in results[slug]:
                todo.append((slug, n))
    print(f"[probe] {len(todo)} requests pending ({len(slugs)} slugs × {len(surahs)} surahs, workers={workers})", file=sys.stderr)
    if not todo:
        return results

    done = 0
    save_every = 500
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(head_probe, f"{CDN}/{slug}/{n:03d}.mp3"): (slug, n)
            for slug, n in todo
        }
        for f in as_completed(futs):
            slug, n = futs[f]
            results[slug][str(n)] = f.result()
            done += 1
            if done % 200 == 0:
                print(f"[probe] {done}/{len(todo)}", file=sys.stderr)
            if cache_path and done % save_every == 0:
                cache_path.write_text(json.dumps(results, ensure_ascii=False))
    if cache_path:
        cache_path.write_text(json.dumps(results, ensure_ascii=False))
    return results


def summarize_coverage(probe: dict[str, dict], surahs: list[int]) -> dict:
    present = sorted(int(k) for k, v in probe.items() if v.get("ok"))
    missing = sorted(int(k) for k, v in probe.items() if not v.get("ok"))
    sizes = [v.get("content_length", 0) for v in probe.values() if v.get("ok")]
    redirects = [
        {"surah": int(k), "final_url": v["final_url"]}
        for k, v in probe.items()
        if v.get("ok") and v.get("final_url") and not v["final_url"].endswith(f"{int(k):03d}.mp3")
    ]
    return {
        "probed": surahs,
        "present": present,
        "missing": missing,
        "n_present": len(present),
        "n_missing": len(missing),
        "size_min": min(sizes) if sizes else 0,
        "size_max": max(sizes) if sizes else 0,
        "size_total": sum(sizes),
        "redirects": redirects,
    }


def scrape(full_coverage: bool, page_delay: float, workers: int,
           cache_path: Path | None) -> dict:
    sections: dict[str, list[tuple[int, str]]] = {}
    for sec, url in SECTIONS.items():
        print(f"[index] {sec} {url}", file=sys.stderr)
        sections[sec] = parse_index(fetch(url))
        time.sleep(page_delay)

    id_sections: dict[int, list[str]] = {}
    id_label: dict[int, str] = {}
    for sec, items in sections.items():
        for rid, label in items:
            id_sections.setdefault(rid, []).append(sec)
            id_label.setdefault(rid, label)

    surahs = list(range(1, 115)) if full_coverage else [1, 57, 114]

    reciters = []
    for rid in sorted(id_sections):
        url = f"{BASE}/quran/{rid}"
        print(f"[reciter] {rid} {id_label[rid]}", file=sys.stderr)
        try:
            html = fetch(url)
        except Exception as e:
            reciters.append({"id": rid, "error": str(e), "index_label": id_label[rid]})
            continue
        info = parse_reciter_page(html)
        info["id"] = rid
        info["page_url"] = url
        info["index_label"] = id_label[rid]
        info["sections"] = id_sections[rid]
        reciters.append(info)
        time.sleep(page_delay)

    slugs = [r["slug"] for r in reciters if r.get("slug")]
    cache = {}
    if cache_path and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
            print(f"[cache] loaded {sum(len(v) for v in cache.values())} probes", file=sys.stderr)
        except Exception as e:
            print(f"[cache] ignored corrupt cache: {e}", file=sys.stderr)
    probe_results = probe_all(slugs, surahs, workers=workers, cache=cache, cache_path=cache_path)

    for r in reciters:
        slug = r.get("slug")
        if not slug:
            r["coverage"] = None
            continue
        r["coverage"] = summarize_coverage(probe_results.get(slug, {}), surahs)
        r["coverage"]["full"] = full_coverage
        r["probe_detail"] = probe_results.get(slug, {})

    # aggregate attributions
    attr_counts: dict[str, int] = {}
    attr_examples: dict[str, list[int]] = {}
    for r in reciters:
        for a in r.get("attributions", []) or []:
            host = re.sub(r"^https?://", "", a["url"]).split("/")[0].lower()
            attr_counts[host] = attr_counts.get(host, 0) + 1
            attr_examples.setdefault(host, []).append(r["id"])
    attributions_summary = [
        {"host": h, "count": attr_counts[h], "example_ids": attr_examples[h][:5]}
        for h in sorted(attr_counts, key=lambda k: -attr_counts[k])
    ]

    return {
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cdn_template": f"{CDN}/<slug>/<NNN>.mp3",
        "sections": {sec: [list(t) for t in items] for sec, items in sections.items()},
        "reciters": reciters,
        "attributions_summary": attributions_summary,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--full-coverage", action="store_true",
                   help="Probe all 114 surahs (default: smoke surahs 1/57/114)")
    p.add_argument("--page-delay", type=float, default=0.3,
                   help="Seconds between page fetches (default 0.3)")
    p.add_argument("--workers", type=int, default=16,
                   help="Concurrent HEAD probe workers (default 16)")
    p.add_argument("--out", type=Path, default=OUT_PATH)
    p.add_argument("--cache", type=Path,
                   default=REPO_ROOT / "data" / "audio" / "quranicaudio_coverage_cache.json",
                   help="Resume cache for HEAD probes")
    p.add_argument("--no-cache", action="store_true", help="Disable probe cache")
    args = p.parse_args()

    cache_path = None if args.no_cache else args.cache
    data = scrape(args.full_coverage, args.page_delay, args.workers, cache_path)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"wrote {args.out} ({len(data['reciters'])} reciters)", file=sys.stderr)


if __name__ == "__main__":
    main()
