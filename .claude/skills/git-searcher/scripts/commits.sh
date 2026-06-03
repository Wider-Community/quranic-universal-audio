#!/usr/bin/env bash
# Terse commit search by message (subject + body). Local git, zero API cost.
# Usage:
#   commits.sh "<query>" [-n N] [--since <date>] [--until <date>]
#                        [--before <ref>] [--skip N] [--and] [--author <x>]
#
# <query>  regex matched case-insensitively against the full commit message.
#          With --and, space-separated words are ALL-required (multi --grep).
#          Without --and, pass an alternation yourself, e.g. "modal|backdrop".
# --before <ref>  only history ending just before <ref> (searches <ref>~1).
# --skip N         skip the N most recent matches (≈ "N commits/merges before").
#
# Output: "<sha8>  <yyyy-mm-dd>  <subject>" — one match per line, newest first.
set -euo pipefail

query="" ; n=15 ; and=0
declare -a extra=()
range="HEAD"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n)        n="$2"; shift 2;;
    --since)   extra+=(--since="$2"); shift 2;;
    --until)   extra+=(--until="$2"); shift 2;;
    --skip)    extra+=(--skip="$2"); shift 2;;
    --author)  extra+=(--author="$2"); shift 2;;
    --before)  range="$2~1"; shift 2;;
    --and)     and=1; shift;;
    *)         query="$1"; shift;;
  esac
done

[[ -z "$query" ]] && { echo "ERR: empty query" >&2; exit 2; }

declare -a greps=()
if [[ $and -eq 1 ]]; then
  greps+=(--all-match)
  for w in $query; do greps+=(--grep="$w"); done
else
  greps+=(--grep="$query")
fi

git log -i -E "${greps[@]}" "${extra[@]}" \
  -n "$n" --date=short --pretty='%h  %ad  %s' "$range"
