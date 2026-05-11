#!/usr/bin/env python3
"""Raw scrape of tvquran.com.

Enumerates the EN authors sitemap, fetches each ``/<lang>/scholar/<id>/profile``
in both English and Arabic, and splits the ``#sheikh-msahif`` section into
panels (one per moshaf variant). Per panel it captures
``name_en + name_ar + riwayah_en + riwayah_ar + surah_count + cdn_base``
and runs a full HEAD coverage probe of each surah against
``download.tvquran.com``.

CDN families on this site
-------------------------
* ``download/<*Quran.com__Slug>/<NNN>.mp3``       — named-vanity full mushaf
* ``download/recitations/<scholar_id>/<mushaf_id>/<NNN>.mp3`` — numeric full mushaf

The scraper only emits manifests for those two; orphan ``selections/`` and
cross-reciter ``tilawa_*`` collections are left unmodelled.
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
OUT_PATH = REPO_ROOT / "docs" / "reciters-research" / "tvquran" / "tvquran_raw.json"
CACHE_PATH = REPO_ROOT / "docs" / "reciters-research" / "tvquran" / "tvquran_coverage_cache.json"

BASE = "https://www.tvquran.com"
SITEMAP = f"{BASE}/en/sitemap/authors/1.xml"
CDN_HOST = "download.tvquran.com"
UA = "qua-research-bot/1.0 (+https://github.com/Hetchy/quranic-universal-audio)"

SCHOLAR_LOC_RE = re.compile(r"<loc>https?://[^<]*?/scholar/(\d+)/profile</loc>", re.I)
TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
MP3_RE = re.compile(r"(download\.tvquran\.com/download/[^\"' ]+\.mp3)")
# Split header on the LAST " - " before the "/<count>" marker so reciter
# names that themselves contain " - " (e.g. "Ahmad Al-Ajmi" vs riwayah "Hafs")
# aren't broken at the first hyphen.
PANEL_HEAD_RE = re.compile(r"^(.+)\s+-\s+([^/-]+?)\s*/\s*(\d+)\b")
SKIP_PANEL_KEYWORDS = (
    "Author selections", "مختارات القارىء", "مختارات القارئ",
)


def fetch(url: str, *, retries: int = 3, sleep: float = 0.4,
          timeout: int = 20) -> str | None:
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last_err = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = str(e)
        time.sleep(sleep * (attempt + 1))
    print(f"[warn] fetch failed: {url} ({last_err})", file=sys.stderr)
    return None


def head_probe(url: str, *, retries: int = 3, timeout: int = 15) -> dict:
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return {
                    "ok": 200 <= r.status < 400,
                    "status": r.status,
                    "content_length": int(r.headers.get("Content-Length") or 0),
                }
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"ok": False, "status": 404, "content_length": 0}
            last_err = f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_err = str(e)
        time.sleep(0.5 * (attempt + 1))
    return {"ok": False, "status": None, "content_length": 0, "error": last_err}


def clean_text(html: str) -> str:
    return WS_RE.sub(" ", unescape(TAG_RE.sub(" ", html))).strip()


def parse_panels(html: str) -> list[dict]:
    """Split the moshaf section into panel records (header + mp3 bases)."""
    i = html.find('id="sheikh-msahif"')
    if i < 0:
        return []
    j = html.find("</section>", i)
    region = html[i:j if j > i else None]
    parts = re.split(r'<div\s+class="panel"\s*>', region)[1:]
    out: list[dict] = []
    for body in parts:
        head_text = clean_text(body[:2500])
        urls = MP3_RE.findall(body)
        bases: dict[str, list[int]] = {}
        for u in urls:
            m = re.match(r"(.*)/(\d{3})\.mp3$", u)
            if not m:
                continue
            bases.setdefault(m.group(1), []).append(int(m.group(2)))
        out.append({
            "head_text": head_text[:400],
            "bases": bases,
        })
    return out


def parse_panel_header(text: str) -> tuple[str, str, int | None]:
    m = PANEL_HEAD_RE.match(text)
    if not m:
        return text.strip(), "", None
    name = m.group(1).strip()
    riwayah = m.group(2).strip()
    try:
        count = int(m.group(3))
    except ValueError:
        count = None
    return name, riwayah, count


def scholar_ids(html: str) -> list[int]:
    return sorted({int(m.group(1)) for m in SCHOLAR_LOC_RE.finditer(html)})


def scrape_scholar(sid: int, page_delay: float) -> dict | None:
    en = fetch(f"{BASE}/en/scholar/{sid}/profile")
    if en is None:
        return None
    ar = fetch(f"{BASE}/ar/scholar/{sid}/profile") or ""
    time.sleep(page_delay)
    en_panels = parse_panels(en)
    ar_panels = parse_panels(ar)
    en_title = (TITLE_RE.search(en) or re.search("", "")).group(1) if TITLE_RE.search(en) else ""
    en_name = re.sub(r"\s*-\s*Quran listen.*$", "", clean_text(en_title)).strip()
    ar_title_m = TITLE_RE.search(ar)
    ar_title = ar_title_m.group(1) if ar_title_m else ""
    ar_name = re.sub(r"\s*-\s*القرآن الكريم.*$", "", clean_text(ar_title)).strip()

    panels: list[dict] = []
    n = max(len(en_panels), len(ar_panels))
    for idx in range(n):
        e = en_panels[idx] if idx < len(en_panels) else {"head_text": "", "bases": {}}
        a = ar_panels[idx] if idx < len(ar_panels) else {"head_text": "", "bases": {}}
        head_e, head_a = e["head_text"], a["head_text"]
        if any(kw in head_e or kw in head_a for kw in SKIP_PANEL_KEYWORDS):
            continue  # "Author selections" panel — not a full mushaf
        en_name_panel, en_riw, en_count = parse_panel_header(head_e)
        ar_name_panel, ar_riw, ar_count = parse_panel_header(head_a)
        # Prefer numeric (recitations/...) bases when present — they're the
        # canonical fingerprint for a moshaf. Otherwise the named-vanity base.
        all_bases = {}
        for b, surahs in {**e["bases"], **a["bases"]}.items():
            all_bases[b] = all_bases.get(b, 0) + len(surahs)
        def base_rank(item: tuple[str, int]) -> tuple[int, int]:
            b, count = item
            is_full_mushaf = 1 if "/recitations/" in b or "Quran.com__" in b else 0
            return (is_full_mushaf, count)
        primary_base = max(all_bases.items(), key=base_rank)[0] if all_bases else None
        if primary_base and "/recitations/" in primary_base:
            kind = "numeric"
        elif primary_base and "Quran.com__" in primary_base:
            kind = "named"
        else:
            kind = None
        panels.append({
            "panel_index": idx,
            "name_en": en_name_panel or en_name,
            "name_ar": ar_name_panel or ar_name,
            "riwayah_en": en_riw,
            "riwayah_ar": ar_riw,
            "declared_surah_count": en_count or ar_count,
            "cdn_base": primary_base,
            "kind": kind,
        })

    return {
        "id": sid,
        "name_en": en_name,
        "name_ar": ar_name,
        "page_en": f"{BASE}/en/scholar/{sid}/profile",
        "page_ar": f"{BASE}/ar/scholar/{sid}/profile",
        "panels": panels,
    }


def probe_all(panels: list[tuple[str, str, int, int]], *, workers: int,
              cache: dict, cache_path: Path | None) -> dict:
    """Probe (scholar_id, panel_idx, surah) for every panel. Pass already-flat
    list of ``(cache_key, base, scholar_id, panel_idx, surah)``."""
    pass  # implemented inline below


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--page-delay", type=float, default=0.2)
    p.add_argument("--workers", type=int, default=12,
                   help="Concurrent HEAD probes against download.tvquran.com")
    p.add_argument("--scholar-workers", type=int, default=6,
                   help="Concurrent scholar-page fetches")
    p.add_argument("--max-scholars", type=int, default=0,
                   help="Cap on number of scholars (0 = all)")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--out", type=Path, default=OUT_PATH)
    args = p.parse_args()

    print(f"[sitemap] {SITEMAP}", file=sys.stderr)
    sitemap = fetch(SITEMAP)
    if sitemap is None:
        print("failed to fetch sitemap", file=sys.stderr)
        sys.exit(1)
    ids = scholar_ids(sitemap)
    if args.max_scholars:
        ids = ids[: args.max_scholars]
    print(f"[scholars] {len(ids)} ids to scrape", file=sys.stderr)

    scholars: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.scholar_workers) as ex:
        futs = {ex.submit(scrape_scholar, sid, args.page_delay): sid for sid in ids}
        for f in as_completed(futs):
            res = f.result()
            sid = futs[f]
            if res is None:
                continue
            scholars.append(res)
            if len(scholars) % 25 == 0:
                print(f"[scholars] scraped {len(scholars)}/{len(ids)}", file=sys.stderr)
    scholars.sort(key=lambda s: s["id"])
    print(f"[scholars] live: {len(scholars)}", file=sys.stderr)

    cache_path = None if args.no_cache else CACHE_PATH
    cache: dict[str, dict[str, dict]] = {}
    if cache_path and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
            print(f"[cache] loaded {sum(len(v) for v in cache.values())} probes", file=sys.stderr)
        except Exception:
            cache = {}

    todo: list[tuple[str, int, int, int, str]] = []  # (base, sid, pidx, surah, url)
    for s in scholars:
        for panel in s["panels"]:
            base = panel.get("cdn_base")
            if not base:
                continue
            cache.setdefault(base, {})
            for n in range(1, 115):
                if str(n) not in cache[base]:
                    todo.append((base, s["id"], panel["panel_index"], n,
                                 f"https://{base}/{n:03d}.mp3"))
    print(f"[probe] pending {len(todo)} HEADs (workers={args.workers})", file=sys.stderr)

    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(head_probe, t[4]): t for t in todo}
        for f in as_completed(futs):
            base, sid, pidx, n, _u = futs[f]
            cache[base][str(n)] = f.result()
            done += 1
            if done % 1000 == 0:
                print(f"[probe] {done}/{len(todo)}", file=sys.stderr)
                if cache_path:
                    cache_path.write_text(json.dumps(cache, ensure_ascii=False))
    if cache_path:
        cache_path.write_text(json.dumps(cache, ensure_ascii=False))

    # Attach coverage to each panel.
    for s in scholars:
        for panel in s["panels"]:
            base = panel.get("cdn_base")
            if not base:
                panel["coverage"] = None
                continue
            probes = cache.get(base, {})
            present = sorted(int(k) for k, v in probes.items() if v.get("ok"))
            missing = sorted(int(k) for k, v in probes.items() if not v.get("ok"))
            sizes = [v.get("content_length", 0) for v in probes.values() if v.get("ok")]
            panel["coverage"] = {
                "present": present,
                "missing": missing,
                "n_present": len(present),
                "size_min": min(sizes) if sizes else 0,
                "size_max": max(sizes) if sizes else 0,
                "size_total": sum(sizes),
            }

    out = {
        "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cdn_host": CDN_HOST,
        "n_scholars": len(scholars),
        "scholars": scholars,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"wrote {args.out} ({len(scholars)} scholars, "
          f"{sum(len(s['panels']) for s in scholars)} panels)", file=sys.stderr)


if __name__ == "__main__":
    main()
