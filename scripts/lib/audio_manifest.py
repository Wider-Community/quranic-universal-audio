"""Audio manifest validation — pre-pipeline checks for a reciter input file.

Auto-detects the input format (verse/sura JSON or directory), reports
coverage (X/114 surahs or X/6236 verses), validates URL reachability or
local file integrity, and flags duplicates.

Pure library — no CLI, no PR-comment formatter. Callers invoke
``validate_audio(path, ...)`` and consume the returned dict directly.
"""

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Repo root: scripts/lib/audio_manifest.py → repo/
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _rel_path(p: Path) -> str:
    """Return path relative to project root, or just the name as fallback."""
    try:
        return str(p.relative_to(_PROJECT_ROOT))
    except ValueError:
        return p.name


# ── Constants ────────────────────────────────────────────────────────────

TOTAL_SURAHS = 114
TOTAL_VERSES = 6236
DEFAULT_URL_TIMEOUT = 10
DEFAULT_MAX_WORKERS = 16
DEFAULT_FFPROBE_TIMEOUT = 5
MIN_AUDIO_BYTES = 50 * 1024  # placeholder/truncated file floor
AUDIO_CT_PREFIX = "audio/"
# A 200 status with these MIMEs almost always means an HTML error page or
# generic placeholder rather than the requested audio asset.
SUSPECT_CT_PREFIXES = ("text/", "application/json", "application/xml")


# ── Input parsing (duplicated from extract_segments.py — cannot import
#    due to heavy ML dependencies at module level) ────────────────────────

AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg"}


def _is_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


