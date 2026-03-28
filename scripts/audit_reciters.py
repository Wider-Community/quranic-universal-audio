#!/usr/bin/env python3
"""
Audit reciter data consistency across all sources.

Cross-references:
- data/RECITERS.md (Aligned + Available tables)
- data/audio/ (audio manifests on disk)
- data/recitation_segments/ (segment files on disk)
- data/timestamps/ (timestamp files on disk, git-tracked only)
- README.md (badge counts: reciters + riwayat)
- dataset/README.md (badge counts: reciters + riwayat)
- GitHub issues (request labels)
- Notion database (request statuses)

Reports inconsistencies and optionally fixes them.
The primary fix mechanism is re-running list_reciters.py --write,
which regenerates RECITERS.md and all badges from disk state.

Usage:
    python scripts/audit_reciters.py              # report only
    python scripts/audit_reciters.py --fix         # fix and report
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from request_helpers import (
    REPO_ROOT,
    slug_from_name,
    gh_list_request_issues,
    notion_query_pending,
)
from list_reciters import (
    discover_reciters,
    collect_processed_reciters,
    load_riwayat_names,
    _is_full_coverage,
    _is_git_tracked,
    TIMESTAMPS_PATH,
)


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------
def collect_disk_state():
    """Gather the actual state of files on disk."""
    state = {
        "audio_manifests": {},      # slug -> {sources, riwayah, style, ...}
        "segments": {},             # slug -> {has_segments, has_detailed}
        "timestamps": {},           # slug -> {has_ts, has_ts_full, audio_type}
        "riwayat_with_data": set(), # set of riwayah slugs that have at least one manifest
    }

    # Audio manifests
    audio_dir = REPO_ROOT / "data" / "audio"
    for category in ("by_surah", "by_ayah"):
        cat_dir = audio_dir / category
        if not cat_dir.is_dir():
            continue
        for source_dir in sorted(cat_dir.iterdir()):
            if not source_dir.is_dir():
                continue
            source_path = f"{category}/{source_dir.name}"
            for f in sorted(source_dir.glob("*.json")):
                slug = f.stem
                try:
                    data = json.loads(f.read_text())
                    meta = data.get("_meta", {})
                except (json.JSONDecodeError, OSError):
                    meta = {}

                riwayah = meta.get("riwayah", "hafs_an_asim")
                state["riwayat_with_data"].add(riwayah)

                if slug not in state["audio_manifests"]:
                    state["audio_manifests"][slug] = {
                        "sources": [],
                        "name": meta.get("name_en", slug.replace("_", " ").title()),
                        "riwayah": riwayah,
                        "style": meta.get("style", "murattal"),
                    }
                state["audio_manifests"][slug]["sources"].append(source_path)

    # Segments
    seg_dir = REPO_ROOT / "data" / "recitation_segments"
    if seg_dir.is_dir():
        for d in sorted(seg_dir.iterdir()):
            if not d.is_dir():
                continue
            state["segments"][d.name] = {
                "has_segments": (d / "segments.json").exists(),
                "has_detailed": (d / "detailed.json").exists(),
            }

    # Timestamps (git-tracked only)
    ts_base = REPO_ROOT / "data" / "timestamps"
    for audio_type in ("by_surah_audio", "by_ayah_audio"):
        ts_dir = ts_base / audio_type
        if not ts_dir.is_dir():
            continue
        for d in sorted(ts_dir.iterdir()):
            if not d.is_dir():
                continue
            ts_file = d / "timestamps.json"
            ts_full = d / "timestamps_full.json"
            has_ts = _is_git_tracked(ts_file)
            has_ts_full = _is_git_tracked(ts_full)
            if has_ts or has_ts_full:
                state["timestamps"][d.name] = {
                    "has_ts": has_ts,
                    "has_ts_full": has_ts_full,
                    "audio_type": audio_type,
                }

    return state


def collect_readme_badges():
    """Parse badge counts from README.md and dataset/README.md."""
    result = {}
    for key, path in [("readme", REPO_ROOT / "README.md"), ("dataset", REPO_ROOT / "dataset" / "README.md")]:
        text = path.read_text() if path.exists() else ""
        avail_match = re.search(r"Available%20Reciters-(\d+)%20%28(\d+)%20Full%20Coverage%29", text)
        aligned_match = re.search(r"Aligned%20Reciters-(\d+)%20%28(\d+)%20Full%20Coverage%29", text)
        riw_match = re.search(r"Riwayat-(\d+)(%20%2F%20)(\d+)", text)
        result[key] = {
            "available": int(avail_match.group(1)) if avail_match else None,
            "available_full": int(avail_match.group(2)) if avail_match else None,
            "aligned": int(aligned_match.group(1)) if aligned_match else None,
            "aligned_full": int(aligned_match.group(2)) if aligned_match else None,
            "riwayat_active": int(riw_match.group(1)) if riw_match else None,
            "riwayat_total": int(riw_match.group(3)) if riw_match else None,
            "has_riwayat_badge": riw_match is not None,
            "raw": text,
        }
    return result


# ---------------------------------------------------------------------------
# Audit checks
# ---------------------------------------------------------------------------
def audit(disk, badges):
    """Run all consistency checks. Returns list of (severity, message)."""
    issues = []

    # Count expected values
    all_records = discover_reciters()
    processed = collect_processed_reciters()
    processed_slugs = {p["slug"] for p in processed}
    available_records = [r for r in all_records if r["slug"] not in processed_slugs]
    expected_available = len(available_records)
    expected_aligned = len(processed)
    expected_available_full = sum(
        1 for r in available_records
        if _is_full_coverage(r["audio_cat"], r["coverage"])
    )
    expected_aligned_full = sum(
        1 for p in processed
        if p["surah_count"] == 114 or p["ayah_count"] == 6236
    )

    riwayat_total = len(json.loads((REPO_ROOT / "data" / "riwayat.json").read_text()))
    riwayat_active = len(disk["riwayat_with_data"])

    # ── 1. Processed reciters: segments on disk ────────────────────────
    for p in processed:
        slug = p["slug"]
        has_seg = slug in disk["segments"] and disk["segments"][slug]["has_segments"]
        if not has_seg:
            issues.append(("WARN", f"Aligned reciter '{slug}' has no segments.json on disk (may be on Katana HPC)"))

    # ── 2. Processed reciters: timestamp level vs git-tracked ──────────
    for p in processed:
        slug = p["slug"]
        ts = disk["timestamps"].get(slug, {})
        has_ts = ts.get("has_ts", False)
        has_full = ts.get("has_ts_full", False)

        if has_ts:
            expected = "✓✓" if has_full else "✓"
        else:
            expected = "✗"

        actual = p["ts_level"]
        if actual != expected:
            issues.append(("FIX", f"Aligned '{slug}' timestamp column is '{actual}' but should be '{expected}' (git-tracked state)"))

    # ── 3. Reciters with segments on disk but not in Aligned table ─────
    for slug, seg_info in disk["segments"].items():
        if seg_info["has_segments"] and slug not in processed_slugs:
            issues.append(("WARN", f"'{slug}' has segments on disk but is not in Aligned table"))

    # ── 4. Audio manifests without style field ────────────────────────
    audio_dir = REPO_ROOT / "data" / "audio"
    for category in ("by_surah", "by_ayah"):
        cat_dir = audio_dir / category
        if not cat_dir.is_dir():
            continue
        for source_dir in cat_dir.iterdir():
            if not source_dir.is_dir():
                continue
            for f in source_dir.glob("*.json"):
                try:
                    data = json.loads(f.read_text())
                    meta = data.get("_meta", {})
                    if "style" not in meta:
                        issues.append(("FIX", f"Manifest '{f.relative_to(REPO_ROOT)}' missing 'style' field"))
                except (json.JSONDecodeError, OSError):
                    pass

    # ── 5. README badge counts ─────────────────────────────────────────
    for key, label in [("readme", "README.md"), ("dataset", "dataset/README.md")]:
        b = badges[key]
        if b["available"] is not None and b["available"] != expected_available:
            issues.append(("FIX", f"{label} available badge: {b['available']} but expected {expected_available}"))
        if b["available_full"] is not None and b["available_full"] != expected_available_full:
            issues.append(("FIX", f"{label} available full coverage: {b['available_full']} but expected {expected_available_full}"))
        if b["aligned"] is not None and b["aligned"] != expected_aligned:
            issues.append(("FIX", f"{label} aligned badge: {b['aligned']} but expected {expected_aligned}"))
        if b["aligned_full"] is not None and b["aligned_full"] != expected_aligned_full:
            issues.append(("FIX", f"{label} aligned full coverage: {b['aligned_full']} but expected {expected_aligned_full}"))
        if b["has_riwayat_badge"]:
            if b["riwayat_active"] != riwayat_active:
                issues.append(("FIX", f"{label} riwayat badge: {b['riwayat_active']} but expected {riwayat_active}"))
            if b["riwayat_total"] != riwayat_total:
                issues.append(("FIX", f"{label} riwayat badge: total {b['riwayat_total']} but expected {riwayat_total}"))
        elif b["raw"]:
            issues.append(("FIX", f"{label} missing riwayat badge"))

    # ── 6. Missing SOURCE files ───────────────────────────────────────
    for category in ("by_surah", "by_ayah"):
        cat_dir = audio_dir / category
        if not cat_dir.is_dir():
            continue
        for source_dir in cat_dir.iterdir():
            if not source_dir.is_dir():
                continue
            if any(source_dir.glob("*.json")) and not (source_dir / "SOURCE").exists():
                issues.append(("FIX", f"Missing SOURCE file in {source_dir.relative_to(REPO_ROOT)}"))

    return issues


# ---------------------------------------------------------------------------
# External source checks (Notion + GitHub)
# ---------------------------------------------------------------------------
def audit_external():
    """Check consistency with GitHub issues and Notion."""
    issues = []

    processed = collect_processed_reciters()
    processed_slugs = {p["slug"] for p in processed}

    # GitHub issues
    try:
        open_issues = gh_list_request_issues(state="open")
        closed_issues = gh_list_request_issues(state="closed")

        for iss in open_issues + closed_issues:
            slug = iss["slug"]
            if not slug:
                continue
            if iss["status"] == "awaiting-review" and slug in processed_slugs:
                issues.append(("WARN", f"Issue #{iss['number']} '{slug}' is awaiting-review but reciter is aligned"))
            if iss["status"] == "pending" and slug in processed_slugs:
                issues.append(("WARN", f"Issue #{iss['number']} '{slug}' is still pending but reciter is already aligned"))
    except Exception as e:
        issues.append(("WARN", f"Could not check GitHub issues: {e}"))

    # Notion
    try:
        pending = notion_query_pending()
        for req in pending:
            if req["slug"] in processed_slugs:
                issues.append(("WARN", f"Notion request for '{req['reciter_name']}' is Pending but reciter is already aligned"))
    except Exception as e:
        issues.append(("INFO", f"Could not check Notion: {e}"))

    return issues


# ---------------------------------------------------------------------------
# Fix application
# ---------------------------------------------------------------------------
def apply_fixes(disk):
    """Apply fixes by re-running list_reciters.py --write and updating dataset badge."""
    print("  Running list_reciters.py --write...")
    result = subprocess.run(
        [sys.executable, "scripts/list_reciters.py", "--write"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            print(f"    {line}")
    if result.returncode != 0:
        print(f"  ERROR: list_reciters.py failed: {result.stderr}")
        return False

    # Update dataset/README.md badges too
    dataset_readme_path = REPO_ROOT / "dataset" / "README.md"
    if dataset_readme_path.exists():
        ds_text = dataset_readme_path.read_text()
        original = ds_text

        # Reciter counts from list_reciters output
        all_records = discover_reciters()
        processed = collect_processed_reciters()
        processed_slugs = {p["slug"] for p in processed}
        available_records = [r for r in all_records if r["slug"] not in processed_slugs]
        available_count = len(available_records)
        aligned_count = len(processed)
        available_full = sum(
            1 for r in available_records
            if _is_full_coverage(r["audio_cat"], r["coverage"])
        )
        aligned_full = sum(
            1 for p in processed
            if p["surah_count"] == 114 or p["ayah_count"] == 6236
        )

        ds_text = re.sub(
            r"Available%20Reciters-\d+%20%28\d+%20Full%20Coverage%29",
            f"Available%20Reciters-{available_count}%20%28{available_full}%20Full%20Coverage%29",
            ds_text,
        )
        ds_text = re.sub(
            r"Aligned%20Reciters-\d+%20%28\d+%20Full%20Coverage%29",
            f"Aligned%20Reciters-{aligned_count}%20%28{aligned_full}%20Full%20Coverage%29",
            ds_text,
        )

        # Riwayat badge
        riwayat_active = len(disk["riwayat_with_data"])
        riwayat_total = len(json.loads((REPO_ROOT / "data" / "riwayat.json").read_text()))
        ds_text = re.sub(
            r"Riwayat-\d+(%20%2F%20)\d+",
            rf"Riwayat-{riwayat_active}\g<1>{riwayat_total}",
            ds_text,
        )

        if ds_text != original:
            dataset_readme_path.write_text(ds_text)
            print(f"  Updated dataset/README.md badges")

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Audit reciter data consistency")
    parser.add_argument("--fix", action="store_true", help="Apply fixes automatically")
    parser.add_argument("--skip-external", action="store_true", help="Skip Notion/GitHub checks")
    args = parser.parse_args()

    print("=" * 60)
    print("RECITER CONSISTENCY AUDIT")
    print("=" * 60)

    # Collect state
    print("\nCollecting disk state...")
    disk = collect_disk_state()
    print(f"  Audio manifests: {len(disk['audio_manifests'])} reciters")
    print(f"  Segments: {len(disk['segments'])} reciters")
    print(f"  Timestamps (git-tracked): {len(disk['timestamps'])} reciters")
    print(f"  Riwayat with data: {len(disk['riwayat_with_data'])}")

    print("\nParsing badges...")
    badges = collect_readme_badges()
    for key, label in [("readme", "README.md"), ("dataset", "dataset/README.md")]:
        b = badges[key]
        if b["available"] is not None:
            parts = [f"{b['available']} Available ({b['available_full']} Full) | {b['aligned']} Aligned ({b['aligned_full']} Full)"]
            if b["has_riwayat_badge"]:
                parts.append(f"Riwayat {b['riwayat_active']}/{b['riwayat_total']}")
            print(f"  {label}: {', '.join(parts)}")
        elif b["raw"]:
            print(f"  {label}: no reciters badge found")

    # Run audit
    print("\n" + "-" * 60)
    print("LOCAL CHECKS")
    print("-" * 60)
    issues = audit(disk, badges)

    # External checks
    ext_issues = []
    if not args.skip_external:
        print("\n" + "-" * 60)
        print("EXTERNAL CHECKS (GitHub + Notion)")
        print("-" * 60)
        ext_issues = audit_external()

    all_issues = issues + ext_issues

    # Report
    print("\n" + "=" * 60)
    print("AUDIT RESULTS")
    print("=" * 60)

    if not all_issues:
        print("\n  Everything is consistent. No issues found.")
        return

    errors = [i for i in all_issues if i[0] == "ERROR"]
    warnings = [i for i in all_issues if i[0] == "WARN"]
    fixable = [i for i in all_issues if i[0] == "FIX"]
    infos = [i for i in all_issues if i[0] == "INFO"]

    if errors:
        print(f"\n  ERRORS ({len(errors)}):")
        for _, msg in errors:
            print(f"    \u2717 {msg}")

    if fixable:
        print(f"\n  FIXABLE ({len(fixable)}):")
        for _, msg in fixable:
            print(f"    ~ {msg}")

    if warnings:
        print(f"\n  WARNINGS ({len(warnings)}):")
        for _, msg in warnings:
            print(f"    ! {msg}")

    if infos:
        print(f"\n  INFO ({len(infos)}):")
        for _, msg in infos:
            print(f"    i {msg}")

    print(f"\n  Total: {len(errors)} errors, {len(fixable)} fixable, {len(warnings)} warnings, {len(infos)} info")

    # Apply fixes
    if fixable and args.fix:
        print("\n" + "-" * 60)
        print("APPLYING FIXES")
        print("-" * 60)
        apply_fixes(disk)
        print("\nFixes applied. Review changes with 'git diff'.")
    elif fixable:
        print(f"\n  Run with --fix to apply.")


if __name__ == "__main__":
    main()
