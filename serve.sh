#!/usr/bin/env bash
# serve.sh — build public/ (same structure as CI) and serve locally.
#
# Usage:
#   ./serve.sh          # build and serve on :8080
#   PORT=9000 ./serve.sh
#
# Generate data first if you haven't already:
#   docker compose run --rm demo

set -euo pipefail

PORT="${PORT:-8080}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"

echo "→ Building public/ bundle..."
rm -rf public
mkdir -p public/assets/processed

cp prod/index.html                             public/
cp prod/game-explorer.html                     public/
cp poss-flow-map-multi-drilldown-real-data.html public/

if ls assets/processed/*.json 1>/dev/null 2>&1; then
  cp assets/processed/*.json public/assets/processed/
  echo "✓ Data files copied from assets/processed/"
else
  echo "⚠  No data in assets/processed/ — run 'docker compose run --rm demo' first."
fi

echo "→ Serving public/ on http://localhost:${PORT}"
echo "   Open: http://localhost:${PORT}/index.html"
python3 -m http.server "$PORT" --directory public
