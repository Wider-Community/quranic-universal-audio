---
name: audit-reciters
description: "Audit reciter data consistency across all sources (disk, RECITERS.md, README.md, GitHub, Notion). This skill should be used when the user wants to check or fix inconsistencies in reciter data, run a reciter audit, or uses /audit-reciters."
---

# Audit Reciter Consistency

Cross-reference all reciter data sources and fix inconsistencies.
The underlying script is `scripts/audit_reciters.py` (local-only, gitignored).

## Audit Report
!`python3 scripts/audit_reciters.py $ARGUMENTS 2>&1`

## Working Tree State (audited files)
!`git diff --stat data/RECITERS.md README.md dataset/README.md 2>/dev/null || echo "No uncommitted changes to audited files."`

If the audit report above is empty or shows an error, investigate by running the script manually.

## Issue Categories

- **ERROR** — data integrity problem, needs investigation
- **FIX** — auto-fixable inconsistency (re-runs `list_reciters.py --write` and updates badges)
- **WARN** — potential issue, may need manual attention
- **INFO** — informational

## Workflow

### If `--fix` was passed (fixes already applied)

1. Review the fix output above — confirm each applied fix is correct.
2. Review the full changes:
   ```bash
   git diff data/RECITERS.md README.md dataset/README.md
   ```
3. If changes look correct, commit and push directly to main.

### If report-only mode (no `--fix`)

1. Review the audit report above.
2. If there are **FIX** issues, ask the user whether to apply fixes.
3. If confirmed, run:
   ```bash
   python3 scripts/audit_reciters.py --fix
   ```
4. Review the changes:
   ```bash
   git diff data/RECITERS.md README.md dataset/README.md
   ```
5. If changes look correct, commit and push directly to main.

### If no issues found

Report that all reciter data is consistent. No action needed.

## What It Checks

- Aligned reciters: segments on disk, timestamp level vs git-tracked state
- Audio manifests: missing style fields, missing SOURCE files
- Badge counts: reciters (Available | Aligned) and riwayat (X / 20) in README.md and dataset/README.md
- External: GitHub issue statuses and Notion request statuses vs aligned state

## Flags

| Flag | Purpose |
|------|---------|
| `--fix` | Apply auto-fixes (re-runs `list_reciters.py --write` + updates dataset badges) |
| `--skip-external` | Skip GitHub/Notion checks (use when offline or tokens unavailable) |

Pass flags when invoking: `/audit-reciters --fix` or `/audit-reciters --skip-external`.
