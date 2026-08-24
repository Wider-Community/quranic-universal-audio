#!/usr/bin/env bash
# Deploy the Inspector to its HF Space straight from the CURRENT checkout — no
# git push, no GH-Actions runner. Wraps scripts/deploy/upload_inspector.py,
# which stages the git-tracked tree, uploads it to the Space repo, and
# factory-reboots the Space. The deploy reflects the committed state of whatever
# branch/worktree you run this from (untracked files are not staged).
#
# Usage:  deploy.sh [dev|prod]   (default: dev)
set -euo pipefail

env="${1:-dev}"
if [[ "$env" != "dev" && "$env" != "prod" ]]; then
    echo "usage: deploy.sh [dev|prod] (got '$env')" >&2
    exit 2
fi

root="$(git rev-parse --show-toplevel)"
cd "$root"
branch="$(git rev-parse --abbrev-ref HEAD)"
python_cmd="${PYTHON:-}"
python_args=(-u)
if [[ -z "$python_cmd" ]]; then
    for candidate in python python3 python.exe py.exe; do
        if command -v "$candidate" >/dev/null 2>&1; then
            python_cmd="$candidate"
            break
        fi
    done
fi
if [[ -z "$python_cmd" ]]; then
    echo "python interpreter not found" >&2
    exit 127
fi
if [[ "$python_cmd" == "py" || "$python_cmd" == "py.exe" ]]; then
    python_args=(-3 -u)
fi
echo "==> Deploying checkout '$branch' to the $env Space"
PYTHONUNBUFFERED=1 "$python_cmd" "${python_args[@]}" scripts/deploy/upload_inspector.py "$env"
echo "==> Upload done + Space factory-rebooting. Monitor readiness with:"
echo "      $python_cmd .claude/skills/deploy/scripts/wait_space.py $env   (run in background)"
