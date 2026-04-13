"""CI wrapper for audio manifest validation.

Runs validate_audio checks on changed manifests, produces a markdown PR
comment, and outputs a JSON summary of metadata changes for downstream
issue-update steps.

Usage (called by .github/workflows/validate-audio-pr.yml):
    python validators/validate_audio_ci.py \\
        --base-sha <sha> \\
        --comment-file /tmp/pr_comment.md \\
        --changes-json /tmp/changes.json \\
        data/audio/by_surah/mp3quran/new_reciter.json [...]
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

from validate_audio import (  # noqa: E402
    ALL_META_KEYS,
    validate_audio,
    load_surah_info,
)
from config_loader import load_template  # noqa: E402

_VALIDATION_HEADER = load_template("reports/audio-validation-header").strip()

# Fields to compare when diffing _meta between base and HEAD versions.
_DIFF_KEYS = list(ALL_META_KEYS) + ["fetched"]


# ---------------------------------------------------------------------------
# Meta diffing
# ---------------------------------------------------------------------------

def _load_meta_from_text(text: str) -> dict:
    """Extract _meta from manifest text (single-line or pretty-printed)."""
    first_line = text.split("\n", 1)[0]
    try:
        meta = json.loads(first_line).get("_meta")
        if meta is not None:
            return meta
    except (json.JSONDecodeError, AttributeError):
        pass
    try:
        return json.loads(text).get("_meta", {})
    except (json.JSONDecodeError, AttributeError):
        return {}


def diff_meta(path: Path, base_sha: str) -> dict | None:
    """Compare _meta of *path* at HEAD vs *base_sha*.

    Returns ``None`` if the file is new (does not exist at *base_sha*),
    or a dict ``{field: {"old": v1, "new": v2}}`` for changed fields.
    Returns an empty dict if nothing changed.
    """
    try:
        rel = path.resolve().relative_to(_PROJECT_ROOT.resolve())
    except ValueError:
        return None

    try:
        base_text = subprocess.check_output(
            ["git", "show", f"{base_sha}:{rel}"],
            cwd=_PROJECT_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except subprocess.CalledProcessError:
        return None  # file is new

    base_meta = _load_meta_from_text(base_text)
    head_meta = _load_meta_from_text(path.read_text(encoding="utf-8"))

    changes = {}
    for key in _DIFF_KEYS:
        old = base_meta.get(key)
        new = head_meta.get(key)
        if old != new:
            changes[key] = {"old": old, "new": new}
    return changes


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _short_path(path_str: str) -> str:
    """Strip ``data/audio/`` prefix for concise display."""
    p = Path(path_str)
    try:
        rel = p.resolve().relative_to((_PROJECT_ROOT / "data" / "audio").resolve())
        return str(rel)
    except ValueError:
        try:
            return str(p.resolve().relative_to(_PROJECT_ROOT.resolve()))
        except ValueError:
            return p.name


def _coverage_str(result: dict) -> str:
    cov = result["coverage"]
    present = cov.get("present_count", len(cov.get("present", [])))
    total = cov["total"]
    unit = "surahs" if result["level"] == "sura" else "ayahs"
    return f"{present} / {total} {unit}"


def _source_str(result: dict) -> str:
    url_results = result["url_results"]
    file_results = result["file_results"]
    if not url_results and not file_results:
        return "not checked"
    ok = sum(1 for r in url_results if r["ok"]) + sum(1 for r in file_results if r["ok"])
    total = len(url_results) + len(file_results)
    errs = total - ok
    if errs == 0:
        return f"{total} reachable, 0 errors"
    return f"{ok}/{total} reachable, {errs} errors"


def _meta_status(result: dict) -> str:
    meta_errors = [e for e in result["errors"] if e.get("msg", "").startswith("_meta")]
    meta_warnings = [w for w in result["warnings"] if w.get("msg", "").startswith("_meta")]
    if meta_errors:
        return f"{'x'} {len(meta_errors)} error(s)"
    if meta_warnings:
        return f"{'!'} {len(meta_warnings)} warning(s)"
    return "all fields valid"


def _meta_summary_short(result: dict) -> str:
    """One-character meta status for table view."""
    meta_errors = [e for e in result["errors"] if e.get("msg", "").startswith("_meta")]
    meta_warnings = [w for w in result["warnings"] if w.get("msg", "").startswith("_meta")]
    if meta_errors:
        return f"x {len(meta_errors)} err"
    if meta_warnings:
        return f"! {len(meta_warnings)} warn"
    return "ok"


def _format_meta_diff(changes: dict) -> str:
    """Format meta diff as markdown lines."""
    lines = []
    for field, vals in changes.items():
        old = vals["old"] if vals["old"] is not None else "(missing)"
        new = vals["new"] if vals["new"] is not None else "(removed)"
        lines.append(f"  - **{field}:** ~~{old}~~ {new}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def _format_single(result: dict, meta_diff: dict | None) -> str:
    """Prose-style report for a single manifest."""
    sp = _short_path(result["path"])
    meta = result.get("meta") or {}
    name_en = meta.get("name_en", "")
    name_ar = meta.get("name_ar", "")
    header = f"**`{sp}`**"
    if name_en:
        header += f" -- {name_en}"
        if name_ar:
            header += f" ({name_ar})"

    lines = [
        _VALIDATION_HEADER,
        "",
        header,
        f"- Coverage: {_coverage_str(result)}",
    ]

    # Meta summary line
    riwayah = meta.get("riwayah", "?")
    style = meta.get("style", "?")
    country = meta.get("country", "?")
    lines.append(f"- Riwayah: {riwayah} | Style: {style} | Country: {country}")

    lines.append(f"- Sources: {_source_str(result)}")
    lines.append(f"- Meta: {_meta_status(result)}")

    if meta_diff:
        lines.append("- **Meta changes:**")
        lines.append(_format_meta_diff(meta_diff))

    # Errors detail
    non_meta_errors = [e for e in result["errors"] if not e.get("msg", "").startswith("_meta")]
    if non_meta_errors:
        lines.append("")
        lines.append(f"**{len(non_meta_errors)} source error(s):**")
        for e in non_meta_errors[:10]:
            key = e.get("key", "")
            lines.append(f"- `{key}`: {e['msg']}")
        if len(non_meta_errors) > 10:
            lines.append(f"- ... and {len(non_meta_errors) - 10} more")

    return "\n".join(lines)


def _format_multi(results: list[dict], meta_diffs: dict) -> str:
    """Table + details report for multiple manifests."""
    lines = [
        _VALIDATION_HEADER,
        "",
        "| File | Reciter | Coverage | Sources | Meta |",
        "|------|---------|----------|---------|------|",
    ]

    for result in results:
        sp = _short_path(result["path"])
        meta = result.get("meta") or {}
        name = meta.get("name_en", Path(result["path"]).stem)
        cov = _coverage_str(result)
        src = _source_str(result)
        ms = _meta_summary_short(result)
        lines.append(f"| `{sp}` | {name} | {cov} | {src} | {ms} |")

    # Details per file
    lines.append("")
    lines.append("<details><summary>Details</summary>")
    lines.append("")
    for result in results:
        sp = _short_path(result["path"])
        slug = Path(result["path"]).stem
        meta = result.get("meta") or {}
        lines.append(f"### `{sp}`")
        riwayah = meta.get("riwayah", "?")
        style = meta.get("style", "?")
        country = meta.get("country", "?")
        lines.append(f"- Riwayah: {riwayah} | Style: {style} | Country: {country}")
        lines.append(f"- Coverage: {_coverage_str(result)}")
        lines.append(f"- Sources: {_source_str(result)}")
        lines.append(f"- Meta: {_meta_status(result)}")

        md = meta_diffs.get(slug)
        if md:
            lines.append("- **Meta changes:**")
            lines.append(_format_meta_diff(md))

        non_meta_errors = [e for e in result["errors"] if not e.get("msg", "").startswith("_meta")]
        if non_meta_errors:
            lines.append(f"- **{len(non_meta_errors)} source error(s):**")
            for e in non_meta_errors[:5]:
                key = e.get("key", "")
                lines.append(f"  - `{key}`: {e['msg']}")
            if len(non_meta_errors) > 5:
                lines.append(f"  - ... and {len(non_meta_errors) - 5} more")
        lines.append("")

    lines.append("</details>")
    return "\n".join(lines)


def format_report(results: list[dict], meta_diffs: dict) -> str:
    """Adaptive markdown report: prose for 1 file, table for multiple."""
    if len(results) == 1:
        slug = Path(results[0]["path"]).stem
        return _format_single(results[0], meta_diffs.get(slug))
    return _format_multi(results, meta_diffs)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="CI audio manifest validation")
    parser.add_argument("manifests", nargs="+", type=Path,
                        help="Manifest file paths to validate")
    parser.add_argument("--base-sha", required=True,
                        help="Base commit SHA for meta diffing")
    parser.add_argument("--comment-file", type=Path, required=True,
                        help="Output path for markdown PR comment")
    parser.add_argument("--changes-json", type=Path, required=True,
                        help="Output path for structured meta changes JSON")
    parser.add_argument("--no-check-sources", action="store_true",
                        help="Skip URL/file reachability checks")
    args = parser.parse_args()

    surah_info = load_surah_info(_PROJECT_ROOT / "data" / "surah_info.json")

    results = []
    meta_diffs = {}
    has_errors = False

    for manifest_path in args.manifests:
        path = manifest_path.resolve()
        if not path.exists():
            print(f"Warning: {manifest_path} does not exist, skipping")
            continue

        print(f"Validating {_short_path(str(path))}...")
        result = validate_audio(
            path, surah_info,
            check_sources=not args.no_check_sources,
        )
        results.append(result)

        if result["errors"]:
            has_errors = True

        diff = diff_meta(path, args.base_sha)
        if diff:  # non-empty dict means changes detected
            slug = path.stem
            meta_diffs[slug] = diff

    if not results:
        args.comment_file.write_text("## Audio Manifest Validation\n\nNo manifests to validate.")
        args.changes_json.write_text("{}")
        return

    comment = format_report(results, meta_diffs)
    args.comment_file.write_text(comment, encoding="utf-8")
    args.changes_json.write_text(
        json.dumps(meta_diffs, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"\nComment written to {args.comment_file}")
    if meta_diffs:
        print(f"Meta changes detected for: {', '.join(meta_diffs.keys())}")

    sys.exit(1 if has_errors else 0)


if __name__ == "__main__":
    main()
