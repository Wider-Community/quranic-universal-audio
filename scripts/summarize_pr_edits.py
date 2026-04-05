"""Generate a markdown summary of edits and validation for a merged segments PR.

Usage:
    python scripts/summarize_pr_edits.py <reciter_slug> [<reciter_slug2> ...]

Reads edit_history.jsonl and runs validate_segments to produce a concise
markdown summary suitable for posting on GitHub issues/PRs.

Output: writes to stdout (markdown).
"""

import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "validators"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "lib"))

from validate_segments import load_word_counts, validate_reciter  # noqa: E402
from config_loader import load_config, load_template  # noqa: E402

SURAH_INFO = PROJECT_ROOT / "data" / "surah_info.json"
SEGMENTS_ROOT = PROJECT_ROOT / "data" / "recitation_segments"

OP_LABELS = load_config("labels")["op_labels"]
_EDIT_SUMMARY_TPL = load_template("reports/edit-summary").strip()


def _parse_records(history_path: Path) -> list[dict]:
    """Parse edit_history.jsonl into a list of records."""
    if not history_path.exists():
        return []
    records = []
    with open(history_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _active_records(records: list[dict]) -> list[dict]:
    """Filter to active batch records, excluding genesis, reverts, and undone batches."""
    reverted_ids = {r["reverts_batch_id"] for r in records if r.get("reverts_batch_id")}
    return [
        r for r in records
        if r.get("record_type") != "genesis"
        and not r.get("reverts_batch_id")
        and r.get("batch_id") not in reverted_ids
        and r.get("operations")
    ]


def _summarize_edit_history(reciter_dir: Path) -> dict:
    """Parse edit_history.jsonl and return summary stats."""
    history_path = reciter_dir / "edit_history.jsonl"
    records = _parse_records(history_path)
    if not records:
        return {}

    active = _active_records(records)

    op_counts = Counter()
    chapters_edited = set()
    total_batches = 0
    fix_kind_counts = Counter()

    for record in active:
        total_batches += 1
        chapter = record.get("chapter")
        if chapter:
            chapters_edited.add(chapter)
        for mch in record.get("chapters") or []:
            chapters_edited.add(mch)
        for op in record.get("operations", []):
            op_type = op.get("op_type", "unknown")
            op_counts[op_type] += 1
            fix_kind = op.get("fix_kind", "unknown")
            fix_kind_counts[fix_kind] += 1

    return {
        "total_operations": sum(op_counts.values()),
        "total_batches": total_batches,
        "chapters_edited": len(chapters_edited),
        "op_counts": dict(op_counts),
        "fix_kind_counts": dict(fix_kind_counts),
    }


_ISSUE_LABELS = load_config("labels")["issue_labels"]


def _compute_issues_delta(reciter_dir: Path) -> dict | None:
    """Compute before→after delta from first-touch validation_summary per chapter."""
    history_path = reciter_dir / "edit_history.jsonl"
    records = _parse_records(history_path)
    if not records:
        return None

    active = _active_records(records)

    chapter_initial = {}
    chapter_final = {}

    for record in active:
        ch = record.get("chapter")
        if not ch:
            continue
        before = record.get("validation_summary_before")
        after = record.get("validation_summary_after")
        if before and ch not in chapter_initial:
            chapter_initial[ch] = before
        if after:
            chapter_final[ch] = after

    if not chapter_initial:
        return None

    before_totals = Counter()
    after_totals = Counter()
    for ch, summary in chapter_initial.items():
        for k, v in summary.items():
            before_totals[k] += v
    for ch, summary in chapter_final.items():
        for k, v in summary.items():
            after_totals[k] += v

    all_keys = sorted(set(list(before_totals.keys()) + list(after_totals.keys())))
    rows = {}
    for k in all_keys:
        b = before_totals.get(k, 0)
        a = after_totals.get(k, 0)
        if b or a:
            rows[k] = {"before": b, "after": a, "delta": a - b}
    return rows


def _format_issues_delta(delta: dict | None) -> str:
    """Format issues-resolved delta as markdown table."""
    if not delta:
        return ""

    # Only show rows where there was at least one issue initially
    rows_with_issues = {k: v for k, v in delta.items() if v["before"] > 0}
    if not rows_with_issues:
        return ""

    lines = ["| Issue type | Before | After | Delta |",
             "|------------|--------|-------|-------|"]
    for key, vals in sorted(rows_with_issues.items(), key=lambda x: -x[1]["before"]):
        label = _ISSUE_LABELS.get(key, key)
        d = vals["delta"]
        delta_str = str(d) if d >= 0 else str(d)
        lines.append(f"| {label} | {vals['before']} | {vals['after']} | {delta_str} |")
    return "\n".join(lines)


def _format_validation(stats: dict) -> str:
    """Format validation stats as a markdown table."""
    rows = []

    coverage = stats["verses"]
    total = stats["total_verses"]
    pct = (coverage / total * 100) if total else 0
    rows.append(f"| Verse coverage | {coverage}/{total} ({pct:.1f}%) |")

    missing = stats.get("missing", 0)
    if missing:
        rows.append(f"| Missing verses | {missing} |")

    errors = stats.get("errors", 0)
    rows.append(f"| Structural errors | {errors} |")

    word_gaps = stats.get("word_gaps", 0)
    rows.append(f"| Word gaps | {word_gaps} |")

    failed = stats.get("failed_segments", 0)
    rows.append(f"| Failed alignments | {failed} |")

    below_80 = stats.get("conf_below_80", 0)
    rows.append(f"| Low confidence (<80%) | {below_80} |")

    below_60 = stats.get("conf_below_60", 0)
    if below_60:
        rows.append(f"| Very low confidence (<60%) | {below_60} |")

    consistency = stats.get("consistency_mismatches", 0)
    if consistency:
        rows.append(f"| Consistency mismatches | {consistency} |")

    conf_mean = stats.get("conf_mean", 0)
    if conf_mean:
        rows.append(f"| Mean confidence | {conf_mean:.1%} |")

    header = "| Metric | Value |\n|--------|-------|\n"
    return header + "\n".join(rows)


def _format_edits(edit_summary: dict) -> str:
    """Format edit history as markdown."""
    if not edit_summary or edit_summary["total_operations"] == 0:
        return "No manual edits recorded."

    lines = []
    lines.append(_EDIT_SUMMARY_TPL.format(
        total_operations=edit_summary['total_operations'],
        chapters_edited=edit_summary['chapters_edited'],
    ))

    op_counts = edit_summary["op_counts"]
    if op_counts:
        lines.append("")
        lines.append("| Edit type | Count |")
        lines.append("|-----------|-------|")
        for op_type, count in sorted(op_counts.items(), key=lambda x: -x[1]):
            label = OP_LABELS.get(op_type, op_type)
            lines.append(f"| {label} | {count} |")

    fix_kinds = edit_summary["fix_kind_counts"]
    manual = fix_kinds.get("manual", 0)
    auto = fix_kinds.get("auto_fix", 0)
    ignored = fix_kinds.get("ignore", 0)
    if manual or auto or ignored:
        parts = []
        if manual:
            parts.append(f"{manual} manual")
        if auto:
            parts.append(f"{auto} auto-fix")
        if ignored:
            parts.append(f"{ignored} ignored")
        lines.append(f"\nFix breakdown: {', '.join(parts)}.")

    return "\n".join(lines)


def generate_summary(slugs: list[str]) -> str:
    """Generate full markdown summary for one or more reciters."""
    word_counts = load_word_counts(SURAH_INFO)
    sections = []

    for slug in slugs:
        reciter_dir = SEGMENTS_ROOT / slug
        if not reciter_dir.is_dir():
            sections.append(f"### {slug}\n\nSegment directory not found.")
            continue

        # Edit history summary
        edit_summary = _summarize_edit_history(reciter_dir)

        # Validation
        stats = validate_reciter(reciter_dir, word_counts, verbose=False)

        parts = []
        if len(slugs) > 1:
            parts.append(f"### {slug}\n")

        # Edits section
        parts.append("#### Edits\n")
        parts.append(_format_edits(edit_summary))

        # Issues resolved section
        delta = _compute_issues_delta(reciter_dir)
        delta_text = _format_issues_delta(delta)
        if delta_text:
            parts.append("\n#### Issues resolved\n")
            parts.append(delta_text)

        # Validation section
        parts.append("\n#### Validation\n")
        parts.append(_format_validation(stats))

        # Remaining issues callout
        remaining = []
        if stats.get("missing", 0):
            remaining.append(f"{stats['missing']} missing verses")
        if stats.get("errors", 0):
            remaining.append(f"{stats['errors']} structural errors")
        if stats.get("word_gaps", 0):
            remaining.append(f"{stats['word_gaps']} word gaps")
        if stats.get("failed_segments", 0):
            remaining.append(f"{stats['failed_segments']} failed alignments")

        if remaining:
            parts.append(f"\n> **Remaining issues:** {', '.join(remaining)}")
        else:
            parts.append("\n> All checks passed.")

        sections.append("\n".join(parts))

    return "\n\n---\n\n".join(sections)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <slug> [<slug2> ...]", file=sys.stderr)
        sys.exit(1)

    slugs = sys.argv[1:]
    print(generate_summary(slugs))
