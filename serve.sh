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
mkdir -p public/src

cp prod/index.html                             public/
cp prod/game-explorer.html                     public/
cp prod/elo.html                               public/
cp prod/score-diff.html                        public/
cp prod/score-d52.html                         public/
cp prod/score-diff-v2.html                     public/
cp prod/score-d52-v2.html                      public/
cp prod/style-insights.html                    public/
cp prod/score-chart.js                         public/

cp game-flow-viewer.html public/
cp game-flow-switcher.html public/
cp src/sankey-renderer.js public/src/

if ls data/*.json 1>/dev/null 2>&1; then
  cp data/*.json public/assets/processed/
  echo "✓ Data files copied from data/"
else
  echo "⚠  No data in data/ — run 'docker compose run --rm demo' first."
fi

# Copy raw_pts scoring event files needed by score-diff.html
mkdir -p public/assets
if ls assets/raw_pts_*.json 1>/dev/null 2>&1; then
  cp assets/raw_pts_*.json public/assets/
  echo "✓ raw_pts files copied"
else
  echo "⚠  No raw_pts_*.json in assets/ — score-diff page will show fetch errors."
fi

echo "→ Serving public/ on http://localhost:${PORT}"
echo "   Open: http://localhost:${PORT}/index.html"
echo "   Open: http://localhost:${PORT}/elo.html?season=2025-2026"
echo "   Open: http://localhost:${PORT}/score-diff.html"
echo "   Open: http://localhost:${PORT}/score-d52.html"
echo "   Open: http://localhost:${PORT}/score-diff-v2.html"
echo "   Open: http://localhost:${PORT}/score-d52-v2.html"
echo "   Open: http://localhost:${PORT}/style-insights.html"
python3 -m http.server "$PORT" --directory public
