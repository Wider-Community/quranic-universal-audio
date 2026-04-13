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
echo "[1/6] npm run typecheck (tsc --noEmit)"
npm run typecheck

echo
echo "[2/6] npm run lint (ESLint; import/no-cycle at warn pending Svelte migration)"
npm run lint

echo
echo "[3/6] npm run build (Vite production build)"
npm run build

cd "$REPO_ROOT/inspector"

# -----------------------------------------------------------------------------
# Backend: `global` keyword must not leak outside services/cache.py
# -----------------------------------------------------------------------------

echo
echo "[4/6] Backend: no 'global' keyword outside services/cache.py"
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
echo "[5/6] Backend: _URL_AUDIO_META and _phonemizer live only in services/cache.py"
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
echo "[6/6] Frontend: zero '// NOTE: circular dependency' comments"
cycle_notes="$(grep -rn "// NOTE: circular dependency" frontend/src/ || true)"
if [[ -n "$cycle_notes" ]]; then
    echo "FAIL: cycle NOTE comments remain:"
    echo "$cycle_notes"
    exit 1
fi
echo "ok: no cycle NOTEs"

echo
echo "== All Stage-2 pre-flight checks passed =="

# -----------------------------------------------------------------------------
# After Wave 2 (Docker distribution): uncomment when Dockerfile lands.
# -----------------------------------------------------------------------------
# echo
# echo "[wave-2] Docker smoke"
# docker build -t inspector:dev . && \
#     docker run --rm --detach --name inspector-dev \
#         -v "$REPO_ROOT/data:/data" -p 5000:5000 inspector:dev >/dev/null
# sleep 3
# if curl -s -f http://localhost:5000/api/seg/config > /dev/null; then
#     echo "ok: docker smoke"
# else
#     echo "FAIL: docker smoke"
#     docker logs inspector-dev
#     docker rm -f inspector-dev
#     exit 1
# fi
# docker rm -f inspector-dev >/dev/null
