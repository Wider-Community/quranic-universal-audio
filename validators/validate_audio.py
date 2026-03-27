"""Validate audio input before running extract_segments.py.

Auto-detects the input format (verse/sura JSON or directory), reports
coverage (X/114 surahs or X/6236 verses), validates URL reachability
or local file integrity, and flags duplicates.

Usage:
    python validate_audio.py <path>                  # auto-detect & validate
    python validate_audio.py <path> --ffprobe        # also check with ffprobe
    python validate_audio.py <path> --no-check-sources   # coverage only
"""

import argparse
import io
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


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
VALID_STYLES = ("murattal", "mujawwad", "muallim", "unknown")
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

    return errors, warnings


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


def check_url(url: str, timeout: int = DEFAULT_URL_TIMEOUT) -> dict:
    """Check a single URL with HTTP HEAD (fallback to ranged GET)."""
    headers = {"User-Agent": "Mozilla/5.0"}
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, headers=headers, method=method)
            if method == "GET":
                req.add_header("Range", "bytes=0-0")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return {
                    "url": url,
                    "ok": True,
                    "status": resp.status,
                    "error": None,
                    "content_type": resp.headers.get("Content-Type"),
                }
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code == 405:
                continue  # try GET fallback
            return {"url": url, "ok": False, "status": e.code,
                    "error": f"HTTP {e.code}", "content_type": None}
        except urllib.error.URLError as e:
            return {"url": url, "ok": False, "status": None,
                    "error": str(e.reason), "content_type": None}
        except Exception as e:
            return {"url": url, "ok": False, "status": None,
                    "error": str(e), "content_type": None}
    return {"url": url, "ok": False, "status": None,
            "error": "All methods failed", "content_type": None}


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

    # Duplicates as warnings
    for dup in coverage.get("duplicates", []):
        warnings.append({
            "msg": f"{dup['count']} audio sources",
            "key": dup["key"],
            "sources": dup["sources"],
        })

    # Load _meta for display if available
    meta_block = None
    if path.is_file() and path.suffix == ".json":
        raw = _load_json_or_jsonl(path)
        meta_block = raw.get("_meta")

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


# ── Verbose output ───────────────────────────────────────────────────────


def _print_verbose(results: dict, surah_info: dict, top_n: int) -> None:
    """Pretty-print a detailed report."""
    W = 72
    cov = results["coverage"]
    level = results["level"]
    fmt = results["format"]

    print("=" * W)
    print(f"  Audio Validation: {_rel_path(Path(results['path']))}")
    print(f"  Format: {fmt} ({level}-level)")
    print("=" * W)

    # ── Metadata ──
    meta = results.get("meta")
    if meta:
        print(f"\n--- Metadata ---")
        for key in ALL_META_KEYS:
            val = meta.get(key, "")
            status = "" if val else "  (empty)"
            print(f"  {key:<18} {val}{status}")
    else:
        # Check if this is a JSON file (metadata expected)
        if Path(results["path"]).suffix == ".json":
            print(f"\n--- Metadata ---")
            print(f"  ERROR: _meta block missing")

    # ── Coverage ──
    pct = cov["present_count"] / cov["total"] * 100 if cov["total"] else 0
    print(f"\n--- Coverage ---")
    if level == "sura":
        print(f"  Surahs found:       {cov['present_count']} / {cov['total']}  ({pct:.1f}%)")
        print(f"  Missing surahs:     {len(cov['missing'])}")
    else:
        print(f"  Verses found:       {cov['present_count']} / {cov['total']}  ({pct:.1f}%)")
        n_suras_missing = len(cov.get("fully_missing_suras", []))
        n_partial = len(cov.get("partial_suras", []))
        print(f"  Missing verses:     {cov['missing_count']}  "
              f"({n_suras_missing} fully missing surahs, {n_partial} partial)")

    # ── Missing details ──
    if level == "sura" and cov["missing"]:
        n_show = min(top_n, len(cov["missing"]))
        print(f"\n--- Missing Surahs (first {n_show} of {len(cov['missing'])}) ---")
        for sura in cov["missing"][:n_show]:
            info = surah_info.get(sura, {})
            name = info.get("name_en", "?")
            nv = info.get("num_verses", "?")
            print(f"  Sura {sura:<4}  {name:<25} ({nv} verses)")
        if len(cov["missing"]) > n_show:
            print(f"  ... and {len(cov['missing']) - n_show} more")

    elif level == "verse":
        fully = cov.get("fully_missing_suras", [])
        partial = cov.get("partial_suras", [])
        missing_by_sura = cov.get("missing_by_sura", {})

        if fully:
            n_show = min(top_n, len(fully))
            print(f"\n--- Fully Missing Surahs (first {n_show} of {len(fully)}) ---")
            for sura in fully[:n_show]:
                info = surah_info.get(sura, {})
                name = info.get("name_en", "?")
                nv = info.get("num_verses", "?")
                print(f"  Sura {sura:<4}  {name:<25} ({nv} verses)")
            if len(fully) > n_show:
                print(f"  ... and {len(fully) - n_show} more")

        if partial:
            n_show = min(top_n, len(partial))
            print(f"\n--- Partially Missing Surahs (first {n_show} of {len(partial)}) ---")
            for sura in partial[:n_show]:
                info = surah_info.get(sura, {})
                name = info.get("name_en", "?")
                mv = missing_by_sura.get(sura, [])
                if len(mv) <= 10:
                    verses_str = ", ".join(str(v) for v in mv)
                else:
                    verses_str = ", ".join(str(v) for v in mv[:10]) + f" ... (+{len(mv) - 10})"
                print(f"  Sura {sura:<4}  {name:<25}  missing: {verses_str}")
            if len(partial) > n_show:
                print(f"  ... and {len(partial) - n_show} more")

    # ── Duplicates ──
    dups = cov.get("duplicates", [])
    if dups:
        n_show = min(top_n, len(dups))
        print(f"\n--- Duplicates ({len(dups)}) ---")
        for dup in dups[:n_show]:
            print(f"  WARN  {dup['key']} has {dup['count']} audio sources")
            for src in dup["sources"][:3]:
                print(f"        - {src}")
            if len(dup["sources"]) > 3:
                print(f"        ... and {len(dup['sources']) - 3} more")

    # ── Source validation ──
    url_results = results["url_results"]
    file_results = results["file_results"]
    errors = results["errors"]

    if url_results:
        ok_count = sum(1 for r in url_results if r["ok"])
        fail_count = len(url_results) - ok_count
        print(f"\n--- Source Validation (URLs) ---")
        print(f"  Reachable:      {ok_count} / {len(url_results)}")
        print(f"  Unreachable:    {fail_count}")

        if fail_count:
            failed = [r for r in url_results if not r["ok"]]
            n_show = min(top_n, len(failed))
            print()
            for r in failed[:n_show]:
                print(f"  ERROR  {r['key']:<12}  {r['error']}")
                print(f"         {r['url']}")
            if len(failed) > n_show:
                print(f"  ... and {len(failed) - n_show} more")

    if file_results:
        ok_count = sum(1 for r in file_results if r["ok"])
        fail_count = len(file_results) - ok_count
        print(f"\n--- Source Validation (Files) ---")
        print(f"  Valid:          {ok_count} / {len(file_results)}")
        print(f"  Invalid:        {fail_count}")

        if fail_count:
            failed = [r for r in file_results if not r["ok"]]
            n_show = min(top_n, len(failed))
            print()
            for r in failed[:n_show]:
                print(f"  ERROR  {r['key']:<12}  {r['error']}")
                print(f"         {r['path']}")
                if r.get("size_bytes") is not None:
                    print(f"         size: {r['size_bytes']} bytes")
            if len(failed) > n_show:
                print(f"  ... and {len(failed) - n_show} more")

    if not url_results and not file_results and not errors:
        print(f"\n--- Source Validation ---")
        print(f"  (skipped)")

    # ── Summary ──
    print(f"\n--- Summary ---")
    print(f"  Total sources:  {results['total_sources']}")
    print(f"  Source type:    {results['source_type']}")
    print(f"  Errors:         {len(errors)}")
    print(f"  Warnings:       {len(results['warnings'])}")
    print()


