#!/usr/bin/env bash
# serve-lab.sh — build a lab-first bundle and serve it locally.
#
# Usage:
#   ./serve-lab.sh
#   PORT=9001 ./serve-lab.sh

set -euo pipefail

PORT="${PORT:-8081}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cd "$SCRIPT_DIR"

echo "→ Building public-lab/ bundle..."
rm -rf public-lab
mkdir -p public-lab/assets/processed public-lab/prod
mkdir -p public-lab/src

# Lab pages and modules.
cp -r ./lab public-lab/lab

# Shared prod pages/assets used for comparison and embedded proofs.
cp prod/index.html              public-lab/prod/
cp prod/game-explorer.html      public-lab/prod/
cp prod/elo.html                public-lab/prod/
cp prod/score-diff.html         public-lab/prod/
cp prod/score-d52.html          public-lab/prod/
cp prod/score-diff-v2.html      public-lab/prod/
cp prod/score-d52-v2.html       public-lab/prod/
cp prod/style-insights.html     public-lab/prod/
cp prod/score-chart.js          public-lab/prod/

# Shared root-level pages referenced from lab landing.
cp prod/game-flow-viewer.html                    public-lab/prod/
cp lab/game-flow-switcher.html                   public-lab/lab/
cp src/sankey-renderer.js                        public-lab/src/

if ls data/*.json 1>/dev/null 2>&1; then
  cp data/*.json public-lab/assets/processed/
  echo "✓ Data files copied from data/"
else
  echo "⚠  No data in data/ — run the pipeline first."
fi

mkdir -p public-lab/assets
if ls assets/raw_pts_*.json 1>/dev/null 2>&1; then
  cp assets/raw_pts_*.json public-lab/assets/
  echo "✓ raw_pts files copied"
else
  echo "⚠  No raw_pts_*.json in assets/ — chart proof pages will show fetch errors."
fi

echo "→ Serving public-lab/ on http://localhost:${PORT}"
echo "   Open: http://localhost:${PORT}/lab/index.html"
echo "   Open: http://localhost:${PORT}/lab/style-consistency-lab.html"
echo "   Open: http://localhost:${PORT}/prod/style-insights.html"
echo "   Open: http://localhost:${PORT}/prod/score-d52-v2.html"
python3 -m http.server "$PORT" --directory public-lab