#!/usr/bin/env bash
# Terse merged-PR search + commit→PR mapping via gh. Costs API calls — run after
# commits.sh has narrowed things; use --for-commit to attach a PR number to a sha.
# Usage:
#   prs.sh "<query>" [--limit N] [--state merged|open|all]
#   prs.sh --for-commit <sha>
#
# Output: "#<num>  <yyyy-mm-dd>  <title>" — newest first.
set -euo pipefail

R="$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)" \
  || { echo "ERR: not a gh repo / not authed" >&2; exit 2; }

query="" ; limit=10 ; state="merged" ; sha=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --for-commit) sha="$2"; shift 2;;
    --limit)      limit="$2"; shift 2;;
    --state)      state="$2"; shift 2;;
    *)            query="$1"; shift;;
  esac
done

fmt='def d: (.mergedAt // .createdAt // "")[0:10];
     .[] | "#\(.number)  \(d)  \(.title)"'

if [[ -n "$sha" ]]; then
  # GitHub indexes the commit sha against the PR that introduced it.
  gh pr list --repo "$R" --state all --search "$sha" \
    --json number,title,mergedAt,createdAt -q "$fmt"
  exit 0
fi

[[ -z "$query" ]] && { echo "ERR: empty query" >&2; exit 2; }

gh pr list --repo "$R" --state "$state" --search "$query in:title,body" \
  --limit "$limit" --json number,title,mergedAt,createdAt -q "$fmt"