# ── Report I/O ────────────────────────────────────────────────────────


@contextmanager
def _tee_to_file(path: Path):
    """Copy stdout to *path* (overwritten) while still printing to console."""
    buf = io.StringIO()
    orig = sys.stdout

    class _Tee:
        def write(self, s):
            orig.write(s)
            buf.write(s)

        def flush(self):
            orig.flush()

    sys.stdout = _Tee()
    try:
        yield
    finally:
        sys.stdout = orig
        content = f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n" + buf.getvalue()
        path.write_text(content, encoding="utf-8")


# ── CLI ──────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Path to a JSON/JSONL file or directory of audio files.",
    )
    parser.add_argument(
        "--surah-info",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "surah_info.json",
        help="Path to surah_info.json (default: data/surah_info.json)",
    )
    parser.add_argument(
        "--no-check-sources",
        action="store_true",
        help="Skip URL/file validity checks (only report coverage).",
    )
    parser.add_argument(
        "--ffprobe",
        action="store_true",
        help="Use ffprobe to validate audio file format/duration.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help=f"Max threads for URL checks (default: {DEFAULT_MAX_WORKERS}).",
    )
    parser.add_argument(
        "--url-timeout",
        type=int,
        default=DEFAULT_URL_TIMEOUT,
        help=f"Timeout per URL check in seconds (default: {DEFAULT_URL_TIMEOUT}).",
    )
    parser.add_argument(
        "--top", "-n",
        type=int,
        default=30,
        help="Max items to show per category (default: 30).",
    )
    args = parser.parse_args()

    target = args.path.resolve()
    if not target.exists():
        print(f"Path not found: {_rel_path(target)}")
        sys.exit(1)

    surah_info = load_surah_info(args.surah_info)

    try:
        results = validate_audio(
            target,
            surah_info,
            check_sources=not args.no_check_sources,
            use_ffprobe=args.ffprobe,
            max_workers=args.max_workers,
            url_timeout=args.url_timeout,
        )
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if target.is_dir():
        report_path = target / "validation.log"
    else:
        report_path = target.parent / "validation.log"

    with _tee_to_file(report_path):
        _print_verbose(results, surah_info, args.top)

    print(f"Report saved to {_rel_path(report_path)}")

    # Exit code: 1 if any errors
    if results["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
