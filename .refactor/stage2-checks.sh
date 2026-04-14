#!/usr/bin/env bash
# Stage-2 pre-flight checks — run at every wave boundary.
#
# Must be invoked from the repository root; paths below are relative to
# `<repo-root>/inspector/`. Each wave's handoff doc may propose additions.
#
# Usage:
#   bash .refactor/stage2-checks.sh

set -euo pipefail

# Resolve repo root from this script's location so invocation-dir
# doesn't matter (we can be run from anywhere in the worktree).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "== Stage-2 pre-flight =="
echo "Repo root: $REPO_ROOT"
echo

# -----------------------------------------------------------------------------
# Frontend: typecheck, lint, build
# -----------------------------------------------------------------------------

cd inspector/frontend
echo "[1/7] npm run typecheck (tsc --noEmit)"
npm run typecheck

echo
echo "[2/7] npm run lint (ESLint; import/no-cycle at warn pending Svelte migration)"
npm run lint

echo
echo "[3/7] npm run build (Vite production build)"
npm run build

cd "$REPO_ROOT/inspector"

# -----------------------------------------------------------------------------
# Backend: `global` keyword must not leak outside services/cache.py
# -----------------------------------------------------------------------------

echo
echo "[4/7] Backend: no 'global' keyword outside services/cache.py"
# Use `|| true` because grep exits 1 on no match; we want non-empty to FAIL.
leaks="$(grep -rn "^\s*global\s" services/ | grep -v "^\s*#" | grep -v "services/cache.py" || true)"
if [[ -n "$leaks" ]]; then
    echo "FAIL: global keyword leak outside services/cache.py:"
    echo "$leaks"
    exit 1
fi
echo "ok: no global keyword outside cache.py"

# -----------------------------------------------------------------------------
# Backend: the two specific module-level dict caches MUST live in cache.py only.
# Looks for `_URL_AUDIO_META` references and bare `_phonemizer =` assignments
# outside services/cache.py (grep excludes pycache).
# -----------------------------------------------------------------------------

echo
echo "[5/7] Backend: _URL_AUDIO_META and _phonemizer live only in services/cache.py"
orphans="$(grep -rln --include="*.py" "_URL_AUDIO_META\|^\s*_phonemizer\s*=" services/ | grep -v "services/cache.py" || true)"
if [[ -n "$orphans" ]]; then
    echo "FAIL: _URL_AUDIO_META or _phonemizer referenced outside cache.py:"
    echo "$orphans"
    exit 1
fi
echo "ok: no orphan global cache vars"

# -----------------------------------------------------------------------------
# Frontend: zero `// NOTE: circular dependency` comments remain.
# -----------------------------------------------------------------------------

echo
echo "[6/7] Frontend: zero '// NOTE: circular dependency' comments"
cycle_notes="$(grep -rn "// NOTE: circular dependency" frontend/src/ || true)"
if [[ -n "$cycle_notes" ]]; then
    echo "FAIL: cycle NOTE comments remain:"
    echo "$cycle_notes"
    exit 1
fi
echo "ok: no cycle NOTEs"


# -----------------------------------------------------------------------------
# Frontend: import/no-cycle warning ceiling (added Wave-1 review per Opus).
#
# The rule is at `warn` severity through Waves 5-10 while segments cycles
# are dissolved by the Svelte migration. This gate asserts the warning count
# is monotonically non-increasing — prevents new cycles from being introduced
# in backend-adjacent frontend work.
#
# Baseline set at end of Wave 1: 23 warnings (all pre-existing segments cycles;
# Wave-1 handoff reported 22 — off-by-one; actual is 23). Update $CYCLE_CEILING
# downward as Svelte waves dissolve cycles; set to 0 at Wave 11 when the rule
# is re-promoted to `error`.
# -----------------------------------------------------------------------------

echo
echo "[7/7] Frontend: import/no-cycle warning count does not exceed ceiling"
cd "$REPO_ROOT/inspector/frontend"
CYCLE_CEILING="${CYCLE_CEILING:-18}"
cycle_warnings="$(npm run -s lint 2>&1 | grep -c "import/no-cycle" || true)"
# grep -c emits 0 when nothing matches; strip any newlines just in case.
cycle_warnings="${cycle_warnings//$'\n'/}"
if (( cycle_warnings > CYCLE_CEILING )); then
    echo "FAIL: import/no-cycle warnings ($cycle_warnings) exceed ceiling ($CYCLE_CEILING)"
    npm run -s lint 2>&1 | grep "import/no-cycle" || true
    exit 1
fi
echo "ok: $cycle_warnings cycle warnings (ceiling: $CYCLE_CEILING)"

cd "$REPO_ROOT/inspector"

# -----------------------------------------------------------------------------
# Wave 2+ Docker smoke — enabled once Dockerfile landed at Wave 2a.
# Skipped when docker isn't available (e.g. WSL w/o Docker Desktop) so the
# pre-flight still completes on dev machines that can't build the image.
# -----------------------------------------------------------------------------

cd "$REPO_ROOT"
if command -v docker >/dev/null 2>&1; then
    echo
    echo "[wave-2+] Docker smoke"
    if ! docker build -t inspector:dev inspector/ ; then
        echo "FAIL: docker build"
        exit 1
    fi
    if ! docker run --rm --detach --name inspector-dev \
            -v "$REPO_ROOT/data:/data" -p 5000:5000 inspector:dev >/dev/null ; then
        echo "FAIL: docker run"
        exit 1
    fi
    # Give Flask a moment to bind (eager phonemizer + timestamp preload can
    # take a few seconds on first start).
    sleep 5
    if curl -s -f http://localhost:5000/api/seg/config > /dev/null; then
        echo "ok: docker smoke"
        docker rm -f inspector-dev >/dev/null
    else
        echo "FAIL: docker smoke (curl /api/seg/config)"
        docker logs inspector-dev || true
        docker rm -f inspector-dev >/dev/null || true
        exit 1
    fi
else
    echo
    echo "[wave-2+] Docker smoke SKIPPED (docker not available on this machine)"
fi

echo
echo "== All Stage-2 pre-flight checks passed =="