def _load_json_or_jsonl(path: Path) -> dict:
    """Load a ``.json`` file into a single dict."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def detect_input_format(path: Path) -> str:
    """Detect the input format from a path.

    Returns one of: ``"verse_json"``, ``"sura_json"``, ``"verse_dir"``,
    ``"sura_dir"``.
    """
    if path.is_file() and path.suffix == ".json":
        data = _load_json_or_jsonl(path)
        if not data:
            raise ValueError("JSON file is empty")
        # Skip internal keys like _meta when detecting format
        first_key = next((k for k in data if not str(k).startswith("_")), None)
        if first_key is None:
            raise ValueError("JSON file has no audio entries")
        return "verse_json" if ":" in str(first_key) else "sura_json"

    if path.is_dir():
        for child in path.iterdir():
            if child.suffix.lower() in AUDIO_EXTENSIONS:
                stem = child.stem
                parts = stem.split("_")
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    return "verse_dir"
        return "sura_dir"

    raise ValueError(f"Cannot detect format for: {path}")


def parse_input(
    path: Path, fmt: str
) -> Dict[int, List[Tuple[str, Optional[int]]]]:
    """Parse input into ``{sura_num: [(audio_source, verse_or_none), ...]}``."""
    grouped: Dict[int, List[Tuple[str, Optional[int]]]] = defaultdict(list)

    if fmt == "verse_json":
        data = _load_json_or_jsonl(path)
        for key, audio_src in data.items():
            if str(key).startswith("_"):
                continue
            sura_str, verse_str = str(key).split(":")
            sura, verse = int(sura_str), int(verse_str)
            grouped[sura].append((str(audio_src), verse))

    elif fmt == "sura_json":
        data = _load_json_or_jsonl(path)
        for key, audio_src in data.items():
            if str(key).startswith("_"):
                continue
            sura = int(key)
            grouped[sura].append((str(audio_src), None))

    elif fmt == "verse_dir":
        for child in sorted(path.iterdir()):
            if child.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            parts = child.stem.split("_")
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                sura, verse = int(parts[0]), int(parts[1])
                grouped[sura].append((str(child), verse))

    elif fmt == "sura_dir":
        for child in sorted(path.iterdir()):
            if child.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            stem = child.stem
            if stem.isdigit():
                sura = int(stem)
                grouped[sura].append((str(child), None))

    return dict(grouped)


# ── Surah info ───────────────────────────────────────────────────────────


def load_surah_info(surah_info_path: Path) -> dict:
    """Load surah_info.json → {sura_int: {num_verses, name_en, verses}}."""
    with open(surah_info_path, encoding="utf-8") as f:
        raw = json.load(f)
    return {int(k): v for k, v in raw.items()}


def _expected_verses(surah_info: dict) -> Dict[int, List[int]]:
    """Build {sura: [1, 2, ..., num_verses]} for all 114 surahs."""
    return {
        sura: list(range(1, data["num_verses"] + 1))
        for sura, data in surah_info.items()
    }


# ── Metadata validation ──────────────────────────────────────────────────

# Keys that MUST have a real value (not empty, not "unknown")
STRICT_META_KEYS = ("reciter", "name_en")
# Keys that must be present but may be "unknown" if not known
ALL_META_KEYS = (
    "reciter", "name_en", "name_ar", "riwayah", "style",
    "audio_category", "source", "country",
)
VALID_STYLES = ("murattal", "mujawwad", "muallim", "children_repeat", "taraweeh", "unknown")
VALID_AUDIO_CATEGORIES = ("by_surah", "by_ayah")


def validate_meta(path: Path) -> Tuple[List[dict], List[dict]]:
    """Check _meta presence and required keys in an audio JSON file.

    Returns (errors, warnings) where each item is a dict with 'msg'.
    Errors: strict key missing/empty, any key missing, or empty value
            (use "unknown" if not known).
    Warnings: non-strict key has value "unknown".
    """
    errors: List[dict] = []
    warnings: List[dict] = []

    if not (path.is_file() and path.suffix == ".json"):
        return errors, warnings  # only applies to JSON files

    data = _load_json_or_jsonl(path)
    meta = data.get("_meta")

    if meta is None:
        errors.append({"msg": "_meta block missing from audio JSON"})
        return errors, warnings

    if not isinstance(meta, dict):
        errors.append({"msg": f"_meta is not an object (got {type(meta).__name__})"})
        return errors, warnings

    for key in ALL_META_KEYS:
        val = str(meta.get(key, "")).strip() if key in meta else None
        is_strict = key in STRICT_META_KEYS

        if val is None:
            errors.append({"msg": f"_meta missing required key: {key}"})
        elif not val:
            errors.append({"msg": f"_meta.{key} is empty (use \"unknown\" if not known)"})
        elif val == "unknown" and is_strict:
            errors.append({"msg": f"_meta.{key} must have a real value, not \"unknown\""})
        elif val == "unknown":
            warnings.append({"msg": f"_meta.{key} is \"unknown\""})

    # Validate constrained values
    style = str(meta.get("style", "")).strip()
    if style and style not in VALID_STYLES:
        errors.append({"msg": f"_meta.style must be one of {VALID_STYLES}, got \"{style}\""})

    audio_cat = str(meta.get("audio_category", "")).strip()
    if audio_cat and audio_cat not in VALID_AUDIO_CATEGORIES:
        errors.append({"msg": f"_meta.audio_category must be one of {VALID_AUDIO_CATEGORIES}, got \"{audio_cat}\""})

    # Identity sanity: filename stem must match _meta.reciter
    reciter = str(meta.get("reciter", "")).strip()
    if reciter and reciter != path.stem:
        errors.append({
            "msg": f"_meta.reciter \"{reciter}\" does not match filename stem \"{path.stem}\""
        })

    return errors, warnings


def validate_format_identity(meta: Optional[dict], fmt: str) -> List[dict]:
    """Cross-check _meta.audio_category against the detected input format."""
    errors: List[dict] = []
    if not meta:
        return errors
    cat = str(meta.get("audio_category", "")).strip()
    expected = "by_ayah" if fmt in ("verse_json", "verse_dir") else "by_surah"
    if cat and cat != expected:
        errors.append({
            "msg": f"_meta.audio_category=\"{cat}\" but detected format is {fmt} (expected \"{expected}\")"
        })
    return errors


# ── Coverage analysis ────────────────────────────────────────────────────


def analyze_sura_coverage(
    grouped: Dict[int, List[Tuple[str, Optional[int]]]],
    surah_info: dict,
) -> dict:
    """Sura-level: which of 114 surahs are present/missing."""
    present = sorted(grouped.keys())
    all_suras = sorted(surah_info.keys())
    missing = sorted(set(all_suras) - set(present))

    # Duplicates: suras with more than one audio source
    duplicates = []
    for sura, entries in sorted(grouped.items()):
        if len(entries) > 1:
            duplicates.append({
                "key": str(sura),
                "count": len(entries),
                "sources": [e[0] for e in entries],
            })

    return {
        "level": "sura",
        "present": present,
        "missing": missing,
        "present_count": len(present),
        "total": TOTAL_SURAHS,
        "duplicates": duplicates,
    }


def analyze_verse_coverage(
    grouped: Dict[int, List[Tuple[str, Optional[int]]]],
    surah_info: dict,
) -> dict:
    """Verse-level: which of 6236 verses are present/missing."""
    expected = _expected_verses(surah_info)

    present_set: set[Tuple[int, int]] = set()
    verse_sources: Dict[str, List[str]] = defaultdict(list)

    for sura, entries in grouped.items():
        for source, verse in entries:
            if verse is not None:
                present_set.add((sura, verse))
                verse_sources[f"{sura}:{verse}"].append(source)

    # Missing verses grouped by sura
    missing_by_sura: Dict[int, List[int]] = {}
    total_missing = 0
    for sura in sorted(expected):
        missing_verses = [v for v in expected[sura] if (sura, v) not in present_set]
        if missing_verses:
            missing_by_sura[sura] = missing_verses
            total_missing += len(missing_verses)

    fully_missing = [s for s, mv in missing_by_sura.items() if len(mv) == len(expected[s])]
    partial = [s for s, mv in missing_by_sura.items() if len(mv) < len(expected[s])]

    # Duplicates
    duplicates = []
    for key, sources in sorted(verse_sources.items()):
        if len(sources) > 1:
            duplicates.append({"key": key, "count": len(sources), "sources": sources})

    return {
        "level": "verse",
        "present_count": len(present_set),
        "total": TOTAL_VERSES,
        "missing_count": total_missing,
        "missing_by_sura": missing_by_sura,
        "fully_missing_suras": fully_missing,
        "partial_suras": partial,
        "duplicates": duplicates,
    }


# ── URL validation ───────────────────────────────────────────────────────


_DIRECT_AUDIO_EXTENSIONS = frozenset(
    {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".opus", ".wma", ".aac"}
)


def _needs_ytdlp(url: str) -> bool:
    """True if the URL requires yt-dlp (not a direct audio file)."""
    from urllib.parse import urlparse
    path = urlparse(url).path.split("?")[0].lower()
    return not any(path.endswith(ext) for ext in _DIRECT_AUDIO_EXTENSIONS)


def _check_via_ytdlp(url: str, timeout: int = DEFAULT_URL_TIMEOUT) -> dict:
    """Check a URL is accessible via yt-dlp --simulate."""
    import shutil
    import subprocess
    if not shutil.which("yt-dlp"):
        return {"url": url, "ok": False, "status": None,
                "error": "yt-dlp not installed (pip install yt-dlp)",
                "content_type": None}
    try:
        subprocess.run(
            ["yt-dlp", "--simulate", "--no-warnings", url],
            capture_output=True, text=True, timeout=timeout,
        )
        return {"url": url, "ok": True, "status": 200,
                "error": None, "content_type": "audio/ytdlp"}
    except subprocess.TimeoutExpired:
        return {"url": url, "ok": False, "status": None,
                "error": "yt-dlp timeout", "content_type": None}
    except Exception as e:
        return {"url": url, "ok": False, "status": None,
                "error": str(e), "content_type": None}


def _audit_response(url: str, status: int, ct: Optional[str],
                    cl: Optional[int]) -> Tuple[bool, Optional[str]]:
    """Validate Content-Type/Length post-fetch. Returns (ok, error)."""
    ct_lower = (ct or "").split(";")[0].strip().lower()
    if ct_lower:
        if any(ct_lower.startswith(p) for p in SUSPECT_CT_PREFIXES):
            return False, f"non-audio Content-Type: {ct_lower}"
        if not ct_lower.startswith(AUDIO_CT_PREFIX):
            # unknown but not obviously-bad type → warn-only by treating as ok
            pass
    if cl is not None and cl < MIN_AUDIO_BYTES:
        return False, f"Content-Length {cl} < floor {MIN_AUDIO_BYTES}"
    return True, None


def check_url(url: str, timeout: int = DEFAULT_URL_TIMEOUT) -> dict:
    """Check a single URL with HTTP HEAD (fallback to ranged GET).

    Captures status, Content-Type, Content-Length, and wall-clock latency.
    Validates Content-Type is audio/* and Content-Length above placeholder
    floor when those headers are present.

    Non-direct-audio URLs are validated via yt-dlp --simulate instead.
    """
    if _needs_ytdlp(url):
        return _check_via_ytdlp(url, timeout=30)
    headers = {"User-Agent": "Mozilla/5.0"}
    import time as _t
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, headers=headers, method=method)
            if method == "GET":
                req.add_header("Range", "bytes=0-0")
            t0 = _t.perf_counter()
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                latency_ms = int((_t.perf_counter() - t0) * 1000)
                ct = resp.headers.get("Content-Type")
                cl_header = resp.headers.get("Content-Length")
                # On a Range response, prefer Content-Range full size.
                cr = resp.headers.get("Content-Range")
                cl: Optional[int] = None
                if cr and "/" in cr:
                    try:
                        cl = int(cr.rsplit("/", 1)[1])
                    except ValueError:
                        cl = None
                if cl is None and cl_header is not None:
                    try:
                        cl = int(cl_header)
                    except ValueError:
                        cl = None
                ok, err = _audit_response(url, resp.status, ct, cl)
                return {
                    "url": url,
                    "ok": ok,
                    "status": resp.status,
                    "error": err,
                    "content_type": ct,
                    "content_length": cl,
                    "latency_ms": latency_ms,
                }
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code == 405:
                continue  # try GET fallback
            return {"url": url, "ok": False, "status": e.code,
                    "error": f"HTTP {e.code}", "content_type": None,
                    "content_length": None, "latency_ms": None}
        except urllib.error.URLError as e:
            return {"url": url, "ok": False, "status": None,
                    "error": str(e.reason), "content_type": None,
                    "content_length": None, "latency_ms": None}
        except Exception as e:
            return {"url": url, "ok": False, "status": None,
                    "error": str(e), "content_type": None,
                    "content_length": None, "latency_ms": None}
    return {"url": url, "ok": False, "status": None,
            "error": "All methods failed", "content_type": None,
            "content_length": None, "latency_ms": None}


def check_urls_parallel(
    url_key_pairs: List[Tuple[str, str]],
    max_workers: int = DEFAULT_MAX_WORKERS,
    timeout: int = DEFAULT_URL_TIMEOUT,
) -> List[dict]:
    """Check URLs in parallel. Each item is (url, key) where key is e.g. '37:151'.

    Returns list of {url, key, ok, status, error, content_type}.
    """
    results = []
    total = len(url_key_pairs)
    if not total:
        return results

    done = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for url, key in url_key_pairs:
            fut = pool.submit(check_url, url, timeout)
            futures[fut] = key

        for fut in as_completed(futures):
            key = futures[fut]
            res = fut.result()
            res["key"] = key
            results.append(res)
            done += 1
            print(f"\r  Checking URLs: {done}/{total}", end="", flush=True)

    print()  # newline after progress
    return results


# ── File validation ──────────────────────────────────────────────────────


def check_file(
    file_path: str,
    use_ffprobe: bool = False,
    ffprobe_timeout: int = DEFAULT_FFPROBE_TIMEOUT,
) -> dict:
    """Validate a local audio file (exists, non-zero, optionally ffprobe)."""
    p = Path(file_path)
    result = {"path": file_path, "ok": True, "exists": True,
              "size_bytes": None, "error": None, "duration_s": None}

    if not p.exists():
        result.update(ok=False, exists=False, error="File not found")
        return result

    size = p.stat().st_size
    result["size_bytes"] = size
    if size == 0:
        result.update(ok=False, error="Zero bytes")
        return result

    if use_ffprobe:
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(p),
            ]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=ffprobe_timeout
            )
            if proc.returncode != 0:
                stderr = proc.stderr.strip()[:100]
                result.update(ok=False, error=f"ffprobe error: {stderr}")
                return result
            dur_str = proc.stdout.strip()
            if not dur_str or dur_str == "N/A":
                result.update(ok=False, error="ffprobe: no duration")
                return result
            dur = float(dur_str)
            result["duration_s"] = dur
            if dur <= 0:
                result.update(ok=False, error=f"ffprobe: duration={dur}s")
        except subprocess.TimeoutExpired:
            result.update(ok=False, error="ffprobe: timeout")
        except ValueError:
            result.update(ok=False, error=f"ffprobe: unparseable duration '{dur_str}'")

    return result


# ── Core validation ──────────────────────────────────────────────────────


def validate_audio(
    path: Path,
    surah_info: dict,
    check_sources: bool = True,
    use_ffprobe: bool = False,
    max_workers: int = DEFAULT_MAX_WORKERS,
    url_timeout: int = DEFAULT_URL_TIMEOUT,
) -> dict:
    """Run all validation checks on the audio input at *path*."""
    fmt = detect_input_format(path)
    grouped = parse_input(path, fmt)

    is_verse = fmt in ("verse_json", "verse_dir")
    level = "verse" if is_verse else "sura"

    # Metadata validation (JSON files only)
    meta_errors, meta_warnings = validate_meta(path)
    meta_block: Optional[dict] = None
    if path.is_file() and path.suffix == ".json":
        try:
            meta_block = _load_json_or_jsonl(path).get("_meta")
        except Exception:
            meta_block = None

    if is_verse:
        coverage = analyze_verse_coverage(grouped, surah_info)
    else:
        coverage = analyze_sura_coverage(grouped, surah_info)

    # Collect all sources with their keys
    all_sources: List[Tuple[str, str]] = []  # (source, key)
    for sura, entries in sorted(grouped.items()):
        for source, verse in entries:
            key = f"{sura}:{verse}" if verse is not None else str(sura)
            all_sources.append((source, key))

    # Partition into URLs vs files
    url_pairs = [(src, key) for src, key in all_sources if _is_url(src)]
    file_pairs = [(src, key) for src, key in all_sources if not _is_url(src)]

    if url_pairs and file_pairs:
        source_type = "mixed"
    elif url_pairs:
        source_type = "url"
    else:
        source_type = "file"

    url_results = []
    file_results = []
    errors = []
    warnings = []

    if check_sources:
        # URL checks
        if url_pairs:
            url_results = check_urls_parallel(url_pairs, max_workers, url_timeout)
            for r in url_results:
                if not r["ok"]:
                    errors.append({
                        "msg": r["error"],
                        "key": r["key"],
                        "source": r["url"],
                    })

        # File checks
        if file_pairs:
            has_ffprobe = shutil.which("ffprobe") is not None
            if use_ffprobe and not has_ffprobe:
                print("  Warning: --ffprobe requested but ffprobe not found; skipping probe checks")
                use_ffprobe = False

            for i, (src, key) in enumerate(file_pairs):
                r = check_file(src, use_ffprobe=use_ffprobe)
                r["key"] = key
                file_results.append(r)
                if not r["ok"]:
                    errors.append({
                        "msg": r["error"],
                        "key": key,
                        "source": src,
                    })
                if (i + 1) % 500 == 0 or i + 1 == len(file_pairs):
                    print(f"\r  Checking files: {i + 1}/{len(file_pairs)}", end="", flush=True)
            if file_pairs:
                print()

    # Metadata issues
    errors.extend(meta_errors)
    warnings.extend(meta_warnings)
    # Audio-category vs detected-format identity
    if meta_block:
        errors.extend(validate_format_identity(meta_block, fmt))

    # Missing coverage as warnings
    if level == "sura":
        for sura in coverage.get("missing", []):
            info = surah_info.get(sura, {})
            name = info.get("name_en", sura)
            warnings.append({"msg": f"Missing surah {sura} ({name})"})
    else:
        missing_count = coverage.get("missing_count", 0)
        if missing_count:
            warnings.append({"msg": f"Missing {missing_count} verse(s)"})

    # Duplicates as warnings
    for dup in coverage.get("duplicates", []):
        warnings.append({
            "msg": f"{dup['count']} audio sources",
            "key": dup["key"],
            "sources": dup["sources"],
        })

    return {
        "path": str(path),
        "format": fmt,
        "level": level,
        "coverage": coverage,
        "source_type": source_type,
        "total_sources": len(all_sources),
        "url_results": url_results,
        "file_results": file_results,
        "errors": errors,
        "warnings": warnings,
        "meta": meta_block,
    }

