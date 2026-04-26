#!/usr/bin/env bash
# .refactor/checks.sh — pre-phase automation
# Run before dispatching each phase's implementation agent.
# Adds new checks as phase handoffs suggest them.

set -e

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

echo "=== pre-phase checks ==="

# 1. Plan path validity (only against the CURRENT phase). Argument $1 is phase id (default: derive from completed handoffs).
echo
PHASE_ARG="${1:-}"
if [ -z "$PHASE_ARG" ]; then
    # Derive: count phase-*-handoff.md files; next phase = count.
    HANDOFF_COUNT=$(ls .refactor/phase-*-handoff.md 2>/dev/null | wc -l)
    PHASE_ARG=$HANDOFF_COUNT
fi
echo "[1] Plan path validity (checking Phase $PHASE_ARG scope only):"
python3 - "$PHASE_ARG" <<'PY'
import yaml, sys, pathlib
phase_id = int(sys.argv[1])
plan = yaml.safe_load(open('.refactor/plan.yaml'))
phase = next((p for p in plan.get('phases', []) if p['id'] == phase_id), None)
if phase is None:
    print(f"  (no Phase {phase_id} in plan; skipping)")
    sys.exit(0)
# Phase 0 is pure additions (test infra + fixtures); skip path validity entirely.
if phase_id == 0:
    print("  (skipped — Phase 0 is all new files)")
    sys.exit(0)
# For Phase 1+: flag a path only when ALL of its ancestor directories up the tree are missing
# (i.e., the path is a complete typo with no plausible parent). Any path whose ancestor chain
# touches an existing directory is treated as "new file in a real area" and accepted.
typos = []
for f in (phase.get('scope_files') or []):
    p = pathlib.Path(f)
    found_real_ancestor = False
    cur = p.parent
    while str(cur) != '.':
        if cur.exists():
            found_real_ancestor = True
            break
        cur = cur.parent
    if not found_real_ancestor:
        typos.append(f)
print("  TYPO PATHS:" if typos else "  ok")
for t in typos:
    print(f"    {t}")
PY

# 2. Backend test collection.
echo
echo "[2] Backend test collection (pytest --collect-only):"
if [ -d "inspector/tests" ]; then
    cd inspector && pytest --collect-only tests/ -q 2>&1 | tail -3 || true
    cd "$ROOT"
else
    echo "  (skipped — inspector/tests/ not yet present)"
fi

# 3. Frontend test collection.
echo
echo "[3] Frontend test collection (vitest --reporter=basic --run):"
if [ -d "inspector/frontend/src/tabs/segments/__tests__" ]; then
    (cd inspector/frontend && npx vitest --reporter=basic --run --no-coverage 2>&1 | tail -5) || true
else
    echo "  (skipped — frontend tests not yet present)"
fi

# 4. Bug log placeholder check.
echo
echo "[4] Bug-log unresolved placeholders:"
if [ -f ".refactor/bug-log.md" ]; then
    if grep -n "_(this commit's SHA)_" .refactor/bug-log.md >/dev/null 2>&1; then
        # Filter out the protocol section (where the placeholder is documented as a literal example).
        OFFENDERS=$(grep -n "_(this commit's SHA)_" .refactor/bug-log.md | grep -v "Append protocol" | grep -v "Resolution" || true)
        if [ -n "$OFFENDERS" ]; then
            echo "  UNRESOLVED PLACEHOLDERS:"
            echo "$OFFENDERS"
        else
            echo "  ok (only doc-protocol references)"
        fi
    else
        echo "  ok"
    fi
fi

# 5. xfail count by phase reason.
echo
echo "[5] xfail count by phase reason (should decrease as phases complete):"
{
    grep -rh 'xfail.*reason="phase-' inspector/tests/ 2>/dev/null || true
    grep -rh 'xfail.*reason="phase-' inspector/frontend/src 2>/dev/null || true
} | sed -E 's/.*reason="(phase-[0-9]+)".*/\1/' | sort | uniq -c | sort -k2

# 6. Plan vs sidecar sync (phase numbers).
echo
echo "[6] Plan markdown ↔ sidecar phase sync:"
python3 - <<'PY'
import yaml
plan = yaml.safe_load(open('.refactor/plan.yaml'))
md = open('.refactor/plan.md').read()
problems = []
for ph in plan.get('phases', []):
    if f"### Phase {ph['id']}" not in md:
        problems.append(f"Phase {ph['id']} ({ph['name']}) in YAML but no '### Phase {ph['id']}' header in plan.md")
print("  ok" if not problems else "  DRIFT:")
for p in problems:
    print(f"    {p}")
PY

# 7. Worktree clean (no uncommitted changes from prior phase).
echo
echo "[7] Worktree status:"
git status --short || true

# 8. MUST-11 refactor-trace breadcrumb check.
# Scope: lines INTRODUCED by this refactor only (compare against main), excluding allowlist directories.
# Pathspec exclusion runs at the git layer so the grep pipeline never sees the noise.
echo
echo "[8] MUST-11 refactor-trace breadcrumb check (vs main):"
if git rev-parse main >/dev/null 2>&1; then
    BREADCRUMBS=$(git diff main...HEAD --no-color -- \
        ':!.refactor/' \
        ':!inspector/tests/fixtures/' \
        ':!docs/inspector-segments-refactor-plan.md' \
        2>/dev/null \
        | grep -E '^\+[^+]' \
        | grep -ivE '^\+\+\+' \
        | grep -inE '(// refactored|// removed|# refactored|# removed|previously this|previously did|now uses the new|now dispatches via|migrated from|replaced by|superseded by Phase|before this refactor|as of Phase [0-9])' \
        | head -20 || true)
    if [ -n "$BREADCRUMBS" ]; then
        echo "  VIOLATIONS — refactor-trace comments introduced:"
        echo "$BREADCRUMBS"
    else
        echo "  ok"
    fi
else
    echo "  (skipped — no 'main' branch ref locally)"
fi

echo
echo "=== checks complete ==="
