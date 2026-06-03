#!/usr/bin/env bash
# OPT-IN diff dig. Default off — only run when the prompt explicitly asks what
# changed. Auto-detects target: numeric => PR, else => commit sha/ref.
# Usage:
#   dig.sh <sha|PR#>           # --stat / file list only (cheap)
#   dig.sh <sha|PR#> --full    # full patch (expensive — last resort)
set -euo pipefail

target="${1:-}" ; [[ -z "$target" ]] && { echo "ERR: need sha or PR#" >&2; exit 2; }
mode="stat" ; [[ "${2:-}" == "--full" ]] && mode="full"

if [[ "$target" =~ ^[0-9]+$ ]]; then
  R="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
  if [[ "$mode" == full ]]; then gh pr diff "$target" --repo "$R"
  else gh pr diff "$target" --repo "$R" --name-only; fi
else
  if [[ "$mode" == full ]]; then git show "$target"
  else git show --stat --pretty='%h %ad %s%n' --date=short "$target"; fi
fi
