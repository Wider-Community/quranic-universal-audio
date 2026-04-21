#!/usr/bin/env bash
# Stage 3 pre-flight checks — run before each phase dispatch.
# Phase handoffs may append more checks.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "== Stage 3 pre-flight =="

# 1. Frontend build + lint
cd inspector/frontend
npm run build > /tmp/build.log 2>&1 || { echo "BUILD FAIL"; tail -30 /tmp/build.log; exit 1; }
echo "build: OK"
npm run lint > /tmp/lint.log 2>&1 || { echo "LINT FAIL"; tail -30 /tmp/lint.log; exit 1; }
echo "lint: OK"

# 2. Python smoke (inspector/app.py uses relative imports; run from inspector/)
cd "$ROOT/inspector"
python3 -c "import app" >/dev/null 2>&1 || { echo "PY IMPORT FAIL"; exit 1; }
echo "py-smoke: OK"
cd "$ROOT"

# 3. Refactor-noise metric (success #5)
NOISE=$(grep -rln -E '(Wave [0-9]|Stage [0-9]|S2-[A-Z]|refactored in|bridge for|\(Wave|previously lived|moved from.*Wave|moved in Wave)' inspector/ --include='*.ts' --include='*.svelte' --include='*.py' 2>/dev/null | grep -v node_modules | grep -v '^\.refactor/' | grep -v '/CLAUDE.md$' | wc -l)
echo "refactor-noise files: $NOISE"

# 4. Imperative DOM in components (success #6) — exclude body.loading + SearchableSelect component
DOM=$(grep -rn -E '\.classList\.|\.querySelector|\.querySelectorAll' inspector/frontend/src --include='*.ts' --include='*.svelte' 2>/dev/null | grep -v 'document.body' | grep -v 'lib/components/SearchableSelect\.svelte' | wc -l)
echo "imperative-DOM calls: $DOM"

# 4b. Post-Ph6: no segments bridge imports in lib (success #18)
BRIDGE=$(grep -rn "from ['\"].*segments/" inspector/frontend/src/lib/ 2>/dev/null | wc -l)
echo "src/lib bridge imports from segments: $BRIDGE"

# 4c. Post-Ph4: B01 map-key cast fix (success #19)
MAPKEY=$(grep -rn 'String(.*) as unknown as number' inspector/frontend/src/ 2>/dev/null | wc -l)
echo "B01 map-key casts remaining: $MAPKEY"

# 5. Legacy dir existence (success #1-4)
for d in segments shared types; do
  if [ -d "inspector/frontend/src/$d" ]; then echo "LEGACY dir still exists: src/$d"; fi
done
if [ -d "inspector/frontend/src/styles" ]; then
  COUNT=$(ls inspector/frontend/src/styles/*.css 2>/dev/null | wc -l)
  if [ "$COUNT" -gt 1 ]; then echo "src/styles has $COUNT css files (expected 1: base.css)"; fi
fi

# 6. as unknown as cast count (success #15)
CASTS=$(grep -rn 'as unknown as' inspector/frontend/src/ 2>/dev/null | wc -l)
echo "as-unknown-as casts: $CASTS"

# 7. Shared doc consistency
if [ -f .refactor/stage3-bugs.md ]; then
  PLACEHOLDERS=$(grep -c '_(this commit' .refactor/stage3-bugs.md || true)
  if [ "$PLACEHOLDERS" -gt 0 ]; then echo "WARN: $PLACEHOLDERS unsubstituted fix-SHA placeholders in bugs log"; fi
fi

echo "== pre-flight done =="
