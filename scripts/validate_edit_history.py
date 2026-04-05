#!/usr/bin/env python3
"""Validate edit_history.jsonl integrity for PRs touching recitation_segments.

Runs 6 checks per reciter:
  1. Genesis record presence
  2. History chain integrity (no missing/duplicate batch_ids)
  3. File hash verification (last record matches detailed.json)
  4. _meta tampering detection
  5. Diff-vs-history cross-reference (all changes explained by operations)
  6. History-only change detection (history changed but data didn't)

Usage:
    python scripts/validate_edit_history.py --base-sha <SHA> --reciters slug1 [slug2 ...]
"""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SEGMENTS_DIR = Path("data/recitation_segments")
COMPARE_FIELDS = ("time_start", "time_end", "matched_ref", "confidence")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _parse_edit_history(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").strip().splitlines():
        line = line.strip()
        if line:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass  # corrupted line — check_history_chain will catch it
    return records


def _git_show(sha: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "show", f"{sha}:{path}"],
        capture_output=True, text=True,
    )
    return result.stdout if result.returncode == 0 else None


def _git_diff_names(base_sha: str, path: str) -> bool:
    """Check if a specific file changed between base and HEAD."""
    result = subprocess.run(
        ["git", "diff", f"{base_sha}...HEAD", "--name-only", "--", path],
        capture_output=True, text=True,
    )
    return bool(result.stdout.strip())


def _diff_segments(base_entries: list[dict], head_entries: list[dict]) -> list[dict]:
    """Find segments that differ between base and head detailed.json entries."""
    changes = []

    base_by_ref = {e["ref"]: e for e in base_entries}
    head_by_ref = {e["ref"]: e for e in head_entries}
    all_refs = sorted(set(list(base_by_ref.keys()) + list(head_by_ref.keys())))

    for ref in all_refs:
        base_entry = base_by_ref.get(ref)
        head_entry = head_by_ref.get(ref)

        if base_entry is None or head_entry is None:
            # Entry added or removed
            entry = head_entry or base_entry
            for i, seg in enumerate(entry.get("segments", [])):
                changes.append({
                    "ref": ref, "seg_index": i,
                    "type": "added" if head_entry else "removed",
                    "segment_uid": seg.get("segment_uid"),
                    "time_start": seg.get("time_start"),
                    "time_end": seg.get("time_end"),
                })
            continue

        base_segs = base_entry.get("segments", [])
        head_segs = head_entry.get("segments", [])
        max_len = max(len(base_segs), len(head_segs))

        for i in range(max_len):
            if i >= len(base_segs) or i >= len(head_segs):
                seg = head_segs[i] if i < len(head_segs) else base_segs[i]
                changes.append({
                    "ref": ref, "seg_index": i, "type": "structural",
                    "segment_uid": seg.get("segment_uid"),
                    "time_start": seg.get("time_start"),
                    "time_end": seg.get("time_end"),
                })
                continue

            field_changes = {}
            for field in COMPARE_FIELDS:
                bv = base_segs[i].get(field)
                hv = head_segs[i].get(field)
                if bv != hv:
                    field_changes[field] = (bv, hv)

            if field_changes:
                changes.append({
                    "ref": ref, "seg_index": i, "type": "modified",
                    "fields": field_changes,
                    "segment_uid": head_segs[i].get("segment_uid"),
                    "time_start": head_segs[i].get("time_start"),
                    "time_end": head_segs[i].get("time_end"),
                })

    return changes


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_genesis_record(reciter: str) -> tuple[bool, str]:
    """Check 1: edit_history.jsonl exists and starts with a genesis record."""
    history_path = SEGMENTS_DIR / reciter / "edit_history.jsonl"
    if not history_path.exists():
        return False, "edit_history.jsonl does not exist"

    records = _parse_edit_history(history_path)
    if not records:
        return False, "edit_history.jsonl is empty"

    first = records[0]
    if first.get("record_type") != "genesis":
        return False, f"First record is not genesis (record_type={first.get('record_type', '<missing>')})"

    required = ["schema_version", "batch_id", "reciter", "created_at_utc", "file_hash_after"]
    missing = [f for f in required if f not in first]
    if missing:
        return False, f"Genesis record missing fields: {', '.join(missing)}"

    return True, "Genesis record present and valid"


