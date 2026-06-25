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
echo "==> Deploying checkout '$branch' to the $env Space"
python scripts/deploy/upload_inspector.py "$env"
echo "==> Upload done + Space factory-rebooting. Monitor readiness with:"
echo "      python .claude/skills/deploy/scripts/wait_space.py $env   (run in background)"
