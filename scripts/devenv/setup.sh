#!/usr/bin/env bash
#
# First-time local setup — install the toolchain deps so the tests, typecheck,
# lint, and build run. Idempotent: safe to re-run. The dev/CI container is
# ephemeral (fresh clone, no node_modules / site-packages), so run this once per
# checkout before `npm run test` or pytest.
#
#   scripts/devenv/setup.sh             # frontend + backend (default)
#   scripts/devenv/setup.sh frontend    # just the FE (npm) deps
#   scripts/devenv/setup.sh backend     # just the BE (pip) deps
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
target="${1:-all}"

setup_frontend() {
    echo "==> Frontend deps (inspector/frontend): npm ci"
    # `npm ci` installs EXACTLY the lockfile versions (vitest 3.x, vite 5, the
    # svelte plugin) — unlike `npm install`, which can drift. Afterwards use the
    # repo's pinned scripts: `npm run test` / check / lint / build, NOT
    # `npx vitest` or `npm exec -- vitest` (those can resolve a mismatched global
    # vitest that fails to transform .svelte files).
    npm --prefix "$ROOT/inspector/frontend" ci
}

setup_backend() {
    echo "==> Backend deps (inspector): pip install requirements + dev"
    local reqs=(-r "$ROOT/inspector/requirements.txt" -r "$ROOT/inspector/requirements-dev.txt")
    if ! python3 -m pip install "${reqs[@]}"; then
        # Some base images ship distro-managed packages (e.g. debian's blinker)
        # that pip can't uninstall to satisfy a version bump ("RECORD file not
        # found"). --ignore-installed installs fresh copies that shadow them.
        echo "   pip conflict (distro-managed package?); retrying --ignore-installed ..."
        python3 -m pip install --ignore-installed "${reqs[@]}"
    fi
}

case "$target" in
    all)         setup_frontend; setup_backend ;;
    frontend|fe) setup_frontend ;;
    backend|be)  setup_backend ;;
    *) echo "usage: setup.sh [all|frontend|backend]" >&2; exit 2 ;;
esac

cat <<'EOF'

Setup complete. Run with the PINNED scripts (not npx / npm exec):
  cd inspector/frontend && npm run test    # vitest — also: npm run check / lint / build
  cd inspector && python -m pytest tests/ -v
EOF