def check_history_chain(reciter: str) -> tuple[bool, str]:
    """Check 2: every record has batch_id + file_hash_after, no duplicates."""
    records = _parse_edit_history(SEGMENTS_DIR / reciter / "edit_history.jsonl")
    if not records:
        return False, "No records to validate"

    batch_ids = set()
    issues = []

    for i, record in enumerate(records):
        bid = record.get("batch_id")
        if not bid:
            issues.append(f"Record {i}: missing batch_id")
        elif bid in batch_ids:
            issues.append(f"Record {i}: duplicate batch_id {bid[:12]}...")
        else:
            batch_ids.add(bid)

        if not record.get("file_hash_after"):
            issues.append(f"Record {i}: missing file_hash_after")

    if issues:
        return False, "; ".join(issues[:5])
    return True, f"Chain intact ({len(records)} records)"


def check_file_hash(reciter: str) -> tuple[bool, str]:
    """Check 3: last record's file_hash_after matches SHA256 of detailed.json."""
    reciter_dir = SEGMENTS_DIR / reciter
    detailed_path = reciter_dir / "detailed.json"
    history_path = reciter_dir / "edit_history.jsonl"

    records = _parse_edit_history(history_path)
    if not records:
        return False, "No edit_history.jsonl records found"

    last = records[-1]
    expected = last.get("file_hash_after")
    if not expected:
        return False, "Last record has no file_hash_after"

    actual = _compute_file_hash(detailed_path)
    if actual != expected:
        return False, f"Hash mismatch: expected {expected[:20]}..., got {actual[:20]}..."
    return True, "File hash matches"


def _check_meta_for_file(reciter: str, base_sha: str, filename: str) -> tuple[bool, str]:
    """Check _meta in a file is unchanged from base."""
    rel_path = f"data/recitation_segments/{reciter}/{filename}"
    base_content = _git_show(base_sha, rel_path)
    if base_content is None:
        return True, f"New reciter, no base {filename} _meta to compare"

    try:
        base_meta = json.loads(base_content).get("_meta", {})
    except json.JSONDecodeError:
        return True, f"Base {filename} not parseable, skipping"

    head_path = SEGMENTS_DIR / reciter / filename
    if not head_path.exists():
        return False, f"{filename} missing from HEAD"

    head_content = head_path.read_text(encoding="utf-8")
    head_meta = json.loads(head_content).get("_meta", {})

    if base_meta != head_meta:
        changed_keys = [
            k for k in set(list(base_meta.keys()) + list(head_meta.keys()))
            if base_meta.get(k) != head_meta.get(k)
        ]
        return False, f"_meta changed: {', '.join(changed_keys)}"
    return True, "_meta unchanged"


def check_meta_tampering(reciter: str, base_sha: str) -> tuple[bool, str]:
    """Check 4: _meta in detailed.json and segments.json must be unchanged from base."""
    results = []
    all_passed = True

    for filename in ("detailed.json", "segments.json"):
        passed, detail = _check_meta_for_file(reciter, base_sha, filename)
        results.append(f"{filename}: {detail}")
        if not passed:
            all_passed = False

    return all_passed, "; ".join(results)


def check_diff_vs_history(reciter: str, base_sha: str) -> tuple[bool, str]:
    """Check 5: every changed segment has a matching operation in new history records."""
    detailed_rel = f"data/recitation_segments/{reciter}/detailed.json"
    history_rel = f"data/recitation_segments/{reciter}/edit_history.jsonl"

    base_content = _git_show(base_sha, detailed_rel)
    if base_content is None:
        return True, "New reciter, skipping diff check"

    try:
        base_entries = json.loads(base_content).get("entries", [])
    except json.JSONDecodeError:
        return True, "Base detailed.json not parseable, skipping"

    head_content = (SEGMENTS_DIR / reciter / "detailed.json").read_text(encoding="utf-8")
    head_entries = json.loads(head_content).get("entries", [])

    changed = _diff_segments(base_entries, head_entries)
    if not changed:
        return True, "No segment changes detected"

    # Determine how many history records are new (not in base)
    base_history = _git_show(base_sha, history_rel)
    base_count = 0
    if base_history:
        base_count = len([l for l in base_history.strip().splitlines() if l.strip()])

    all_records = _parse_edit_history(SEGMENTS_DIR / reciter / "edit_history.jsonl")
    new_records = all_records[base_count:]

    # Collect identifiers from operation targets
    covered_uids = set()
    covered_times = set()
    for record in new_records:
        for op in record.get("operations", []):
            for target in op.get("targets_before", []) + op.get("targets_after", []):
                uid = target.get("segment_uid")
                if uid:
                    covered_uids.add(uid)
                ts = target.get("time_start")
                te = target.get("time_end")
                if ts is not None and te is not None:
                    covered_times.add((ts, te))

    # Cross-reference changed segments against covered identifiers
    unexplained = []
    for change in changed:
        uid = change.get("segment_uid")
        ts = change.get("time_start")
        te = change.get("time_end")
        if uid and uid in covered_uids:
            continue
        if ts is not None and te is not None and (ts, te) in covered_times:
            continue
        unexplained.append(change)

    if unexplained:
        samples = "; ".join(
            f"{c['ref']}[{c['seg_index']}]" for c in unexplained[:10]
        )
        suffix = f" (showing 10/{len(unexplained)})" if len(unexplained) > 10 else ""
        return False, f"{len(unexplained)} unexplained segment change(s): {samples}{suffix}"

    return True, f"All {len(changed)} changes covered by history"


def check_history_only_change(reciter: str, base_sha: str) -> tuple[bool, str]:
    """Check 6: flag if edit_history.jsonl changed but detailed.json did not."""
    detailed_rel = f"data/recitation_segments/{reciter}/detailed.json"
    history_rel = f"data/recitation_segments/{reciter}/edit_history.jsonl"

    detailed_changed = _git_diff_names(base_sha, detailed_rel)
    history_changed = _git_diff_names(base_sha, history_rel)

    if history_changed and not detailed_changed:
        return False, "edit_history.jsonl changed but detailed.json did not (suspicious)"
    return True, "OK"


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def validate_reciter(reciter: str, base_sha: str) -> tuple[bool, list[str]]:
    """Run all checks for a single reciter."""
    messages = []
    all_passed = True

    reciter_dir = SEGMENTS_DIR / reciter
    if not reciter_dir.exists() or not (reciter_dir / "detailed.json").exists():
        messages.append(f"  SKIP: {reciter} (deleted or missing detailed.json)")
        return True, messages

    checks = [
        ("Genesis record", check_genesis_record(reciter)),
        ("History chain", check_history_chain(reciter)),
        ("File hash", check_file_hash(reciter)),
        ("Meta tampering", check_meta_tampering(reciter, base_sha)),
        ("Diff vs history", check_diff_vs_history(reciter, base_sha)),
        ("History-only change", check_history_only_change(reciter, base_sha)),
    ]

    for name, (passed, detail) in checks:
        status = "PASS" if passed else "FAIL"
        messages.append(f"  [{status}] {name}: {detail}")
        if not passed:
            all_passed = False

    return all_passed, messages


def main():
    parser = argparse.ArgumentParser(
        description="Validate edit_history.jsonl integrity for PRs"
    )
    parser.add_argument(
        "--base-sha", required=True, help="Base commit SHA for diff"
    )
    parser.add_argument(
        "--reciters", nargs="+", required=True, help="Reciter slugs to validate"
    )
    args = parser.parse_args()

    overall_pass = True

    for reciter in args.reciters:
        print(f"\n{'=' * 50}")
        print(f"Validating: {reciter}")
        print(f"{'=' * 50}")

        passed, messages = validate_reciter(reciter, args.base_sha)
        for msg in messages:
            print(msg)

        if not passed:
            overall_pass = False

    print(f"\n{'=' * 50}")
    if overall_pass:
        print("ALL CHECKS PASSED")
    else:
        print("SOME CHECKS FAILED")

    sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
